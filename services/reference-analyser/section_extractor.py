"""
section_extractor.py
====================
Detect named sections in a research paper PDF using font-size/bold heuristics
(with keyword-only fallback) and extract:
  - Per-section plain text + page list
  - Raw reference strings from the References section (for the 5-check pipeline)
"""
from __future__ import annotations

import re
from statistics import mode as stats_mode
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF

# ── Section heading patterns (strict: must be the WHOLE line) ───────────────
_SECTION_RE: Dict[str, re.Pattern] = {
    "abstract":        re.compile(r"^abstract\s*$", re.I),
    "introduction":    re.compile(r"^(?:\d+\.?\s+)?introduction\s*$", re.I),
    "related":         re.compile(r"^(?:\d+\.?\s+)?related\s+work\s*$", re.I),
    "methods":         re.compile(r"^(?:\d+\.?\s+)?(?:methods?|methodology|materials?\s+(?:and\s+)?methods?|experimental(?:\s+section)?|experiments?)\s*$", re.I),
    "results":         re.compile(r"^(?:\d+\.?\s+)?(?:results?|findings?)\s*$", re.I),
    "discussion":      re.compile(r"^(?:\d+\.?\s+)?discussion\s*$", re.I),
    "conclusion":      re.compile(r"^(?:\d+\.?\s+)?conclusions?\s*$", re.I),
    "acknowledgements":re.compile(r"^(?:\d+\.?\s+)?acknowledg(?:e?ments?)\s*$", re.I),
    "references":      re.compile(r"^(?:references?|bibliography|works?\s+cited)\s*$", re.I),
}

# Minimum ratio of a line's font size to body font size to count as heading
_HEADING_RATIO = 1.05
_MIN_HEAD_LEN  = 3
_MAX_HEAD_LEN  = 80


# ────────────────────────────────────────────────────────────────────────────
# Public entry point
# ────────────────────────────────────────────────────────────────────────────

def extract_sections(pdf_path: str) -> Dict[str, dict]:
    """
    Returns a dict keyed by section name:
    {
      "abstract":   {"text": "...", "pages": [1]},
      "body":       {"text": "...", "pages": [2,3,...,11]},
      "references": {"text": "...", "pages": [12],
                     "raw_strings": ["[1] Smith J...", "[2] ...]},
      ...
    }
    Missing sections are absent from the dict.
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"section_extractor: cannot open PDF: {e}")
        return {}

    blocks = _collect_blocks(doc)
    doc.close()

    if not blocks:
        return {}

    body_size = _estimate_body_font(blocks)
    headings  = _find_headings(blocks, body_size)

    if headings:
        return _slice_sections(blocks, headings)
    else:
        return _keyword_fallback(blocks)


# ────────────────────────────────────────────────────────────────────────────
# Block collection
# ────────────────────────────────────────────────────────────────────────────

def _collect_blocks(doc: fitz.Document) -> List[dict]:
    """
    Extract every text line from the PDF with its font size, bold flag, and page.
    Falls back to raw page text if get_text("dict") fails.
    """
    all_blocks = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_num = page_idx + 1  # 1-indexed

        try:
            raw = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
            for block in raw.get("blocks", []):
                if block.get("type") != 0:   # 0 = text block
                    continue
                for line in block.get("lines", []):
                    line_text = ""
                    max_size  = 0.0
                    is_bold   = False
                    for span in line.get("spans", []):
                        line_text += span.get("text", "")
                        sz = float(span.get("size", 0))
                        if sz > max_size:
                            max_size = sz
                        if span.get("flags", 0) & 16:   # flag bit 4 = bold
                            is_bold = True

                    line_text = line_text.strip()
                    if line_text and max_size > 0:
                        all_blocks.append({
                            "page": page_num,
                            "text": line_text,
                            "size": max_size,
                            "bold": is_bold,
                        })
        except Exception:
            # Fallback: plain text, assign default size
            plain = page.get_text().strip()
            for line in plain.splitlines():
                line = line.strip()
                if line:
                    all_blocks.append({"page": page_num, "text": line,
                                       "size": 10.0, "bold": False})

    return all_blocks


# ────────────────────────────────────────────────────────────────────────────
# Font-size analysis
# ────────────────────────────────────────────────────────────────────────────

def _estimate_body_font(blocks: List[dict]) -> float:
    sizes = [round(b["size"]) for b in blocks if b["size"] > 0]
    if not sizes:
        return 10.0
    try:
        return float(stats_mode(sizes))
    except Exception:
        sizes.sort()
        return float(sizes[len(sizes) // 2])


# ────────────────────────────────────────────────────────────────────────────
# Heading detection
# ────────────────────────────────────────────────────────────────────────────

def _find_headings(blocks: List[dict], body_size: float) -> List[Tuple[int, str, int]]:
    """
    Returns [(block_index, section_key, page_num), ...] in document order.
    A block is a heading candidate if its font is larger than body OR it is bold,
    AND its text matches one of our section patterns.
    """
    threshold = body_size * _HEADING_RATIO
    headings: List[Tuple[int, str, int]] = []

    for i, b in enumerate(blocks):
        text = b["text"].strip()
        if not (_MIN_HEAD_LEN <= len(text) <= _MAX_HEAD_LEN):
            continue
        is_prominent = (b["size"] >= threshold) or b["bold"]
        if not is_prominent:
            continue
        for key, pat in _SECTION_RE.items():
            if pat.match(text):
                headings.append((i, key, b["page"]))
                break  # one match per block

    return headings


# ────────────────────────────────────────────────────────────────────────────
# Section slicing
# ────────────────────────────────────────────────────────────────────────────

def _slice_sections(
    blocks: List[dict],
    headings: List[Tuple[int, str, int]],
) -> Dict[str, dict]:
    result: Dict[str, dict] = {}

    for si, (start_idx, section_key, _start_page) in enumerate(headings):
        end_idx = headings[si + 1][0] if si + 1 < len(headings) else len(blocks)

        section_blocks = blocks[start_idx + 1: end_idx]
        text  = "\n".join(b["text"] for b in section_blocks).strip()
        pages = sorted({b["page"] for b in section_blocks})

        entry: dict = {"text": text, "pages": pages}
        if section_key == "references":
            entry["raw_strings"] = split_reference_section(text)

        # Merge: if section appears twice (rare) concatenate
        if section_key in result:
            result[section_key]["text"]  += "\n" + text
            result[section_key]["pages"]  = sorted(set(result[section_key]["pages"]) | set(pages))
            if "raw_strings" in entry:
                result[section_key].setdefault("raw_strings", []).extend(entry["raw_strings"])
        else:
            result[section_key] = entry

    # Synthesise "body" = abstract..references minus heading blocks
    body_text, body_pages = _build_body(blocks, headings)
    if body_text:
        result["body"] = {"text": body_text, "pages": body_pages}

    return result


def _build_body(
    blocks: List[dict],
    headings: List[Tuple[int, str, int]],
) -> Tuple[str, List[int]]:
    """
    Body = everything between the first content section and References.
    Excludes the heading lines themselves.
    """
    # Indices that are heading lines
    heading_idxs = {idx for idx, _, _ in headings}
    ref_idx = next((idx for idx, key, _ in headings if key == "references"), len(blocks))
    # Start after abstract or introduction (whichever comes first)
    first_content_idx = next(
        (idx for idx, key, _ in headings if key in ("abstract", "introduction")), 0
    )

    body_parts: List[str] = []
    body_pages: set = set()
    for i in range(first_content_idx + 1, ref_idx):
        if i in heading_idxs:
            continue
        b = blocks[i]
        body_parts.append(b["text"])
        body_pages.add(b["page"])

    return "\n".join(body_parts).strip(), sorted(body_pages)


# ────────────────────────────────────────────────────────────────────────────
# Keyword-only fallback (no font analysis)
# ────────────────────────────────────────────────────────────────────────────

def _keyword_fallback(blocks: List[dict]) -> Dict[str, dict]:
    full_text = "\n".join(b["text"] for b in blocks)
    result: Dict[str, dict] = {}

    ref_match = re.search(r"(?im)^(?:references?|bibliography|works?\s+cited)\s*$", full_text)
    if ref_match:
        ref_text = full_text[ref_match.end():].strip()
        result["references"] = {
            "text": ref_text,
            "pages": [],
            "raw_strings": split_reference_section(ref_text),
        }
        result["body"] = {
            "text": full_text[:ref_match.start()].strip(),
            "pages": [],
        }
    else:
        result["body"] = {"text": full_text, "pages": []}

    return result


# ────────────────────────────────────────────────────────────────────────────
# Reference string splitter (standalone — also called externally)
# ────────────────────────────────────────────────────────────────────────────

def split_reference_section(ref_text: str) -> List[str]:
    """
    Split a reference section into individual reference strings.
    Tries strategies in order:
      1. [N] at start of line     (IEEE / numeric with brackets)
      2. N. at start of line      (Vancouver / numbered list)
      3. Line-based (one ref per non-trivial line)  ← last resort
    """
    if not ref_text:
        return []

    # Strategy 1 — [N] style
    parts = re.split(r"(?m)(?=^\s*\[\d+\])", ref_text)
    entries = [p.strip() for p in parts
               if p.strip() and re.match(r"\s*\[\d+\]", p)]
    if len(entries) >= 2:
        return entries

    # Strategy 2 — N. at line start followed by uppercase letter
    parts = re.split(r"(?m)(?=^\s*\d+\.\s+[A-Z])", ref_text)
    entries = [p.strip() for p in parts
               if p.strip() and re.match(r"\s*\d+\.", p)]
    if len(entries) >= 2:
        return entries

    # Strategy 3 — line-by-line (each substantive line = one reference)
    lines = [l.strip() for l in ref_text.splitlines()
             if l.strip() and len(l.strip()) > 15]
    return lines
