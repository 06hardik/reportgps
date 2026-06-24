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

# DOI pattern inside a reference string
_DOI = re.compile(
    r'(?:doi:|https?://doi\.org/)(\S+)',
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


def extract_references(full_text: str) -> List[Dict[str, Any]]:
    """
    Extract reference list entries from the full document text.

    Returns a list of dicts with keys:
        raw_string, number, year, doi, url
    """
    refs: List[Dict[str, Any]] = []
    seen: set = set()

    # Locate bibliography section start to avoid matching citations in body text
    headers = ["references", "bibliography", "literature cited"]
    start_pos = 0
    for h in headers:
        pos = full_text.lower().rfind(h)
        if pos > start_pos:
            if pos == 0 or not full_text[pos - 1].isalnum():
                start_pos = pos

    ref_text = full_text[start_pos:] if start_pos > 0 else full_text

    # Try numbered-bracket style first  [1] ...
    for m in _NUMBERED_REF.finditer(ref_text):
        num = int(m.group(1))
        raw = m.group(0).strip()
        body = m.group(2).strip()

        # Collect continuation lines (non-blank lines without a new [N] marker)
        raw = _collect_continuation(ref_text, m.end(), raw)

        key = raw[:80].lower()
        if key in seen:
            continue
        seen.add(key)

        refs.append({
            "raw_string":  raw,
            "number":      num,
            "year":        _find_year(raw),
            "doi":         _find_doi(raw),
            "url":         _find_url(raw),
            "entry_type":  None,
        })

    if refs:
        return sorted(refs, key=lambda r: r["number"] or 0)

    # Fallback: dot-number style  1. ...
    for m in _DOTNUM_REF.finditer(ref_text):
        num = int(m.group(1))
        raw = m.group(0).strip()
        raw = _collect_continuation(ref_text, m.end(), raw)

        key = raw[:80].lower()
        if key in seen:
            continue
        seen.add(key)

        refs.append({
            "raw_string":  raw,
            "number":      num,
            "year":        _find_year(raw),
            "doi":         _find_doi(raw),
            "url":         _find_url(raw),
            "entry_type":  None,
        })

    return sorted(refs, key=lambda r: r["number"] or 0)


def _collect_continuation(text: str, start: int, current: str) -> str:
    """
    Read continuation lines after a reference opening line.
    Stop at blank lines or a new numbered reference marker.
    """
    lines = text[start:start + 600].splitlines()
    for line in lines[:6]:
        stripped = line.strip()
        if not stripped:
            break
        if _NUMBERED_REF.match(line) or _DOTNUM_REF.match(line):
            break
        current += " " + stripped
    return current.strip()


def _find_year(text: str) -> int | None:
    m = _YEAR.search(text)
    return int(m.group(1)) if m else None


def _find_doi(text: str) -> str | None:
    m = _DOI.search(text)
    return m.group(0) if m else None


def _find_url(text: str) -> str | None:
    m = _URL.search(text)
    url = m.group(1) if m else None
    if url and 'doi.org' in url:
        return url  # keep doi URLs
    return url


# ─────────────────────────────────────────────────────────────────────────────
# In-text citation extraction
# ─────────────────────────────────────────────────────────────────────────────

# [1], [1,2], [1-3], [1, 2, 3]
_NUMERIC_BRACKET = re.compile(
    r'(\[[\d,\s\-–]+\])',
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

    for m in _NUMERIC_BRACKET.finditer(full_text):
        _add(m.group(1), "numeric-bracket", m.start())

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
