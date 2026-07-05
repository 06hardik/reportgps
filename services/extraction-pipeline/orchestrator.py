"""
orchestrator.py
===============
Lean, 3-step extraction pipeline — no LLM, no ML models, no heavy table grids.

Architecture:
  PDF
   ├─► Step 1: PyMuPDF          → raw page text + font metadata + image bboxes
   ├─► Step 2: structural_analyzer → headings, metadata, figures, tables, equations
   ├─► Step 3a: regex_extractor → references + in-text citations
   └─► Step 3b: typography_checker → en-dash, unit-space, percent, latin abbrevs

Target time: 3–8 seconds for a 20-page paper (was 50–175s with NuExtract).

Output JSON schema: see docs/extraction_pipeline_architecture.md
"""

from __future__ import annotations

import os
import re
import time
import traceback
from typing import Any, Dict, List

from pymupdf_extractor import PyMuPDFExtractor
from structural_analyzer import analyze_structure
from regex_extractor import extract_references, extract_in_text_citations
from typography_checker import check_typography


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def extract_document(pdf_path: str) -> dict:
    """
    Run the full extraction pipeline on a PDF file.

    Returns a structured dict suitable for the checks engine and frontend display.
    """
    timings: Dict[str, float] = {}
    t_start = time.monotonic()

    if not os.path.isfile(pdf_path):
        return _error_result(f"File not found: {pdf_path}")

    print(f"\n[Orchestrator] ═══ Starting: {pdf_path}")

    # ── Step 1: PyMuPDF — extract text + font metadata + image bboxes ─────────
    t1 = time.monotonic()
    print("[Orchestrator] Step 1/3 — PyMuPDF extraction …")
    try:
        with PyMuPDFExtractor(pdf_path) as ex:
            page_chunks = list(ex.page_chunks())
    except Exception as exc:
        return _error_result(f"Cannot read PDF: {exc}")

    page_texts: List[str] = [c.plain_text for c in page_chunks]
    full_text: str = "\n".join(page_texts)

    total_images = sum(c.image_count for c in page_chunks)
    print(f"[Orchestrator] {len(page_texts)} page(s), {total_images} image block(s).")
    timings["pymupdf_s"] = round(time.monotonic() - t1, 2)

    # ── Step 2: Structural analysis ───────────────────────────────────────────
    t2 = time.monotonic()
    print("[Orchestrator] Step 2/3 — Structural analysis …")
    try:
        structural = analyze_structure(page_chunks, full_text, page_texts)
    except Exception as exc:
        traceback.print_exc()
        print(f"[Orchestrator] Structural analysis error (non-fatal): {exc}")
        structural = {
            "manuscript": _empty_manuscript(),
            "sections": [],
            "figures": [],
            "tables": [],
            "equations": [],
            "estimated_word_count": len(full_text.split()),
        }

    print(
        f"[Orchestrator] Structural: "
        f"{len(structural.get('sections', []))} section(s), "
        f"{len(structural.get('figures', []))} figure(s), "
        f"{len(structural.get('tables', []))} table(s), "
        f"{len(structural.get('equations', []))} equation(s)."
    )
    timings["structural_s"] = round(time.monotonic() - t2, 2)

    # ── Step 3a: Regex — references + in-text citations ───────────────────────
    t3 = time.monotonic()
    print("[Orchestrator] Step 3/3 — Regex extraction (refs + citations + typography) …")
    try:
        references = extract_references(full_text, pdf_path)
    except Exception as exc:
        print(f"[Orchestrator] Reference extraction error (non-fatal): {exc}")
        references = []

    try:
        citations = extract_in_text_citations(full_text, page_texts)
    except Exception as exc:
        print(f"[Orchestrator] Citation extraction error (non-fatal): {exc}")
        citations = []

    print(f"[Orchestrator] Regex: {len(references)} reference(s), {len(citations)} citation(s).")
    timings["regex_s"] = round(time.monotonic() - t3, 2)

    # ── Step 3b: Typography checks ────────────────────────────────────────────
    t4 = time.monotonic()
    try:
        # Run typography on body only (exclude references section)
        ref_re = re.compile(
            r'^\s*(?:\d+\.?\s+)?(?:references?|bibliography)\s*$',
            re.IGNORECASE | re.MULTILINE,
        )
        ref_start = ref_re.search(full_text)
        body_text = full_text[: ref_start.start()] if ref_start else full_text
        typography = check_typography(body_text)
    except Exception as exc:
        print(f"[Orchestrator] Typography check error (non-fatal): {exc}")
        typography = {
            "en_dash_violations": [],
            "number_unit_violations": [],
            "percent_degree_violations": [],
            "latin_abbrev_violations": [],
        }

    typo_total = sum(len(v) for v in typography.values())
    print(f"[Orchestrator] Typography: {typo_total} violation(s) flagged.")
    timings["typography_s"] = round(time.monotonic() - t4, 2)

    # ── Assemble final result ─────────────────────────────────────────────────
    timings["total_s"] = round(time.monotonic() - t_start, 2)

    result = {
        **structural,
        "references":        references,
        "in_text_citations": citations,
        "typography":        typography,
        "extraction_errors": [],
        "total_pages_processed": len(page_texts),
        "pdf_path":          pdf_path,
        "pipeline_timings":  timings,
    }

    _print_summary(result)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _print_summary(r: dict) -> None:
    t = r.get("pipeline_timings", {})
    ms = r.get("manuscript", {})
    typo = r.get("typography", {})
    typo_total = sum(len(v) for v in typo.values()) if isinstance(typo, dict) else 0

    print(
        f"\n[Orchestrator] ═══ Done ═══════════════════════════════════════\n"
        f"  Pages        : {r.get('total_pages_processed', '?')}\n"
        f"  Title        : {'YES' if ms.get('title') else 'NOT FOUND'}\n"
        f"  Abstract     : {'YES (' + str(ms.get('abstract_word_count') or 0) + ' words)' if ms.get('abstract_text') else 'NOT FOUND'}\n"
        f"  Keywords     : {len(ms.get('keywords') or [])}\n"
        f"  Sections     : {len(r.get('sections', []))}\n"
        f"  Figures      : {len(r.get('figures', []))}\n"
        f"  Tables       : {len(r.get('tables', []))}\n"
        f"  Equations    : {len(r.get('equations', []))}\n"
        f"  References   : {len(r.get('references', []))} (regex)\n"
        f"  Citations    : {len(r.get('in_text_citations', []))}\n"
        f"  Typography   : {typo_total} violation(s)\n"
        f"  Word count   : ~{r.get('estimated_word_count', 0)}\n"
        f"  PyMuPDF      : {t.get('pymupdf_s', '?')}s\n"
        f"  Structural   : {t.get('structural_s', '?')}s\n"
        f"  Regex        : {t.get('regex_s', '?')}s\n"
        f"  Typography   : {t.get('typography_s', '?')}s\n"
        f"  TOTAL        : {t.get('total_s', '?')}s\n"
        f"═══════════════════════════════════════════════════════════════"
    )


def _empty_manuscript() -> dict:
    return {
        "title":                    None,
        "abstract_text":            None,
        "abstract_word_count":      None,
        "keywords":                 [],
        "keywords_section_present": False,
        "authors":                  [],
        "publishing_statements": {
            "conflict_of_interest":          None,
            "ethics_statement":              None,
            "funding_statement":             None,
            "data_access_statement":         None,
            "author_contribution_statement": None,
        },
    }


def _error_result(message: str) -> dict:
    print(f"[Orchestrator] FATAL: {message}")
    return {
        "error":               message,
        "manuscript":          _empty_manuscript(),
        "sections":            [],
        "figures":             [],
        "tables":              [],
        "equations":           [],
        "references":          [],
        "in_text_citations":   [],
        "typography": {
            "en_dash_violations": [],
            "number_unit_violations": [],
            "percent_degree_violations": [],
            "latin_abbrev_violations": [],
        },
        "extraction_errors":   [{"page": 0, "reason": message}],
        "estimated_word_count": 0,
        "total_pages_processed": 0,
    }
