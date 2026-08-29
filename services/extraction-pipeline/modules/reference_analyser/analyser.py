"""
analyser.py
===========
Reference analysis: existing BibTeX field checks + 5 new quality checks.

Raw reference string priority:
  1. GROBID refBibs[].rawForm  -- ideal, exact PDF text
  2. PDF text extraction        -- from regex-checker section extractor
  3. Reconstructed from BibTeX  -- last resort, ordering/completeness skipped

Quality result cap: MAX_QUALITY_ISSUES (50) to avoid UI overload.
"""
import json
import re
import bibtexparser
from typing import Any, Dict, List, Optional

from .reference_quality import (
    build_enriched_refs,
    detect_citation_style,
)


# ---------------------------------------------------------------------------
# Existing BibTeX consistency checker (unchanged)
# ---------------------------------------------------------------------------

class ConsistencyHandler:
    def __init__(self):
        self.articleExtraFields        = set()
        self.inbookExtraFields         = set()
        self.techreportExtraFields     = set()
        self.inproceedingsExtraFields  = set()
        self.articleImportantFields    = {'year','author','title','journal','volume','pages'}
        self.inbookImportantFields     = {'author','year','booktitle'}
        self.techreportImportantFields = {'title','author','institution','year','number'}
        self.inproceedingsImportantFields = {'author','title','booktitle','year','pages'}
        self.articleCount       = 0
        self.inbookCount        = 0
        self.techreportCount    = 0
        self.inproceedingscount = 0

    def _check(self, entry, important, extra_set, count_attr):
        all_fields  = set(entry.keys()) - {'ID', 'number', 'ENTRYTYPE', 'date'}
        # imp_errors: required fields that are absent from this entry
        imp_errors  = important - all_fields if not important.issubset(all_fields) else set()
        # temp: extra (non-required) fields present in this entry
        temp        = all_fields - important
        cons_errors = set()
        count       = getattr(self, count_attr)

        for f in temp:
            if count == 0:
                extra_set.add(f)          # establish pattern from first entry
            elif f not in extra_set:
                cons_errors.add(f)        # field present here but not in pattern (unusual)

        # Fields in the established pattern that are ABSENT from this entry
        # (i.e., most entries have them but this one doesn't)
        if count > 0:
            cons_errors = cons_errors.union(extra_set - temp)

        # Remove trivial or universally-required fields that should never appear
        # in inconsistency warnings (they would be caught as critical errors if truly missing)
        _NEVER_INCONSISTENT = {'title', 'author', 'year', 'month', 'note', 'abstract'}
        cons_errors -= _NEVER_INCONSISTENT

        setattr(self, count_attr, count + 1)
        return imp_errors, cons_errors


    def checkArticles(self, entry):
        return self._check(entry, self.articleImportantFields,
                           self.articleExtraFields, 'articleCount')
    def checkInbook(self, entry):
        return self._check(entry, self.inbookImportantFields,
                           self.inbookExtraFields, 'inbookCount')
    def checkTechreport(self, entry):
        return self._check(entry, self.techreportImportantFields,
                           self.techreportExtraFields, 'techreportCount')
    def checkInproceedings(self, entry):
        return self._check(entry, self.inproceedingsImportantFields,
                           self.inproceedingsExtraFields, 'inproceedingscount')


def bibtex_to_dict_list(bibtex_string: str) -> List[Dict[str, Any]]:
    bib_database = bibtexparser.loads(bibtex_string)
    return [dict(entry) for entry in bib_database.entries]


def _run_consistency_checks(entries: List[Dict]) -> None:
    checker = ConsistencyHandler()
    for entry in entries:
        etype = entry.get('ENTRYTYPE', '')
        if etype == 'article':
            imp, cons = checker.checkArticles(entry)
            entry['asterikError']     = list(imp)
            entry['consistencyError'] = list(cons)
        elif etype == 'inbook':
            imp, cons = checker.checkInbook(entry)
            entry['asterikError']     = list(imp)
            entry['consistencyError'] = list(cons)
        elif etype == 'inproceedings':
            imp, cons = checker.checkInproceedings(entry)
            entry['asterikError']     = list(imp)
            entry['consistencyError'] = list(cons)
        elif etype == 'misc':
            # Only warn if truly incomplete (missing multiple essential fields)
            has_author = bool(entry.get('author', '').strip())
            has_title  = bool(entry.get('title',  '').strip())
            has_year   = bool(entry.get('year',   '').strip())
            has_url    = bool(entry.get('url', '').strip()) or bool(entry.get('howpublished', '').strip())
            # A misc entry is fine if it has at least (author + year) or (title + year)
            truly_incomplete = not has_year or (not has_author and not has_title)
            if truly_incomplete:
                missing = []
                if not has_author: missing.append('author')
                if not has_title:  missing.append('title')
                if not has_year:   missing.append('year')
                entry['warningMessage'] = (
                    f"Miscellaneous entry is incomplete — missing: {', '.join(missing)}. "
                    "If this is a website, also add URL/howpublished."
                )
            # else: book/chapter with author+title+year is fine as @misc



# ---------------------------------------------------------------------------
# Extract raw reference strings from GROBID refBibs
# ---------------------------------------------------------------------------

def _extract_raw_strings_from_grobid(ref_bibs: List[Dict]) -> List[str]:
    """
    Try to get the raw text of each reference from GROBID's refBibs.
    GROBID standard returns refBibs[].rawForm; some HF-space deployments
    only return {id, pos}. Falls back to TEI XML text stripping, then 'note'.
    """
    raw_strings = []
    for rb in ref_bibs:
        if not isinstance(rb, dict):
            continue

        # Priority 1: rawForm (standard GROBID)
        raw = (rb.get("rawForm") or "").strip()
        if raw:
            raw_strings.append(raw)
            continue

        # Priority 2: strip TEI XML tags
        tei = (rb.get("tei") or "").strip()
        if tei:
            text = re.sub(r'<[^>]+>', ' ', tei)
            text = re.sub(r'\s+', ' ', text).strip()
            if len(text) > 20:
                raw_strings.append(text)
                continue

        # Priority 3: note field
        note = (rb.get("note") or "").strip()
        if note and len(note) > 20:
            raw_strings.append(note)

    return raw_strings


# ---------------------------------------------------------------------------
# Reconstruct raw strings from BibTeX (last resort)
# ---------------------------------------------------------------------------

def _reconstruct_raw_from_bibtex(entries: List[Dict[str, Any]]) -> List[str]:
    """
    Build IEEE-style reference strings from BibTeX fields.
    Used when GROBID rawForm is unavailable and PDF text extraction fails.
    Ordering and completeness checks are skipped for reconstructed strings
    since they are always sequential and fully populated.
    """
    def sort_key(e):
        m = re.search(r'(\d+)$', e.get("ID", ""))
        return int(m.group(1)) if m else 0

    raw_strings = []
    for i, entry in enumerate(sorted(entries, key=sort_key)):
        authors = entry.get("author", "Unknown")
        title   = entry.get("title", "")
        year    = entry.get("year", "")
        journal = entry.get("journal") or entry.get("booktitle") or ""
        volume  = entry.get("volume", "")
        pages   = entry.get("pages", "")
        doi     = entry.get("doi", "")

        parts = [f"[{i+1}]", f"{authors}."]
        if title:
            parts.append(f'"{title}."')
        if journal:
            parts.append(journal)
        if volume:
            parts.append(f"vol. {volume}")
        if year:
            parts.append(f"({year})")
        if pages:
            parts.append(f"pp. {pages}")
        if doi:
            parts.append(f"doi:{doi}")

        raw_strings.append(" ".join(p for p in parts if p))

    return raw_strings


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def referenceErrorParser(
    bibtex_string:   str,
    coordinate_str:  str,
    raw_ref_strings: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Full reference analysis pipeline.

    Returns list of BibTeX entry dicts enriched with:
      - asterikError / consistencyError  (BibTeX field checks)
      - quality_issues                   (ordering, doi, journal_casing, etc.)
      - page, coordinates                (GROBID pos → fitz coords)
    """
    MAX_QUALITY_ISSUES = 50

    # Parse inputs
    try:
        coord_data = json.loads(coordinate_str) if coordinate_str else {}
    except Exception:
        coord_data = {}

    ref_bibs        = coord_data.get("refBibs", [])
    page_dimensions = coord_data.get("pages",   [])

    bibtex_entries = bibtex_to_dict_list(bibtex_string) if bibtex_string.strip() else []

    # ── Select raw reference strings source ────────────────────────────
    raw_strings_source = "none"
    grobid_raw = _extract_raw_strings_from_grobid(ref_bibs)

    if grobid_raw:
        raw_strings        = grobid_raw
        raw_strings_source = "grobid"
        print(f"[analyser] Source=GROBID rawForm ({len(raw_strings)})")
    elif raw_ref_strings and len(raw_ref_strings) >= 3:
        raw_strings        = raw_ref_strings
        raw_strings_source = "pdf_text"
        print(f"[analyser] Source=PDF text ({len(raw_strings)})")
    elif bibtex_entries:
        raw_strings        = _reconstruct_raw_from_bibtex(bibtex_entries)
        raw_strings_source = "bibtex_recon"
        print(f"[analyser] Source=BibTeX reconstruction ({len(raw_strings)}) — ordering/completeness skipped")
    else:
        raw_strings        = []
        raw_strings_source = "none"
        print("[analyser] No raw strings — quality checks skipped")

    # ── BibTeX consistency checks ────────────────────────────────────
    _run_consistency_checks(bibtex_entries)

    # ── Build enriched list ──────────────────────────────────────────
    enriched = build_enriched_refs(bibtex_entries, raw_strings, ref_bibs, page_dimensions)

    # ── Style detection ──────────────────────────────────────────────
    # Run the full classifier on all available raw strings.
    # For bibtex_recon we still try — if the reconstructed strings carry
    # enough structural signal (bracket labels, author format, year parens)
    # the classifier can still detect the style. Fall back to IEEE only when
    # truly ambiguous (UNKNOWN result).
    style = detect_citation_style(raw_strings) if raw_strings else "UNKNOWN"
    if style == "UNKNOWN":
        style = "IEEE"   # safe fallback — most CS/Engineering papers use IEEE

    print(f"[analyser] Style={style} source={raw_strings_source}")

    # ── Quality checks ───────────────────────────────────────────────
    quality_issues: List[Dict] = []

    if raw_strings and style != "UNKNOWN":
        from .check_ordering         import check_ordering
        from .check_doi              import check_doi
        from .check_journal_casing   import check_journal_casing
        from .check_completeness     import check_completeness

        def _by_id(ref_id: str) -> dict:
            return next((r for r in enriched if r.get("id") == ref_id), {})

        def _issue(er: dict, msg: str, ctx: str, sug: list, chk: str) -> dict:
            bib = er.get("_bibtex") or {}
            return {
                "ENTRYTYPE":   bib.get("ENTRYTYPE", "misc"),
                "ID":          er.get("id", ""),
                "page":        er.get("page", 0),
                "coordinates": er.get("coordinates", []),
                "category":    "ARTICLE",
                "message":     msg,
                "context":     ctx,
                "suggestions": sug,
                "check":       chk,
            }

        # Ordering — GROBID rawForm only (PDF text extraction gives unreliable raw_text)
        # Reconstructed BibTeX strings are always sequential so also excluded.
        if raw_strings_source == "grobid":
            try:
                for iss in check_ordering(enriched, style).issues:
                    if len(quality_issues) >= MAX_QUALITY_ISSUES:
                        break
                    er = _by_id(iss.ref_id)
                    sug = getattr(iss, "suggestion", None) or f"Reorder ref at position {iss.position}"
                    quality_issues.append(_issue(er,
                        f"[Ordering] {iss.issue}",
                        f"Expected: {iss.expected} | Found: {iss.found}",
                        [sug], "ordering"))
            except Exception as e:
                print(f"[analyser] ordering error: {e}")


        # DOI — everywhere, skip pure suggestions
        try:
            for iss in check_doi(enriched, deep_check=False).issues:
                if len(quality_issues) >= MAX_QUALITY_ISSUES:
                    break
                if getattr(iss, "issue_type", "") == "suggestion":
                    continue
                er = _by_id(iss.ref_id)
                quality_issues.append(_issue(er,
                    f"[DOI] {iss.detail}",
                    getattr(iss, "suggestion", "") or "",
                    [iss.suggestion] if getattr(iss, "suggestion", None) else [],
                    "doi"))
        except Exception as e:
            print(f"[analyser] doi error: {e}")

        # Journal casing — everywhere
        try:
            for iss in check_journal_casing(enriched, style).issues:
                if len(quality_issues) >= MAX_QUALITY_ISSUES:
                    break
                er = _by_id(iss.ref_id)
                quality_issues.append(_issue(er,
                    f"[Journal Casing] {iss.detail}",
                    f"Journal: {getattr(iss,'journal','')}",
                    [iss.suggestion] if getattr(iss, "suggestion", None) else [],
                    "journal_casing"))
        except Exception as e:
            print(f"[analyser] journal_casing error: {e}")

        # Completeness — GROBID rawForm only (reconstructed strings would not
        # reveal true missing fields since we build them from the BibTeX)
        if raw_strings_source == "grobid":
            try:
                for iss in check_completeness(enriched, style).issues:
                    if len(quality_issues) >= MAX_QUALITY_ISSUES:
                        break
                    if getattr(iss, "issue_type", "") != "missing":
                        continue
                    er = _by_id(iss.ref_id)
                    quality_issues.append(_issue(er,
                        f"[Completeness] {iss.detail}",
                        f"Missing: {getattr(iss,'field_name','')}",
                        [iss.suggestion] if getattr(iss, "suggestion", None) else [],
                        "completeness"))
            except Exception as e:
                print(f"[analyser] completeness error: {e}")


        print(f"[analyser] Quality issues: {len(quality_issues)}/{MAX_QUALITY_ISSUES}")

    # ── Merge into per-entry output ──────────────────────────────────
    result = []
    for i, entry in enumerate(bibtex_entries):
        e_copy = dict(entry)
        if i < len(enriched):
            e_copy["page"]        = enriched[i]["page"]
            e_copy["coordinates"] = enriched[i]["coordinates"]
        else:
            e_copy["page"]        = 0
            e_copy["coordinates"] = []

        ref_id = e_copy.get("ID", f"ref_{i+1:03d}")
        e_copy["quality_issues"] = [
            qi for qi in quality_issues if qi.get("ID") == ref_id
        ]
        result.append(e_copy)

    seen_ids = {e.get("ID") for e in bibtex_entries}
    for qi in quality_issues:
        if qi.get("ID") not in seen_ids:
            result.append(qi)

    return result
