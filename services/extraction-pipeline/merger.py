"""
merger.py
=========
Merges per-page NuExtract extraction results into a single coherent document.

NuExtract is called once per PDF page, so we receive N partial dicts.  This
module:
  1. Concatenates list fields (references, figures, tables, etc.) across pages.
  2. Picks the "best" single value for scalar manuscript fields (title, abstract)
     using a simple longest-string heuristic.
  3. De-duplicates list items that the model may have emitted on multiple
     consecutive pages (e.g., references that straddle a page break).
  4. Merges typography aggregate data (merging the lists, re-evaluating booleans).
  5. Attaches Camelot table data to the NuExtract table records where a match
     can be found by page/label.

Output structure mirrors NUEXTRACT_TEMPLATE with two additional top-level keys:
  "camelot_tables": [ ... ]   — raw Camelot ExtractedTable.as_dict() records
  "extraction_errors": [ ... ] — per-page error records (page, reason)
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

# TEMPLATE_TOP_KEYS is still exported by nuextract_schema for compat
try:
    from nuextract_schema import TEMPLATE_TOP_KEYS
except ImportError:
    TEMPLATE_TOP_KEYS = []


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def merge_page_results(
    page_results:   List[Tuple[int, Optional[dict], Optional[str]]],
    camelot_tables: List[dict],
) -> dict:
    """
    Merge per-page extraction results into one document dict.

    Arguments:
        page_results   — list of (page_number, extracted_dict_or_None, error_or_None)
        camelot_tables — list of ExtractedTable.as_dict() records

    Returns the merged document dict.
    """
    merged: dict = _empty_document()
    extraction_errors: List[dict] = []

    for (page_num, page_data, error) in page_results:
        if error or page_data is None:
            extraction_errors.append({
                "page":   page_num,
                "reason": error or "null result",
            })
            continue

        # Strip internal meta keys before merging
        page_data = {k: v for k, v in page_data.items() if not k.startswith("_")}

        # references and in_text_citations come from regex_extractor, not LLM
        _merge_manuscript(merged["manuscript"], page_data.get("manuscript") or {})
        _extend_list(merged["sections"],  page_data.get("sections") or [])
        _extend_list(merged["figures"],   page_data.get("figures") or [])
        _extend_list(merged["tables"],    page_data.get("tables") or [])
        _extend_list(merged["equations"], page_data.get("equations") or [])
        _extend_list(merged["acronyms"],  page_data.get("acronyms") or [])
        _merge_typography(merged["typography"], page_data.get("typography") or {})

    # De-duplicate LLM-sourced lists
    merged["figures"]   = _dedup_by_label(merged["figures"])
    merged["tables"]    = _dedup_by_label(merged["tables"])
    merged["equations"] = _dedup_equations(merged["equations"])
    merged["acronyms"]  = _dedup_acronyms(merged["acronyms"])
    merged["sections"]  = _dedup_sections(merged["sections"])

    # Re-evaluate typography consistency booleans from merged data
    _finalise_typography(merged["typography"])

    # Attach Camelot data
    merged["camelot_tables"]    = camelot_tables
    _link_camelot_to_nuextract(merged)

    merged["extraction_errors"] = extraction_errors
    merged["total_pages_processed"] = len(page_results)
    merged["pages_with_errors"]     = len(extraction_errors)

    return merged


# ─────────────────────────────────────────────────────────────────────────────
# Empty document scaffold
# ─────────────────────────────────────────────────────────────────────────────

def _empty_document() -> dict:
    return {
        "manuscript": {
            "title": None,
            "abstract_text": None,
            "abstract_word_count": None,
            "keywords": [],
            "keywords_section_present": None,
            "authors": [],
            "publishing_statements": {
                "conflict_of_interest": None,
                "ethics_statement": None,
                "funding_statement": None,
                "data_access_statement": None,
                "author_contribution_statement": None,
            },
        },
        "sections":          [],
        "in_text_citations": [],
        "references":        [],
        "figures":           [],
        "tables":            [],
        "equations":         [],
        "acronyms":          [],
        "typography": {
            "quote_style_used": [],
            "quote_style_consistent": None,
            "serial_comma_usage": [],
            "serial_comma_consistent": None,
            "double_spaces_detected": None,
            "en_dash_for_ranges_violations": [],
            "number_unit_space_violations": [],
            "percent_degree_space_violations": [],
            "american_spellings": [],
            "british_spellings": [],
            "spelling_variety_consistent": None,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Manuscript scalar merging
# ─────────────────────────────────────────────────────────────────────────────

def _merge_manuscript(base: dict, incoming: dict) -> None:
    """Pick the best scalar values; extend list fields."""
    # Title: keep longest non-null
    base["title"] = _pick_longest(base.get("title"), incoming.get("title"))

    # Abstract: keep longest
    base["abstract_text"] = _pick_longest(
        base.get("abstract_text"), incoming.get("abstract_text")
    )

    # abstract_word_count: take first non-null integer
    if base.get("abstract_word_count") is None and incoming.get("abstract_word_count") is not None:
        base["abstract_word_count"] = incoming["abstract_word_count"]

    # keywords: union, preserve order
    existing_kw = set(base.get("keywords") or [])
    for kw in (incoming.get("keywords") or []):
        if kw and kw not in existing_kw:
            base.setdefault("keywords", []).append(kw)
            existing_kw.add(kw)

    # keywords_section_present: OR
    if incoming.get("keywords_section_present"):
        base["keywords_section_present"] = True

    # authors: extend (de-dup by name later)
    _extend_list(base.setdefault("authors", []), incoming.get("authors") or [])

    # publishing_statements: OR booleans
    for key in base.get("publishing_statements", {}):
        if incoming.get("publishing_statements", {}).get(key):
            base["publishing_statements"][key] = True


def _pick_longest(a: Optional[str], b: Optional[str]) -> Optional[str]:
    if not a and not b:
        return None
    if not a:
        return b
    if not b:
        return a
    return a if len(a) >= len(b) else b


# ─────────────────────────────────────────────────────────────────────────────
# Typography merging
# ─────────────────────────────────────────────────────────────────────────────

def _merge_typography(base: dict, incoming: dict) -> None:
    # Quote style: union
    for style in (incoming.get("quote_style_used") or []):
        if style and style not in base["quote_style_used"]:
            base["quote_style_used"].append(style)

    # Serial comma: extend observations
    base["serial_comma_usage"].extend(incoming.get("serial_comma_usage") or [])

    # Boolean: double spaces
    if incoming.get("double_spaces_detected"):
        base["double_spaces_detected"] = True

    # Violation lists: extend
    for key in (
        "en_dash_for_ranges_violations",
        "number_unit_space_violations",
        "percent_degree_space_violations",
        "american_spellings",
        "british_spellings",
    ):
        incoming_vals = incoming.get(key) or []
        existing_vals = base.get(key) or []
        existing_set = {
            v if isinstance(v, str) else (v.get("text") if isinstance(v, dict) else str(v))
            for v in existing_vals
        }
        for v in incoming_vals:
            v_key = v if isinstance(v, str) else (v.get("text") if isinstance(v, dict) else str(v))
            if v_key and v_key not in existing_set:
                existing_vals.append(v)
                existing_set.add(v_key)
        base[key] = existing_vals


def _finalise_typography(typo: dict) -> None:
    """Compute consistency booleans from the merged observation lists."""
    # Quote consistency: more than 1 distinct style = inconsistent
    typo["quote_style_consistent"] = len(set(typo.get("quote_style_used") or [])) <= 1

    # Serial comma consistency: all observations same
    usages = [u for u in (typo.get("serial_comma_usage") or []) if u in ("used", "omitted")]
    if usages:
        typo["serial_comma_consistent"] = len(set(usages)) == 1
    else:
        typo["serial_comma_consistent"] = None

    # Spelling variety
    has_american = bool(typo.get("american_spellings"))
    has_british  = bool(typo.get("british_spellings"))
    if has_american and has_british:
        typo["spelling_variety_consistent"] = False
    elif has_american or has_british:
        typo["spelling_variety_consistent"] = True
    else:
        typo["spelling_variety_consistent"] = None


# ─────────────────────────────────────────────────────────────────────────────
# List extension helper
# ─────────────────────────────────────────────────────────────────────────────

def _extend_list(target: list, incoming: list) -> None:
    if not isinstance(incoming, list):
        return
    target.extend(item for item in incoming if isinstance(item, dict))


# ─────────────────────────────────────────────────────────────────────────────
# De-duplication helpers
# ─────────────────────────────────────────────────────────────────────────────

def _dedup_references(refs: list) -> list:
    """Deduplicate by raw_string (first 60 chars, lowercased)."""
    seen: set = set()
    out:  list = []
    for ref in refs:
        key = (ref.get("raw_string") or "")[:60].lower().strip()
        if not key:
            out.append(ref)
            continue
        if key not in seen:
            seen.add(key)
            out.append(ref)
    return out


def _dedup_by_label(items: list) -> list:
    """Deduplicate figures/tables by their label string."""
    seen: set = set()
    out:  list = []
    for item in items:
        label = (item.get("label") or "").strip().lower()
        if not label:
            out.append(item)
            continue
        if label not in seen:
            seen.add(label)
            out.append(item)
    return out


def _dedup_equations(eqs: list) -> list:
    """Deduplicate equations by (number, number_format)."""
    seen: set = set()
    out:  list = []
    for eq in eqs:
        key = (str(eq.get("number") or ""), (eq.get("number_format") or "").strip())
        if key == ("", ""):
            out.append(eq)
            continue
        if key not in seen:
            seen.add(key)
            out.append(eq)
    return out


def _dedup_acronyms(acrs: list) -> list:
    """Keep only the first occurrence entry per acronym."""
    seen: set = set()
    out:  list = []
    for acr in acrs:
        key = (acr.get("acronym") or "").upper().strip()
        if not key:
            out.append(acr)
            continue
        if key not in seen:
            seen.add(key)
            out.append(acr)
    return out


def _dedup_citations(cits: list) -> list:
    """Deduplicate by (marker, context_snippet[:40])."""
    seen: set = set()
    out:  list = []
    for cit in cits:
        key = (
            (cit.get("marker") or "").strip(),
            (cit.get("context_snippet") or "")[:40].strip(),
        )
        if key == ("", ""):
            out.append(cit)
            continue
        if key not in seen:
            seen.add(key)
            out.append(cit)
    return out


def _dedup_sections(secs: list) -> list:
    """Deduplicate by exact heading_text."""
    seen: set = set()
    out:  list = []
    for sec in secs:
        key = (sec.get("heading_text") or "").strip()
        if not key:
            out.append(sec)
            continue
        if key not in seen:
            seen.add(key)
            out.append(sec)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Camelot ↔ NuExtract table linking
# ─────────────────────────────────────────────────────────────────────────────

def _link_camelot_to_nuextract(merged: dict) -> None:
    """
    Attempt to match each Camelot table to a NuExtract table entry by page
    number and label similarity.  When a match is found, the NuExtract entry
    is enriched with camelot_index, camelot_bbox, and camelot_analysis_flags.
    """
    camelot_tables = merged.get("camelot_tables") or []
    nu_tables      = merged.get("tables") or []

    for ct in camelot_tables:
        ct_page = ct.get("page_number")
        ct_idx  = ct.get("table_index")

        # Find the best matching NuExtract table on the same page
        match = None
        for nt in nu_tables:
            if nt.get("table_page") == ct_page or nt.get("first_mention_page") == ct_page:
                match = nt
                break

        if match:
            match["camelot_index"]  = ct_idx
            match["camelot_bbox"]   = ct.get("bbox")
            match["camelot_has_empty_cells"]       = ct.get("has_empty_cells")
            match["camelot_empty_cell_locations"]  = ct.get("empty_cell_locations")
            match["camelot_has_footnote_markers"]  = ct.get("has_footnote_markers")
            match["camelot_row_count"]             = ct.get("row_count")
            match["camelot_col_count"]             = ct.get("col_count")
            match["camelot_data_json"]             = ct.get("data_json")
