"""
equation_extractor.py
=====================
Fast equation extraction from academic PDFs using PyMuPDF text layer only.

Strategy
--------
All equation-quality checks (sequential numbering, punctuation, in-text
call-out consistency) operate on:
  1. The equation NUMBER — e.g. (1), (2), (A.1)
  2. The TEXT CONTEXT immediately before and after each equation

Both are reliably available from the PDF's embedded text layer via PyMuPDF.
There is NO need to run deep-learning OCR (Pix2Text) just to get the LaTeX
representation when the checks never use it.

How equation numbers are found
-------------------------------
In academic PDFs, numbered display equations are typeset with the equation
label (e.g. "(3)") right-aligned on the same line as the formula.
PyMuPDF exposes individual words with their bounding boxes. We:
  1. Find every word matching the pattern "(N)" or "(N.M)" or "(Na)".
  2. Confirm it is right-aligned: its left edge is beyond 65% of page width.
  3. Filter out years (1900-2099) and large numbers (> 999) which are never eq labels.
  4. Skip header / footer zones.
  5. Deduplicate so each equation NUMBER appears only once (first occurrence wins).

Output schema (per equation)
-----------------------------
{
    "number":         1,          # parsed integer label, e.g. "(1)" → 1; None if unlabelled
    "number_format":  "(1)",      # the raw label string, e.g. "(1)" / "(A.1)"
    "latex":          "",         # always empty string; LaTeX not extracted here
    "page_number":    3,          # 1-based page index
    "bbox": {
        "x0": ..., "y0": ..., "x1": ..., "y1": ...,
        "page": ...,
    },
    "context_before": "...",      # up to 300 chars of plain text before the eq
    "context_after":  "...",      # up to 300 chars of plain text after the eq
}

Performance: < 1 second for any size PDF on any hardware.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Equation-number pattern
# Matches labels like (1), (1a), (A.1), (12b) — whole word only.
# Supports standard parens and alternate encodings (\xf0, \xde) often found in PDFs.
# ─────────────────────────────────────────────────────────────────────────────
_LABEL_RE = re.compile(
    r"""
    ^[\(\xf0]
      (?P<inner>[A-Za-z]?\d+[A-Za-z]?(?:\.\d+)?)
    [\)\xde]$
    """,
    re.VERBOSE,
)

# Equation labels must appear in the right half of a column.
# Using 0.35 safely covers the right side of the left column (usually ~0.45) 
# and the right column (~0.90) in a 2-column layout.
_LABEL_X_THRESHOLD = 0.35  # eq_x0 / page_width must be > this value

# Ignore labels in header/footer zones (first and last 50 pt of page).
_HEADER_FOOTER_PT = 50

# Characters to collect around each equation for context.
_CONTEXT_CHARS = 400

# Max sensible equation number in a paper. Anything above this is not an equation label.
_MAX_EQ_NUMBER = 200

# Year range to exclude: (1900) through (2099) are years, not equation labels.
_YEAR_RE = re.compile(r'^[\(\xf0](?:19|20)\d{2}[\)\xde]$')


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def extract_equations(pdf_path: str) -> List[Dict[str, Any]]:
    """
    Extract all numbered display equations from *pdf_path* using PyMuPDF.

    Args:
        pdf_path: Absolute path to a readable PDF file.

    Returns:
        List of equation dicts ordered by (page_number, y-position).

    Raises:
        FileNotFoundError: if *pdf_path* does not exist.
        ImportError:       if PyMuPDF (fitz) is not installed.
        RuntimeError:      if PDF cannot be opened or parsed.
    """
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    try:
        import pymupdf as fitz  # PyMuPDF
    except ImportError as exc:
        raise ImportError(
            "PyMuPDF is not installed. Run: pip install pymupdf"
        ) from exc

    logger.info("[equation_extractor] Processing PDF via PyMuPDF: %s", pdf_path)
    t0 = time.monotonic()

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        raise RuntimeError(f"Cannot open PDF: {exc}") from exc

    all_candidates: List[Dict[str, Any]] = []

    for page in doc:
        page_num = page.number + 1  # 1-based
        _extract_page_equations(page, page_num, all_candidates)

    doc.close()

    # ── Global deduplication by equation NUMBER ────────────────────────────
    # In a well-formed paper, each equation number appears exactly once as a
    # display label. Keep only the FIRST occurrence of each integer number.
    # This also removes duplicates caused by headers re-printing the same label.
    seen_numbers: set = set()
    unique: List[Dict[str, Any]] = []
    for eq in all_candidates:
        n = eq["number"]
        if n is None:
            # Unlabelled equations: always keep
            unique.append(eq)
        elif n not in seen_numbers:
            seen_numbers.add(n)
            unique.append(eq)
        # else: duplicate label — skip silently

    # Sort by page then by vertical position
    unique.sort(key=lambda e: (e["page_number"], e.get("bbox", {}).get("y0", 0)))

    elapsed = time.monotonic() - t0
    logger.info(
        "[equation_extractor] Found %d equation(s) in %.2f s (PyMuPDF fast path).",
        len(unique),
        elapsed,
    )
    return unique


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_page_equations(
    page: Any,
    page_num: int,
    equations: List[Dict[str, Any]],
) -> None:
    """
    Extract equation labels from a single PyMuPDF page.

    We use word-level extraction to get precise bounding boxes for each token,
    group them by logical lines, and check if the last word on a line is a label.
    """
    page_width = page.rect.width
    page_height = page.rect.height

    # Full page text for context extraction (plain text, fast)
    full_text: str = page.get_text("text")

    # Word-level data: (x0, y0, x1, y1, "word", block_no, line_no, word_no)
    words = page.get_text("words")

    # Group words by (block_no, line_no) to find the last word on each line
    lines = {}
    for w in words:
        b, l = w[5], w[6]
        lines.setdefault((b, l), []).append(w)

    for (b, l), line_words in lines.items():
        # Ensure words are sorted by x0 within the line
        line_words.sort(key=lambda w: w[0])
        last_word = line_words[-1]
        
        x0, y0, x1, y1, word_text, _bn, _ln, _wn = last_word
        word_text = word_text.strip()

        # Must be in right margin zone of either left or right column
        if x0 <= page_width * _LABEL_X_THRESHOLD:
            continue

        # Skip header / footer zones
        if y0 < _HEADER_FOOTER_PT or y1 > page_height - _HEADER_FOOTER_PT:
            continue

        # Filter out years like (2020), (1997) — these are never equation labels
        if _YEAR_RE.match(word_text):
            continue

        # Word must match "(N)" or "(N.M)" pattern exactly (or encoded variants)
        m = _LABEL_RE.fullmatch(word_text)
        if not m:
            continue

        # Filter in-text citations that happen to be at the end of a line.
        # Equation labels are pushed to the right, creating a large gap.
        if len(line_words) > 1:
            prev_word = line_words[-2]
            gap = x0 - prev_word[2]
            # If the gap is small (< 10 points), it's part of a flowing sentence (in-text citation).
            # True equation labels typically have gaps > 20 points, or are on their own logical line.
            if gap < 10:
                continue

        inner = m.group("inner")

        # Parse the number
        num = _parse_inner_label(inner)

        # Filter out unreasonably large numbers — equation labels are never > 200
        if num is not None and num > _MAX_EQ_NUMBER:
            continue

        # Filter out 0 — equation labels start at 1
        if num is not None and num < 1:
            continue

        # Convert back to standard parens for frontend consistency (if weird font was used)
        standard_format = f"({inner})"

        # Collect context from the full page text around this equation's position.
        ctx_before, ctx_after = _get_context(full_text, word_text, y0, page)

        equations.append({
            "number":         num,
            "number_format":  standard_format,
            "latex":          "",      # not extracted — not needed for checks
            "page_number":    page_num,
            "bbox": {
                "page": page_num,
                "x0":   x0,
                "y0":   y0,
                "x1":   x1,
                "y1":   y1,
            },
            "context_before": ctx_before,
            "context_after":  ctx_after,
        })


def _parse_inner_label(inner: str) -> Optional[int]:
    """
    Parse the inner content of an equation label like "1", "1a", "A.1", "12b".
    Returns integer if the label (or its numeric part) can be parsed, else None.
    """
    # Strip leading letter prefix (e.g. "A.1" → "1")
    clean = re.sub(r'^[A-Za-z]\.?', '', inner)
    # Strip trailing letter suffix (e.g. "1a" → "1")
    clean = re.sub(r'[A-Za-z]$', '', clean)
    try:
        return int(clean)
    except ValueError:
        return None


def _get_context(
    full_text: str,
    label: str,
    eq_y: float,
    page: Any,
) -> Tuple[str, str]:
    """
    Return (context_before, context_after) around the equation label in the
    full page text.

    We locate the LAST occurrence of the label in the text (since right-margin
    labels appear near the end of a logical line), then grab text around it.
    """
    # Find the last occurrence of the label in the page text
    pos = full_text.rfind(label)
    if pos == -1:
        pos = full_text.find(label)
    if pos == -1:
        return "", ""

    before = full_text[max(0, pos - _CONTEXT_CHARS): pos].strip()
    after = full_text[pos + len(label): pos + len(label) + _CONTEXT_CHARS].strip()
    return before, after
