"""
reference_quality.py
====================
Integration layer for all 5 reference quality checks.

Responsibilities:
  1. Convert GROBID BibTeX entries → the `parsed` format the checks expect
  2. Combine BibTeX + raw strings → enriched reference list
  3. Detect citation style from raw strings
  4. Classify each entry's individual style (for Check 5)
  5. Run all 5 checks and return unified issues in our pipeline format
  6. Convert GROBID referenceAnnotations coordinates (bottom-left PDF origin)
     → fitz coordinates (top-left origin) for correct annotation placement
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .check_ordering       import check_ordering
from .check_doi            import check_doi
from .check_journal_casing import check_journal_casing
from .check_completeness   import check_completeness
from .check_style_conformity import check_style_conformity


# ─────────────────────────────────────────────────────────────────────────────
# Citation style detection — powered by the full citation_classifier rule engine
# ─────────────────────────────────────────────────────────────────────────────

# Normalise classifier style names → uppercase pipeline names
_STYLE_NORMALISE = {
    "IEEE":      "IEEE",
    "APA":       "APA",
    "MLA":       "MLA",
    "Harvard":   "HARVARD",
    "HARVARD":   "HARVARD",
    "Vancouver": "VANCOUVER",
    "VANCOUVER": "VANCOUVER",
    "Unknown":   "UNKNOWN",
}


def detect_citation_style(raw_strings: List[str]) -> str:
    """
    Detect the dominant citation style for a reference list.

    Runs the full citation_classifier rule engine on every raw string,
    then majority-votes across HIGH + MEDIUM confidence predictions.
    Falls back to LOW-confidence votes if no high-confidence consensus.

    Returns one of: "IEEE" | "APA" | "MLA" | "HARVARD" | "VANCOUVER" | "UNKNOWN"
    """
    from .citation_classifier import classify

    if not raw_strings:
        return "UNKNOWN"

    vote_buckets = {"HIGH": {}, "MEDIUM": {}, "LOW": {}}

    for s in raw_strings:
        s = s.strip()
        if not s:
            continue
        result   = classify(s)
        style    = _STYLE_NORMALISE.get(result.predicted_style, "UNKNOWN")
        conf     = result.confidence.upper()  # HIGH / MEDIUM / LOW
        bucket   = vote_buckets.get(conf, vote_buckets["LOW"])
        bucket[style] = bucket.get(style, 0) + 1

    # Try to reach consensus starting from most confident votes
    for level in ("HIGH", "MEDIUM", "LOW"):
        bucket = vote_buckets[level]
        if not bucket:
            continue
        best_style = max(bucket, key=bucket.get)
        total_votes = sum(bucket.values())
        # Require at least 25% agreement among votes at this confidence level
        if bucket[best_style] / total_votes >= 0.25 and best_style != "UNKNOWN":
            return best_style

    return "UNKNOWN"


def _classify_entry_style(raw_text: str) -> Dict[str, Any]:
    """
    Classify a single reference string using the full rule engine.
    Returns the dict format expected by build_enriched_refs() and check_style_conformity().
    """
    from .citation_classifier import classify

    if not raw_text or not raw_text.strip():
        return {"predicted": "UNKNOWN", "confidence": "LOW", "scores": {}}

    result = classify(raw_text.strip())
    # Normalise style name to uppercase pipeline convention
    predicted = _STYLE_NORMALISE.get(result.predicted_style, "UNKNOWN")
    return {
        "predicted":   predicted,
        "confidence":  result.confidence,
        "scores":      {_STYLE_NORMALISE.get(k, k): v for k, v in result.scores.items()},
        "matched_rules": [(r.rule_id, r.style, r.weight) for r in result.matched_rules[:8]],
    }



# ────────────────────────────────────────────────────────────────────────────
# BibTeX → parsed format converter
# ────────────────────────────────────────────────────────────────────────────

def _parse_bibtex_authors(authors_raw: str) -> List[str]:
    """
    "Smith, John and Doe, Jane" → ["John Smith", "Jane Doe"]
    """
    if not authors_raw:
        return []
    parts = re.split(r"\s+and\s+", authors_raw, flags=re.IGNORECASE)
    result = []
    for part in parts:
        part = part.strip()
        if "," in part:
            chunks  = part.split(",", 1)
            surname = chunks[0].strip()
            forename = chunks[1].strip()
            result.append(f"{forename} {surname}")
        else:
            result.append(part)
    return result


def bibtex_entry_to_parsed(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a bibtexparser entry dict → the `parsed` dict the 5 checks expect."""
    return {
        "authors":         _parse_bibtex_authors(entry.get("author", "")),
        "title":           entry.get("title", ""),
        "container_title": (entry.get("journal") or entry.get("booktitle") or entry.get("series") or ""),
        "pub_date":        (entry.get("year") or entry.get("date") or ""),
        "volume":          entry.get("volume", ""),
        "issue":           entry.get("number", ""),
        "pages":           entry.get("pages", ""),
        "doi":             entry.get("doi", ""),
        "url":             entry.get("url", ""),
        "publisher":       entry.get("publisher", ""),
        "entry_type":      (entry.get("ENTRYTYPE") or "misc").lower(),
        "parser_status":   "ok",
    }


# ────────────────────────────────────────────────────────────────────────────
# GROBID coordinate conversion
# (GROBID uses bottom-left PDF origin; fitz uses top-left origin)
# ────────────────────────────────────────────────────────────────────────────

def grobid_pos_to_fitz(
    pos_list: List[Dict],
    page_dimensions: List[Dict],
) -> List[float]:
    """
    Convert a GROBID `pos` array [{p, x, y, w, h}, ...] to a flat
    fitz rect [x0, y0, x1, y1] using the page height for Y-axis flip.

    GROBID coordinate system:
      - Origin: bottom-left corner of the page
      - y increases upward
    fitz coordinate system:
      - Origin: top-left corner of the page
      - y increases downward

    Conversion:
      fitz_y0 = page_height - (grobid_y + grobid_h)
      fitz_y1 = page_height - grobid_y
    """
    if not pos_list:
        return []

    first = pos_list[0]
    page_idx = int(first.get("p", 1)) - 1  # 0-indexed

    page_height = 792.0  # fallback: US Letter
    if page_dimensions and page_idx < len(page_dimensions):
        ph = page_dimensions[page_idx].get("page_height", 0)
        if ph > 0:
            page_height = float(ph)

    gx = float(first.get("x", 0))
    gy = float(first.get("y", 0))
    gw = float(first.get("w", 0))
    gh = float(first.get("h", 0))

    # If the annotation covers multiple pos entries, extend x1/y1
    for extra in pos_list[1:]:
        ex2 = float(extra.get("x", gx)) + float(extra.get("w", 0))
        ey2 = float(extra.get("y", gy)) + float(extra.get("h", 0))
        if ex2 > gx + gw:
            gw = ex2 - gx
        if ey2 > gy + gh:
            gh = ey2 - gy

    fitz_x0 = gx
    fitz_y0 = page_height - (gy + gh)
    fitz_x1 = gx + gw
    fitz_y1 = page_height - gy

    return [fitz_x0, fitz_y0, fitz_x1, fitz_y1]


# ────────────────────────────────────────────────────────────────────────────
# Build the enriched reference list
# ────────────────────────────────────────────────────────────────────────────

def build_enriched_refs(
    bibtex_entries:  List[Dict[str, Any]],
    raw_strings:     List[str],
    ref_bibs:        List[Dict],         # from GROBID referenceAnnotations
    page_dimensions: List[Dict],         # from GROBID referenceAnnotations pages[]
) -> List[Dict[str, Any]]:
    """
    Combine BibTeX entries + raw strings + GROBID coordinate data
    into the enriched format expected by all 5 checks.

    Matching is positional (entry[i] ↔ raw_string[i] ↔ ref_bibs[i]).
    """
    n = max(len(bibtex_entries), len(raw_strings), 1)
    enriched = []

    for i in range(n):
        entry = bibtex_entries[i] if i < len(bibtex_entries) else {}
        raw   = raw_strings[i]   if i < len(raw_strings)    else ""
        rb    = ref_bibs[i]      if i < len(ref_bibs)       else {}

        ref_id = (entry.get("ID") or f"ref_{i+1:03d}").strip()
        parsed = bibtex_entry_to_parsed(entry) if entry else {"parser_status": "failed"}

        # Convert GROBID pos → fitz rect
        pos_list = rb.get("pos", []) if isinstance(rb, dict) else []
        coords   = grobid_pos_to_fitz(pos_list, page_dimensions)
        page_num = int(pos_list[0].get("p", 0)) if pos_list else 0

        enriched.append({
            "id":          ref_id,
            "raw_text":    raw.strip(),
            "parsed":      parsed,
            "style":       _classify_entry_style(raw),
            "coordinates": coords,      # fitz-ready [x0,y0,x1,y1]
            "page":        page_num,
            "_bibtex":     entry,       # keep original for existing analyser
        })

    return enriched


# ────────────────────────────────────────────────────────────────────────────
# Run all 5 checks and return unified issues
# ────────────────────────────────────────────────────────────────────────────

def _to_issue(enriched_ref: Dict, msg: str, context: str,
              suggestions: List[str], check_name: str) -> Dict:
    """Convert a check finding into our standard pipeline issue dict."""
    return {
        "ENTRYTYPE":   enriched_ref["_bibtex"].get("ENTRYTYPE", "misc"),
        "ID":          enriched_ref["id"],
        "page":        enriched_ref["page"],
        "coordinates": enriched_ref["coordinates"],
        "category":    "ARTICLE",   # tells the annotator to use blue highlight
        "message":     msg,
        "context":     context,
        "suggestions": suggestions,
        "check":       check_name,
        # Copy parsed fields so the frontend can display reference details
        **{k: v for k, v in enriched_ref["_bibtex"].items()
           if k not in ("ID", "ENTRYTYPE")},
    }


def run_all_quality_checks(
    enriched:  List[Dict],
    style:     str,
) -> List[Dict]:
    """
    Run all 5 checks on the enriched reference list.
    Returns a flat list of issue dicts in our standard format.
    """
    issues: List[Dict] = []

    def ref_by_id(ref_id: str) -> Dict:
        return next((r for r in enriched if r["id"] == ref_id), {})

    # ── Check 1: Ordering ────────────────────────────────────────────
    try:
        for iss in check_ordering(enriched, style).issues:
            ref = ref_by_id(iss.ref_id)
            issues.append(_to_issue(
                ref,
                msg=f"[Ordering] {iss.issue}",
                context=f"Expected: {iss.expected} | Found: {iss.found}",
                suggestions=[f"Reorder reference at position {iss.position}"],
                check_name="ordering",
            ))
    except Exception as e:
        print(f"check_ordering error: {e}")

    # ── Check 2: DOI ─────────────────────────────────────────────────
    try:
        for iss in check_doi(enriched, deep_check=False).issues:
            if iss.issue_type == "missing":
                ref = ref_by_id(iss.ref_id)
                issues.append(_to_issue(
                    ref,
                    msg=f"[DOI] {iss.detail}",
                    context=iss.suggestion or "",
                    suggestions=[iss.suggestion] if iss.suggestion else [],
                    check_name="doi",
                ))
    except Exception as e:
        print(f"check_doi error: {e}")

    # ── Check 3: Journal Casing ───────────────────────────────────────
    try:
        for iss in check_journal_casing(enriched, style).issues:
            ref = ref_by_id(iss.ref_id)
            issues.append(_to_issue(
                ref,
                msg=f"[Journal Casing] {iss.detail}",
                context=f"Journal: {iss.journal}",
                suggestions=[iss.suggestion] if iss.suggestion else [],
                check_name="journal_casing",
            ))
    except Exception as e:
        print(f"check_journal_casing error: {e}")

    # ── Check 4: Completeness ─────────────────────────────────────────
    try:
        for iss in check_completeness(enriched, style).issues:
            if iss.issue_type == "missing":   # only hard errors
                ref = ref_by_id(iss.ref_id)
                issues.append(_to_issue(
                    ref,
                    msg=f"[Completeness] {iss.detail}",
                    context=f"Missing field: {iss.field_name}",
                    suggestions=[iss.suggestion] if iss.suggestion else [],
                    check_name="completeness",
                ))
    except Exception as e:
        print(f"check_completeness error: {e}")

    # ── Check 5: Style Conformity ──────────────────────────────────────
    try:
        for iss in check_style_conformity(enriched, style).issues:
            ref = ref_by_id(iss.ref_id)
            issues.append(_to_issue(
                ref,
                msg=f"[Style] {iss.detail}",
                context=f"Expected: {iss.dominant_style} | Found: {iss.entry_style}",
                suggestions=[iss.suggestion] if iss.suggestion else [],
                check_name="style_conformity",
            ))
    except Exception as e:
        print(f"check_style_conformity error: {e}")

    return issues
