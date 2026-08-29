"""
regex_extractor.py
==================
Fast, regex-based extractor for references and in-text citations.

These two tasks are given to the LLM in many pipelines but actually work
BETTER with regex:
  - References are highly structured (numbered, author-year, etc.)
  - In-text citations have well-known patterns ([1], [1,2], (Smith, 2020))
  - Regex preserves verbatim text perfectly (no hallucination risk)
  - Regex is ~100x faster than an LLM call

This module is called ONCE on the full document text (all pages concatenated
by the orchestrator) rather than page-by-page, which also improves
reference detection across page boundaries.
"""

from __future__ import annotations

import re
from typing import List, Dict, Any
import pymupdf as fitz  # PyMuPDF

# ─────────────────────────────────────────────────────────────────────────────
# Reference extraction
# ─────────────────────────────────────────────────────────────────────────────

# Matches:  [1] Smith, J. ...   or   [12] ...
_NUMBERED_REF = re.compile(
    r'^\s*\[(\d+)\]\s+(.+)',
    re.MULTILINE,
)

# Matches IEEE/ACM style: 1. Smith, J. ...
_DOTNUM_REF = re.compile(
    r'^\s*(\d+)\.\s+([A-Z].+)',
    re.MULTILINE,
)

# Matches APA/Author-Year style: Lastname, F. M. (Year). ...
_APA_REF = re.compile(
    r'^\s*([A-Z][^(\n]{2,120}\(((?:19|20)\d{2})\)\s*\..+)',
    re.MULTILINE,
)
_APA_START = re.compile(
    r'^\s*[A-Z][^(\n]{2,120}\(((?:19|20)\d{2})\)\s*\.',
)

# DOI pattern inside a reference string (supporting spaces)
_DOI = re.compile(
    r'(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)\s*(\S+)',
    re.IGNORECASE,
)

# URL pattern
_URL = re.compile(
    r'(https?://\S+)',
)

# Year in parentheses or bare 4-digit year (1900–2099)
_YEAR = re.compile(
    r'\b((?:19|20)\d{2})\b',
)


def extract_references(full_text: str, pdf_path: str | None = None) -> List[Dict[str, Any]]:
    """
    Extract reference list entries from the full document text.

    Returns a list of dicts with keys:
        raw_string, number, year, doi, url
    """
    if pdf_path:
        try:
            return _extract_references_layout(pdf_path)
        except Exception as e:
            print(f"[RegexExtractor] Layout reference extraction failed, falling back to text: {e}")
    # Locate bibliography section start using a robust line-based search
    headers_regex = re.compile(
        r'^\s*(references|bibliography|literature cited|reference)\s*$', 
        re.IGNORECASE | re.MULTILINE
    )
    
    header_matches = list(headers_regex.finditer(full_text))
    start_pos = 0
    if header_matches:
        best_match = header_matches[-1]
        for m in reversed(header_matches):
            if m.start() > len(full_text) * 0.5:
                best_match = m
                break
        start_pos = best_match.start()
    else:
        # Fallback to substring rfind search
        headers = ["references", "bibliography", "literature cited"]
        for h in headers:
            pos = full_text.lower().rfind(h)
            if pos > start_pos:
                if pos == 0 or not full_text[pos - 1].isalnum():
                    start_pos = pos

    ref_text = full_text[start_pos:] if start_pos > 0 else full_text

    # Extract using three different styles
    
    # ── Style A: Numbered brackets [1] ────────────────────────────────────────
    refs_a: List[Dict[str, Any]] = []
    seen_a: set = set()
    for m in _NUMBERED_REF.finditer(ref_text):
        num = int(m.group(1))
        raw = m.group(0).strip()
        raw = _collect_continuation(ref_text, m.end(), raw)
        key = raw[:80].lower()
        if key not in seen_a:
            seen_a.add(key)
            refs_a.append({
                "raw_string":  raw,
                "number":      num,
                "year":        _find_year(raw),
                "doi":         _find_doi(raw),
                "url":         _find_url(raw),
                "entry_type":  None,
            })
            
    # ── Style B: Dotted numbers 1. ────────────────────────────────────────────
    refs_b: List[Dict[str, Any]] = []
    seen_b: set = set()
    for m in _DOTNUM_REF.finditer(ref_text):
        num = int(m.group(1))
        raw = m.group(0).strip()
        raw = _collect_continuation(ref_text, m.end(), raw)
        key = raw[:80].lower()
        if key not in seen_b:
            seen_b.add(key)
            refs_b.append({
                "raw_string":  raw,
                "number":      num,
                "year":        _find_year(raw),
                "doi":         _find_doi(raw),
                "url":         _find_url(raw),
                "entry_type":  None,
            })
            
    # ── Style C: APA Author-Year (un-numbered) ────────────────────────────────
    refs_c: List[Dict[str, Any]] = []
    seen_c: set = set()
    for m in _APA_REF.finditer(ref_text):
        raw = m.group(0).strip()
        raw = _collect_continuation(ref_text, m.end(), raw)
        key = raw[:80].lower()
        if key not in seen_c:
            seen_c.add(key)
            refs_c.append({
                "raw_string":  raw,
                "number":      None,
                "year":        _find_year(raw),
                "doi":         _find_doi(raw),
                "url":         _find_url(raw),
                "entry_type":  None,
            })

    # Select the method that extracted the maximum number of references
    candidates = [
        ("numbered-bracket", refs_a),
        ("dot-number", refs_b),
        ("apa-style", refs_c)
    ]
    candidates.sort(key=lambda item: len(item[1]), reverse=True)
    best_style, best_refs = candidates[0]
    
    print(f"[RegexExtractor] Selected reference style: {best_style} (found {len(best_refs)} references)")
    print(f"  - numbered-bracket: {len(refs_a)}")
    print(f"  - dot-number:       {len(refs_b)}")
    print(f"  - apa-style:        {len(refs_c)}")

    if best_style == "numbered-bracket" or best_style == "dot-number":
        return sorted(best_refs, key=lambda r: r["number"] or 0)
    else:
        return best_refs


def _collect_continuation(text: str, start: int, current: str) -> str:
    """
    Read continuation lines after a reference opening line.
    Stop at blank lines, new reference starting markers, or noise tables.
    """
    remainder = text[start:start + 600]
    if remainder.startswith('\n'):
        remainder = remainder[1:]
    elif remainder.startswith('\r\n'):
        remainder = remainder[2:]

    lines = remainder.splitlines()
    for line in lines[:6]:
        stripped = line.strip()
        if not stripped:
            break
        if _NUMBERED_REF.match(line) or _DOTNUM_REF.match(line) or _APA_START.match(line):
            break
        if "ACCEPTED MANUSCRIPT" in stripped or re.match(r'^(Table|Figure|Fig\.)\s+\d+', stripped, re.IGNORECASE):
            break
        current += " " + stripped
    return current.strip()


def _find_year(text: str) -> int | None:
    m = _YEAR.search(text)
    return int(m.group(1)) if m else None


def _find_doi(text: str) -> str | None:
    m = _DOI.search(text)
    if m:
        return re.sub(r'\s+', '', m.group(0))
    return None


def _extract_references_layout(pdf_path: str) -> List[Dict[str, Any]]:
    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    ref_header_re = re.compile(
        r'^\s*(?:\d+\.?\s+)?(?:references|bibliography|literature cited)\s*$',
        re.IGNORECASE
    )
    caption_re = re.compile(r'^\s*(?:Table|Figure|Fig|Figs)\b', re.IGNORECASE)

    ref_start_page_idx = None
    for page_idx in range(total_pages - 1, -1, -1):
        page = doc[page_idx]
        page_height = page.rect.height
        raw = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES)
        has_header = False
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_bbox = line.get("bbox", (0, 0, 0, 0))
                y0, y1 = line_bbox[1], line_bbox[3]
                if y0 < 55 or y1 > page_height - 55:
                    continue
                line_text = "".join(s.get("text", "") for s in line.get("spans", [])).strip()
                if ref_header_re.match(line_text):
                    has_header = True
                    break
            if has_header:
                break
        if has_header:
            ref_start_page_idx = page_idx
            break

    if ref_start_page_idx is None:
        raise ValueError("References section header not found in PDF pages.")

    pages_to_process = range(ref_start_page_idx, total_pages)
    all_ref_lines = []

    for page_idx in pages_to_process:
        page = doc[page_idx]
        page_width = page.rect.width
        page_height = page.rect.height

        raw = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES)
        lines_data = []
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_bbox = line.get("bbox", (0, 0, 0, 0))
                y0, y1 = line_bbox[1], line_bbox[3]
                if y0 < 55 or y1 > page_height - 55:
                    continue
                line_text = "".join(s.get("text", "") for s in line.get("spans", []))
                if caption_re.match(line_text):
                    continue
                if not line_text.strip():
                    continue
                lines_data.append({
                    "text": line_text,
                    "bbox": line_bbox,
                    "x0": line_bbox[0],
                    "y0": line_bbox[1],
                    "x1": line_bbox[2],
                    "y1": line_bbox[3],
                    "page_num": page_idx + 1,
                })

        if not lines_data:
            continue

        # Detect layout columns: if substantial lines start at x0 > page_width * 0.45
        right_col_lines = [l for l in lines_data if l["x0"] > page_width * 0.45]
        is_two_column = len(right_col_lines) > 3 and len(right_col_lines) > 0.1 * len(lines_data)
        for l in lines_data:
            l["is_two_column"] = is_two_column

        if is_two_column:
            left_lines = [l for l in lines_data if l["x0"] <= page_width * 0.45]
            right_lines = [l for l in lines_data if l["x0"] > page_width * 0.45]
            left_lines.sort(key=lambda l: l["y0"])
            right_lines.sort(key=lambda l: l["y0"])
            columns = []
            if left_lines:
                columns.append(left_lines)
            if right_lines:
                columns.append(right_lines)
        else:
            lines_data.sort(key=lambda l: l["y0"])
            columns = [lines_data]

        # Slicing the start page at references header
        if page_idx == ref_start_page_idx:
            header_found = False
            header_col_idx = -1
            header_line_idx = -1
            for col_idx, col in enumerate(columns):
                for l_idx, l in enumerate(col):
                    if ref_header_re.match(l["text"].strip()):
                        header_found = True
                        header_col_idx = col_idx
                        header_line_idx = l_idx
                        break
                if header_found:
                    break
            if header_found:
                new_columns = []
                for col_idx, col in enumerate(columns):
                    if col_idx < header_col_idx:
                        continue
                    elif col_idx == header_col_idx:
                        sliced_col = col[header_line_idx + 1:]
                        if sliced_col:
                            new_columns.append(sliced_col)
                    else:
                        new_columns.append(col)
                columns = new_columns

        for col in columns:
            if col:
                all_ref_lines.append(col)

    if not all_ref_lines:
        raise ValueError("No text lines found in references section.")

    # Classify bibliography style
    flat_lines = [l for col in all_ref_lines for l in col]
    bracket_prefix_re = re.compile(r'^\s*\[(?!(?:19|20)\d{2}\])\d+\]')
    dotnum_prefix_re = re.compile(r'^\s*(?!(?:19|20)\d{2}\.)\d+\.\s+')

    bracket_count = sum(1 for l in flat_lines if bracket_prefix_re.match(l["text"]))
    dotnum_count = sum(1 for l in flat_lines if dotnum_prefix_re.match(l["text"]))

    if bracket_count >= 3 and bracket_count >= dotnum_count:
        style = "numbered-bracket"
    elif dotnum_count >= 3:
        style = "dot-number"
    else:
        style = "apa-style"

    # Partition lines into individual reference items
    items = []
    current_item_lines = []

    is_first_col = True
    for col in all_ref_lines:
        if not col:
            continue
        col_x0_min = min(l["x0"] for l in col)
        # Check if this column has indented lines
        has_indents = any(line["x0"] >= col_x0_min + 5.5 for line in col)

        for idx, l in enumerate(col):
            is_start = False
            text = l["text"]

            if style == "numbered-bracket":
                if bracket_prefix_re.match(text):
                    is_start = True
            elif style == "dot-number":
                if dotnum_prefix_re.match(text):
                    is_start = True
            else: # APA style
                if idx == 0:
                    if is_first_col:
                        is_start = True
                    else:
                        if has_indents:
                            if l.get("is_two_column"):
                                is_start = (l["x0"] < col_x0_min + 5.0)
                            else:
                                is_start = (l["x0"] < col_x0_min + 5.5)
                        else:
                            is_start = True
                else:
                    prev = col[idx - 1]
                    if has_indents:
                        if l.get("is_two_column"):
                            is_start = (l["x0"] < col_x0_min + 5.0) or ((l["y0"] - prev["y1"]) > 4.5)
                        else:
                            is_start = (l["x0"] < col_x0_min + 5.5) or ((l["y0"] - prev["y1"]) > 4.0)
                    else:
                        is_start = ((l["y0"] - prev["y1"]) > 4.0)

            if is_start:
                if current_item_lines:
                    items.append(current_item_lines)
                current_item_lines = [l]
            else:
                if current_item_lines:
                    current_item_lines.append(l)
                else:
                    current_item_lines = [l]

        is_first_col = False

    if current_item_lines:
        items.append(current_item_lines)

    # Construct final list of references
    results = []
    for item in items:
        raw_string = " ".join(line["text"] for line in item).strip()
        raw_string = re.sub(r'\s+', ' ', raw_string)
        if not raw_string:
            continue

        raw_string = re.sub(r'-\s+', '-', raw_string)
        raw_string = re.sub(r'/\s+', '/', raw_string)
        raw_string = re.sub(r'\.\s+(com|org|net|edu|gov|mil|int)\b', r'.\1', raw_string)

        year = _find_year(raw_string)

        m_doi = _DOI.search(raw_string)
        if m_doi:
            doi = re.sub(r'\s+', '', m_doi.group(0))
        else:
            _BARE_DOI = re.compile(r'\b(10\.\d{4,9}/\S+)', re.IGNORECASE)
            m_bare = _BARE_DOI.search(raw_string)
            if m_bare:
                doi = re.sub(r'\s+', '', m_bare.group(1))
            else:
                doi = None

        if doi:
            doi = doi.rstrip('.,;()[]{}')

        url = _find_url(raw_string)

        num = None
        if style == "numbered-bracket":
            m_num = bracket_prefix_re.match(item[0]["text"])
            if m_num:
                digit_match = re.search(r'\d+', m_num.group(0))
                if digit_match:
                    num = int(digit_match.group(0))
        elif style == "dot-number":
            m_num = dotnum_prefix_re.match(item[0]["text"])
            if m_num:
                digit_match = re.search(r'\d+', m_num.group(0))
                if digit_match:
                    num = int(digit_match.group(0))

        # Set reference bbox directly from lines' bounding boxes and set coordinate_found = True
        first_page = item[0]["page_num"]
        lines_on_first_page = [l for l in item if l["page_num"] == first_page]
        x0_min = min(l["x0"] for l in lines_on_first_page)
        y0_min = min(l["y0"] for l in lines_on_first_page)
        x1_max = max(l["x1"] for l in lines_on_first_page)
        y1_max = max(l["y1"] for l in lines_on_first_page)

        ref_dict = {
            "raw_string": raw_string,
            "number": num,
            "year": year,
            "doi": doi,
            "url": url,
            "entry_type": None,
            "bbox": {
                "page": first_page,
                "x0": x0_min,
                "y0": y0_min,
                "x1": x1_max,
                "y1": y1_max,
            },
            "coordinate_found": True,
            "_page_hint": first_page,
        }
        results.append(ref_dict)

    if style == "numbered-bracket" or style == "dot-number":
        return sorted(results, key=lambda r: r["number"] or 0)
    else:
        return results


def _find_url(text: str) -> str | None:
    m = _URL.search(text)
    url = m.group(1) if m else None
    if url and 'doi.org' in url:
        return url  # keep doi URLs
    return url


# ─────────────────────────────────────────────────────────────────────────────
# In-text citation extraction
# ─────────────────────────────────────────────────────────────────────────────

# [1], [1,2], [1-3], [1, 2, 3]  — requires at least one number >= 1 (never [0])
_NUMERIC_BRACKET = re.compile(
    r'(\[[1-9][\d,\s\-\u2013]*\])',
)

# Superscript numbers attached to words: word^1,2  (common in PDFs extracted as plain text)
_SUPERSCRIPT_NUM = re.compile(
    r'\b\w{3,}\s*(\d{1,2}(?:,\d{1,2})*)\b',
)

# (Smith, 2020), (Smith and Jones, 2020), (Smith et al., 2020)
_AUTHOR_YEAR = re.compile(
    r'\(([A-Z][a-zA-Z]+(?:\s+(?:and|&|et al\.?))?\s*(?:[A-Z][a-zA-Z]+)?(?:,\s*(?:19|20)\d{2})?)\)',
)

_CONTEXT_WINDOW = 60   # chars each side


def extract_in_text_citations(
    full_text: str,
    page_texts: list[str],
    references: List[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Extract in-text citation markers from the full document text.

    Returns list of dicts with keys:
        marker, style, context_snippet, page_number
    """
    citations: List[Dict[str, Any]] = []
    seen_markers: set = set()

    # Build page-start offsets for page number attribution
    page_offsets = _build_page_offsets(page_texts)

    def _add(marker: str, style: str, pos: int) -> None:
        norm = marker.strip()
        if norm in seen_markers:
            return
        seen_markers.add(norm)
        ctx_start = max(0, pos - _CONTEXT_WINDOW)
        ctx_end   = min(len(full_text), pos + len(norm) + _CONTEXT_WINDOW)
        snippet   = full_text[ctx_start:ctx_end].replace("\n", " ").strip()
        page_num  = _find_page(pos, page_offsets)
        citations.append({
            "marker":          norm,
            "style":           style,
            "context_snippet": snippet,
            "page_number":     page_num,
        })

    is_numeric_style = False
    max_ref_num = 0
    if references:
        ref_nums = [r.get("number") for r in references if r.get("number") is not None]
        if ref_nums:
            is_numeric_style = True
            max_ref_num = max(ref_nums)
        else:
            is_numeric_style = False

    for m in _NUMERIC_BRACKET.finditer(full_text):
        # If we have extracted references and none of them have numbers, this document 
        # uses author-year style. Any bracketed number like [2020] is a false positive.
        if references and not is_numeric_style:
            continue
            
        marker_text = m.group(1)
        
        # If it is numeric style, ensure the numbers in the bracket aren't absurdly high
        # (e.g. capturing an array like [250, 500, 1000] when there are only 50 references)
        if is_numeric_style and max_ref_num > 0:
            nums = [int(n) for n in re.findall(r'\d+', marker_text)]
            if nums and max(nums) > max_ref_num + 5:  # small buffer for missing refs
                continue
                
        _add(marker_text, "numeric-bracket", m.start())

    for m in _AUTHOR_YEAR.finditer(full_text):
        _add(m.group(0), "author-year", m.start())

    return citations


def _build_page_offsets(page_texts: list[str]) -> list[int]:
    offsets = []
    pos = 0
    for pt in page_texts:
        offsets.append(pos)
        pos += len(pt) + 1  # +1 for newline separator
    return offsets


def _find_page(char_pos: int, offsets: list[int]) -> int:
    """Return 1-based page number for a character position in the full text."""
    page = 1
    for i, offset in enumerate(offsets):
        if char_pos >= offset:
            page = i + 1
        else:
            break
    return page
