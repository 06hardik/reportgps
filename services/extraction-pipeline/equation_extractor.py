"""
equation_extractor.py
=====================
Pix2Text wrapper for extracting numbered display equations from academic PDFs.

Strategy
--------
We use Pix2Text's `recognize_pdf()` method which:
  1. Renders each page at a high-enough DPI internally.
  2. Runs Mathematical Formula Detection (MFD) to locate math regions.
  3. Runs Mathematical Formula Recognition (MFR) on each detected region,
     returning LaTeX for every formula block.
  4. Returns a document object whose pages contain typed content blocks.

We then filter for "isolated" / display-equation blocks and cross-reference
the surrounding text context (the blocks immediately before and after each
formula block on the same page) so that the checker can assess punctuation
and in-text call-out patterns.

Model singleton
---------------
Pix2Text loads ~300–700 MB of model weights on the first call.  We
instantiate a single `Pix2Text` object at module import time so that every
FastAPI request reuses the warm model — loading happens once at startup.

Output schema (per equation)
-----------------------------
{
    "number":         1,          # parsed integer label, e.g. "(1)" → 1; None if unlabelled
    "number_format":  "(1)",      # the raw label string as it appeared, e.g. "(1)" / "[1]"
    "latex":          "...",      # LaTeX string produced by MFR
    "page_number":    3,          # 1-based page index
    "context_before": "...",      # up to 300 chars of plain text preceding the equation
    "context_after":  "...",      # up to 300 chars of plain text following the equation
}
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Equation-number patterns
# Matches labels like (1), (1a), (A.1), [1] at the START or END of a string.
# ─────────────────────────────────────────────────────────────────────────────
_LABEL_RE = re.compile(
    r"""
    (?:                              # opening delimiter
        \(  (?P<paren>[A-Za-z0-9][A-Za-z0-9.\-]*)  \)   # (1) / (A.1) / (1a)
      | \[  (?P<brack>[0-9]+)                       \]   # [1]
    )
    """,
    re.VERBOSE,
)

# ─────────────────────────────────────────────────────────────────────────────
# Pix2Text singleton — loaded once at module import
# ─────────────────────────────────────────────────────────────────────────────
_p2t_instance: Optional[Any] = None


def _get_p2t() -> Any:
    """
    Return the module-level Pix2Text singleton, creating it on first call.
    Raises ImportError if pix2text is not installed.
    """
    global _p2t_instance
    if _p2t_instance is None:
        try:
            from pix2text import Pix2Text  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "pix2text is not installed. Run: pip install pix2text"
            ) from exc

        logger.info("[equation_extractor] Loading Pix2Text model (first call) …")
        t0 = time.monotonic()
        # Pass device='cpu' to avoid ONNXRuntime CoreMLExecutionProvider bugs on macOS 
        # (dynamic sequence length reshaping error in CoreML).
        _p2t_instance = Pix2Text.from_config(device='cpu')
        logger.info(
            "[equation_extractor] Pix2Text model loaded in %.1f s.",
            time.monotonic() - t0,
        )
    return _p2t_instance


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def extract_equations(pdf_path: str) -> List[Dict[str, Any]]:
    """
    Extract all numbered display equations from *pdf_path* using Pix2Text.

    Args:
        pdf_path: Absolute path to a readable PDF file.

    Returns:
        List of equation dicts ordered by (page_number, position).
        See module docstring for the per-equation schema.

    Raises:
        FileNotFoundError: if *pdf_path* does not exist.
        ImportError:       if pix2text is not installed.
        RuntimeError:      if Pix2Text fails to process the document.
    """
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    p2t = _get_p2t()

    logger.info("[equation_extractor] Processing PDF: %s", pdf_path)
    t0 = time.monotonic()

    try:
        # recognize_pdf returns a Pix2Text document object.
        # Each page is a list of content blocks; each block has:
        #   .type   : "text" | "formula" | "isolated" | "embedding" | ...
        #   .text   : rendered text / LaTeX string
        #   .meta   : dict with positional info if available
        doc = p2t.recognize_pdf(pdf_path)
    except Exception as exc:
        raise RuntimeError(f"Pix2Text failed to process PDF: {exc}") from exc

    elapsed = time.monotonic() - t0
    logger.info(
        "[equation_extractor] Pix2Text finished in %.1f s. Parsing blocks …",
        elapsed,
    )

    equations: List[Dict[str, Any]] = []
    _parse_document(doc, equations)

    # Sort by page then by natural document order (insertion order is already
    # page-sequential, but sort defensively).
    equations.sort(key=lambda e: (e["page_number"], e.get("_block_index", 0)))

    # Strip internal ordering key before returning
    for eq in equations:
        eq.pop("_block_index", None)

    logger.info(
        "[equation_extractor] Found %d equation(s). Pix2Text time: %.1f s.",
        len(equations),
        elapsed,
    )
    return equations


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_document(doc: Any, equations: List[Dict[str, Any]]) -> None:
    """
    Walk the Pix2Text document object and collect display-equation blocks.

    Pix2Text's document can be structured as:
      - doc.pages  → list of pages
      - page.elements (or page.blocks, depending on version)
    We handle both naming conventions gracefully.
    """
    pages = _get_pages(doc)
    if not pages:
        logger.warning("[equation_extractor] No pages found in Pix2Text output.")
        return

    for page_idx, page in enumerate(pages):
        page_number = page_idx + 1  # 1-based
        blocks = _get_blocks(page)
        _parse_blocks(blocks, page_number, equations)


def _get_pages(doc: Any) -> List[Any]:
    """Return the list of page objects from a Pix2Text document."""
    # Try common attribute names across Pix2Text versions
    for attr in ("pages", "page_list", "document_pages"):
        pages = getattr(doc, attr, None)
        if pages is not None:
            return list(pages)

    # If the doc itself is iterable (some versions return a list of pages)
    try:
        return list(doc)
    except TypeError:
        return []


def _get_blocks(page: Any) -> List[Any]:
    """Return the list of content blocks from a Pix2Text page object."""
    for attr in ("elements", "blocks", "content", "lines"):
        blocks = getattr(page, attr, None)
        if blocks is not None:
            return list(blocks)
    try:
        return list(page)
    except TypeError:
        return []


def _parse_blocks(
    blocks: List[Any],
    page_number: int,
    equations: List[Dict[str, Any]],
) -> None:
    """
    Parse a flat list of blocks from one page, collecting display equations.

    A block is considered a *display equation* when its type is one of:
      "isolated"  — standalone display formula (Pix2Text's primary label)
      "formula"   — also used in some versions for display math

    Inline ("embedding") formulas are intentionally skipped because numbered
    equations are always typeset as isolated display math in academic papers.

    Context extraction: the plain-text content of the block immediately before
    and after each equation block is used for Checks 16 & 17.
    """
    text_blocks = [b for b in blocks]  # keep all for context extraction

    for block_idx, block in enumerate(text_blocks):
        block_type = _block_type(block)

        if block_type not in ("isolated", "formula"):
            continue

        latex = _block_text(block)
        if not latex or not latex.strip():
            continue

        # ── Context: up to 300 chars before and after ─────────────────────────
        context_before = _collect_context(text_blocks, block_idx, direction="before")
        context_after  = _collect_context(text_blocks, block_idx, direction="after")

        # ── Try to extract the equation number from the LaTeX / label field ──
        number, number_format, context_after = _parse_equation_number(block, latex, context_after)

        equations.append({
            "number":         number,
            "number_format":  number_format,
            "latex":          latex.strip(),
            "page_number":    page_number,
            "context_before": context_before,
            "context_after":  context_after,
            "_block_index":   len(equations),  # insertion order for sorting
        })


def _block_type(block: Any) -> str:
    """Safely extract the type string from a block object."""
    for attr in ("type", "block_type", "category"):
        val = getattr(block, attr, None)
        if val is not None:
            return str(val).lower()
    # Some versions use dicts
    if isinstance(block, dict):
        for key in ("type", "block_type", "category"):
            if key in block:
                return str(block[key]).lower()
    return "unknown"


def _block_text(block: Any) -> str:
    """Safely extract the text/LaTeX string from a block object."""
    for attr in ("text", "latex", "content", "value"):
        val = getattr(block, attr, None)
        if val is not None:
            return str(val)
    if isinstance(block, dict):
        for key in ("text", "latex", "content", "value"):
            if key in block:
                return str(block[key])
    return ""


def _parse_equation_number(
    block: Any, latex: str, context_after: str
) -> tuple[Optional[int], Optional[str], str]:
    """
    Attempt to find the numeric label for a display equation.

    Sources checked (in priority order):
      1. block.label / block.number attribute (Pix2Text may provide this)
      2. A `(N)` or `[N]` token found at the end of the LaTeX string itself
         (many TeX systems embed the label inside the math environment)
      3. A trailing label token in the next text block (handled in context extraction)

    Returns (integer_number, raw_format_string) or (None, None) if unlabelled.
    """
    # 1. Direct attribute
    for attr in ("label", "number", "eq_number", "eqno"):
        raw = getattr(block, attr, None)
        if raw is None and isinstance(block, dict):
            raw = block.get(attr)
        if raw is not None:
            raw_str = str(raw).strip()
            m = _LABEL_RE.search(raw_str)
            if m:
                inner = m.group("paren") or m.group("brack")
                try:
                    return int(inner), raw_str, context_after
                except ValueError:
                    return None, raw_str, context_after

    # 2. Label embedded at the end of the LaTeX string
    #    e.g. "f_k = \mu_k m g \cos\theta \qquad (7)"
    m = _LABEL_RE.search(latex[-50:])  # search tail only to avoid false positives
    if m:
        inner = m.group("paren") or m.group("brack")
        label_str = m.group(0)
        try:
            return int(inner), label_str, context_after
        except ValueError:
            return None, label_str, context_after

    # 3. Label at the very beginning of context_after
    m = _LABEL_RE.match(context_after)
    if m:
        inner = m.group("paren") or m.group("brack")
        try:
            return int(inner), m.group(0), context_after[m.end():].lstrip()
        except ValueError:
            pass

    return None, None, context_after


def _collect_context(
    blocks: List[Any],
    eq_idx: int,
    direction: str,
    max_chars: int = 300,
) -> str:
    """
    Collect up to *max_chars* of plain text from blocks adjacent to the equation.

    *direction* is "before" or "after".
    Only "text" typed blocks are used for context — formula blocks are skipped.
    """
    if direction == "before":
        neighbours = reversed(blocks[:eq_idx])
    else:
        neighbours = iter(blocks[eq_idx + 1:])

    parts: List[str] = []
    total = 0
    for blk in neighbours:
        if _block_type(blk) in ("isolated", "formula"):
            break  # stop at the next/previous equation
        text = _block_text(blk).strip()
        if not text:
            continue
        parts.append(text)
        total += len(text)
        if total >= max_chars:
            break

    if direction == "before":
        parts.reverse()

    combined = " ".join(parts)
    return combined[:max_chars]
