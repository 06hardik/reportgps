"""
check_completeness.py
=====================
Check 4 — Verifies that each reference contains all required fields for
its detected citation style, and flags field-level formatting errors.

Two-layer check:
  Layer A — Completeness: required fields must be non-empty.
  Layer B — Formatting:   field values must match style-specific patterns
                          (e.g. year in parentheses for APA, pages with
                          "pp." for MLA, etc.)

Required fields per style:
──────────────────────────────────────────────────────────────────────
Field           IEEE  APA   MLA   Harvard Vancouver
──────────────────────────────────────────────────────────────────────
authors          R     R     R     R       R       R
title            R     R     R     R       R       R
container_title  R*    R*    R*    R*      R*      R*   (* for articles)
pub_date         R     R     R     R       R       R
volume           O     O     O     O       O       R
pages            O     O     R     O       O       O
doi/url          O     O     O     O       O       O
publisher        R*    R*    R*    R*      R*      R*   (* for books)
──────────────────────────────────────────────────────────────────────
R = required, O = optional, R* = required for certain reference types

Reference types inferred from parsed fields:
  article  — has container_title (journal) but no publisher
  book     — has publisher, no container_title
  chapter  — has both container_title and publisher
  web/other — has url but minimal other fields
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FieldIssue:
    ref_id:     str
    position:   int
    field_name: str          # e.g. "pub_date", "pages"
    issue_type: str          # "missing" | "formatting" | "suspicious"
    detail:     str          # human-readable description of the problem
    found:      Optional[str] = None     # the value that was found (if any)
    suggestion: Optional[str] = None     # how to fix it


@dataclass
class CompletenessResult:
    style:    str
    issues:   List[FieldIssue] = field(default_factory=list)
    checked:  int = 0

    @property
    def passed(self) -> bool:
        return len(self.issues) == 0


# ---------------------------------------------------------------------------
# Reference type inference
# ---------------------------------------------------------------------------

def _infer_ref_type(parsed: Dict[str, Any]) -> str:
    """
    Infer whether a parsed reference is an article, book, chapter, or web/other.
    This determines which fields are 'required'.
    """
    has_container = bool((parsed.get("container_title") or "").strip())
    has_publisher = bool((parsed.get("publisher") or "").strip())
    has_url_only  = bool((parsed.get("url") or "").strip()) and not has_container

    if has_container and has_publisher:
        return "chapter"      # book chapter: journal=book title, publisher present
    if has_container:
        return "article"      # journal article
    if has_publisher:
        return "book"
    if has_url_only:
        return "web"
    return "other"


# ---------------------------------------------------------------------------
# Per-style schemas
#
# Each schema is:
#   {
#     "<ref_type>": {
#       "required": [list of field names],
#       "recommended": [list of field names],  (warn, don't hard-fail)
#     }
#   }
# ---------------------------------------------------------------------------

_SCHEMAS: Dict[str, Dict[str, Dict[str, List[str]]]] = {

    "IEEE": {
        "article": {
            "required":    ["authors", "title", "container_title", "pub_date", "volume", "pages"],
            "recommended": ["issue", "doi"],
        },
        "book": {
            "required":    ["authors", "title", "publisher", "pub_date"],
            "recommended": ["doi"],
        },
        "chapter": {
            "required":    ["authors", "title", "container_title", "publisher", "pub_date", "pages"],
            "recommended": [],
        },
        "web": {
            "required":    ["authors", "title", "pub_date"],
            "recommended": ["url"],
        },
        "other": {
            "required":    ["authors", "title", "pub_date"],
            "recommended": [],
        },
    },

    "APA": {
        "article": {
            "required":    ["authors", "title", "container_title", "pub_date", "volume"],
            "recommended": ["issue", "pages", "doi"],
        },
        "book": {
            "required":    ["authors", "title", "publisher", "pub_date"],
            "recommended": ["doi"],
        },
        "chapter": {
            "required":    ["authors", "title", "container_title", "pub_date", "pages"],
            "recommended": ["publisher"],
        },
        "web": {
            "required":    ["authors", "title", "pub_date"],
            "recommended": ["url"],
        },
        "other": {
            "required":    ["authors", "title", "pub_date"],
            "recommended": [],
        },
    },

    "MLA": {
        "article": {
            "required":    ["authors", "title", "container_title", "pub_date", "volume", "pages"],
            "recommended": ["issue", "doi"],
        },
        "book": {
            "required":    ["authors", "title", "publisher", "pub_date"],
            "recommended": [],
        },
        "chapter": {
            "required":    ["authors", "title", "container_title", "publisher", "pub_date", "pages"],
            "recommended": [],
        },
        "web": {
            "required":    ["authors", "title", "pub_date"],
            "recommended": ["url"],
        },
        "other": {
            "required":    ["authors", "title", "pub_date"],
            "recommended": [],
        },
    },

    "HARVARD": {
        "article": {
            "required":    ["authors", "title", "container_title", "pub_date", "volume"],
            "recommended": ["issue", "pages"],
        },
        "book": {
            "required":    ["authors", "title", "publisher", "pub_date"],
            "recommended": [],
        },
        "chapter": {
            "required":    ["authors", "title", "container_title", "pub_date", "pages"],
            "recommended": ["publisher"],
        },
        "web": {
            "required":    ["authors", "title", "pub_date"],
            "recommended": ["url"],
        },
        "other": {
            "required":    ["authors", "title", "pub_date"],
            "recommended": [],
        },
    },

    "VANCOUVER": {
        "article": {
            "required":    ["authors", "title", "container_title", "pub_date", "volume", "pages"],
            "recommended": ["issue", "doi"],
        },
        "book": {
            "required":    ["authors", "title", "publisher", "pub_date"],
            "recommended": [],
        },
        "chapter": {
            "required":    ["authors", "title", "container_title", "publisher", "pub_date", "pages"],
            "recommended": [],
        },
        "web": {
            "required":    ["authors", "title"],
            "recommended": ["pub_date", "url"],
        },
        "other": {
            "required":    ["authors", "title"],
            "recommended": ["pub_date"],
        },
    },
}


def _get_field_value(parsed: Dict[str, Any], field_name: str) -> Optional[str]:
    """
    Retrieve a field from parsed dict.
    'authors' field is a list — returns None if empty, joined string if non-empty.
    'doi_or_url' is a virtual field that checks doi OR url.
    """
    if field_name == "doi_or_url":
        doi = (parsed.get("doi") or "").strip()
        url = (parsed.get("url") or "").strip()
        return doi or url or None

    if field_name == "authors":
        authors = parsed.get("authors") or []
        return ", ".join(authors) if authors else None

    val = parsed.get(field_name)
    if val is None:
        return None
    val = str(val).strip()
    return val if val else None


# ---------------------------------------------------------------------------
# Formatting checks — per-style, per-field
# ---------------------------------------------------------------------------

# Year patterns
_YEAR_PARENS_RE     = re.compile(r'\(\d{4}\)')           # (2020)
_BARE_YEAR_RE       = re.compile(r'\b(19|20)\d{2}\b')   # 2020
_PAGES_PP_RE        = re.compile(r'\bpp?\.\s*\d+')       # pp. 45 or p. 45
_PAGES_RANGE_RE     = re.compile(r'\d+\s*[-\u2013]\s*\d+')   # 45-67 or 45-67
_VOLUME_NUM_RE      = re.compile(r'^\d+$')               # pure number


def _check_formatting(
    ref_id:      str,
    position:    int,
    parsed:      Dict[str, Any],
    raw_text:    str,
    style_upper: str,
    issues:      List[FieldIssue],
) -> None:
    """
    Apply style-specific formatting checks. Appends FieldIssue items to `issues`.
    Does not check presence (that's done in check_completeness).
    """
    pub_date = (parsed.get("pub_date") or "").strip()
    pages    = (parsed.get("pages")    or "").strip()
    volume   = (parsed.get("volume")   or "").strip()
    authors_list = parsed.get("authors") or []

    # ── APA ──────────────────────────────────────────────────────────
    if style_upper == "APA":

        # Year must appear in parentheses in raw text
        if pub_date and not re.search(r'\(' + re.escape(pub_date) + r'\)', raw_text):
            if not _YEAR_PARENS_RE.search(raw_text):
                issues.append(FieldIssue(
                    ref_id     = ref_id,
                    position   = position,
                    field_name = "pub_date",
                    issue_type = "formatting",
                    detail     = f"APA requires the year in parentheses: ({pub_date})",
                    found      = pub_date,
                    suggestion = f"({pub_date})",
                ))

        # APA authors must use '&' before last author (not 'and')
        if re.search(r'\band\b', raw_text) and len(authors_list) > 1:
            # Heuristic: 'and' near the start of the entry (first 40% of chars)
            pre_title = raw_text[:max(1, int(len(raw_text) * 0.4))]
            if re.search(r'\band\b', pre_title, re.IGNORECASE):
                issues.append(FieldIssue(
                    ref_id     = ref_id,
                    position   = position,
                    field_name = "authors",
                    issue_type = "formatting",
                    detail     = "APA uses '&' to join the last two authors, not 'and'",
                    found      = "and",
                    suggestion = "Replace 'and' with '&' between last two authors",
                ))

    # ── MLA ──────────────────────────────────────────────────────────
    elif style_upper == "MLA":

        # MLA page ranges must use 'pp.' prefix in the raw text
        if pages and not re.search(r'\bpp?\.\s', raw_text):
            # Only flag for article/chapter (not books)
            if _infer_ref_type(parsed) in ("article", "chapter"):
                issues.append(FieldIssue(
                    ref_id     = ref_id,
                    position   = position,
                    field_name = "pages",
                    issue_type = "formatting",
                    detail     = f"MLA requires 'pp.' before page ranges (found: '{pages}')",
                    found      = pages,
                    suggestion = f"pp. {pages}",
                ))

        # MLA volume must be written as "vol. N"
        if volume and re.match(r'^\d+$', volume):
            if not re.search(r'\bvol\.\s*\d', raw_text, re.IGNORECASE):
                issues.append(FieldIssue(
                    ref_id     = ref_id,
                    position   = position,
                    field_name = "volume",
                    issue_type = "formatting",
                    detail     = f"MLA writes volume as 'vol. {volume}' not a bare number",
                    found      = volume,
                    suggestion = f"vol. {volume}",
                ))

        # MLA year must appear at the END (after publisher/container), not directly after author
        if pub_date and _BARE_YEAR_RE.search(raw_text):
            year_pos = raw_text.rfind(pub_date)
            if year_pos != -1 and year_pos < len(raw_text) * 0.4:
                issues.append(FieldIssue(
                    ref_id     = ref_id,
                    position   = position,
                    field_name = "pub_date",
                    issue_type = "formatting",
                    detail     = (
                        f"MLA places the year at the end of the entry, "
                        f"not directly after the author name (year '{pub_date}' found early in entry)"
                    ),
                    found      = pub_date,
                    suggestion = "Move publication year to the end of the citation",
                ))

    # ── Harvard ───────────────────────────────────────────────────────
    elif style_upper == "HARVARD":

        if pub_date and not _YEAR_PARENS_RE.search(raw_text):
            issues.append(FieldIssue(
                ref_id     = ref_id,
                position   = position,
                field_name = "pub_date",
                issue_type = "formatting",
                detail     = f"Harvard requires the year in parentheses: ({pub_date})",
                found      = pub_date,
                suggestion = f"({pub_date})",
            ))

    # ── Vancouver ─────────────────────────────────────────────────────
    elif style_upper == "VANCOUVER":

        # Vancouver authors use initials without periods: "Smith AB" not "Smith, A.B."
        for author in authors_list[:3]:   # check first few authors
            if re.search(r'[A-Z]\.[A-Z]\.', author):
                issues.append(FieldIssue(
                    ref_id     = ref_id,
                    position   = position,
                    field_name = "authors",
                    issue_type = "formatting",
                    detail     = (
                        f"Vancouver authors use initials without periods "
                        f"('Smith AB' not 'Smith, A.B.'): found '{author}'"
                    ),
                    found      = author,
                    suggestion = re.sub(r'\.', '', author),
                ))
                break   # one warning per entry is enough

        # Vancouver date format: Year;Volume(Issue):Pages — check semicolon format
        if pub_date and volume and pages:
            if not re.search(r'\d{4};\d+', raw_text):
                issues.append(FieldIssue(
                    ref_id     = ref_id,
                    position   = position,
                    field_name = "pub_date",
                    issue_type = "formatting",
                    detail     = (
                        f"Vancouver uses the format 'Year;Volume(Issue):Pages' "
                        f"(e.g. '{pub_date};{volume}:{pages}')"
                    ),
                    found      = raw_text[max(0, raw_text.rfind(pub_date)):raw_text.rfind(pub_date)+30],
                    suggestion = f"{pub_date};{volume}:{pages}",
                ))

    # ── Cross-style: suspicious/malformed fields ──────────────────────

    # Flag pages that look like they might be a year (e.g. "2020" as pages)
    if pages and re.match(r'^(19|20)\d{2}$', pages):
        issues.append(FieldIssue(
            ref_id     = ref_id,
            position   = position,
            field_name = "pages",
            issue_type = "suspicious",
            detail     = (
                f"Pages field contains what looks like a year ('{pages}') — "
                f"possible GROBID parsing error"
            ),
            found      = pages,
            suggestion = "Verify this is a page number and not an access year",
        ))

    # Flag volume that looks like a day number (1-31 only) when there's an access-date keyword
    if volume and re.match(r'^([1-9]|[12]\d|3[01])$', volume):
        if re.search(r'\b(accessed|retrieved|cited)\b', raw_text, re.IGNORECASE):
            issues.append(FieldIssue(
                ref_id     = ref_id,
                position   = position,
                field_name = "volume",
                issue_type = "suspicious",
                detail     = (
                    f"Volume field contains '{volume}' which looks like a day number — "
                    f"possible GROBID parsing error in an access-date pattern"
                ),
                found      = volume,
                suggestion = "Verify this is a volume number and not an access day",
            ))

    # Flag pub_date that doesn't look like a year
    if pub_date:
        clean_date = re.sub(r'[()]', '', pub_date).strip()
        if not re.match(r'^(19|20)\d{2}$', clean_date) and \
           clean_date.lower() not in ("n.d.", "nd", "no date", "forthcoming"):
            issues.append(FieldIssue(
                ref_id     = ref_id,
                position   = position,
                field_name = "pub_date",
                issue_type = "suspicious",
                detail     = f"Publication date '{pub_date}' does not look like a valid year",
                found      = pub_date,
                suggestion = "Verify publication year is a 4-digit year (YYYY)",
            ))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_completeness(refs: List[dict], style: str) -> CompletenessResult:
    """
    Parameters
    ----------
    refs  : enriched reference dicts. Each must have:
              "id"       — reference ID
              "raw_text" — original citation text
              "parsed"   — dict from the field extraction model with fields: title, authors,
                           container_title, pub_date, volume, issue, pages,
                           doi, url, publisher, parser_status
    style : detected citation style string

    Returns
    -------
    CompletenessResult with all FieldIssue items found.
    """
    result      = CompletenessResult(style=style)
    style_upper = style.upper()
    schema_key  = style_upper if style_upper in _SCHEMAS else "APA"   # APA as fallback

    for pos, ref in enumerate(refs, start=1):
        ref_id   = ref.get("id", f"ref_{pos:03d}")
        parsed   = ref.get("parsed") or {}
        raw_text = (ref.get("raw_text") or "").strip()

        # Skip entries that completely failed Grobid parsing
        parser_status = (parsed.get("parser_status") or "").lower()
        if parser_status in ("failed", "no_text"):
            continue

        result.checked += 1
        ref_type = _infer_ref_type(parsed)
        schema   = _SCHEMAS.get(schema_key, {}).get(ref_type, {})

        required    = schema.get("required", [])
        recommended = schema.get("recommended", [])

        # ── Layer A: Completeness ────────────────────────────────────
        for fname in required:
            val = _get_field_value(parsed, fname)
            if val is None:
                result.issues.append(FieldIssue(
                    ref_id     = ref_id,
                    position   = pos,
                    field_name = fname,
                    issue_type = "missing",
                    detail     = (
                        f"Required field '{fname}' is missing for a {ref_type} "
                        f"citation in {style_upper} style"
                    ),
                ))

        for fname in recommended:
            val = _get_field_value(parsed, fname)
            if val is None:
                result.issues.append(FieldIssue(
                    ref_id     = ref_id,
                    position   = pos,
                    field_name = fname,
                    issue_type = "suspicious",    # lower severity for optional fields
                    detail     = (
                        f"Recommended field '{fname}' is absent — consider adding "
                        f"it for a complete {style_upper} {ref_type} citation"
                    ),
                ))

        # ── Layer B: Formatting ──────────────────────────────────────
        _check_formatting(
            ref_id      = ref_id,
            position    = pos,
            parsed      = parsed,
            raw_text    = raw_text,
            style_upper = style_upper,
            issues      = result.issues,
        )

    return result
