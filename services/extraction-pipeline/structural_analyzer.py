"""
structural_analyzer.py
=======================
Heuristic-based structural analysis of PDF papers using PyMuPDF data only.
Replaces the old NuExtract LLM pipeline entirely.

What this module does (in ~0.3–0.5s per paper):
  1. Heading detection  — font size + bold flag analysis
  2. Manuscript metadata — title, abstract, keywords, authors (page-1 heuristics)
  3. Figure discovery   — regex on full text + image block bboxes from PyMuPDF
  4. Table discovery    — regex on full text for caption patterns
  5. Equation discovery — regex for (N) labels at line end
  6. Word count         — len(body_text.split()) excluding references section

Design principles:
  - Zero LLM calls.
  - Zero external ML models.
  - Every output field is directly traceable to a PDF text/geometry primitive.
  - Graceful degradation: if a pattern isn't found, return None/empty — never crash.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from pymupdf_extractor import PageChunk


# ─────────────────────────────────────────────────────────────────────────────
# Compiled patterns (top-level for performance)
# ─────────────────────────────────────────────────────────────────────────────

_ABSTRACT_HEADER = re.compile(
    r'^\s*a(?:\s+b\s+s\s+t\s+r\s+a\s+c\s+t|bstract)\s*$', re.IGNORECASE
)
_ABSTRACT_INLINE = re.compile(
    r'^\s*abstract\s*[—–\-:]\s*(.+)', re.IGNORECASE
)
_KW_LINE = re.compile(
    r'(?:keywords?|index\s+terms?|key\s+words?)\s*[—–\-:\s]\s*(.+)',
    re.IGNORECASE,
)
_KW_HEADER = re.compile(
    r'^\s*(?:keywords?|index\s+terms?|key\s+words?)\s*:?\s*$', re.IGNORECASE
)
_SECTION_BREAK = re.compile(
    r'^\s*(?:\d+\.?\s+)?(?:introduction|keywords?|index\s+terms?|'
    r'related\s+work|background|method|proposed|experiment|result|'
    r'conclusion|discussion|references?|bibliography|acknowledgement)\s*$',
    re.IGNORECASE,
)

_FIG_CAPTION_RE = re.compile(
    r'(?:^|\n)[ \t]*(Fig(?:ure)?\.?\s*)(\d+)[.\s:][ \t]*(.{5,400})',
    re.IGNORECASE | re.MULTILINE,
)
_TABLE_CAPTION_RE = re.compile(
    r'(?:^|\n)[ \t]*(Table\s*)(\d+)[.\s:][ \t]*(.{5,400})',
    re.IGNORECASE | re.MULTILINE,
)
_FIG_MENTION_RE = re.compile(
    r'\bFig(?:ure)?s?\.?\s*(\d+)\b', re.IGNORECASE
)
_TABLE_MENTION_RE = re.compile(
    r'\bTables?\s*(\d+)\b', re.IGNORECASE
)
_EQ_LABEL_RE = re.compile(
    r'^(.{3,150}?)\s+\((\d+)\)\s*$', re.MULTILINE
)

_HEADING_NOISE = re.compile(
    r'^\s*(?:'
    r'fig(?:ure)?\.?\s*\d+'
    r'|table\s+\d+'
    r'|eq(?:uation)?\.?\s*[\d(]'
    r'|received\s+\d'
    r'|accepted\s+\d'
    r'|doi[\s:]'
    r'|copyright\s'
    r'|©\s*\d{4}'
    r'|\d{4}\s+(?:elsevier|springer|ieee|acm)'
    r'|knowledge.based\s+systems'
    r'|contents\s+lists'
    r'|journal\s+homepage'
    r'|www\.'
    r'|https?://'
    r'|e-?mail'
    r'|^\d+$'
    r')',
    re.IGNORECASE,
)

_REF_SECTION_RE = re.compile(
    r'^\s*(?:\d+\.?\s+)?(?:references?|bibliography)\s*$',
    re.IGNORECASE | re.MULTILINE,
)

_AFFILIATION_RE = re.compile(
    r'@|'
    r'\bUniv(?:ersity)?\b|\bDept\.?\b|\bDepartment\b|'
    r'\bInstitut(?:e|ion)?\b|\bSchool\b|\bLaborator(?:y|ies)\b|'
    r'\bCollege\b|\bCenter\b|\bCentre\b|'
    r'^\s*\d{5,}',  # zip/postal codes
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def analyze_structure(
    page_chunks: List[PageChunk],
    full_text: str,
    page_texts: List[str],
) -> Dict[str, Any]:
    """
    Main entry point.  Accepts PyMuPDF page chunks and returns the structured
    document dict needed by the checks engine.

    Returns:
        {
          "manuscript":  {...},
          "sections":    [...],
          "figures":     [...],
          "tables":      [...],
          "equations":   [...],
          "estimated_word_count": int,
        }
    """
    if not page_chunks:
        return {
            "manuscript": _empty_manuscript(),
            "sections": [],
            "figures": [],
            "tables": [],
            "equations": [],
            "estimated_word_count": 0,
        }

    page_offsets = _build_page_offsets(page_texts)
    body_font_size = _estimate_body_font_size(page_chunks)

    sections = _detect_headings(page_chunks, body_font_size)
    manuscript = _extract_manuscript_metadata(page_chunks, sections, body_font_size)
    figures = _discover_figures(full_text, page_offsets, page_chunks)
    tables = _discover_tables(full_text, page_offsets)
    equations = _discover_equations(full_text, page_offsets)
    word_count = _estimate_word_count(full_text)

    return {
        "manuscript": manuscript,
        "sections": sections,
        "figures": figures,
        "tables": tables,
        "equations": equations,
        "estimated_word_count": word_count,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Heading detection
# ─────────────────────────────────────────────────────────────────────────────

def _detect_headings(
    page_chunks: List[PageChunk],
    body_font_size: float,
) -> List[Dict[str, Any]]:
    """
    Detect section headings from font size + bold flag analysis.

    Rules:
      - font_size >= body_font_size * HEADING_SIZE_RATIO  → size-based heading
      - is_bold AND font_size >= body_font_size * BOLD_RATIO AND len <= 80 chars → bold heading
        BUT the bold line must also be short (< 80 chars) AND not contain a period mid-sentence
      - ALL-CAPS short line (len 3–50) at body font size → caps heading
      - Skip top/bottom 55pt margin (running headers/footers)
      - Skip lines matching HEADING_NOISE (captions, DOI, copyright, etc.)
      - Skip lines that look like body text (contain sentence-ending patterns)
    """
    HEADING_SIZE_RATIO = 1.15   # must be 15% bigger than body to be a size heading
    BOLD_MIN_SIZE_RATIO = 1.00  # bold headings must be at least body size (not smaller!)

    candidates: List[Dict] = []
    seen_texts: set = set()

    for chunk in page_chunks:
        ph = chunk.page_height

        for line in chunk.lines:
            y0, y1 = line.bbox[1], line.bbox[3]

            # Skip running headers / footers
            if y0 < 55 or y1 > ph - 55:
                continue

            text = line.text.strip()
            if not text or len(text) < 2 or len(text) > 160:
                continue

            # Deduplication (same heading at same position won't repeat, but
            # running head might; use a 70-char key)
            key = text[:70].lower()
            if key in seen_texts:
                continue

            # Skip noise
            if _HEADING_NOISE.match(text):
                continue

            max_size = line.max_font_size
            is_bold = line.is_bold
            is_allcaps = text.replace(' ', '').isupper() and 3 <= len(text) <= 60

            # Bold body-text line check: must be short AND not look like a sentence
            # (sentences contain mid-text periods followed by spaces)
            is_sentence_like = bool(re.search(r'[a-z]\. [A-Za-z]', text))  # mid-sentence period
            is_bold_heading = (
                is_bold
                and max_size >= body_font_size * BOLD_MIN_SIZE_RATIO
                and len(text) <= 80
                and not is_sentence_like
                and not text.endswith(',')  # author lists end in comma
                and '·' not in text         # author name separator
                and '@' not in text         # email
            )

            is_heading = (
                max_size >= body_font_size * HEADING_SIZE_RATIO
                or is_bold_heading
                or (is_allcaps and max_size >= body_font_size * 0.90 and len(text) <= 50
                    and not is_sentence_like)
            )

            if not is_heading:
                continue

            seen_texts.add(key)
            # Clean control characters from text before storing
            clean_text = re.sub(r'[\x00-\x08\x0b-\x1f]', '', text).strip()
            candidates.append({
                "_text":       clean_text or text,
                "_font_size":  max_size,
                "_is_bold":    is_bold,
                "_page":       chunk.page_number,
                "_bbox":       line.bbox,
            })

    if not candidates:
        return []

    # Assign heading levels by font size (larger = lower level number = more important)
    unique_sizes = sorted(set(c["_font_size"] for c in candidates), reverse=True)
    size_to_level = {s: (i + 1) for i, s in enumerate(unique_sizes[:5])}

    sections: List[Dict] = []
    for c in candidates:
        raw_text = c["_text"]
        level = size_to_level.get(c["_font_size"], 5)

        # Extract leading number prefix: "1.2 Background" → num="1.2", text="Background"
        m = re.match(r'^(\d+(?:\.\d+)*\.?\s+)(.*)', raw_text)
        if m:
            heading_number = m.group(1).strip().rstrip('.')
            heading_text = m.group(2).strip()
        else:
            heading_number = None
            heading_text = raw_text

        if not heading_text:
            heading_text = raw_text

        bbox = c["_bbox"]
        sections.append({
            "heading_text":    heading_text,
            "heading_number":  heading_number,
            "heading_level":   level,
            "page_number":     c["_page"],
            "bbox": {
                "page": c["_page"],
                "x0":   bbox[0],
                "y0":   bbox[1],
                "x1":   bbox[2],
                "y1":   bbox[3],
            },
            "coordinate_found": True,
        })

    return sections


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Manuscript metadata
# ─────────────────────────────────────────────────────────────────────────────

def _extract_manuscript_metadata(
    page_chunks: List[PageChunk],
    sections: List[Dict],
    body_font_size: float,
) -> Dict[str, Any]:
    """Extract title, abstract, keywords, authors from page 1."""

    p1 = page_chunks[0]

    title = _find_title(p1, body_font_size)
    abstract_text, abstract_word_count = _find_abstract(page_chunks)
    keywords = _find_keywords(page_chunks)
    authors = _find_authors(p1, title, body_font_size)

    return {
        "title":                    title,
        "abstract_text":            abstract_text,
        "abstract_word_count":      abstract_word_count,
        "keywords":                 keywords,
        "keywords_section_present": bool(keywords),
        "authors":                  authors,
        "publishing_statements": {
            "conflict_of_interest":          None,
            "ethics_statement":              None,
            "funding_statement":             None,
            "data_access_statement":         None,
            "author_contribution_statement": None,
        },
    }


def _find_title(page1: PageChunk, body_font_size: float) -> Optional[str]:
    """Largest-font non-header text block on page 1, above y=60% of page."""
    max_size = body_font_size * 1.15
    title_lines: List[str] = []
    title_size = 0.0

    for line in page1.lines:
        y0 = line.bbox[1]
        # Title is in the upper 65% of the first page
        if y0 < 40 or y0 > page1.page_height * 0.65:
            continue

        size = line.max_font_size
        text = line.text.strip()
        if not text:
            continue

        # Skip obvious non-title lines
        if _AFFILIATION_RE.search(text):
            continue
        if len(text) > 200 or len(text) < 3:
            continue

        if size > title_size + 0.5:
            title_lines = [text]
            title_size = size
        elif abs(size - title_size) <= 0.5 and title_size > body_font_size * 1.15:
            title_lines.append(text)

    if title_lines:
        title = " ".join(title_lines)
        title = re.sub(r'\s+', ' ', title).strip()
        return title or None
    return None


def _find_abstract(page_chunks: List[PageChunk]) -> Tuple[Optional[str], Optional[int]]:
    """
    Find abstract text. Handles two formats:
      A. Inline: "Abstract — This paper proposes..."
      B. Block:  "Abstract" on its own line, text below
    """
    for chunk in page_chunks[:3]:
        lines = chunk.plain_text.splitlines()

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue

            # Format A: inline
            m = _ABSTRACT_INLINE.match(stripped)
            if m:
                parts = [m.group(1).strip()]
                for j in range(i + 1, min(i + 50, len(lines))):
                    nl = lines[j].strip()
                    if _SECTION_BREAK.match(nl):
                        break
                    if nl:
                        parts.append(nl)
                text = " ".join(parts).strip()
                if len(text.split()) >= 30:
                    return text, len(text.split())
                continue

            # Format B: header then block
            if _ABSTRACT_HEADER.match(stripped):
                parts = []
                for j in range(i + 1, min(i + 60, len(lines))):
                    nl = lines[j].strip()
                    if _SECTION_BREAK.match(nl):
                        break
                    if nl:
                        parts.append(nl)
                text = " ".join(parts).strip()
                if len(text.split()) >= 30:
                    return text, len(text.split())

    return None, None


def _find_keywords(page_chunks: List[PageChunk]) -> List[str]:
    """Find keywords from 'Keywords:' or 'Index Terms:' line.
    Handles separators: comma, semicolon, dot, middle-dot (·), pipe.
    """
    # Extended separator pattern: comma, semicolon, en-dash-separated, · (middot)
    _SPLIT_KW = re.compile(r'[;,·|]|\s{2,}')

    for chunk in page_chunks[:3]:
        lines = chunk.plain_text.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()

            # Inline: "Keywords: kw1, kw2, kw3" or "Keywords · kw1 · kw2"
            m = _KW_LINE.match(stripped)
            if m:
                kw_text = m.group(1).strip()
                # Check if keywords continue on next line
                if i + 1 < len(lines):
                    nl = lines[i + 1].strip()
                    # Continue if next line has keyword-like content (no section start, not too long)
                    if nl and not re.match(r'^\d+\.?\s+[A-Z]', nl) and not _SECTION_BREAK.match(nl) and len(nl) < 200:
                        kw_text += " " + nl
                kws = [k.strip() for k in _SPLIT_KW.split(kw_text) if k.strip() and len(k.strip()) > 1]
                if kws:
                    return kws[:15]

            # Header only: "Keywords" or "Keywords:" on its own line
            if _KW_HEADER.match(stripped) and i + 1 < len(lines):
                nl = lines[i + 1].strip()
                # Check if it's a one-per-line format (short lines, no separators)
                kw_candidates = [nl]
                for j in range(i + 2, min(i + 20, len(lines))):
                    jl = lines[j].strip()
                    if not jl or _SECTION_BREAK.match(jl) or re.match(r'^a\s+b\s+s', jl, re.I):
                        break
                    # Stop if line looks like start of abstract (long sentence)
                    if len(jl.split()) > 12:
                        break
                    kw_candidates.append(jl)

                # If we have one-per-line keywords (each < 5 words), return them
                if all(len(k.split()) <= 6 for k in kw_candidates) and len(kw_candidates) >= 2:
                    return [k for k in kw_candidates if k][:15]

                # Otherwise try comma/middot split on first line
                kws = [k.strip() for k in _SPLIT_KW.split(nl) if k.strip() and len(k.strip()) > 1]
                if kws:
                    return kws[:15]

    return []


def _find_authors(
    page1: PageChunk,
    title: Optional[str],
    body_font_size: float,
) -> List[str]:
    """
    Find author names: lines on page 1 between title and abstract,
    that are not affiliation lines.
    Uses a robust multi-strategy approach:
      1. Font-size region between title y1 and abstract y0
      2. Pattern match for "Name, Name and Name" structures
    """
    # Estimate title y-end and abstract y-start
    title_y1 = 0.0
    abstract_y0 = page1.page_height

    for line in page1.lines:
        text = line.text.strip()
        if _ABSTRACT_HEADER.match(text) or _ABSTRACT_INLINE.match(text):
            abstract_y0 = min(abstract_y0, line.bbox[1])
        if title and len(title) > 5:
            # Check if this line is part of the title (by matching first few words)
            title_words = title.split()[:4]
            if any(w in line.text for w in title_words if len(w) > 3):
                title_y1 = max(title_y1, line.bbox[3])

    author_region_lines: List[str] = []
    for line in page1.lines:
        y0 = line.bbox[1]
        text = line.text.strip()

        # Must be between title and abstract
        if y0 <= title_y1 or y0 >= abstract_y0:
            continue
        if not text or len(text) < 3:
            continue

        # Skip affiliation lines
        if _AFFILIATION_RE.search(text):
            continue

        # Skip very long lines (paragraphs, not names)
        if len(text) > 120:
            continue

        # Skip lines that look like journal titles or headings
        if line.max_font_size > body_font_size * 1.4:
            continue

        author_region_lines.append(text)

    # Parse author names from collected lines
    authors: List[str] = []
    seen: set = set()

    for line_text in author_region_lines[:8]:
        # Split on "and", "&", ",", ";"
        parts = re.split(r'\s*(?:,\s*and|;\s*and|,\s*&|\band\b|&|;)\s*', line_text, flags=re.IGNORECASE)
        # Also split on commas if they separate full names
        new_parts: List[str] = []
        for p in parts:
            sub = re.split(r',\s*(?=[A-Z])', p)
            new_parts.extend(sub)

        for part in new_parts:
            part = part.strip().strip(',').strip()
            # Remove superscript markers (numbers, *, †, ‡)
            part = re.sub(r'[\*†‡§¶\d,]+$', '', part).strip()
            part = re.sub(r'^[\*†‡§¶\d,]+', '', part).strip()

            # Validate: 2–5 words, starts with capital
            words = part.split()
            if 2 <= len(words) <= 5 and re.match(r'[A-Z]', part):
                key = part.lower()
                if key not in seen:
                    seen.add(key)
                    authors.append(part)

    return authors[:12]


# ─────────────────────────────────────────────────────────────────────────────
# Step 3a: Figure discovery
# ─────────────────────────────────────────────────────────────────────────────

def _discover_figures(
    full_text: str,
    page_offsets: List[int],
    page_chunks: List[PageChunk],
) -> List[Dict[str, Any]]:
    """
    Discover figures from:
      - Regex on full text for caption patterns (Figure N: ...)
      - First inline mentions (Fig. N)
      - PyMuPDF image block bboxes (for figure position checks)
    """
    # Build image block map: page_num → list of {x0, y0, x1, y1, area}
    image_map: Dict[int, List[Dict]] = {}
    for chunk in page_chunks:
        if chunk.image_blocks:
            blocks = [
                {**b, "area": (b["x1"] - b["x0"]) * (b["y1"] - b["y0"])}
                for b in chunk.image_blocks
                if (b["x1"] - b["x0"]) > 20 and (b["y1"] - b["y0"]) > 20  # skip tiny icons
            ]
            if blocks:
                image_map[chunk.page_number] = blocks

    # Collect captions
    captions: Dict[int, Dict] = {}
    for m in _FIG_CAPTION_RE.finditer(full_text):
        num = int(m.group(2))
        if num in captions:
            continue
        cap_text = m.group(3).strip()
        cap_text = re.sub(r'\n\s*', ' ', cap_text)[:300]
        page = _char_pos_to_page(m.start(), page_offsets)
        captions[num] = {
            "caption_text": cap_text,
            "caption_page": page,
            "caption_ends_period": cap_text.rstrip().endswith('.'),
        }

    # Collect first mentions
    first_mentions: Dict[int, int] = {}
    for m in _FIG_MENTION_RE.finditer(full_text):
        num = int(m.group(1))
        if num not in first_mentions:
            first_mentions[num] = _char_pos_to_page(m.start(), page_offsets)

    all_nums = sorted(set(list(captions.keys()) + list(first_mentions.keys())))

    figures: List[Dict] = []
    used_image_keys: set = set()

    for num in all_nums:
        cap_info = captions.get(num, {})
        cap_page = cap_info.get("caption_page") or first_mentions.get(num, 1)

        # Match image block: prefer image directly above caption on same page,
        # then adjacent pages. Pick the largest unused image block.
        image_bbox = None
        for p in [cap_page, cap_page - 1, cap_page + 1]:
            blocks = image_map.get(p, [])
            if not blocks:
                continue
            # Sort by area descending, pick the largest unused
            for b in sorted(blocks, key=lambda x: -x["area"]):
                key = (p, round(b["x0"]), round(b["y0"]))
                if key not in used_image_keys:
                    image_bbox = {"page": p, "x0": b["x0"], "y0": b["y0"],
                                  "x1": b["x1"], "y1": b["y1"]}
                    used_image_keys.add(key)
                    break
            if image_bbox:
                break

        figures.append({
            "number":              num,
            "caption_text":        cap_info.get("caption_text", ""),
            "caption_page":        cap_page,
            "caption_ends_period": cap_info.get("caption_ends_period", False),
            "image_bbox":          image_bbox,
            "first_mention_page":  first_mentions.get(num, cap_page),
            "coordinate_found":    image_bbox is not None,
        })

    return figures


# ─────────────────────────────────────────────────────────────────────────────
# Step 3b: Table discovery
# ─────────────────────────────────────────────────────────────────────────────

def _discover_tables(
    full_text: str,
    page_offsets: List[int],
) -> List[Dict[str, Any]]:
    """Discover tables from caption patterns in text."""

    captions: Dict[int, Dict] = {}
    for m in _TABLE_CAPTION_RE.finditer(full_text):
        num = int(m.group(2))
        if num in captions:
            continue
        cap_text = m.group(3).strip()
        cap_text = re.sub(r'\n\s*', ' ', cap_text)[:300]
        page = _char_pos_to_page(m.start(), page_offsets)
        captions[num] = {
            "caption_text": cap_text,
            "caption_page": page,
            "caption_ends_period": cap_text.rstrip().endswith('.'),
        }

    first_mentions: Dict[int, int] = {}
    for m in _TABLE_MENTION_RE.finditer(full_text):
        num = int(m.group(1))
        if num not in first_mentions:
            first_mentions[num] = _char_pos_to_page(m.start(), page_offsets)

    all_nums = sorted(set(list(captions.keys()) + list(first_mentions.keys())))

    tables: List[Dict] = []
    for num in all_nums:
        cap_info = captions.get(num, {})
        cap_page = cap_info.get("caption_page") or first_mentions.get(num, 1)
        tables.append({
            "number":              num,
            "caption_text":        cap_info.get("caption_text", ""),
            "caption_page":        cap_page,
            "caption_ends_period": cap_info.get("caption_ends_period", False),
            "caption_bbox":        None,  # no heavy search — checks use page proximity
            "first_mention_page":  first_mentions.get(num, cap_page),
            "coordinate_found":    False,
        })

    return tables


# ─────────────────────────────────────────────────────────────────────────────
# Step 3c: Equation discovery
# ─────────────────────────────────────────────────────────────────────────────

def _discover_equations(
    full_text: str,
    page_offsets: List[int],
) -> List[Dict[str, Any]]:
    """
    Find equation labels: "(N)" at the end of a line, where the line contains
    at least 3 chars before the label (the equation content).
    """
    equations: Dict[int, Dict] = {}

    for m in _EQ_LABEL_RE.finditer(full_text):
        raw = m.group(1).strip()
        num = int(m.group(2))
        if num in equations:
            continue
        # Filter out false positives: "(N)" in citations or reference list
        # Heuristic: skip if raw text looks like a reference start
        if re.match(r'^\s*\[?\d+\]?\.?\s+[A-Z]', raw):
            continue
        page = _char_pos_to_page(m.start(), page_offsets)
        equations[num] = {
            "number":        num,
            "number_format": f"({num})",
            "raw_text":      raw[:120],
            "page_number":   page,
        }

    return sorted(equations.values(), key=lambda e: e["number"])


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _estimate_body_font_size(
    page_chunks: List[PageChunk],
) -> float:
    """
    Return the modal font size that represents body text.
    Strategy: collect all span sizes > 7pt (ignore footnotes/captions that tend
    to be very small), then return the most common one.
    Also compute the weighted-by-length version to avoid tiny superscripts skewing.
    """
    # Weighted count: weight by text length so 1-char spans don't dominate
    size_weight: Dict[int, int] = {}
    for chunk in page_chunks:
        for line in chunk.lines:
            for span in line.spans:
                sz = span.size
                if sz < 7.0:   # skip footnote-sized text
                    continue
                key = round(sz * 2)   # half-point buckets
                weight = max(1, len(span.text.strip()))
                size_weight[key] = size_weight.get(key, 0) + weight

    if not size_weight:
        return 10.0
    most_common_key = max(size_weight, key=lambda k: size_weight[k])
    return most_common_key / 2.0


def _build_page_offsets(page_texts: List[str]) -> List[int]:
    """Build cumulative character offsets for each page in the full_text."""
    offsets: List[int] = []
    pos = 0
    for pt in page_texts:
        offsets.append(pos)
        pos += len(pt) + 1  # +1 for '\n' joiner
    return offsets


def _char_pos_to_page(char_pos: int, page_offsets: List[int]) -> int:
    """Convert a character position in full_text to a 1-based page number."""
    page = 1
    for i, offset in enumerate(page_offsets):
        if char_pos >= offset:
            page = i + 1
        else:
            break
    return page


def _estimate_word_count(full_text: str) -> int:
    """Estimate body word count, excluding the references section."""
    m = _REF_SECTION_RE.search(full_text)
    body = full_text[: m.start()] if m else full_text
    return len(body.split())


def _empty_manuscript() -> Dict[str, Any]:
    return {
        "title":                    None,
        "abstract_text":            None,
        "abstract_word_count":      None,
        "keywords":                 [],
        "keywords_section_present": False,
        "authors":                  [],
        "publishing_statements": {
            "conflict_of_interest":          None,
            "ethics_statement":              None,
            "funding_statement":             None,
            "data_access_statement":         None,
            "author_contribution_statement": None,
        },
    }
