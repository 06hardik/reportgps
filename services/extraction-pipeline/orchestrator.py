"""
orchestrator.py
===============
6-step extraction and validation pipeline.

Architecture:
  PDF
   ├─► Step 1:   PyMuPDF              → raw page text + font metadata + image bboxes
   ├─► Step 2:   structural_analyzer  → headings, metadata, figures, tables
   ├─► Step 2.5: equation_extractor   → right-margin label scan (PyMuPDF, fast)
   ├─► Step 3a:  regex_extractor       → references + in-text citations
   ├─► Step 3b:  typography_checker    → en-dash, unit-space, percent, latin abbrevs
   ├─► Step 3c:  figures_tables_checker → checks 7–13
   ├─► Step 3d:  syntax_grammar_checker → checks 17–24
   ├─► Step 3e:  equation_checker      → checks 15–17
   └─► Step 4:   verifier              → AI false-positive filter (optional)

Target time: < 2 seconds per paper (< 0.5s without AI verifier).

Output JSON schema: see docs/pipeline_architecture.md
"""

from __future__ import annotations

import os
import re
import time
import traceback
from typing import Any, Dict, List


from modules.extractors.pymupdf_extractor import PyMuPDFExtractor
from modules.extractors.structural_analyzer import analyze_structure
from modules.extractors.regex_extractor import extract_references, extract_in_text_citations
from modules.checkers.typography_checker import check_typography
from modules.checkers.figures_tables_checker import check_figures_and_tables
from modules.checkers.syntax_grammar_checker import check_syntax_grammar

from modules.verifier.verifier_config import VERIFIER_ENABLED
from modules.verifier.verifier import verify_candidates

from modules.reference_analyser.analyser import referenceErrorParser


# ─────────────────────────────────────────────────────────────────────────────
# Reference Checks Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _call_reference_analyser(raw_ref_strings: List[str]) -> List[Dict]:
    """
    Directly call the local reference analyser function instead of using HTTP.
    Returns the enriched reference list with quality_issues populated.
    """
    if not raw_ref_strings:
        return []

    try:
        return referenceErrorParser(
            bibtex_string="",
            coordinate_str="{}",
            raw_ref_strings=raw_ref_strings
        )
    except Exception as exc:
        traceback.print_exc()
        print(f"[Orchestrator] Reference-analyser call failed (non-fatal): {exc}")
        return []


def _parse_citation_numbers(cit: Dict) -> List[int]:
    """
    Extract all integer reference numbers from a citation dict.
    Handles the `numbers`, `number`, and `marker` fields produced by
    extract_in_text_citations (which stores e.g. "[1,2]" or "[3-5]" in `marker`).
    """
    nums: List[int] = []

    # Prefer explicit numbers list
    explicit = cit.get("numbers") or []
    if not explicit:
        n = cit.get("number")
        if n is not None:
            explicit = [n]
    for n in explicit:
        try:
            nums.append(int(n))
        except (ValueError, TypeError):
            pass
    if nums:
        return nums

    # Fall back to parsing the marker string e.g. "[1,2,3]" or "[1-3]"
    marker = str(cit.get("marker", ""))
    # Strip brackets
    inner = re.sub(r"[\[\](){}]", " ", marker)
    # Expand ranges like "3-5" → 3,4,5
    for part in re.split(r"[,;]\s*", inner):
        part = part.strip()
        rng = re.match(r"(\d+)\s*[-\u2013\u2014]\s*(\d+)", part)
        if rng:
            lo, hi = int(rng.group(1)), int(rng.group(2))
            if 0 < hi - lo < 50:   # sanity cap
                nums.extend(range(lo, hi + 1))
        else:
            m = re.match(r"(\d+)$", part)
            if m:
                nums.append(int(m.group(1)))
                
    # Heuristic: if the extracted numbers contain duplicates (e.g., [100, 100]),
    # it's almost certainly a mathematical vector or coordinate, not a citation.
    if len(nums) > 1 and len(set(nums)) < len(nums):
        return []
        
    return nums


def _check_bidirectional_match(
    references: List[Dict],
    citations: List[Dict],
) -> Dict:
    """
    Check 2 — Bidirectional citation match.

    Forward : every cited number in the body text must appear in the reference list.
    Backward: every reference in the list must be cited at least once.
    """
    ref_numbers: set = set()
    for ref in references:
        num = ref.get("number")
        if num is not None:
            try:
                n = int(num)
                if n > 0:          # references always start from 1
                    ref_numbers.add(n)
            except (ValueError, TypeError):
                pass

    max_ref = max(ref_numbers) if ref_numbers else 0
    buffer = max(5, int(max_ref * 0.2))

    cited_numbers: set = set()
    cited_pages: dict = {}
    for cit in citations:
        page = cit.get("page_number", 1)
        for n in _parse_citation_numbers(cit):
            if n > 0:              # [0] is never a valid citation
                # Heuristic: if the citation number is absurdly higher than the reference count,
                # it's almost certainly a math/table artifact (e.g., [128] in a 95-ref paper).
                if max_ref > 0 and n > max_ref + buffer:
                    continue
                cited_numbers.add(n)
                if n not in cited_pages:
                    cited_pages[n] = page

    # If we couldn't extract any citation numbers at all, skip the check
    # (better to show nothing than 100% false positives)
    if not cited_numbers and citations:
        return {"passed": True, "violations": [], "skipped": True,
                "reason": "Could not parse numeric citation markers."}

    missing_from_refs = sorted(cited_numbers - ref_numbers)
    uncited_refs      = sorted(ref_numbers - cited_numbers)

    violations = []
    for n in missing_from_refs:
        violations.append({
            "type":       "missing_from_refs",
            "number":     n,
            "page":       cited_pages.get(n, 1),
            "detail":     f"[{n}] is cited in the text but has no corresponding entry in the reference list.",
            "suggestion": f"Add a reference entry for [{n}] in the reference list.",
        })
    for n in uncited_refs:
        violations.append({
            "type":       "uncited_ref",
            "number":     n,
            "detail":     f"Reference [{n}] appears in the reference list but is never cited in the body text.",
            "suggestion": f"Either cite reference [{n}] in the text or remove it from the reference list.",
        })

    return {"passed": len(violations) == 0, "violations": violations}



def _build_reference_checks(
    analyser_results: List[Dict],
    bidirectional: Dict,
) -> Dict:
    """
    Flatten the reference-analyser output + bidirectional results into
    the 6-check schema expected by the frontend under `reference_checks`.
    """
    style_violations        = []
    ordering_violations     = []
    completeness_violations = []
    doi_violations          = []
    consistency_violations  = []

    for entry in analyser_results:
        ref_id = entry.get("ID") or entry.get("id") or "?"

        for qi in entry.get("quality_issues", []):
            check = qi.get("check", "")
            msg   = qi.get("message", "")
            ctx   = qi.get("context", "")
            sug   = qi.get("suggestions") or []
            v = {
                "ref_id":     ref_id,
                "detail":     msg,
                "context":    ctx,
                "suggestion": sug[0] if sug else "",
            }
            if check == "ordering":
                ordering_violations.append(v)
            elif check == "doi":
                doi_violations.append(v)
            elif check in ("journal_casing", "style_conformity"):
                style_violations.append(v)
            elif check == "completeness":
                completeness_violations.append(v)

        for field in entry.get("asterikError", []):
            completeness_violations.append({
                "ref_id":     ref_id,
                "detail":     f"Required field missing: '{field}'",
                "context":    f"Entry type: {entry.get('ENTRYTYPE', '?')}",
                "suggestion": f"Add the '{field}' field to this reference.",
            })
        for field in entry.get("consistencyError", []):
            consistency_violations.append({
                "ref_id":     ref_id,
                "detail":     f"Field '{field}' is present in some entries but missing here.",
                "context":    f"Entry type: {entry.get('ENTRYTYPE', '?')}",
                "suggestion": f"Ensure all {entry.get('ENTRYTYPE','?')} entries include the '{field}' field.",
            })

    return {
        "style_compliance": {
            "passed":     len(style_violations) == 0,
            "violations": style_violations,
        },
        "bidirectional_match": bidirectional,
        "metadata_completeness": {
            "passed":     len(completeness_violations) == 0,
            "violations": completeness_violations,
        },
        "doi_url": {
            "passed":     len(doi_violations) == 0,
            "violations": doi_violations,
        },
        "sequential_ordering": {
            "passed":     len(ordering_violations) == 0,
            "violations": ordering_violations,
        },
        "field_consistency": {
            "passed":     len(consistency_violations) == 0,
            "violations": consistency_violations,
        },
    }
from modules.extractors.equation_extractor import extract_equations
from modules.checkers.equation_checker import run_all_checks


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
            "estimated_word_count": len(full_text.split()),
        }

    print(
        f"[Orchestrator] Structural: "
        f"{len(structural.get('sections', []))} section(s), "
        f"{len(structural.get('figures', []))} figure(s), "
        f"{len(structural.get('tables', []))} table(s)."
    )
    timings["structural_s"] = round(time.monotonic() - t2, 2)

    # ── Step 2.5: Equation extraction (PyMuPDF right-margin scan) ───────────────
    t_eq = time.monotonic()
    print("[Orchestrator] Step 2.5/3 — Equation extraction (PyMuPDF) …")
    try:
        equations = extract_equations(pdf_path)
    except Exception as exc:
        traceback.print_exc()
        print(f"[Orchestrator] Equation extraction error (non-fatal): {exc}")
        equations = []
    
    print(f"[Orchestrator] Equation extraction: {len(equations)} equation(s) found.")
    timings["equation_extraction_s"] = round(time.monotonic() - t_eq, 2)


    # ── Step 3a: Regex — references + in-text citations ───────────────────────
    t3 = time.monotonic()
    print("[Orchestrator] Step 3/3 — Regex extraction (refs + citations + typography) …")
    try:
        references = extract_references(full_text, pdf_path)
    except Exception as exc:
        print(f"[Orchestrator] Reference extraction error (non-fatal): {exc}")
        references = []

    try:
        citations = extract_in_text_citations(full_text, page_texts, references)
    except Exception as exc:
        print(f"[Orchestrator] Citation extraction error (non-fatal): {exc}")
        citations = []

    print(f"[Orchestrator] Regex: {len(references)} reference(s), {len(citations)} citation(s).")
    timings["regex_s"] = round(time.monotonic() - t3, 2)

    # ── Compute body_text (references section excluded) — shared by Steps 3b & 3d ──
    _ref_re = re.compile(
        r'^\s*(?:\d+\.?\s+)?(?:references?|bibliography)\s*$',
        re.IGNORECASE | re.MULTILINE,
    )
    _ref_start = _ref_re.search(full_text)
    body_text = full_text[: _ref_start.start()] if _ref_start else full_text

    # ── Step 3b: Typography checks ────────────────────────────────────────────
    t4 = time.monotonic()
    try:
        typography = check_typography(body_text)
    except Exception as exc:
        print(f"[Orchestrator] Typography check error (non-fatal): {exc}")
        typography = {
            "en_dash_violations": [],
            "number_unit_violations": [],
            "percent_degree_violations": [],
        }

    typo_total = sum(len(v) for v in typography.values())
    print(f"[Orchestrator] Typography: {typo_total} violation(s) flagged.")
    timings["typography_s"] = round(time.monotonic() - t4, 2)

    # ── Step 3c: Figures & Tables checks ─────────────────────────────────────
    t5 = time.monotonic()
    try:
        figures_tables_checks = check_figures_and_tables(
            figures=structural.get("figures", []),
            tables=structural.get("tables", []),
            page_texts=page_texts,
        )
    except Exception as exc:
        print(f"[Orchestrator] Figures/Tables check error (non-fatal): {exc}")
        figures_tables_checks = {}
    print(
        f"[Orchestrator] Figures/Tables checks: "
        f"{len(figures_tables_checks)} check(s) run."
    )
    timings["figures_tables_s"] = round(time.monotonic() - t5, 2)
    page_offsets = []
    pos = 0
    for pt in page_texts:
        page_offsets.append(pos)
        pos += len(pt) + 1

    # ── Step 3d: Syntax / Grammar checks ─────────────────────────────────────
    t6 = time.monotonic()
    try:
        syntax_grammar_checks = check_syntax_grammar(
            full_text=full_text,
            body_text=body_text,
            page_offsets=page_offsets,
        )
    except Exception as exc:
        print(f"[Orchestrator] Syntax/Grammar check error (non-fatal): {exc}")
        syntax_grammar_checks = {}
    print(
        f"[Orchestrator] Syntax/Grammar: "
        f"{len(syntax_grammar_checks)} check(s) run."
    )
    timings["syntax_grammar_s"] = round(time.monotonic() - t6, 2)


    # ── Step 3e: Reference quality checks ────────────────────────────────────
    t7 = time.monotonic()
    # Extract raw reference strings from already-parsed references list
    raw_ref_strings = [
        ref["raw_string"] for ref in references
        if ref.get("raw_string", "").strip()
    ]
    try:
        analyser_results = _call_reference_analyser(raw_ref_strings)
    except Exception as exc:
        print(f"[Orchestrator] Reference analyser error (non-fatal): {exc}")
        analyser_results = []

    try:
        bidirectional = _check_bidirectional_match(references, citations)
    except Exception as exc:
        print(f"[Orchestrator] Bidirectional check error (non-fatal): {exc}")
        bidirectional = {"passed": True, "violations": []}

    reference_checks = _build_reference_checks(analyser_results, bidirectional)
    ref_issue_count  = sum(
        len(v["violations"]) for v in reference_checks.values()
        if isinstance(v, dict) and "violations" in v
    )
    print(f"[Orchestrator] Reference checks: {ref_issue_count} issue(s) found.")
    timings["reference_checks_s"] = round(time.monotonic() - t7, 2)

    # ── Assemble partial result for verifier ──────────────────────────────────
    # ── Step 3e: Equation checks (15-18) ─────────────────────────────────────
    t_eq_check = time.monotonic()
    print("[Orchestrator] Step 3f/3 — Equation checks …")
    try:
        equation_checks = run_all_checks(
            equations=equations, 
            full_text=full_text,
            page_offsets=page_offsets,
        )
    except Exception as exc:
        traceback.print_exc()
        print(f"[Orchestrator] Equation checks error (non-fatal): {exc}")
        equation_checks = {}
    
    timings["equation_checks_s"] = round(time.monotonic() - t_eq_check, 2)

    # ── Assemble final result ─────────────────────────────────────────────────
    timings["total_s"] = round(time.monotonic() - t_start, 2)

    result = {
        **structural,
        "equations":               equations,
        "equation_checks":         equation_checks,
        "references":              references,
        "in_text_citations":       citations,
        "typography":              typography,
        "figures_tables_checks":   figures_tables_checks,
        "syntax_grammar_checks":   syntax_grammar_checks,
        "reference_checks":        reference_checks,
        "extraction_errors":       [],
        "total_pages_processed":   len(page_texts),
        "pdf_path":                pdf_path,
        "pipeline_timings":        timings,
    }

    # ── Step 3f: AI Verifier (optional — controlled by VERIFIER_ENABLED) ──────
    if VERIFIER_ENABLED:
        t8 = time.monotonic()
        try:
            validated_findings = verify_candidates(result)
        except Exception as exc:
            print(f"[Orchestrator] Verifier error (non-fatal): {exc}")
            validated_findings = []
        timings["verifier_s"] = round(time.monotonic() - t8, 2)
        timings["total_s"]    = round(time.monotonic() - t_start, 2)
    else:
        validated_findings = []

    result["validated_findings"] = validated_findings

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
    eq_checks = r.get("equation_checks", {})
    eq_checks_passed = sum(1 for v in eq_checks.values() if isinstance(v, dict) and v.get("passed"))
    eq_checks_total  = len(eq_checks)

    print(
        f"\n[Orchestrator] ═══ Done ═══════════════════════════════════════\n"
        f"  Pages        : {r.get('total_pages_processed', '?')}\n"
        f"  Title        : {'YES' if ms.get('title') else 'NOT FOUND'}\n"
        f"  Abstract     : {'YES (' + str(ms.get('abstract_word_count') or 0) + ' words)' if ms.get('abstract_text') else 'NOT FOUND'}\n"
        f"  Keywords     : {len(ms.get('keywords') or [])}\n"
        f"  Authors      : {len(ms.get('authors') or [])}\n"
        f"  Sections     : {len(r.get('sections', []))}\n"
        f"  Figures      : {len(r.get('figures', []))}\n"
        f"  Tables       : {len(r.get('tables', []))}\n"
        f"  Equations    : {len(r.get('equations', []))} (checks: {eq_checks_passed}/{eq_checks_total} passed)\n"
        f"  References   : {len(r.get('references', []))} (regex)\n"
        f"  Citations    : {len(r.get('in_text_citations', []))}\n"
        f"  Typography   : {typo_total} violation(s)\n"
        f"  Word count   : ~{r.get('estimated_word_count', 0)}\n"
        f"  PyMuPDF      : {t.get('pymupdf_s', '?')}s\n"
        f"  Structural   : {t.get('structural_s', '?')}s\n"
        f"  Equations    : {t.get('equation_extraction_s', '?')}s (extraction) + {t.get('equation_checks_s', '?')}s (checks)\n"
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
        },
        "figures_tables_checks":  {},
        "syntax_grammar_checks":  {},
        "equation_checks":        {},
        "extraction_errors":   [{"page": 0, "reason": message}],
        "estimated_word_count": 0,
        "total_pages_processed": 0,
    }
