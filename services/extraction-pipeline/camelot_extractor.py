"""
camelot_extractor.py
====================
Camelot wrapper for coordinate-preserving table extraction.

Why Camelot instead of NuExtract for tables?
  NuExtract collapses tabular grids into flat text, destroying row/column
  identity and bounding-box information.  Camelot parses the actual PDF drawing
  primitives (lines/cells) and returns DataFrames WITH bbox metadata, which we
  need for:
    - Empty-cell detection
    - Row/column structure linting
    - Pinning table coordinates for the PDF annotator

Camelot strategy selection:
  - "lattice": PDF tables with visible ruling lines (most structured papers)
  - "stream" : Tables with whitespace-only column separators (fallback)

The orchestrator calls extract_tables(pdf_path) and receives a list of
ExtractedTable objects, each containing the DataFrame and coordinates.

Camelot requires Ghostscript:
  sudo apt-get install ghostscript   (or equivalent)
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

# Camelot may not be installed in every environment.  Wrap the import so the
# service can still start and degrade gracefully.
try:
    import camelot
    CAMELOT_AVAILABLE = True
except ImportError:
    camelot = None  # type: ignore
    CAMELOT_AVAILABLE = False
    print("[CamelotExtractor] camelot-py not installed — table extraction disabled.")


# ─────────────────────────────────────────────────────────────────────────────
# Data containers
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ExtractedTable:
    """
    One table extracted from the PDF.

    bbox is in PDF page coordinates (x0, y0, x1, y1) relative to the page
    lower-left origin (as Camelot reports it).  The annotation layer must
    convert to the top-left origin used by PyMuPDF / the frontend renderer.
    """
    table_index:  int                            # 0-based index across all pages
    page_number:  int                            # 1-indexed page
    bbox:         Dict[str, float]               # {x1, y1, x2, y2} as Camelot names them
    dataframe:    pd.DataFrame = field(default_factory=pd.DataFrame)
    accuracy:     float = 0.0                    # Camelot accuracy score
    parse_method: str = "lattice"                # "lattice" | "stream"

    # Derived analysis flags (populated by analyse_table)
    has_empty_cells:       bool = False
    empty_cell_locations:  List[Dict] = field(default_factory=list)   # [{row, col}]
    has_footnote_markers:  bool = False
    row_count:             int = 0
    col_count:             int = 0
    headers:               List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        """Serialise to a JSON-friendly dict for the orchestrator output."""
        return {
            "table_index":        self.table_index,
            "page_number":        self.page_number,
            "bbox":               self.bbox,
            "accuracy":           self.accuracy,
            "parse_method":       self.parse_method,
            "has_empty_cells":    self.has_empty_cells,
            "empty_cell_locations": self.empty_cell_locations,
            "has_footnote_markers": self.has_footnote_markers,
            "row_count":          self.row_count,
            "col_count":          self.col_count,
            "headers":            self.headers,
            "data_json":          self.dataframe.to_json(orient="records"),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Footnote marker pattern
# ─────────────────────────────────────────────────────────────────────────────

import re
_FOOTNOTE_RE = re.compile(
    r"""
    (?:^|\s)          # start of cell or after whitespace
    (?:
        [a-z]{1,2}    # single/double lowercase letter marker (e.g. a, ab)
        | \*{1,3}     # asterisk(s)
        | †{1,2}      # dagger(s)
        | ‡           # double dagger
        | [¶§]        # pilcrow / section sign
    )
    (?:\s|$)          # followed by whitespace or end
    """,
    re.VERBOSE,
)


# ─────────────────────────────────────────────────────────────────────────────
# Core extraction function
# ─────────────────────────────────────────────────────────────────────────────

def extract_tables(
    pdf_path:         str,
    prefer_method:    str = "lattice",
    accuracy_cutoff:  float = 70.0,
) -> List[ExtractedTable]:
    """
    Extract all tables from the PDF.

    Strategy:
      1. Try "lattice" (ruled lines) for the whole document.
      2. For pages that yield no tables with lattice, retry those pages with
         "stream" (whitespace-based).
      3. Tables scoring below accuracy_cutoff are dropped to avoid garbage.

    Returns a list of ExtractedTable objects, sorted by (page_number, y1 desc).
    """
    if not CAMELOT_AVAILABLE:
        print("[CamelotExtractor] Skipping — camelot-py not available.")
        return []

    results: List[ExtractedTable] = []
    global_index = 0

    # ── Pass 1: lattice (full document) ──────────────────────────────────────
    lattice_tables = _run_camelot(pdf_path, method="lattice")
    pages_with_lattice: set = set()

    for tbl in lattice_tables:
        if tbl.accuracy < accuracy_cutoff:
            continue
        page_num = int(tbl.page)
        pages_with_lattice.add(page_num)
        et = _build_extracted_table(tbl, global_index, "lattice")
        results.append(et)
        global_index += 1

    # ── Pass 2: stream fallback on pages with no lattice result ──────────────
    try:
        import fitz
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        doc.close()
    except Exception:
        total_pages = 9999

    pages_needing_stream = [
        p for p in range(1, total_pages + 1)
        if p not in pages_with_lattice
    ]

    if pages_needing_stream:
        page_spec = ",".join(str(p) for p in pages_needing_stream)
        stream_tables = _run_camelot(pdf_path, method="stream", pages=page_spec)
        for tbl in stream_tables:
            if tbl.accuracy < accuracy_cutoff:
                continue
            et = _build_extracted_table(tbl, global_index, "stream")
            results.append(et)
            global_index += 1

    # Sort by page, then top-of-page first (descending y1 in PDF coords)
    results.sort(key=lambda t: (t.page_number, -t.bbox.get("y2", 0)))

    # Analyse each table for empty cells and footnote markers
    for et in results:
        _analyse_table(et)

    print(f"[CamelotExtractor] Extracted {len(results)} table(s) from {pdf_path}")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _run_camelot(
    pdf_path: str,
    method: str,
    pages: str = "all",
) -> list:
    """
    Run camelot.read_pdf with appropriate settings and return a TableList.
    Returns an empty list on any failure.
    """
    if not CAMELOT_AVAILABLE:
        return []
    try:
        kwargs = {
            "pages":   pages,
            "flavor":  method,
            "suppress_stdout": True,
        }
        if method == "stream":
            # edge_tol: tolerate slight misalignment in whitespace tables
            kwargs["edge_tol"] = 100
            kwargs["row_tol"]  = 10

        tables = camelot.read_pdf(pdf_path, **kwargs)
        return list(tables)
    except Exception as exc:
        print(f"[CamelotExtractor] camelot.read_pdf (method={method}, pages={pages}) failed: {exc}")
        if "ghostscript" in str(exc).lower():
            print("[CamelotExtractor] Ghostscript may not be installed. "
                  "Install with: sudo apt-get install ghostscript")
        return []


def _build_extracted_table(
    camelot_table,
    global_index: int,
    parse_method: str,
) -> ExtractedTable:
    """Convert a camelot Table object into our ExtractedTable dataclass."""
    df: pd.DataFrame = camelot_table.df

    # Camelot bbox is a string "(x1,y1,x2,y2)" in PDF coordinates
    # x1,y1 = bottom-left; x2,y2 = top-right (PDF origin is bottom-left)
    raw_bbox = camelot_table._bbox if hasattr(camelot_table, "_bbox") else (0, 0, 0, 0)
    if isinstance(raw_bbox, str):
        try:
            raw_bbox = tuple(float(v) for v in raw_bbox.strip("()").split(","))
        except Exception:
            raw_bbox = (0, 0, 0, 0)
    bbox_dict = {
        "x1": raw_bbox[0] if len(raw_bbox) > 0 else 0,
        "y1": raw_bbox[1] if len(raw_bbox) > 1 else 0,
        "x2": raw_bbox[2] if len(raw_bbox) > 2 else 0,
        "y2": raw_bbox[3] if len(raw_bbox) > 3 else 0,
    }

    return ExtractedTable(
        table_index=global_index,
        page_number=int(camelot_table.page),
        bbox=bbox_dict,
        dataframe=df,
        accuracy=float(camelot_table.accuracy),
        parse_method=parse_method,
    )


def _analyse_table(et: ExtractedTable) -> None:
    """
    Populate derived analysis flags on an ExtractedTable in-place.
    Checks:
      - has_empty_cells
      - empty_cell_locations
      - has_footnote_markers (in any cell)
      - row_count / col_count / headers
    """
    df = et.dataframe
    if df.empty:
        return

    et.row_count = len(df)
    et.col_count = len(df.columns)

    # Headers — first row as list of strings
    if len(df) > 0:
        et.headers = [str(v) for v in df.iloc[0].tolist()]

    # Empty cells
    empty_locs: List[Dict] = []
    for row_idx in range(len(df)):
        for col_idx in range(len(df.columns)):
            cell_val = str(df.iloc[row_idx, col_idx]).strip()
            if cell_val == "" or cell_val.lower() in ("nan", "none"):
                empty_locs.append({"row": row_idx, "col": col_idx})

    et.has_empty_cells = len(empty_locs) > 0
    et.empty_cell_locations = empty_locs

    # Footnote markers — any cell value matches the footnote pattern
    has_fn = False
    for row_idx in range(len(df)):
        for col_idx in range(len(df.columns)):
            cell_val = str(df.iloc[row_idx, col_idx])
            if _FOOTNOTE_RE.search(cell_val):
                has_fn = True
                break
        if has_fn:
            break
    et.has_footnote_markers = has_fn
