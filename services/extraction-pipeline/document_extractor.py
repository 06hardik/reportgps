"""
document_extractor.py
=====================
The core structural extractor — PyMuPDF-first, laser-focused on 5 key elements:

  1. Manuscript metadata  — title, abstract (full text), authors, keywords
  2. Sections             — heading + ALL body paragraph text beneath it
  3. References           — complete multi-line raw strings from the refs section
  4. Equations            — equation text + (N) label, extracted from text blocks
  5. Tables               — caption + position (Camelot provides the actual grid)

Philosophy:
  - PyMuPDF knows font sizes, bold flags, and block geometry. Use those signals
    directly rather than asking an LLM to re-read plain text.
  - The "References" section is identified by heading, then ALL text inside it
    is re-parsed as numbered entries — no single-line truncation.
  - Section body text is collected by slicing the block stream between headings.
  - Equations are detected by the (N) right-margin label + indent pattern.
  - NuExtract is NOT called for any of these — it remains for caption position
    and typography signals only.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF


# ─────────────────────────────────────────────────────────────────────────────
# Internal data types
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RawBlock:
    """A single text block from PyMuPDF with metadata."""
    text:      str
    page:      int
    x0: float; y0: float; x1: float; y1: float
    max_font:  float
    is_bold:   bool
    is_italic: bool


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def extract_document_structure(pdf_path: str) -> Dict[str, Any]:
    """
    Full structural extraction from a PDF.

    Returns:
        {
          "manuscript":    { title, abstract_text, abstract_word_count,
                             authors, keywords, keywords_section_present },
          "sections":      [ { heading_text, heading_number, heading_level,
                               page_number, body_text, bbox } ],
          "references":    [ { raw_string, number, year, doi, url } ],
          "equations":     [ { number, number_format, raw_text, page_number, bbox } ],
          "table_captions":[ { label, number, caption_text, caption_position,
                               page_number, bbox } ],
          "figure_captions":[ { label, number, caption_text, caption_position,
                                page_number, bbox } ],
        }
    """
    doc = fitz.open(pdf_path)
    try:
        blocks = _extract_all_blocks(doc)
        body_size = _estimate_body_font_size(blocks)

        sections          = _extract_sections(blocks, body_size)
        refs              = _extract_references(blocks, sections)
        equations         = _extract_equations(blocks, body_size)
        table_caps, fig_caps = _extract_captions(blocks, body_size)
        manuscript        = _extract_manuscript(blocks, sections, body_size)

        return {
            "manuscript":      manuscript,
            "sections":        sections,
            "references":      refs,
            "equations":       equations,
            "table_captions":  table_caps,
            "figure_captions": fig_caps,
        }
    finally:
        doc.close()


# ─────────────────────────────────────────────────────────────────────────────
# Block extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_all_blocks(doc: fitz.Document) -> List[RawBlock]:
    """Extract all text blocks from all pages with font metadata."""
    blocks: List[RawBlock] = []
    for page_idx, page in enumerate(doc):
        page_num = page_idx + 1
        raw = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES)
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            block_text_parts = []
            max_size  = 0.0
            has_bold  = False
            has_italic = False
            for line in block.get("lines", []):
                line_text = ""
                for span in line.get("spans", []):
                    t = span.get("text", "")
                    line_text += t
                    sz = float(span.get("size", 0))
                    fl = span.get("flags", 0)
                    if sz > max_size:
                        max_size = sz
                    if fl & 16:
                        has_bold = True
                    if fl & 2:
                        has_italic = True
                stripped = line_text.strip()
                if stripped:
                    block_text_parts.append(stripped)

            text = " ".join(block_text_parts).strip()
            if not text:
                continue

            bbox = block.get("bbox", (0, 0, 0, 0))
            blocks.append(RawBlock(
                text=text,
                page=page_num,
                x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3],
                max_font=max_size,
                is_bold=has_bold,
                is_italic=has_italic,
            ))
    return blocks


def _estimate_body_font_size(blocks: List[RawBlock]) -> float:
    """Modal font size across all blocks = body text size."""
    sizes = [round(b.max_font) for b in blocks if b.max_font > 4]
    if not sizes:
        return 10.0
    return float(Counter(sizes).most_common(1)[0][0])


# ─────────────────────────────────────────────────────────────────────────────
# Heading detection
# ─────────────────────────────────────────────────────────────────────────────

_NUMBERED_HEADING = re.compile(
    r'^(\d+(?:\.\d+)*(?:\.\d+)*)\s*\.?\s+(.+)$'
)
_APPENDIX_HEADING = re.compile(
    r'^(Appendix\s+[A-Z][\w\.]*)\s*[\.:]?\s*(.*)$',
    re.IGNORECASE,
)
# Standalone keywords that are section headings in academic papers
_KNOWN_SECTIONS = re.compile(
    r'^(Abstract|Introduction|Related Work|Background|Methodology|Method|'
    r'Proposed|Results?|Experiments?|Discussion|Conclusion|Future Work|'
    r'Acknowledgements?|References?|Appendix)[\s\.:]*$',
    re.IGNORECASE,
)


def _is_heading(block: RawBlock, body_size: float) -> Tuple[bool, str, int]:
    """
    Returns (is_heading, heading_number_str, level).
    Level: 1 = top, 2 = sub, 3 = sub-sub.
    """
    text = block.text.strip()
    # Too long to be a heading (body paragraph)
    if len(text) > 200:
        return False, "", 0
    # Too short
    if len(text) < 2:
        return False, "", 0

    # Numbered heading: "3.1 Limitations of GSA"
    m = _NUMBERED_HEADING.match(text)
    if m:
        num = m.group(1)
        level = num.count(".") + 1
        return True, num, min(level, 3)

    # Appendix heading
    m = _APPENDIX_HEADING.match(text)
    if m:
        return True, m.group(1), 1

    # Known section names
    if _KNOWN_SECTIONS.match(text):
        return True, "", 1

    # Font-size heuristic: bigger font or bold in a short line
    if block.max_font >= body_size + 1.5 and len(text) < 120:
        return True, "", 1
    if block.is_bold and len(text) < 100 and len(text) > 3:
        return True, "", 1

    return False, "", 0


# ─────────────────────────────────────────────────────────────────────────────
# Section extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_sections(blocks: List[RawBlock], body_size: float) -> List[Dict[str, Any]]:
    """
    Detect headings and collect all body text between consecutive headings.
    Returns list of section dicts with body_text populated.
    """
    sections: List[Dict[str, Any]] = []
    current_heading: Optional[Dict] = None
    body_parts: List[str] = []

    for block in blocks:
        is_h, num, level = _is_heading(block, body_size)
        if is_h:
            # Save previous section
            if current_heading is not None:
                current_heading["body_text"] = "\n\n".join(body_parts).strip()
                sections.append(current_heading)
            body_parts = []
            current_heading = {
                "heading_text":   block.text.strip(),
                "heading_number": num or None,
                "heading_level":  level,
                "page_number":    block.page,
                "body_text":      "",
                "bbox": {
                    "page": block.page,
                    "x0": block.x0, "y0": block.y0,
                    "x1": block.x1, "y1": block.y1,
                },
            }
        else:
            if current_heading is not None:
                body_parts.append(block.text)

    # Save last section
    if current_heading is not None:
        current_heading["body_text"] = "\n\n".join(body_parts).strip()
        sections.append(current_heading)

    return sections


# ─────────────────────────────────────────────────────────────────────────────
# Reference extraction — full multi-line strings from the references section
# ─────────────────────────────────────────────────────────────────────────────

_REF_SECTION_HEADING = re.compile(
    r'^references?$',
    re.IGNORECASE,
)
_NUMBERED_REF_START = re.compile(r'^\[(\d+)\]\s+(.+)')
_DOTNUM_REF_START   = re.compile(r'^(\d+)\.\s+([A-Z].+)')
_DOI_PAT = re.compile(r'(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)\s*(\S+)', re.IGNORECASE)
_URL_PAT = re.compile(r'(https?://\S+)')
_YEAR_PAT = re.compile(r'\b((?:19|20)\d{2})\b')


def _extract_references(
    blocks: List[RawBlock],
    sections: List[Dict],
) -> List[Dict[str, Any]]:
    """
    Locate the References section and parse COMPLETE multi-line reference strings.
    """
    # Find the start page/block index of the references section
    ref_section_start_idx = None
    for i, block in enumerate(blocks):
        if _REF_SECTION_HEADING.match(block.text.strip()):
            ref_section_start_idx = i + 1
            break

    if ref_section_start_idx is None:
        # No explicit References heading — try to find numbered entries
        # in the last 30% of blocks
        ref_section_start_idx = int(len(blocks) * 0.7)

    ref_blocks = blocks[ref_section_start_idx:]

    # Collect all text from the references section
    ref_texts = [b.text for b in ref_blocks]
    full_ref_text = "\n".join(ref_texts)

    refs = _parse_numbered_refs(full_ref_text)
    if not refs:
        refs = _parse_dotnum_refs(full_ref_text)

    return refs


def _parse_numbered_refs(text: str) -> List[Dict[str, Any]]:
    """Parse [N] Author, Title... style references, collecting continuation lines."""
    refs = []
    seen = set()

    # Split into candidate reference entries by [N] markers
    # Find all positions of [N] markers
    starts = [(m.start(), int(m.group(1))) for m in re.finditer(r'^\[(\d+)\]', text, re.MULTILINE)]
    if not starts:
        return []

    for i, (pos, num) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        raw = text[pos:end].strip()

        # Clean: join hyphenated line-breaks, collapse whitespace
        raw = _clean_ref_text(raw)

        key = raw[:60].lower()
        if key in seen:
            continue
        seen.add(key)

        refs.append({
            "raw_string": raw,
            "number":     num,
            "year":       _first_year(raw),
            "doi":        _first_doi(raw),
            "url":        _first_url(raw),
        })

    return sorted(refs, key=lambda r: r["number"])


def _parse_dotnum_refs(text: str) -> List[Dict[str, Any]]:
    """Parse N. Author, Title... style references."""
    refs = []
    seen = set()

    starts = [(m.start(), int(m.group(1))) for m in re.finditer(r'^(\d+)\.\s+[A-Z]', text, re.MULTILINE)]
    if not starts:
        return []

    for i, (pos, num) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        raw = text[pos:end].strip()
        raw = _clean_ref_text(raw)

        key = raw[:60].lower()
        if key in seen:
            continue
        seen.add(key)

        refs.append({
            "raw_string": raw,
            "number":     num,
            "year":       _first_year(raw),
            "doi":        _first_doi(raw),
            "url":        _first_url(raw),
        })

    return sorted(refs, key=lambda r: r["number"])


def _clean_ref_text(raw: str) -> str:
    """Normalise a raw reference string: collapse whitespace, join hyphenated breaks."""
    # Join lines
    raw = " ".join(raw.splitlines())
    # Collapse multiple spaces
    raw = re.sub(r' {2,}', ' ', raw)
    # Remove hyphenation at line breaks: "algo- rithm" → "algorithm"
    raw = re.sub(r'(\w+)-\s+(\w)', lambda m: m.group(1) + m.group(2), raw)
    return raw.strip()


def _first_year(text: str) -> Optional[int]:
    m = _YEAR_PAT.search(text)
    return int(m.group(1)) if m else None

def _first_doi(text: str) -> Optional[str]:
    m = _DOI_PAT.search(text)
    if m:
        return re.sub(r'\s+', '', m.group(0))
    return None

def _first_url(text: str) -> Optional[str]:
    m = _URL_PAT.search(text)
    return m.group(1) if m else None


# ─────────────────────────────────────────────────────────────────────────────
# Equation extraction
# ─────────────────────────────────────────────────────────────────────────────

_EQ_LABEL = re.compile(r'\((\d+)\)\s*$')


def _extract_equations(blocks: List[RawBlock], body_size: float) -> List[Dict[str, Any]]:
    """
    Detect numbered equations by the (N) right-margin label pattern.
    Short, indented blocks ending with (N) are equation blocks.
    """
    equations = []
    seen_nums = set()

    for block in blocks:
        text = block.text.strip()
        m = _EQ_LABEL.search(text)
        if not m:
            continue

        num = int(m.group(1))
        if num in seen_nums:
            continue
        seen_nums.add(num)

        # The equation text is everything before the label
        eq_text = text[:m.start()].strip()

        equations.append({
            "number":        num,
            "number_format": f"({num})",
            "raw_text":      eq_text,
            "page_number":   block.page,
            "bbox": {
                "page": block.page,
                "x0": block.x0, "y0": block.y0,
                "x1": block.x1, "y1": block.y1,
            },
        })

    return sorted(equations, key=lambda e: e["number"])


# ─────────────────────────────────────────────────────────────────────────────
# Caption extraction (figure + table)
# ─────────────────────────────────────────────────────────────────────────────

_FIG_CAPTION  = re.compile(r'^(Fig(?:ure)?\.?\s*(\d+))[\.:\s]', re.IGNORECASE)
_TBL_CAPTION  = re.compile(r'^(Table\s*(\d+))[\.:\s]', re.IGNORECASE)


def _extract_captions(
    blocks: List[RawBlock],
    body_size: float,
) -> Tuple[List[Dict], List[Dict]]:
    """Return (table_captions, figure_captions)."""
    table_caps = []
    figure_caps = []
    seen_figs = set()
    seen_tbls = set()

    for i, block in enumerate(blocks):
        text = block.text.strip()

        # Table caption
        m = _TBL_CAPTION.match(text)
        if m:
            num = int(m.group(2))
            if num not in seen_tbls:
                seen_tbls.add(num)
                # Determine if caption is above or below by looking at adjacent blocks
                pos = _caption_position(blocks, i, "table")
                table_caps.append({
                    "label":          m.group(1),
                    "number":         num,
                    "caption_text":   text,
                    "caption_position": pos,
                    "page_number":    block.page,
                    "bbox": {
                        "page": block.page,
                        "x0": block.x0, "y0": block.y0,
                        "x1": block.x1, "y1": block.y1,
                    },
                })
            continue

        # Figure caption
        m = _FIG_CAPTION.match(text)
        if m:
            num = int(m.group(2))
            if num not in seen_figs:
                seen_figs.add(num)
                pos = _caption_position(blocks, i, "figure")
                figure_caps.append({
                    "label":          m.group(1),
                    "number":         num,
                    "caption_text":   text,
                    "caption_position": pos,
                    "page_number":    block.page,
                    "bbox": {
                        "page": block.page,
                        "x0": block.x0, "y0": block.y0,
                        "x1": block.x1, "y1": block.y1,
                    },
                })

    return (
        sorted(table_caps,  key=lambda t: t["number"]),
        sorted(figure_caps, key=lambda f: f["number"]),
    )


def _caption_position(blocks: List[RawBlock], cap_idx: int, kind: str) -> str:
    """
    Heuristic: table captions should be ABOVE, figure captions BELOW.
    Returns "above" or "below" based on what's actually in the PDF.
    A large non-text block (image) or a Camelot table area just below
    this caption → caption is above the element.
    """
    # Check y-position relative to same-page blocks immediately following
    cap = blocks[cap_idx]
    for j in range(cap_idx + 1, min(cap_idx + 5, len(blocks))):
        nxt = blocks[j]
        if nxt.page != cap.page:
            break
        # If the next block is text that doesn't look like another caption,
        # it could be the body — meaning the caption is above
        if nxt.y0 > cap.y1:
            return "above"  # something is below the caption
    return "below"


# ─────────────────────────────────────────────────────────────────────────────
# Manuscript metadata extraction
# ─────────────────────────────────────────────────────────────────────────────

_AUTHOR_LINE = re.compile(
    r'\b([A-Z][a-z]+(?:\.\s?)?(?:[A-Z][a-z]+)*)\s*,?\s*([A-Z]\.(?:\s?[A-Z]\.)*)',
)
_EMAIL = re.compile(r'\b[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}\b')
_KEYWORDS_HEADER = re.compile(r'^keywords?\s*[:.]?', re.IGNORECASE)


def _extract_manuscript(
    blocks: List[RawBlock],
    sections: List[Dict],
    body_size: float,
) -> Dict[str, Any]:
    """
    Extract title, abstract, authors, keywords from the first few pages.

    Strategy:
      - Title: largest-font block on page 1
      - Abstract: body_text of section with heading "Abstract"
      - Keywords: block immediately after keyword header
      - Authors: text on page 1 between title and abstract using author-name pattern
    """
    # Abstract from sections list
    abstract_text = ""
    abstract_section = next(
        (s for s in sections if re.search(r'abstract', s["heading_text"], re.IGNORECASE)),
        None,
    )
    if abstract_section:
        abstract_text = abstract_section["body_text"]

    # Title: largest font block on page 1, must be reasonable length
    page1_blocks = [b for b in blocks if b.page == 1]
    title = ""
    if page1_blocks:
        # Sort by font size descending, pick largest non-trivial block
        candidates = sorted(
            [b for b in page1_blocks if 5 < len(b.text) < 300],
            key=lambda b: b.max_font,
            reverse=True,
        )
        if candidates:
            title = candidates[0].text.strip()

    # Keywords: find keyword header block, grab following block's text
    keywords = []
    for i, block in enumerate(blocks):
        if block.page > 3:
            break
        if _KEYWORDS_HEADER.match(block.text.strip()):
            # Keywords might be in the same block after the header
            kw_text = re.sub(r'^keywords?\s*[:.]?\s*', '', block.text, flags=re.IGNORECASE)
            if kw_text.strip():
                keywords = [k.strip() for k in re.split(r'[;,]', kw_text) if k.strip()]
            elif i + 1 < len(blocks):
                kw_text = blocks[i + 1].text.strip()
                keywords = [k.strip() for k in re.split(r'[;,]', kw_text) if k.strip()]
            break

    # Keywords may also be a label + content in the abstract block
    if not keywords and abstract_text:
        m = re.search(r'[Kk]eywords?\s*[:.]?\s*(.+?)(?:\n|$)', abstract_text)
        if m:
            keywords = [k.strip() for k in re.split(r'[;,]', m.group(1)) if k.strip()]

    word_count = len(abstract_text.split()) if abstract_text else 0

    return {
        "title":                    title,
        "abstract_text":            abstract_text,
        "abstract_word_count":      word_count,
        "keywords":                 keywords,
        "keywords_section_present": len(keywords) > 0,
        "authors":                  [],   # populated by NuExtract Pass B
        "publishing_statements": {
            "conflict_of_interest":          None,
            "ethics_statement":              None,
            "funding_statement":             None,
            "data_access_statement":         None,
            "author_contribution_statement": None,
        },
    }
