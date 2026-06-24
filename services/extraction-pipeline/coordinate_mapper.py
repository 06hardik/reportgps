"""
coordinate_mapper.py
====================
Bridge between NuExtract-returned string data and PyMuPDF bounding boxes.

NuExtract operates in "text space" — it returns strings copied verbatim from
the PDF.  This module takes those verbatim strings, passes them to PyMuPDF's
page.search_for(), and enriches each extracted item with:
  - page_number  (confirmed by the search)
  - bbox         {x0, y0, x1, y1} in PDF user-space points (top-left origin)

Mapping strategy:
  1. We know the page each item came from (NuExtract is called page-by-page).
  2. We search on that specific page first (fast, usually correct).
  3. If not found, search ±1 pages (items near page breaks may straddle pages).
  4. If still not found, fall back to a document-wide scan (max 3 pages either
     side to avoid matching the wrong occurrence in a long paper).

The mapper only ENRICHES data; it never removes items.  Items that cannot be
located get "bbox": null and "coordinate_found": false so the linter/annotator
know to skip them.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pymupdf_extractor import PyMuPDFExtractor, CoordinateHit


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def enrich_with_coordinates(
    extracted_doc: dict,
    extractor:     PyMuPDFExtractor,
) -> dict:
    """
    Walk the extracted document structure and add PDF coordinates to every
    item that carries a verbatim string we can search for.

    Modifies `extracted_doc` IN PLACE and returns it.
    """
    total_pages = extractor.page_count

    # ── in_text_citations ─────────────────────────────────────────────────────
    for cit in extracted_doc.get("in_text_citations", []) or []:
        _enrich_item(
            item=cit,
            search_field="context_snippet",
            page_hint=cit.get("page_number"),
            extractor=extractor,
            total_pages=total_pages,
        )

    # ── references ────────────────────────────────────────────────────────────
    for ref in extracted_doc.get("references", []) or []:
        if ref.get("coordinate_found") is True:
            continue
        # Use the first 80 chars of raw_string as the search target
        raw = ref.get("raw_string") or ""
        search_str = raw[:80].strip()
        _enrich_item_with_string(
            item=ref,
            search_str=search_str,
            page_hint=ref.get("_page_hint"),   # set by orchestrator if known
            extractor=extractor,
            total_pages=total_pages,
        )

    # ── figures ───────────────────────────────────────────────────────────────
    for fig in extracted_doc.get("figures", []) or []:
        # Search for the label first (most distinctive), then caption start
        label  = (fig.get("label") or "").strip()
        cap    = (fig.get("caption_text") or "")[:60].strip()
        search = label or cap
        page_h = fig.get("page_number") or fig.get("figure_page") or fig.get("first_mention_page")
        _enrich_item_with_string(
            item=fig,
            search_str=search,
            page_hint=page_h,
            extractor=extractor,
            total_pages=total_pages,
        )

        # Also resolve first_mention coordinates
        mention_ctx = (fig.get("first_mention_context") or "").strip()
        if mention_ctx:
            hits = _search_with_fallback(
                extractor=extractor,
                query=mention_ctx[:60],
                page_hint=fig.get("first_mention_page"),
                total_pages=total_pages,
            )
            if hits:
                fig["first_mention_bbox"] = hits[0].as_dict()

    # ── tables ────────────────────────────────────────────────────────────────
    for tbl in extracted_doc.get("tables", []) or []:
        label   = (tbl.get("label") or "").strip()
        cap     = (tbl.get("caption_text") or "")[:60].strip()
        search  = label or cap
        page_h  = tbl.get("page_number") or tbl.get("table_page") or tbl.get("first_mention_page")
        _enrich_item_with_string(
            item=tbl,
            search_str=search,
            page_hint=page_h,
            extractor=extractor,
            total_pages=total_pages,
        )

        mention_ctx = (tbl.get("first_mention_context") or "").strip()
        if mention_ctx:
            hits = _search_with_fallback(
                extractor=extractor,
                query=mention_ctx[:60],
                page_hint=tbl.get("first_mention_page"),
                total_pages=total_pages,
            )
            if hits:
                tbl["first_mention_bbox"] = hits[0].as_dict()

    # ── equations ────────────────────────────────────────────────────────────
    for eq in extracted_doc.get("equations", []) or []:
        # The number_format label "(3)" is the most searchable
        label  = (eq.get("number_format") or "").strip()
        eq_txt = (eq.get("raw_text") or eq.get("equation_text") or "")[:40].strip()
        search = label or eq_txt
        _enrich_item_with_string(
            item=eq,
            search_str=search,
            page_hint=eq.get("page_number"),
            extractor=extractor,
            total_pages=total_pages,
        )

    # ── acronyms ─────────────────────────────────────────────────────────────
    for acr in extracted_doc.get("acronyms", []) or []:
        _enrich_item(
            item=acr,
            search_field="acronym",
            page_hint=acr.get("page_number"),
            extractor=extractor,
            total_pages=total_pages,
        )

    # ── sections ─────────────────────────────────────────────────────────────
    for sec in extracted_doc.get("sections", []) or []:
        _enrich_item(
            item=sec,
            search_field="heading_text",
            page_hint=sec.get("page_number"),
            extractor=extractor,
            total_pages=total_pages,
        )

    # ── typography violations ─────────────────────────────────────────────────
    typo = extracted_doc.get("typography") or {}
    for violation_key in (
        "en_dash_for_ranges_violations",
        "number_unit_space_violations",
        "percent_degree_space_violations",
    ):
        snippets = typo.get(violation_key) or []
        enriched_snippets = []
        for snippet in snippets:
            if not isinstance(snippet, str) or not snippet.strip():
                enriched_snippets.append({"text": snippet, "bbox": None, "coordinate_found": False})
                continue
            hits = _search_with_fallback(
                extractor=extractor,
                query=snippet[:60],
                page_hint=None,
                total_pages=total_pages,
            )
            enriched_snippets.append({
                "text": snippet,
                "bbox": hits[0].as_dict() if hits else None,
                "coordinate_found": bool(hits),
            })
        typo[violation_key] = enriched_snippets

    return extracted_doc


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _enrich_item(
    item:         dict,
    search_field: str,
    page_hint:    Optional[int],
    extractor:    PyMuPDFExtractor,
    total_pages:  int,
) -> None:
    """Search using item[search_field] and attach bbox / coordinate_found."""
    raw = item.get(search_field) or ""
    search_str = str(raw)[:80].strip()
    _enrich_item_with_string(item, search_str, page_hint, extractor, total_pages)


def _enrich_item_with_string(
    item:         dict,
    search_str:   str,
    page_hint:    Optional[int],
    extractor:    PyMuPDFExtractor,
    total_pages:  int,
) -> None:
    """Perform the search and attach results to `item` in-place."""
    if not search_str:
        item["bbox"] = None
        item["coordinate_found"] = False
        return

    hits = _search_with_fallback(
        extractor=extractor,
        query=search_str,
        page_hint=page_hint,
        total_pages=total_pages,
    )
    if hits:
        item["bbox"] = hits[0].as_dict()
        item["coordinate_found"] = True
    else:
        item["bbox"] = None
        item["coordinate_found"] = False


def _search_with_fallback(
    extractor:   PyMuPDFExtractor,
    query:       str,
    page_hint:   Optional[int],
    total_pages: int,
    spread:      int = 2,
) -> List[CoordinateHit]:
    """
    Search for `query` using a three-tier strategy:
      1. Exact page (page_hint, if provided)
      2. page_hint ± spread
      3. Document-wide (all pages, max spread*2 pages from hint)
    """
    query = _normalise_query(query)
    if not query:
        return []

    # Tier 1: exact page
    if page_hint and 1 <= page_hint <= total_pages:
        hits = extractor.search_string(query, page_number=page_hint)
        if hits:
            return hits

    # Tier 2: pages within ± spread
    if page_hint:
        pages_to_try = [
            p for p in range(
                max(1, page_hint - spread),
                min(total_pages + 1, page_hint + spread + 1),
            )
            if p != page_hint
        ]
        for p in pages_to_try:
            hits = extractor.search_string(query, page_number=p)
            if hits:
                return hits

    # Tier 3: full-document scan (only for short queries to avoid false matches)
    if len(query) >= 20:
        hits = extractor.search_string(query, page_number=None, max_hits=1)
        if hits:
            return hits

    # Tier 4: try a shorter prefix (first 40 chars) to handle line-break splits
    if len(query) > 40:
        short_q = _normalise_query(query[:40])
        if short_q:
            hits = extractor.search_string(short_q, page_number=page_hint, max_hits=3)
            if hits:
                return hits

    return []


def _normalise_query(text: str) -> str:
    """Collapse whitespace (handles PDF word-break artefacts)."""
    return re.sub(r"\s+", " ", text).strip()
