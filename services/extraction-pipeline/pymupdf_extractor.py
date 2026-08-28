"""
pymupdf_extractor.py
====================
Base extraction layer using PyMuPDF (fitz).

Responsibilities:
  - Open the PDF and iterate pages.
  - Extract per-page plain text AND rich block data (font size, bold, bbox).
  - Expose search_string() to find the bounding-box Rect of any exact string on
    a given page (used to pin NuExtract-returned strings to PDF coordinates).
  - Expose page_chunks() for the orchestrator to drive NuExtract page-by-page.

All coordinate data uses PyMuPDF's native Rect (x0, y0, x1, y1) expressed in
PDF user-space points.  No coordinate transformation is applied here; the
annotation layer handles display-space conversion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

import pymupdf as fitz  # PyMuPDF


# ─────────────────────────────────────────────────────────────────────────────
# Data containers
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TextSpan:
    """One run of characters sharing the same font / size / flags."""
    text:    str
    font:    str
    size:    float
    bold:    bool
    italic:  bool
    bbox:    Tuple[float, float, float, float]  # x0, y0, x1, y1


@dataclass
class TextLine:
    spans:       List[TextSpan] = field(default_factory=list)
    bbox:        Tuple[float, float, float, float] = (0, 0, 0, 0)
    page_number: int = 0

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)

    @property
    def max_font_size(self) -> float:
        return max((s.size for s in self.spans), default=0.0)

    @property
    def is_bold(self) -> bool:
        return any(s.bold for s in self.spans)


@dataclass
class PageChunk:
    """Everything extracted from a single PDF page."""
    page_number:   int                                    # 1-indexed
    page_width:    float
    page_height:   float
    plain_text:    str                                    # joined plain text
    lines:         List[TextLine] = field(default_factory=list)
    image_count:   int = 0
    image_blocks:  List[Dict[str, float]] = field(default_factory=list)  # [{x0,y0,x1,y1}]
    # Strategy C: raw block sequence in reading order (y-sorted).
    # Each entry is {"type": 0|1, "bbox": (x0,y0,x1,y1)} where type 0=text, 1=image.
    # Used by structural_analyzer for block-order image-caption association.
    raw_blocks:    List[Dict] = field(default_factory=list)


@dataclass
class CoordinateHit:
    page_number: int
    x0: float
    y0: float
    x1: float
    y1: float

    def as_dict(self) -> dict:
        return {
            "page": self.page_number,
            "x0":   self.x0,
            "y0":   self.y0,
            "x1":   self.x1,
            "y1":   self.y1,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Main extractor
# ─────────────────────────────────────────────────────────────────────────────

class PyMuPDFExtractor:
    """
    Open a PDF once and provide page chunks and string-search utilities.

    Usage:
        extractor = PyMuPDFExtractor("/path/to/paper.pdf")
        for chunk in extractor.page_chunks():
            ...
        hits = extractor.search_string("Smith et al.", page_number=3)
        extractor.close()

    Context-manager usage is also supported (with statement).
    """

    # fitz search flags for best accuracy
    _SEARCH_FLAGS = (
        fitz.TEXT_PRESERVE_LIGATURES
        | fitz.TEXT_PRESERVE_WHITESPACE
    )

    def __init__(self, pdf_path: str) -> None:
        self._path = pdf_path
        try:
            self._doc: fitz.Document = fitz.open(pdf_path)
        except Exception as exc:
            raise IOError(f"PyMuPDFExtractor: cannot open '{pdf_path}': {exc}") from exc

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "PyMuPDFExtractor":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        if self._doc:
            self._doc.close()

    # ── Core properties ───────────────────────────────────────────────────────

    @property
    def page_count(self) -> int:
        return len(self._doc)

    # ── Page iteration ────────────────────────────────────────────────────────

    def page_chunks(self) -> Iterator[PageChunk]:
        """Yield one PageChunk per PDF page (1-indexed)."""
        for idx in range(len(self._doc)):
            yield self._extract_page(idx)

    def get_page_chunk(self, page_number: int) -> PageChunk:
        """Extract a specific page (1-indexed)."""
        if not (1 <= page_number <= len(self._doc)):
            raise ValueError(f"Page {page_number} out of range (1–{len(self._doc)})")
        return self._extract_page(page_number - 1)

    # ── String search / coordinate lookup ────────────────────────────────────

    def search_string(
        self,
        query: str,
        page_number: Optional[int] = None,
        max_hits: int = 20,
    ) -> List[CoordinateHit]:
        """
        Search for 'query' across the whole document or a specific page.

        Returns a list of CoordinateHit objects (may be empty).
        Searches are case-sensitive to preserve error detection integrity.
        Whitespace inside the query is normalised to single spaces before
        searching to compensate for PDF word-break artefacts.
        """
        query_clean = re.sub(r"\s+", " ", query.strip())
        if not query_clean:
            return []

        hits: List[CoordinateHit] = []
        pages_to_search = (
            [self._doc[page_number - 1]]
            if page_number is not None
            else list(self._doc)
        )
        base_page_number = (
            page_number
            if page_number is not None
            else 1
        )

        for page_idx, page in enumerate(pages_to_search):
            pnum = (
                page_number
                if page_number is not None
                else page_idx + 1
            )
            try:
                rects: List[fitz.Rect] = page.search_for(
                    query_clean,
                    flags=self._SEARCH_FLAGS,
                )
                for rect in rects:
                    hits.append(CoordinateHit(
                        page_number=pnum,
                        x0=rect.x0,
                        y0=rect.y0,
                        x1=rect.x1,
                        y1=rect.y1,
                    ))
                    if len(hits) >= max_hits:
                        return hits
            except Exception as exc:
                print(f"[PyMuPDF] search_for error on page {pnum}: {exc}")

        return hits

    def search_strings_batch(
        self,
        queries: List[str],
        page_number: Optional[int] = None,
    ) -> Dict[str, List[CoordinateHit]]:
        """
        Search for multiple strings at once.  Returns a dict mapping each
        query to its list of CoordinateHit results.
        """
        return {q: self.search_string(q, page_number=page_number) for q in queries}

    # ── Internal page builder ─────────────────────────────────────────────────

    def _extract_page(self, page_idx: int) -> PageChunk:
        page = self._doc[page_idx]
        page_number = page_idx + 1

        lines: List[TextLine] = []
        plain_parts: List[str] = []

        try:
            raw = page.get_text(
                "dict",
                flags=(
                    fitz.TEXT_PRESERVE_WHITESPACE
                    | fitz.TEXT_PRESERVE_LIGATURES
                ),
            )
            for block in raw.get("blocks", []):
                if block.get("type") != 0:   # 0 = text block
                    continue
                for raw_line in block.get("lines", []):
                    tline = self._parse_line(raw_line, page_number)
                    text = tline.text.strip()
                    if text:
                        lines.append(tline)
                        plain_parts.append(text)
        except Exception as exc:
            print(f"[PyMuPDF] get_text dict error page {page_number}: {exc}. Using plain fallback.")
            for raw_line in page.get_text().splitlines():
                stripped = raw_line.strip()
                if stripped:
                    plain_parts.append(stripped)

        plain_text = "\n".join(plain_parts)

        # Collect image bounding boxes (used by structural_analyzer for figure matching)
        image_blocks: List[Dict[str, float]] = []
        try:
            for img_info in page.get_image_info(hashes=False, xrefs=False):
                bbox = img_info.get("bbox")
                if bbox and len(bbox) == 4:
                    x0, y0, x1, y1 = bbox
                    if x1 > x0 and y1 > y0:  # valid non-empty rect
                        image_blocks.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1})
        except Exception:
            # Fallback: count only, no bboxes
            pass

        image_count = len(image_blocks)

        # Strategy C: Build raw block sequence sorted by y0 (reading order).
        # Interleaves text blocks (type=0) and image blocks (type=1) so
        # structural_analyzer can determine relative order without y-value math.
        raw_blocks: List[Dict] = []
        try:
            dict_data = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
            for blk in dict_data.get("blocks", []):
                btype = blk.get("type", -1)
                bbox  = blk.get("bbox")
                if bbox and btype in (0, 1):
                    x0, y0, x1, y1 = bbox
                    if x1 > x0 and y1 > y0:
                        raw_blocks.append({
                            "type": btype,       # 0=text, 1=image
                            "bbox": (x0, y0, x1, y1),
                        })
            # Sort top-to-bottom (primary), left-to-right (secondary)
            raw_blocks.sort(key=lambda b: (round(b["bbox"][1] / 10), b["bbox"][0]))
        except Exception:
            pass

        return PageChunk(
            page_number=page_number,
            page_width=page.rect.width,
            page_height=page.rect.height,
            plain_text=plain_text,
            lines=lines,
            image_count=image_count,
            image_blocks=image_blocks,
            raw_blocks=raw_blocks,
        )

    @staticmethod
    def _parse_line(raw_line: dict, page_number: int) -> TextLine:
        spans: List[TextSpan] = []
        bbox_vals = raw_line.get("bbox", (0, 0, 0, 0))

        for raw_span in raw_line.get("spans", []):
            flags = raw_span.get("flags", 0)
            span = TextSpan(
                text=raw_span.get("text", ""),
                font=raw_span.get("font", ""),
                size=float(raw_span.get("size", 10.0)),
                bold=bool(flags & 16),    # bit 4 = bold
                italic=bool(flags & 2),   # bit 1 = italic
                bbox=raw_span.get("bbox", (0, 0, 0, 0)),
            )
            spans.append(span)

        return TextLine(
            spans=spans,
            bbox=bbox_vals,
            page_number=page_number,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Utility: estimate body font size from a list of PageChunks
# ─────────────────────────────────────────────────────────────────────────────

def estimate_body_font_size(chunks: List[PageChunk]) -> float:
    """
    Return the modal font size across all spans — this is the body text size.
    Used upstream to identify headings (size > body * threshold).
    """
    from collections import Counter
    sizes: List[int] = []
    for chunk in chunks:
        for line in chunk.lines:
            for span in line.spans:
                if span.size > 4:
                    sizes.append(round(span.size))
    if not sizes:
        return 10.0
    most_common = Counter(sizes).most_common(1)
    return float(most_common[0][0])
