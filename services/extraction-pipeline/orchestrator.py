"""
orchestrator.py
===============
NuExtract-first extraction pipeline with regex for references/citations.

Architecture:
  PDF
   ├─► Camelot          → table grid data (once, full doc)
   ├─► PyMuPDF          → raw page text
   ├─► regex_extractor  → references (100% recall, zero tokens)
   │                    → in-text citations
   ├─► NuExtract3       → SOURCE OF TRUTH for:
   │     Page 1 (METADATA): title, abstract, authors, keywords
   │     All pages (BODY):  sections + body_text, equations, captions, acronyms
   └─► PyMuPDF          → coordinate mapping (post-process)

Why regex for references?
  References are mechanically structured ([N] Author, Title...).
  Regex found all 46 references vs NuExtract's 13 — because NuExtract
  truncates before finishing dense reference pages.
  NuExtract remains source of truth for everything semantic.
"""

from __future__ import annotations

import os
import re
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

from pymupdf_extractor import PyMuPDFExtractor
from nuextract_client import NuExtractClient, ExtractionMode
from camelot_extractor import extract_tables, CAMELOT_AVAILABLE
from regex_extractor import extract_references, extract_in_text_citations
from coordinate_mapper import enrich_with_coordinates


# ─────────────────────────────────────────────────────────────────────────────
# Constants — tuned for -c 16384 context window
# ─────────────────────────────────────────────────────────────────────────────

# Char caps per page sent to NuExtract
# With -c 16384: ~4000 chars input ≈ 1000 tokens + schema 300 + instructions 200
#   = ~1500 tokens input → 14000+ tokens available for output → safe
MAX_CHARS_METADATA: int = 15000  # page 1 needs full abstract & early sections
MAX_CHARS_BODY:     int = 15000  # body pages — captures most/all content

MIN_CHARS_FOR_LLM: int = 60     # skip blank/image-only pages

# Camelot noise filter: reject "tables" that are clearly full-page text blocks
CAMELOT_MIN_COLS: int = 2       # real tables have ≥2 columns
CAMELOT_MAX_ROWS_SINGLE_COL: int = 10  # single-col tables with >10 rows are text blocks


# ─────────────────────────────────────────────────────────────────────────────
# Helpers for cleanup
# ─────────────────────────────────────────────────────────────────────────────

def _clean_control_characters(text: str) -> str:
    """Map PDF mathematical control characters to standard Unicode/ASCII symbols."""
    mapping = {
        '\x02': '∑',
        '\x03': '∑',
        '\x04': '[',
        '\x05': ']',
        '\x06': '(',
        '\x07': ')',
        '\x08': '∑',
        '\x0b': '(',
        '\x0c': ')',
        '\x0e': '{',
        '\x0f': '}',
        '\x11': '[',
        '\x12': ']',
    }
    for char, repl in mapping.items():
        text = text.replace(char, repl)
    # Remove remaining other control characters (keeping tab, newline, carriage return)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    return text


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def extract_document(pdf_path: str) -> dict:
    timings: dict = {}
    t_start = time.monotonic()

    if not os.path.isfile(pdf_path):
        return _error_result(f"File not found: {pdf_path}")

    print(f"\n[Orchestrator] ═══ Starting: {pdf_path}")

    # ── Step 1: PyMuPDF — page text extraction ───────────────────────────────
    t1 = time.monotonic()
    print("[Orchestrator] Step 1/4 — PyMuPDF page text extraction …")
    try:
        with PyMuPDFExtractor(pdf_path) as ex:
            page_chunks = list(ex.page_chunks())
            for chunk in page_chunks:
                chunk.plain_text = _clean_control_characters(chunk.plain_text)
    except Exception as exc:
        return _error_result(f"Cannot read PDF: {exc}")

    page_texts: List[str] = [c.plain_text for c in page_chunks]
    full_text = "\n".join(page_texts)
    print(f"[Orchestrator] {len(page_texts)} page(s) extracted.")
    timings["pymupdf_s"] = round(time.monotonic() - t1, 2)

    # ── Step 2: Regex — references + in-text citations ───────────────────────
    t2 = time.monotonic()
    print("[Orchestrator] Step 2/4 — Regex reference + citation extraction …")
    references = extract_references(full_text, pdf_path)
    citations  = extract_in_text_citations(full_text, page_texts)
    print(f"[Orchestrator] Regex: {len(references)} reference(s), {len(citations)} citation(s).")
    timings["regex_s"] = round(time.monotonic() - t2, 2)

    # ── Step 3: Camelot — table grids ────────────────────────────────────────
    t3 = time.monotonic()
    camelot_tables: List[dict] = []
    if CAMELOT_AVAILABLE:
        try:
            print("[Orchestrator] Step 3/4 — Camelot table grids …")
            raw_tables = extract_tables(pdf_path)
            camelot_tables = _filter_camelot_noise([t.as_dict() for t in raw_tables])
            print(f"[Orchestrator] Camelot: {len(camelot_tables)} real table(s) (after noise filter).")
        except Exception as exc:
            print(f"[Orchestrator] Camelot failed (non-fatal): {exc}")
    else:
        print("[Orchestrator] Step 3/4 — Camelot not available.")
    timings["camelot_s"] = round(time.monotonic() - t3, 2)

    # ── Step 4: NuExtract — page-by-page structural extraction ───────────────
    t4 = time.monotonic()
    print("[Orchestrator] Step 4/4 — NuExtract page-by-page extraction …")

    import concurrent.futures

    # Scan first 5 pages to dynamically locate the page containing the abstract
    metadata_page = 1
    for chunk in page_chunks[:5]:
        if re.search(r'\babstract\b', chunk.plain_text, re.IGNORECASE):
            metadata_page = chunk.page_number
            print(f"[Orchestrator] Dynamic metadata page detected: Page {metadata_page}")
            break

    # Identify references start page to avoid extracting subsequent bibliography pages via LLM
    references_start_page = 9999
    if references:
        pages = [r.get("bbox", {}).get("page") for r in references if r.get("bbox")]
        if pages:
            references_start_page = min(pages)
            print(f"[Orchestrator] Dynamic references page detected: Page {references_start_page}")

    page_results: List[Tuple[int, ExtractionMode, Optional[dict], Optional[str]]] = []
    extraction_errors: List[dict] = []

    def extract_page_task(chunk, idx, llm_client):
        page_num = chunk.page_number
        if page_num > references_start_page:
            print(f"[Orchestrator] p{page_num}: skipping (references page).")
            return (page_num, ExtractionMode.BODY, {}, None)

        is_metadata = (page_num == metadata_page)
        mode = ExtractionMode.METADATA if is_metadata else ExtractionMode.BODY

        cap = MAX_CHARS_METADATA if is_metadata else MAX_CHARS_BODY
        # Replace newlines with spaces for NuExtract to avoid line-broken equation/section issues
        llm_input = chunk.plain_text.replace('\n', ' ').replace('\r', ' ')
        llm_input = re.sub(r'\s+', ' ', llm_input).strip()
        page_text = _trim_text(llm_input, cap)

        if len(page_text.strip()) < MIN_CHARS_FOR_LLM:
            print(f"[Orchestrator] p{page_num}: skipping (blank/image).")
            return (page_num, mode, {}, None)

        print(
            f"[Orchestrator] p{page_num}/{len(page_texts)} "
            f"[{mode.value}] ({len(page_text)} chars) → NuExtract …"
        )

        result, error = llm_client.extract(page_text, mode=mode, page_number=page_num)
        return (page_num, mode, result, error)

    try:
        with NuExtractClient() as llm:
            alive = llm.health_check()
            if not alive:
                print("[Orchestrator] WARNING: NuExtract server not responding.")

            # Concurrently extract pages using a pool size of 1
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                futures = {
                    executor.submit(extract_page_task, chunk, idx, llm): chunk
                    for idx, chunk in enumerate(page_chunks)
                }
                for future in concurrent.futures.as_completed(futures):
                    page_num, mode, result, error = future.result()
                    if error:
                        print(f"[Orchestrator] p{page_num}: failed ({error}).")
                        extraction_errors.append({"page": page_num, "reason": error})
                        page_results.append((page_num, mode, None, error))
                    else:
                        page_results.append((page_num, mode, result, None))

    except Exception as exc:
        traceback.print_exc()
        print(f"[Orchestrator] NuExtract session error: {exc}")

    # Ensure results are sorted in ascending page number order
    page_results.sort(key=lambda r: r[0])

    timings["nuextract_s"] = round(time.monotonic() - t4, 2)

    # ── Merge all results ─────────────────────────────────────────────────────
    merged = _merge_results(page_results, camelot_tables)
    merged["references"]        = references
    merged["in_text_citations"] = citations
    merged["extraction_errors"] = extraction_errors

    # ── Post-processing cleanup ───────────────────────────────────────────────
    _post_process(merged, full_text)

    # ── Coordinate mapping ────────────────────────────────────────────────────
    try:
        with PyMuPDFExtractor(pdf_path) as ex:
            enrich_with_coordinates(merged, ex)
        
        # Filter out headings that are journal headers or page headers/footers based on y-coordinate
        clean_sections = []
        for sec in merged.get("sections", []):
            bbox = sec.get("bbox")
            if bbox and sec.get("coordinate_found"):
                y0 = bbox.get("y0", 0)
                y1 = bbox.get("y1", 0)
                if y0 < 55 or y1 > 750:
                    print(f"[Orchestrator] Filtering out running header/footer section: {sec.get('heading_text')} (y0={y0}, y1={y1})")
                    continue
            clean_sections.append(sec)
        merged["sections"] = clean_sections

        print("[Orchestrator] Coordinate mapping complete.")
    except Exception as exc:
        print(f"[Orchestrator] Coordinate mapping failed (non-fatal): {exc}")

    timings["total_s"] = round(time.monotonic() - t_start, 2)
    merged["pipeline_timings"] = timings
    merged["total_pages_processed"] = len(page_texts)
    merged["pdf_path"] = pdf_path

    _print_summary(merged)
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# Camelot noise filter
# ─────────────────────────────────────────────────────────────────────────────

def _filter_camelot_noise(tables: List[dict]) -> List[dict]:
    """
    Remove Camelot "tables" that are clearly body text misdetected as tables.
    Real tables have ≥2 columns. Single-column "tables" with many rows are
    just body text blocks.
    """
    clean = []
    for t in tables:
        cols = t.get("col_count", 0)
        rows = t.get("row_count", 0)

        # Single-column with many rows → body text block, not a table
        if cols <= 1 and rows > CAMELOT_MAX_ROWS_SINGLE_COL:
            continue

        # Check headers — if the header is a page header/footer, skip
        headers = t.get("headers", [])
        if headers:
            h = headers[0] if isinstance(headers, list) else str(headers)
            if re.search(r'Knowledge-Based Systems|Contents lists available', str(h)):
                continue

        clean.append(t)
    return clean


# ─────────────────────────────────────────────────────────────────────────────
# Result merger
# ─────────────────────────────────────────────────────────────────────────────

def _merge_results(
    page_results: List[Tuple[int, ExtractionMode, Optional[dict], Optional[str]]],
    camelot_tables: List[dict],
) -> dict:
    doc: dict = {
        "manuscript":     _empty_manuscript(),
        "sections":       [],
        "references":     [],     # filled by regex later
        "equations":      [],
        "figures":        [],
        "tables":         [],
        "acronyms":       [],
        "camelot_tables": camelot_tables,
        "in_text_citations": [],  # filled by regex later
    }

    seen_sec_texts: set = set()
    seen_eq_nums:   set = set()
    seen_fig_nums:  set = set()
    seen_tbl_nums:  set = set()

    for (page_num, mode, data, error) in page_results:
        if not data:
            continue

        if mode == ExtractionMode.METADATA:
            _merge_manuscript(doc["manuscript"], data)

        if mode == ExtractionMode.BODY or mode == ExtractionMode.METADATA:
            # Sections
            for sec in data.get("sections") or []:
                key = (sec.get("heading_text") or "").strip().lower()[:80]
                if key and key not in seen_sec_texts:
                    seen_sec_texts.add(key)
                    # Ensure body_text is always a string
                    bt = sec.get("body_text", "")
                    if not isinstance(bt, str):
                        bt = str(bt) if bt else ""
                    sec["body_text"] = bt
                    sec["page_number"] = page_num
                    doc["sections"].append(sec)

            # Equations
            for eq in data.get("equations") or []:
                num = eq.get("number")
                try:
                    num = int(num)
                except (TypeError, ValueError):
                    continue  # skip non-integer equation numbers
                if num in seen_eq_nums:
                    continue
                seen_eq_nums.add(num)
                eq["number"] = num
                eq["page_number"] = page_num
                doc["equations"].append(eq)

            # Figures
            for fig in data.get("figures") or []:
                num = fig.get("number")
                try:
                    num = int(num)
                except (TypeError, ValueError):
                    continue
                if num not in seen_fig_nums:
                    seen_fig_nums.add(num)
                    fig["number"] = num
                    fig["page_number"] = page_num
                    doc["figures"].append(fig)

            # Tables (NuExtract captions — grids from Camelot)
            for tbl in data.get("tables") or []:
                num = tbl.get("number")
                try:
                    num = int(num)
                except (TypeError, ValueError):
                    continue
                if num not in seen_tbl_nums:
                    seen_tbl_nums.add(num)
                    tbl["number"] = num
                    tbl["page_number"] = page_num
                    doc["tables"].append(tbl)

            # Acronyms
            for acr in data.get("acronyms") or []:
                acr["page_number"] = page_num
                doc["acronyms"].append(acr)

    # Sort
    doc["sections"]  = doc["sections"]  # keep page order
    doc["equations"] = sorted(doc["equations"], key=lambda e: e.get("number", 0))
    doc["figures"]   = sorted(doc["figures"],   key=lambda f: f.get("number", 0))
    doc["tables"]    = sorted(doc["tables"],    key=lambda t: t.get("number", 0))

    # Attach Camelot grids
    doc["tables"] = _attach_camelot_grids(doc["tables"], camelot_tables)

    return doc


def _merge_manuscript(base: dict, update: dict) -> None:
    for field in ("title", "abstract_text"):
        if not base.get(field) and update.get(field):
            base[field] = update[field]
    if not base.get("abstract_word_count") and update.get("abstract_word_count"):
        base["abstract_word_count"] = update["abstract_word_count"]
    if not base.get("keywords") and update.get("keywords"):
        base["keywords"] = update["keywords"]
        base["keywords_section_present"] = True
    if not base.get("authors") and update.get("authors"):
        base["authors"] = update["authors"]
    ps = base.setdefault("publishing_statements", {})
    for key in ("conflict_of_interest", "funding_statement", "ethics_statement",
                "data_access_statement"):
        if ps.get(key) is None and update.get(key) is not None:
            ps[key] = update[key]


def _attach_camelot_grids(
    nu_tables: List[dict],
    camelot_tables: List[dict],
) -> List[dict]:
    used = set()
    result = []

    for tbl in nu_tables:
        t = dict(tbl)
        t["grid_data"] = None
        tbl_page = t.get("page_number") or 0

        best, best_d = None, 9999
        for i, ct in enumerate(camelot_tables):
            if i in used:
                continue
            d = abs((ct.get("page_number", ct.get("page", 0))) - tbl_page)
            if d < best_d:
                best_d, best = d, i

        if best is not None and best_d <= 2:
            t["grid_data"] = camelot_tables[best]
            used.add(best)

        result.append(t)

    # Append unmatched Camelot grids
    for i, ct in enumerate(camelot_tables):
        if i not in used:
            result.append({
                "label":            None,
                "number":           None,
                "caption_text":     None,
                "caption_position": None,
                "page_number":      ct.get("page_number", ct.get("page")),
                "grid_data":        ct,
            })

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Post-processing cleanup
# ─────────────────────────────────────────────────────────────────────────────

def _post_process(doc: dict, full_text: str) -> None:
    """Fix known extraction artifacts."""
    ms = doc.get("manuscript", {})

    # 1. Title — clean PDF word-break artifacts
    title = ms.get("title", "") or ""
    # Fix patterns like "gb est-guide d" → "gbest-guided"
    # Step 1: collapse spaces around hyphens only: " - " → "-"
    title = re.sub(r'\s*-\s+', '-', title)  # "guide- d" → "guide-d"
    title = re.sub(r'\s+-\s*', '-', title)  # "est -guide" → "est-guide"
    # Step 2: merge remaining short non-word fragments
    title = _fix_broken_words(title)
    ms["title"] = title.strip()

    # 2. Abstract — recount words after cleanup
    abstract = ms.get("abstract_text", "") or ""
    if abstract:
        ms["abstract_word_count"] = len(abstract.split())

    # 3. Equations — filter out bogus entries
    clean_eqs = []
    for eq in doc.get("equations", []):
        raw = eq.get("raw_text") or ""
        num = eq.get("number", 0)
        fmt = eq.get("number_format") or ""

        # Skip if no raw text
        if not raw.strip():
            continue

        # Skip if raw_text is just a number like "103", "10−25", "100"
        if re.match(r'^[\d\.\-−×\s]+$', raw.strip()):
            continue

        # Skip if raw_text is an equation reference like "Eq. (14)"
        if re.match(r'^Eq\.\s*\(\d+\)', raw.strip(), re.IGNORECASE):
            continue

        # Skip parameter settings without equals signs in equation format
        if re.match(r'^[αβγ]\s*=\s*\d', raw.strip()):
            continue

        # Ensure number_format is "(N)"
        if num and not fmt:
            eq["number_format"] = f"({num})"

        clean_eqs.append(eq)

    doc["equations"] = clean_eqs

    # 4. Sections — reconstruct body_text & clean up type safety
    sections = doc.get("sections", [])
    if sections:
        # Reconstruct body_text sequentially
        ref_header_re = re.compile(
            r'^\s*(?:\d+\.?\s+)?(?:references|bibliography|literature cited)\s*$',
            re.IGNORECASE | re.MULTILINE
        )
        ref_match = ref_header_re.search(full_text)
        doc_end = ref_match.start() if ref_match else len(full_text)

        heading_positions = []
        current_pos = 0
        for sec in sections:
            heading_text = (sec.get("heading_text") or "").strip()
            if not heading_text:
                heading_positions.append(None)
                continue

            words = heading_text.split()
            if not words:
                heading_positions.append(None)
                continue

            pattern_str = r'(?:^|\n)\s*(' + r'\s+'.join(re.escape(w) for w in words) + r')'
            pattern = re.compile(pattern_str, re.IGNORECASE)

            m = pattern.search(full_text, current_pos)
            if m:
                heading_positions.append((m.start(1), m.end(1)))
                current_pos = m.end(1)
            else:
                m_fallback = pattern.search(full_text)
                if m_fallback:
                    heading_positions.append((m_fallback.start(1), m_fallback.end(1)))
                    if m_fallback.end(1) > current_pos:
                        current_pos = m_fallback.end(1)
                else:
                    heading_positions.append(None)

        for i, sec in enumerate(sections):
            pos = heading_positions[i]
            if pos is None:
                sec["body_text"] = ""
                continue

            start_body = pos[1]
            end_body = doc_end
            for j in range(i + 1, len(sections)):
                next_pos = heading_positions[j]
                if next_pos is not None:
                    end_body = next_pos[0]
                    break

            body_text = full_text[start_body:end_body].strip()
            sec["body_text"] = body_text

    # Type safety and noise filtering
    for sec in sections:
        bt = sec.get("body_text", "")
        if not isinstance(bt, str):
            sec["body_text"] = str(bt) if bt else ""

        # Remove noise section headings
        heading = sec.get("heading_text", "") or ""
        heading_text = heading.strip()
        if (
            heading_text.isdigit()
            or re.match(r'^\s*(Table|Figure|Fig\.)\s+\d+', heading, re.IGNORECASE)
            or len(heading) > 150
            or re.search(r'Knowledge-Based Systems|journal homepage|Contents lists available', heading, re.IGNORECASE)
        ):
            sec["_is_noise"] = True

    # Remove noise sections
    doc["sections"] = [s for s in doc["sections"] if not s.get("_is_noise")]


def _fix_broken_words(title: str) -> str:
    """
    Fix PDF word-break artifacts in title text.
    E.g. "gb est-guide d" → "gbest-guided", "op timization" → "optimization"
    """
    REAL_SHORT_WORDS = {
        'a', 'an', 'in', 'on', 'of', 'to', 'or', 'is', 'it', 'by',
        'at', 'if', 'no', 'so', 'up', 'do', 'we', 'as', 'he', 'be',
        'am', 'my', 'us', 'me', 'vs'
    }

    words = title.split()

    # Pass 1: LEFT merge for 1-character fragments (suffixes like 'd', 's')
    changed = True
    while changed:
        changed = False
        new_words = []
        i = 0
        while i < len(words):
            if i + 1 < len(words) and len(words[i + 1]) == 1 and words[i + 1].isalpha() and words[i + 1].lower() not in REAL_SHORT_WORDS:
                new_words.append(words[i] + words[i + 1])
                i += 2
                changed = True
            else:
                new_words.append(words[i])
                i += 1
        words = new_words

    # Pass 2: RIGHT merge for remaining 1-2 character fragments (prefixes like 'gb', 'op')
    changed = True
    while changed:
        changed = False
        new_words = []
        i = 0
        while i < len(words):
            if len(words[i]) <= 2 and words[i].isalpha() and words[i].lower() not in REAL_SHORT_WORDS and i + 1 < len(words):
                new_words.append(words[i] + words[i + 1])
                i += 2
                changed = True
            else:
                new_words.append(words[i])
                i += 1
        words = new_words

    return " ".join(words)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _trim_text(text: str, cap: int) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    if len(text) > cap:
        text = text[:cap]
        # Try to break at a sentence or line boundary
        last_period = text.rfind(". ")
        last_nl = text.rfind("\n")
        break_at = max(last_period, last_nl)
        if break_at > cap * 0.85:
            text = text[:break_at + 1]
        text += "\n[...truncated...]"
    return text.strip()


def _empty_manuscript() -> dict:
    return {
        "title":                    None,
        "abstract_text":            None,
        "abstract_word_count":      None,
        "keywords":                 [],
        "keywords_section_present": None,
        "authors":                  [],
        "publishing_statements": {
            "conflict_of_interest":          None,
            "ethics_statement":              None,
            "funding_statement":             None,
            "data_access_statement":         None,
            "author_contribution_statement": None,
        },
    }


def _print_summary(r: dict) -> None:
    t = r.get("pipeline_timings", {})
    errs = r.get("extraction_errors", [])
    abs_text = r.get("manuscript", {}).get("abstract_text") or ""
    print(
        f"\n[Orchestrator] ═══ Done ═══════════════════════════════════════\n"
        f"  Pages        : {r.get('total_pages_processed', '?')}\n"
        f"  Errors       : {len(errs)}\n"
        f"  Abstract     : {'YES (' + str(len(abs_text)) + ' chars)' if abs_text else 'NOT FOUND'}\n"
        f"  Sections     : {len(r.get('sections', []))}\n"
        f"  References   : {len(r.get('references', []))} (regex)\n"
        f"  Equations    : {len(r.get('equations', []))}\n"
        f"  Tables       : {len(r.get('tables', []))} (NuExtract) + {len(r.get('camelot_tables', []))} (Camelot)\n"
        f"  Figures      : {len(r.get('figures', []))}\n"
        f"  Citations    : {len(r.get('in_text_citations', []))}\n"
        f"  PyMuPDF      : {t.get('pymupdf_s', '?')}s\n"
        f"  Regex        : {t.get('regex_s', '?')}s\n"
        f"  Camelot      : {t.get('camelot_s', '?')}s\n"
        f"  NuExtract    : {t.get('nuextract_s', '?')}s\n"
        f"  TOTAL        : {t.get('total_s', '?')}s\n"
        f"═══════════════════════════════════════════════════════════════"
    )


def _error_result(message: str) -> dict:
    print(f"[Orchestrator] FATAL: {message}")
    return {
        "error":               message,
        "manuscript":          _empty_manuscript(),
        "sections":            [],
        "references":          [],
        "equations":           [],
        "figures":             [],
        "tables":              [],
        "in_text_citations":   [],
        "camelot_tables":      [],
        "acronyms":            [],
        "extraction_errors":   [{"page": 0, "reason": message}],
        "total_pages_processed": 0,
    }
