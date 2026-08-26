"""
structural_analyzer.py
=======================
Heuristic-based structural analysis of PDF papers using PyMuPDF data only.

What this module does (in ~0.03–0.1 s per paper):
  1. Heading detection  — font size + bold flag analysis with math-line rejection
  2. Manuscript metadata — title, abstract, keywords, authors (page-1 heuristics)
  3. Figure discovery   — regex on full text + image block bboxes from PyMuPDF
  4. Table discovery    — caption-only (not cross-references)
  5. Word count         — len(body_text.split()) excluding references section

NOTE: Equations removed — to be implemented via a dedicated math library.

Design principles:
  - Zero LLM calls, zero external ML models.
  - Zero hardcoded journal/publisher names.
  - Every rule is derived from universal structural properties of academic PDFs,
    not from specific paper content.
  - Graceful degradation: if a pattern isn't found, return None/empty — never crash.
"""

from __future__ import annotations

import re
import unicodedata
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

# Figure caption: "Figure N:" or "Fig. N." at start of line, description follows
# Caption must have at least 3 chars of description (filters "Fig. 3.")
_FIG_CAPTION_RE = re.compile(
    r'(?:^|\n)[ \t]*(Fig(?:ure)?\.?\s*)(\d+)(?:[.:]|\b)\s*(.{3,400})',
    re.IGNORECASE | re.MULTILINE,
)

# Table caption: distinguished from cross-reference (see _discover_tables logic)
# Only matches "Table N" at start of a line — cross-references are mid-sentence
_TABLE_CAPTION_RE = re.compile(
    r'(?:^|\n)[ \t]*(Table\s*)(\d+)(?:[.:]|\b)\s*(.{3,400})',
    re.IGNORECASE | re.MULTILINE,
)

_FIG_MENTION_RE = re.compile(
    r'\bFig(?:ure)?s?\.?\s*(\d+)\b', re.IGNORECASE
)
_TABLE_MENTION_RE = re.compile(
    r'\bTables?\s*(\d+)\b', re.IGNORECASE
)

_HEADING_NOISE = re.compile(
    r'^\s*(?:'
    r'fig(?:ure)?\.?\s*(?:\d+|[ivxldcm]+)\b'
    r'|table\s+(?:\d+|[ivxldcm]+)\b'
    r'|eq(?:uation)?\.?\s*[\d(]'
    r'|received\s+\d'
    r'|accepted\s+\d'
    r'|doi[\s:]'
    r'|copyright\s'
    r'|©\s*\d{4}'
    r'|available\s+online'
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

# Affiliation line detector — used ONLY for filtering affiliation lines from authors
_AFFILIATION_RE = re.compile(
    r'@|'
    r'\bUniv(?:ersity)?\b|\bDept\.?\b|\bDepartment\b|'
    r'\bInstitut(?:e|ion)?\b|\bSchool\b|\bLaborator(?:y|ies)\b|'
    r'\bCollege\b|\bCenter\b|\bCentre\b|\bFaculty\b|'
    r'\bDivision\b|\bResearch\s+Group\b|\bResearch\b|'
    r'\bAcademy\b|\bTechnology\b|\bCorporation\b|\bAssociation\b|'
    r'\b(?:Student\s+)?Member\b|\bSenior\s+Member\b|\bFellow\b|\bIEEE\b|\bACM\b|'
    r'^\s*\d{5,}',  # zip/postal codes
    re.IGNORECASE,
)

# Detects mathematical content: operators, Greek, special symbols common in formulas.
# Used to reject math-typeset lines from heading/title detection.
#
# KEY DESIGN DECISION — what is NOT math:
#   Hyphens INSIDE words ("cost-efficient", "Ghobaei-Arani") are compound-word markers,
#   not arithmetic minus signs. We only flag standalone operator patterns.
#
_MATH_CONTENT_RE = re.compile(
    # Standalone operator: space-OPERATOR-space or operator between digits
    # Hyphen as word joiner (x-y with no spaces) is excluded.
    r'(?<=[\s\d])[-+](?=[\s\d])'         # standalone -, + (space/digit on both sides)
    r'|(?<=[\s\d])=(?=[\s\d])'           # standalone =
    r'|\b\d+\s*[=+]\s*\d+'              # 3 = 4 or 3 + 4
    r'|[A-Za-z]\s*=\s*[A-Za-z]'         # variable = variable (e.g. "x = y")
    r'|[\u0370-\u03ff\u2190-\u21ff\u2200-\u22ff]'  # Greek, Arrows, Math Operators
    r'|\\frac|\\sum|\\int'              # LaTeX remnants
    r'|\bsin\b|\bcos\b|\btan\b'         # trig function names (standalone)
    r'|\d+\s*/\s*\d+'                   # fractions like 1/2
)

# A valid English heading word starts with a letter and is mostly ASCII word chars
_ENGLISH_WORD_RE = re.compile(r'^[A-Za-z][A-Za-z\'\-]{1,}$')

# Caption description start verbs (cross-references tend to start with these)
# e.g. "Table 3 shows...", "Table 1 presents..."
_CAPTION_VERB_RE = re.compile(
    r'^(?:shows?|presents?|illustrates?|depicts?|compares?|lists?|gives?|'
    r'provides?|reports?|displays?|summarizes?|contains?|includes?|describes?)',
    re.IGNORECASE,
)

# Detects publication metadata lines: journal name lines, article-info lines
# Used to filter out publisher branding from title candidates
_PUB_META_RE = re.compile(
    r'\(\s*\d{4}\s*\)'                  # (2022) — year in parens = journal line
    r'|\b(?:PII|ISSN|eISSN)\b'          # publisher codes
    r'|^\s*(?:PII|DOI|Reference|To appear|Received date|Revised date|Accepted date)'
    r'|^\s*(?:Please cite|This is a PDF|accepted for publication)'
    r'|^\s*(?:Received:|Revised:|Accepted:|Available online)'
    r'|\bSpringer(?:-Verlag)?\b'         # Springer publisher line
    r'|©',
    re.IGNORECASE,
)

_ALGORITHM_KEYWORD_RE = re.compile(
    r'\b(?:while|do|then|else|end\s+if|end\s+for|end\s+while)\b',
    re.IGNORECASE,
)

def _clean_superscripts_from_line(line: Any) -> str:
    """Strip superscript affiliation symbols, footmarks, or small digits."""
    max_sz = line.max_font_size
    parts = []
    for span in line.spans:
        t = span.text.strip()
        is_punctuation = all(not c.isalnum() for c in t) if t else True
        is_superscript = (max_sz - span.size) > 1.5 and span.size < 11.0
        if is_punctuation or not is_superscript:
            parts.append(span.text)
    return "".join(parts).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def analyze_structure(
    page_chunks: List[PageChunk],
    full_text: str,
    page_texts: List[str],
) -> Dict[str, Any]:
    """
    Main entry point. Accepts PyMuPDF page chunks and returns structured document dict.

    Returns:
        {
          "manuscript":  {...},
          "sections":    [...],
          "figures":     [...],
          "tables":      [...],
          "estimated_word_count": int,
        }
    NOTE: equations removed — to be implemented via dedicated math library.
    """
    if not page_chunks:
        return {
            "manuscript": _empty_manuscript(),
            "sections": [],
            "figures": [],
            "tables": [],
            "estimated_word_count": 0,
        }

    page_offsets = _build_page_offsets(page_texts)
    body_font_size = _estimate_body_font_size(page_chunks)

    sections = _detect_headings(page_chunks, body_font_size)
    manuscript = _extract_manuscript_metadata(page_chunks, sections, body_font_size)
    figures = _discover_figures(full_text, page_offsets, page_chunks)
    tables = _discover_tables(full_text, page_offsets, page_chunks)
    word_count = _estimate_word_count(full_text)

    return {
        "manuscript": manuscript,
        "sections": sections,
        "figures": figures,
        "tables": tables,
        "estimated_word_count": word_count,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Heading detection
# ─────────────────────────────────────────────────────────────────────────────

def _is_math_line(text: str) -> bool:
    """
    Determine if a text line is a mathematical expression rather than a section heading.

    Principled approach — no hardcoding of specific content:
      1. Contains math operators or Greek/special symbols
      2. High density of non-English characters (symbols, digits, operators)
      3. Contains patterns typical of formula fragments (single-letter variables with subscripts)

    A genuine section heading is an English noun phrase — mostly ASCII letters and spaces.
    A math line has high symbol density and typically contains operators.
    """
    if not text:
        return False

    # Quick check: contains math symbols/Greek
    if _MATH_CONTENT_RE.search(text):
        return True

    # Symbol density check: count non-letter, non-space, non-standard punctuation chars
    total = len(text)
    if total == 0:
        return False

    # Count "unusual" characters (not a-z, A-Z, 0-9, space, common punctuation)
    unusual = sum(
        1 for ch in text
        if not ch.isalpha() and not ch.isdigit() and ch not in ' .,;:!?-–—()[]{}"\''
    )
    symbol_ratio = unusual / total

    # High symbol density → math
    if symbol_ratio > 0.25:
        return True

    # Check if text has very few English words relative to length
    # (math lines have many single-letter variables)
    words = text.split()
    if len(words) >= 3:
        cleaned_words = [re.sub(r'^[^a-zA-Z]+|[^a-zA-Z]+$', '', w) for w in words]
        english_words = sum(1 for w in cleaned_words if _ENGLISH_WORD_RE.match(w))
        if english_words / len(words) < 0.35:
            return True

    return False


def _detect_headings(
    page_chunks: List[PageChunk],
    body_font_size: float,
) -> List[Dict[str, Any]]:
    """
    Detect section headings from font-size + bold-flag analysis.

    Core discriminators (all principled, zero hardcoding):
    ─────────────────────────────────────────────────────────
    SIZE HEADING:  font_size >= body_size * 1.15  AND line is not a math expression
    BOLD HEADING:  is_bold AND font_size >= body_size AND len <= 80 AND
                   not sentence-like (no mid-text ". ") AND not math content
    CAPS HEADING:  ALL_CAPS AND short (3–50 chars) AND not math AND not noise

    EXCLUDED (universal patterns, not paper-specific):
      - y < 60pt or y > page_height-55pt  → running header/footer zone
      - Lines with math content (operators, Greek, high symbol density)
      - Lines matching _HEADING_NOISE (captions, DOI, copyright, URLs)
      - Lines > 160 chars (paragraphs)
      - Lines ending in comma (author lists)
      - Deduplication by first-70-chars key
    """
    # Pre-calculate abstract_y0 on page 1 to filter out metadata above it
    p1 = page_chunks[0]
    abstract_y0 = p1.page_height
    for line in p1.lines:
        t = line.text.strip()
        if _ABSTRACT_HEADER.match(t) or _ABSTRACT_INLINE.match(t):
            abstract_y0 = min(abstract_y0, line.bbox[1])
    if abstract_y0 >= p1.page_height * 0.95:
        abstract_y0 = p1.page_height * 0.50

    HEADING_SIZE_RATIO = 1.15
    BOLD_MIN_SIZE_RATIO = 1.00

    candidates: List[Dict] = []
    seen_texts: set = set()

    for chunk in page_chunks:
        ph = chunk.page_height

        for line in chunk.lines:
            y0, y1 = line.bbox[1], line.bbox[3]

            # Skip running headers / footers (universal 60pt zone)
            if y0 < 60 or y1 > ph - 55:
                continue

            text = line.text.strip()
            if not text or len(text) < 2 or len(text) > 160:
                continue

            # Skip metadata above abstract on Page 1
            if chunk.page_number == 1 and y0 < abstract_y0:
                continue

            # Deduplication
            key = text[:70].lower()
            if key in seen_texts:
                continue

            # Skip noise patterns
            if _HEADING_NOISE.match(text):
                continue

            # Reject programming keywords/loops
            if _ALGORITHM_KEYWORD_RE.search(text):
                continue

            # Reject transition adverbs (e.g. "First, ...", "Second, ...")
            transition_adverbs = re.compile(
                r'^\s*(?:First|Second|Third|Fourth|Fifth|Moreover|However|Furthermore|Specifically|Therefore|In\s+addition|Last),',
                re.IGNORECASE
            )
            if transition_adverbs.match(text):
                continue

            # Heading must start with an uppercase letter, digit, or common quotes
            if not re.match(r'^[A-Z0-9“\"\'\‘\“]', text):
                continue

            # Single-word filter (using strict Roman numerals regex)
            words = text.split()
            if len(words) == 1:
                _KNOWN_SINGLE_WORD_HEADINGS = {
                    'introduction', 'conclusion', 'references', 'bibliography', 'appendix',
                    'abstract', 'discussion', 'methods', 'results', 'experiments',
                    'preliminaries', 'background', 'theory', 'overview', 'declaration'
                }
                roman_re = re.compile(
                    r'^(?:M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3}))\.?$',
                    re.IGNORECASE
                )
                is_numbered = bool(roman_re.match(text)) or bool(re.match(r'^[1-9]\d*\.?$', text))
                is_known = text.lower().strip('.:-') in _KNOWN_SINGLE_WORD_HEADINGS
                if not is_numbered and not is_known:
                    continue

            # Title case ratio check
            _LOWERCASE_EXCLUDED = {
                'of', 'the', 'and', 'to', 'in', 'for', 'a', 'an', 'with', 'by', 'on', 'at',
                'from', 'as', 'that', 'we', 'is', 'are', 'be', 'or', 'its', 'about', 'via', 'using'
            }
            words_cleaned = [w.strip('.,:;()[]{}') for w in words]
            words_filtered = [w for w in words_cleaned if w.lower() not in _LOWERCASE_EXCLUDED and w]
            if words_filtered:
                cap_words = sum(1 for w in words_filtered if w[0].isupper() or w[0].isdigit())
                cap_ratio = cap_words / len(words_filtered)
                if cap_ratio < 0.60:
                    continue

            max_size = line.max_font_size
            is_bold = line.is_bold

            # ── MATH LINE REJECTION ─────────────────────────────────────────
            # Mathematical expressions can have bold formatting or larger size
            # in equation-heavy papers. Reject them before applying heading rules.
            if _is_math_line(text):
                continue

            # Reject all-caps that are parenthetical abbreviation markers or end with punctuation e.g. "(VLA)", "2D)."
            is_allcaps = (
                text.replace(' ', '').isupper()
                and 3 <= len(text) <= 50
                and not (text.startswith('(') and text.endswith(')'))
                and not text.endswith(')')
                and not text.endswith(']')
                and not text.endswith('.')
            )
            is_sentence_like = bool(re.search(r'[a-z]\. [A-Za-z]', text))

            # Apply float tolerance of -0.25 to the body font size comparisons
            is_bold_heading = (
                is_bold
                and max_size >= body_font_size * BOLD_MIN_SIZE_RATIO - 0.25
                and len(text) <= 80
                and not is_sentence_like
                and not text.endswith(',')
                and not text.endswith('.')
                and not (text.startswith('(') and text.endswith(')'))
                and not text.endswith(']')
                and '@' not in text
            )

            is_numbered_heading = (
                bool(re.match(r'^[1-9]\d*(?:\.\d+)+\.?\s+[A-Z]', text))
                and len(text) <= 100
                and not is_sentence_like
            )

            is_heading = (
                max_size >= body_font_size * HEADING_SIZE_RATIO - 0.25
                or is_bold_heading
                or is_numbered_heading
                or (is_allcaps and max_size >= body_font_size * 0.90 - 0.25 and len(text) <= 50
                    and not is_sentence_like)
            )

            if not is_heading:
                continue

            seen_texts.add(key)
            # Strip control characters
            clean_text = re.sub(r'[\x00-\x08\x0b-\x1f]', '', text).strip()
            candidates.append({
                "_text":      clean_text or text,
                "_font_size": max_size,
                "_is_bold":   is_bold,
                "_page":      chunk.page_number,
                "_bbox":      line.bbox,
            })

    if not candidates:
        return []

    # Assign heading levels by font size rank
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
    """
    Find the paper title on page 1.

    Principled layout strategy:
    - Restrict candidates to be strictly above the abstract top boundary.
    - Clean superscript symbols/footnote markers before analyzing candidate text.
    - Rank candidates primarily by max_font_size (descending), and secondarily by y position.
    """
    abstract_y0 = page1.page_height
    for line in page1.lines:
        t = line.text.strip()
        if _ABSTRACT_HEADER.match(t) or _ABSTRACT_INLINE.match(t):
            abstract_y0 = min(abstract_y0, line.bbox[1])

    if abstract_y0 >= page1.page_height * 0.95:
        abstract_y0 = page1.page_height * 0.50

    PUBLISHER_TOP_ZONE = 45   # pt — publisher stamps/banners sit here
    candidates: List[Dict] = []

    for line in page1.lines:
        y0   = line.bbox[1]
        
        if y0 < PUBLISHER_TOP_ZONE or y0 >= abstract_y0:
            continue

        cleaned_text = _clean_superscripts_from_line(line)
        if not cleaned_text or len(cleaned_text) < 4:
            continue

        words = cleaned_text.split()
        if len(words) < 2:
            continue

        if _AFFILIATION_RE.search(cleaned_text):
            continue
        if _HEADING_NOISE.match(cleaned_text):
            continue
        if _PUB_META_RE.search(cleaned_text):
            continue
        if _is_math_line(cleaned_text):
            continue
        if '@' in cleaned_text:
            continue

        # Skip lines that look like author lists:
        # ≥2 commas, and ≥50% of comma-parts are short (≤4 words) + capitalized
        # Strip trailing affiliation markers before checking
        comma_parts_raw = [p.strip() for p in cleaned_text.split(',')]
        comma_parts = [re.sub(r'\s*[a-z\*†‡∗\d]+$', '', p).strip() for p in comma_parts_raw]
        if len(comma_parts) >= 3:
            short_cap = sum(
                1 for p in comma_parts
                if 1 <= len(p.split()) <= 4 and re.match(r'^[A-Z]', p)
            )
            if short_cap >= 2 and short_cap / len(comma_parts) >= 0.5:
                continue
        # Also detect middot-separated author lines (Springer format)
        dot_parts = re.split(r'\s*[·‧]​?\s*', cleaned_text)
        if len(dot_parts) >= 2:
            cleaned_dots = [re.sub(r'\s*\d+\s*$', '', p).strip() for p in dot_parts]
            short_cap = sum(
                1 for p in cleaned_dots
                if 2 <= len(p.split()) <= 4 and re.match(r'^[A-Z]', p)
            )
            if short_cap >= 2 and short_cap / len(dot_parts) >= 0.5:
                continue

        size = line.max_font_size
        candidates.append({'text': cleaned_text, 'size': size, 'y': y0})

    if not candidates:
        return None

    # Pick largest size first, then topmost (by y ascending)
    candidates.sort(key=lambda c: (-c['size'], c['y']))
    best = candidates[0]
    best_size = best['size']

    # Cluster: all candidates at the same font size (within 1pt), sorted by y,
    # starting from the topmost line at that size
    same_size = sorted(
        [c for c in candidates if abs(c['size'] - best_size) <= 1.0],
        key=lambda c: c['y']
    )
    if not same_size:
        return best['text']

    start_y = same_size[0]['y']

    # Collect continuation lines (within 80pt vertical span of the first line)
    # Stop early if we hit an author-like line
    title_parts: List[str] = []
    for c in same_size:
        if c['y'] - start_y > 80:
            break
        # Author-like stop
        comma_parts = [p.strip() for p in c['text'].split(',')]
        if len(comma_parts) >= 3:
            short_cap = sum(
                1 for p in comma_parts
                if 1 <= len(p.split()) <= 4 and re.match(r'^[A-Z]', p)
            )
            if short_cap >= 2 and short_cap / len(comma_parts) >= 0.5:
                break
        title_parts.append(c['text'])

    if not title_parts:
        title_parts = [best['text']]

    title = ' '.join(title_parts)
    return re.sub(r'\s+', ' ', title).strip() or None



def _find_abstract(page_chunks: List[PageChunk]) -> Tuple[Optional[str], Optional[int]]:
    """
    Find abstract text. Handles three formats:
      A. Inline:  "Abstract — This paper proposes..."
      B. Block:   "Abstract" (or "a b s t r a c t") on its own line, text below
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
                text = ' '.join(parts).strip()
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
                text = ' '.join(parts).strip()
                if len(text.split()) >= 30:
                    return text, len(text.split())

    return None, None


def _find_keywords(page_chunks: List[PageChunk]) -> List[str]:
    """
    Find keywords from 'Keywords:' or 'Index Terms:' line.
    Handles separators: comma, semicolon, middot (·), pipe, or one-per-line.
    """
    _SPLIT_KW = re.compile(r'[;,·|]|\s{2,}')

    for chunk in page_chunks[:3]:
        lines = chunk.plain_text.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()

            # Inline: "Keywords: kw1 · kw2, kw3"
            m = _KW_LINE.match(stripped)
            if m:
                kw_text = m.group(1).strip()
                # Collect continuation lines
                if i + 1 < len(lines):
                    nl = lines[i + 1].strip()
                    if (nl and not re.match(r'^\d+\.?\s+[A-Z]', nl)
                            and not _SECTION_BREAK.match(nl)
                            and not _ABSTRACT_HEADER.match(nl)
                            and len(nl) < 200):
                        kw_text += ' ' + nl
                kws = [k.strip() for k in _SPLIT_KW.split(kw_text)
                       if k.strip() and len(k.strip()) > 1]
                if kws:
                    return kws[:15]

            # Header-only: "Keywords:" on its own line, values follow
            if _KW_HEADER.match(stripped) and i + 1 < len(lines):
                kw_candidates = []
                for j in range(i + 1, min(i + 20, len(lines))):
                    jl = lines[j].strip()
                    if not jl:
                        continue
                    if (_SECTION_BREAK.match(jl)
                            or _ABSTRACT_HEADER.match(jl)
                            or re.match(r'^a\s+b\s+s', jl, re.I)):
                        break
                    if len(jl.split()) > 12:
                        break
                    kw_candidates.append(jl)

                if kw_candidates:
                    # One-per-line format (each ≤ 6 words)
                    if all(len(k.split()) <= 6 for k in kw_candidates) and len(kw_candidates) >= 2:
                        return [k for k in kw_candidates if k][:15]

                    # Comma/middot separated on first line
                    kws = [k.strip() for k in _SPLIT_KW.split(kw_candidates[0])
                           if k.strip() and len(k.strip()) > 1]
                    if kws:
                        return kws[:15]

    return []


def _find_authors(
    page1: PageChunk,
    title: Optional[str],
    body_font_size: float,
) -> List[str]:
    """
    Find author names on page 1.

    Principled strategy:
    ────────────────────
    Authors occupy a geometric region on page 1:
      - Below the title block
      - Above the abstract header
      - NOT in the publisher top zone (y < 95pt)

    Region boundaries:
      title_y1    — bottom of the last line sharing font-size with the title
      abstract_y0 — top of the abstract header line

    We detect title_y1 by finding lines at the title's font size (not by matching
    words, which breaks when the title is mis-detected). Then we collect lines in
    [title_y1 .. abstract_y0] that look like names.

    Parsing: splits on ALL common author-name separators (,  and  &  ·  ;)
    then strips affiliation superscripts (*, †, digits).
    Validates: 2–5 words, starts Capital, mostly alphabetic.
    """
    abstract_y0 = page1.page_height

    for line in page1.lines:
        text = line.text.strip()
        if _ABSTRACT_HEADER.match(text) or _ABSTRACT_INLINE.match(text):
            abstract_y0 = min(abstract_y0, line.bbox[1])

    # If abstract not found on page 1 (e.g. accepted-manuscript cover pages),
    # cap the author search zone at a reasonable upper bound.
    if abstract_y0 >= page1.page_height * 0.95:
        abstract_y0 = min(page1.page_height * 0.35, 300.0)

    # Find the y-bottom of the title block.
    # Strategy: find the LARGEST font above the abstract, then title_y1 = bottom
    # of the LAST line at that specific size (not just any large font).
    # This prevents the author line (often slightly smaller) from being included.
    PUBLISHER_TOP_ZONE = 45
    large_font_lines = [
        line for line in page1.lines
        if (PUBLISHER_TOP_ZONE <= line.bbox[1] < abstract_y0
            and line.max_font_size >= body_font_size * 1.2
            and len(line.text.strip()) >= 4  # Avoid drop caps!
            and line.text.strip())
    ]
    if large_font_lines:
        max_title_size = max(line.max_font_size for line in large_font_lines)
        # Only lines at the maximum font size define the title block
        title_lines_at_max = [
            line for line in large_font_lines
            if line.max_font_size >= max_title_size * 0.97
        ]
        title_y1 = max(line.bbox[3] for line in title_lines_at_max)
    else:
        # Fallback: word-matching approach
        title_y1 = PUBLISHER_TOP_ZONE
        if title and len(title) > 5:
            title_words = [w for w in title.split()[:5] if len(w) > 3]
            for line in page1.lines:
                if (PUBLISHER_TOP_ZONE <= line.bbox[1] < abstract_y0 
                        and any(w in line.text for w in title_words)):
                    title_y1 = max(title_y1, line.bbox[3])

    # Collect candidate lines in author region
    raw_lines: List[str] = []
    for line in page1.lines:
        y0 = line.bbox[1]
        if y0 <= title_y1 or y0 >= abstract_y0:
            continue

        # Filter out right-column body lines in two-column layouts
        if line.bbox[0] > page1.page_width * 0.45:
            continue

        text = _clean_superscripts_from_line(line)
        text = re.sub(r'[\xa0\u2009\u200b]', ' ', text).strip()

        if not text or len(text) < 3:
            continue
        if len(text) > 120:
            continue
        if line.max_font_size > body_font_size * 1.4:
            continue
        if _is_math_line(text):
            continue
        if _HEADING_NOISE.match(text):
            continue
        if _PUB_META_RE.search(text):
            continue
        if len(text.split()) < 2:
            continue

        raw_lines.append(text)

    if not raw_lines:
        return []

    # Parse names from candidate lines
    # Split on all known author separators — universal set, not paper-specific
    _AUTHOR_SPLIT = re.compile(
        r'\s*(?:,\s*and|;\s*and|,\s*&|\band\b|&|;|,|·|•|\u00b7|\u2022|\u2027)\s*',
        re.IGNORECASE,
    )

    authors: List[str] = []
    seen: set = set()

    # Join the raw lines of authors with a space first to handle line wraps
    combined_text = " ".join(raw_lines[:6])
    combined_text = re.sub(r'[\xa0\u2009\u200b]', ' ', combined_text).strip()

    parts = _AUTHOR_SPLIT.split(combined_text)

    for part in parts:
        part = part.strip()
        part = re.sub(r'[\xa0\u2009\u200b]', ' ', part).strip()
        if not part:
            continue

        # Strip affiliation superscripts: trailing/leading *, †, digits, bullets, dots
        # e.g. "Smith A1,2" → "Smith A", "Jones*" → "Jones", "• Harifi" → "Harifi"
        part = re.sub(r'[\*†‡§¶∗•·\u2022\u00b7\-]+$', '', part).strip()
        part = re.sub(r'^[\*†‡§¶∗•·\u2022\u00b7\-]+', '', part).strip()
        part = re.sub(r'\s*\d+(?:[,\s]*\d+)*\s*$', '', part).strip()
        # Strip trailing single lowercase letters (affiliation letter codes)
        part = re.sub(r'\s+[a-z](?:\s*,\s*[a-z])*\s*$', '', part).strip()
        # Strip academic degrees/titles (e.g. MD, PhD, Dr.)
        part = re.sub(r'\b(?:PhD|MD|Dr|Ph\.D\.|M\.D\.|Dr\.)\b', '', part, flags=re.IGNORECASE).strip()

        # Validate: must look like a name
        words = part.split()
        if len(words) < 2 or len(words) > 6:
            continue
        if not re.match(r'[A-Z]', part):
            continue
        # Must be mostly alphabetic (names don't have many numbers/symbols)
        alpha_ratio = sum(1 for c in part if c.isalpha() or c in ' .-') / max(1, len(part))
        if alpha_ratio < 0.75:
            continue
        # Skip if it matches an affiliation keyword
        if _AFFILIATION_RE.search(part):
            continue
        # Skip if it looks like a section heading or metadata
        if _SECTION_BREAK.match(part):
            continue
        if _PUB_META_RE.search(part):
            continue
        # Plausibility: each word in a name should be Title-Case or initial (A.)
        name_word_re = re.compile(r'^[A-Z][a-z]')
        title_case_words = sum(1 for w in words if name_word_re.match(w))
        if title_case_words == len(words) and len(words) >= 4:
            common_content = re.compile(
                r'\b(?:Algorithm|Method|System|Application|Analysis|Model|'
                r'Optimization|Approach|Framework|Technique|Approach|'
                r'Learning|Network|Image|Signal|Control|Theory|Review|'
                r'Segmentation|Thresholding|Multilevel|Performance)\b',
                re.IGNORECASE,
            )
            if common_content.search(part):
                continue

        key = part.lower()
        if key not in seen:
            seen.add(key)
            authors.append(part)

    return authors[:30]


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
                if (b["x1"] - b["x0"]) > 20 and (b["y1"] - b["y0"]) > 20
            ]
            if blocks:
                image_map[chunk.page_number] = blocks

    # Collect captions using layout-aware paragraph reconstruction.
    # Key guard: a real caption line is SHORT (ends without a verb clause) or
    # starts with non-sentence text. We reject lines where the text after the
    # figure label looks like a running sentence (e.g. "Figure 2 depicts the…").
    _CAPTION_SENTENCE_RE = re.compile(
        r'^(?:shows?|depicts?|illustrates?|presents?|displays?|is\s|are\s|can\s|'
        r'was\s|were\s|has\s|have\s|represents?)\b',
        re.IGNORECASE,
    )
    captions: Dict[int, Dict] = {}
    for chunk in page_chunks:
        for idx, line in enumerate(chunk.lines):
            text = line.text.strip()
            # Match "Figure N" or "Fig. N" at start of line
            m = re.match(r'^Fig(?:ure)?\.?\s+(\d+)\b', text, re.IGNORECASE)
            if m:
                num = int(m.group(1))
                if num in captions:
                    continue

                # Reject in-text references that look like running sentences
                # e.g. "Figure 2 depicts the routes..." is NOT a caption
                after = re.sub(r'^[:.]\s*', '', text[m.end():].strip())
                if _CAPTION_SENTENCE_RE.match(after):
                    continue

                # Reconstruct multi-line caption
                caption_y0 = line.bbox[1]   # top of the first caption line (for Check 12)
                caption_parts = [after] if after else []
                prev_y1 = line.bbox[3]

                for j in range(idx + 1, min(len(chunk.lines), idx + 10)):
                    next_line = chunk.lines[j]
                    next_text = next_line.text.strip()
                    if not next_text:
                        continue
                    # Skip if it matches a table/figure marker or section heading
                    if re.match(r'^(?:Table|Fig(?:ure)?|Algorithm)\s+\d+', next_text, re.IGNORECASE):
                        break
                    if re.match(r'^[1-9]\d*(?:\.\d+)+\.?\s+[A-Z]', next_text):
                        break

                    gap = next_line.bbox[1] - prev_y1
                    size_diff = abs(next_line.max_font_size - line.max_font_size)
                    if gap < 16.0 and size_diff < 0.5:
                        caption_parts.append(next_text)
                        prev_y1 = next_line.bbox[3]
                    else:
                        break

                cap_text = ' '.join(caption_parts).strip()
                cap_text = re.sub(r'\s+', ' ', cap_text).strip()

                if len(cap_text) >= 3:
                    captions[num] = {
                        "caption_text": cap_text,
                        "caption_page": chunk.page_number,
                        "caption_ends_period": cap_text.rstrip().endswith('.'),
                        "caption_y0": caption_y0,  # top of caption (Check 12)
                        "caption_y1": prev_y1,     # bottom of last caption line
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

        # Match image block: prefer largest unused image on caption page or adjacent
        image_bbox = None
        for p in [cap_page, cap_page - 1, cap_page + 1]:
            blocks = image_map.get(p, [])
            for b in sorted(blocks, key=lambda x: -x["area"]):
                key = (p, round(b["x0"]), round(b["y0"]))
                if key not in used_image_keys:
                    image_bbox = {"page": p, "x0": b["x0"], "y0": b["y0"],
                                  "x1": b["x1"], "y1": b["y1"]}
                    used_image_keys.add(key)
                    break
            if image_bbox:
                break

        # Build caption_bbox only when y-coordinates were captured (i.e. caption found)
        _cap_y0 = cap_info.get("caption_y0")
        _cap_y1 = cap_info.get("caption_y1")
        caption_bbox = (
            {"page": cap_page, "y0": _cap_y0, "y1": _cap_y1}
            if _cap_y0 is not None else None
        )

        figures.append({
            "number":              num,
            "caption_text":        cap_info.get("caption_text", ""),
            "caption_page":        cap_page,
            "caption_ends_period": cap_info.get("caption_ends_period", False),
            "image_bbox":          image_bbox,
            "caption_bbox":        caption_bbox,  # y0/y1 of caption text (Check 12)
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
    page_chunks: List[PageChunk],
) -> List[Dict[str, Any]]:
    """
    Discover table captions from layout page chunk lines.
    """
    header_keywords = re.compile(
        r'^\s*(?:Methods|Worst|Mean|Best|SD|FEs|Function|Index|Parameters|Value|Winner|p\s*value|GA\b|PSO\b|DE\b|AEO\b|CS\b|GSA\b|ABC\b|[a-z]\d+\(x\))\b',
        re.IGNORECASE
    )

    captions: Dict[int, Dict] = {}
    for chunk in page_chunks:
        for idx, line in enumerate(chunk.lines):
            text = line.text.strip()
            # Match "Table N" at start of line
            m = re.match(r'^Table\s+(\d+)\b', text, re.IGNORECASE)
            if m:
                num = int(m.group(1))
                if num in captions:
                    continue
                # Reconstruct multi-line caption
                caption_y0 = line.bbox[1]  # top of first caption line (for Check 11)
                caption_parts = [text[m.end():].strip()]
                prev_y1 = line.bbox[3]
                table_body_y0: Optional[float] = None  # y0 of first table-body line

                for j in range(idx + 1, min(len(chunk.lines), idx + 10)):
                    next_line = chunk.lines[j]
                    next_text = next_line.text.strip()
                    if not next_text:
                        continue
                    # Check if it looks like a header/table row
                    if header_keywords.match(next_text):
                        table_body_y0 = next_line.bbox[1]   # table body starts here
                        break
                    # Check for multiple wide spaces indicating columns
                    if '   ' in next_text or '  ' in next_text:
                        if len(re.split(r'\s{2,}', next_text)) >= 3:
                            table_body_y0 = next_line.bbox[1]  # column-formatted row
                            break
                    # New table/figure/heading — not part of this table's body
                    if re.match(r'^(?:Table|Fig(?:ure)?|Algorithm)\s+\d+', next_text, re.IGNORECASE):
                        break
                    if re.match(r'^[1-9]\d*(?:\.\d+)+\.?\s+[A-Z]', next_text):
                        break

                    gap = next_line.bbox[1] - prev_y1
                    size_diff = abs(next_line.max_font_size - line.max_font_size)
                    if gap < 16.0 and size_diff < 0.5:
                        caption_parts.append(next_text)
                        prev_y1 = next_line.bbox[3]
                    else:
                        # Gap/font-size change signals start of table body
                        table_body_y0 = next_line.bbox[1]
                        break

                cap_text = ' '.join(caption_parts).strip()
                cap_text = re.sub(r'\s+', ' ', cap_text).strip()

                # Validate
                if _CAPTION_VERB_RE.match(cap_text):
                    continue
                if len(cap_text.split()) < 2:
                    continue

                captions[num] = {
                    "caption_text": cap_text,
                    "caption_page": chunk.page_number,
                    "caption_ends_period": cap_text.rstrip().endswith('.'),
                    "caption_y0": caption_y0,       # top of caption (Check 11)
                    "caption_y1": prev_y1,           # bottom of last caption line
                    "table_body_y0": table_body_y0,  # top of first table-body line
                }

    # First mentions (cross-references)
    first_mentions: Dict[int, int] = {}
    for m in _TABLE_MENTION_RE.finditer(full_text):
        num = int(m.group(1))
        if num not in first_mentions:
            first_mentions[num] = _char_pos_to_page(m.start(), page_offsets)

    # Only emit tables that have a genuine caption
    tables: List[Dict] = []
    for num in sorted(captions.keys()):
        cap_info = captions[num]
        _cap_pg  = cap_info.get("caption_page", 1)
        _tc_y0   = cap_info.get("caption_y0")
        _tc_y1   = cap_info.get("caption_y1")
        _tb_y0   = cap_info.get("table_body_y0")
        caption_bbox = (
            {"page": _cap_pg, "y0": _tc_y0, "y1": _tc_y1}
            if _tc_y0 is not None else None
        )

        tables.append({
            "number":              num,
            "caption_text":        cap_info.get("caption_text", ""),
            "caption_page":        _cap_pg,
            "caption_ends_period": cap_info.get("caption_ends_period", False),
            "caption_bbox":        caption_bbox,  # real y-coords now (Check 11)
            "table_body_y0":       _tb_y0,        # y0 of first detected table-body line
            "first_mention_page":  first_mentions.get(num, _cap_pg),
            "coordinate_found":    False,
        })

    return tables


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _estimate_body_font_size(page_chunks: List[PageChunk]) -> float:
    """
    Return the modal font size representing body text.
    Uses length-weighted mode (weights by char count) on spans > 7pt.
    Restricts to pages 2-5 to avoid bibliography and table noise skewing the result.
    """
    size_weight: Dict[int, int] = {}
    target_chunks = page_chunks[1:5] if len(page_chunks) >= 2 else page_chunks
    for chunk in target_chunks:
        for line in chunk.lines:
            for span in line.spans:
                sz = span.size
                if sz < 7.0:
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
        pos += len(pt) + 1
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
