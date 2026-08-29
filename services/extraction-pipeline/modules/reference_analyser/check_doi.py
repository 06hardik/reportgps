"""
check_doi.py
============
Check 2 — DOI presence.

Two strategies are provided:

Strategy B — Fast offline pattern detection (default, always runs):
  Scans each entry's raw text and the Grobid-parsed `doi` field for a
  DOI in any recognised format.  If a DOI is found → satisfied.
  If absent → advisory flag: "No DOI found — consider adding one if
  available."  Only article and chapter references are checked by
  default (books, theses, and web pages are not expected to always
  carry DOIs).

  DOI patterns recognised:
    doi:10.<reg>/suffix               (bare prefix, case-insensitive)
    https://doi.org/10.<reg>/suffix
    http://doi.org/10.<reg>/suffix
    http://dx.doi.org/10.<reg>/suffix
    DOI: 10.<reg>/suffix              (IEEE style, space optional)
    plain 10.<reg>/suffix             (fallback bare pattern)

Strategy A — CrossRef API lookup (optional, requires network):
  Triggered when deep_check=True is passed to check_doi().
  Queries api.crossref.org using the parsed title + first-author surname.
  If CrossRef returns a DOI that is NOT already in the entry → the
  advisory is upgraded to an ERROR with the missing DOI shown.
  If CrossRef finds no record → the advisory note is updated to reflect
  that no DOI could be confirmed.

  Rate limiting: uses the CrossRef "polite pool" by including a
  mailto: email address in the User-Agent header.  A configurable
  delay (default 1 s) is inserted between requests.
  Requires: pip install requests
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set

# ---------------------------------------------------------------------------
# DOI regex patterns
# ---------------------------------------------------------------------------

# Prefixed form:  doi:10.xxx/...  or  https?://[dx.]doi.org/10.xxx/...
_DOI_PREFIXED_RE = re.compile(
    r'(?:'
    r'doi\s*:\s*'
    r'|https?://(?:dx\.)?doi\.org/'
    r')'
    r'(10\.\d{4,9}/[^\s,\]>"\'\)]+)',
    re.IGNORECASE,
)

# Bare form:  10.xxxx/suffix  (catch-all fallback)
_DOI_BARE_RE = re.compile(
    r'\b(10\.\d{4,9}/[^\s,\]>"\'\)]+)',
    re.IGNORECASE,
)


def _extract_doi(text: str) -> Optional[str]:
    """
    Return the first DOI found in `text`, or None.
    Strips trailing punctuation that is part of the surrounding sentence.
    """
    m = _DOI_PREFIXED_RE.search(text)
    if m:
        return m.group(1).rstrip(".,;)")
    m = _DOI_BARE_RE.search(text)
    if m:
        return m.group(1).rstrip(".,;)")
    return None


# ---------------------------------------------------------------------------
# Reference-type helper (local copy to avoid circular imports)
# ---------------------------------------------------------------------------

def _ref_type(parsed: Dict[str, Any]) -> str:
    has_container = bool((parsed.get("container_title") or "").strip())
    has_publisher = bool((parsed.get("publisher")       or "").strip())
    has_url_only  = bool((parsed.get("url")             or "").strip()) and not has_container
    if has_container and has_publisher:
        return "chapter"
    if has_container:
        return "article"
    if has_publisher:
        return "book"
    if has_url_only:
        return "web"
    return "other"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DOIIssue:
    ref_id:     str
    position:   int
    issue_type: str             # "missing" | "crossref_found" | "crossref_no_match"
    detail:     str
    doi_found:  Optional[str] = None   # CrossRef-discovered DOI (Strategy A only)
    suggestion: Optional[str] = None


@dataclass
class DOICheckResult:
    issues:  List[DOIIssue] = field(default_factory=list)
    checked: int = 0

    @property
    def passed(self) -> bool:
        """
        Pass = no ERROR-grade issues.
        Strategy-B "missing" issues are advisory; only Strategy-A
        "crossref_found" issues (confirmed missing DOI) are errors.
        """
        return not any(i.issue_type == "crossref_found" for i in self.issues)


# ---------------------------------------------------------------------------
# Strategy B — offline, fast
# ---------------------------------------------------------------------------

def _strategy_b(
    entries:    List[Dict[str, Any]],
    result:     DOICheckResult,
    check_types: Set[str],
) -> None:
    """
    Scans every entry for an existing DOI and emits an advisory for
    any article/chapter that lacks one.
    """
    for pos, entry in enumerate(entries, start=1):
        ref_id   = entry.get("id", f"ref_{pos:03d}")
        parsed   = entry.get("parsed") or {}
        raw_text = (entry.get("raw_text") or "").strip()

        parser_status = (parsed.get("parser_status") or "").lower()
        if parser_status in ("failed", "no_text", "dry_run"):
            continue

        rtype = _ref_type(parsed)
        if rtype not in check_types:
            continue

        result.checked += 1

        doi = (parsed.get("doi") or "").strip() or _extract_doi(raw_text)

        if not doi:
            result.issues.append(DOIIssue(
                ref_id     = ref_id,
                position   = pos,
                issue_type = "missing",
                detail     = (
                    f"No DOI found in this {rtype} entry. "
                    f"Consider adding one if the work has been registered with a DOI."
                ),
                suggestion = "Add: doi:10.xxxx/suffix  or  https://doi.org/10.xxxx/suffix",
            ))


# ---------------------------------------------------------------------------
# Strategy A — CrossRef API (optional deep check)
# ---------------------------------------------------------------------------

_CROSSREF_URL             = "https://api.crossref.org/works"
_CROSSREF_ROWS            = 3
_CROSSREF_SCORE_THRESHOLD = 50.0   # CrossRef relevance score minimum


def _query_crossref(
    title:   str,
    author:  str,
    email:   Optional[str],
    timeout: int,
) -> Optional[Dict[str, Any]]:
    """
    Query CrossRef and return the top result if its relevance score is
    above _CROSSREF_SCORE_THRESHOLD.  Returns None on any failure.
    """
    try:
        import requests
    except ImportError:
        return None

    params: Dict[str, Any] = {
        "query.title": title,
        "rows":        _CROSSREF_ROWS,
        "select":      "DOI,title,score,published-print,author",
    }
    if author:
        params["query.author"] = author

    agent = "ReferenceQualityPipeline/1.0"
    if email:
        agent += f" (mailto:{email})"
    headers = {"User-Agent": agent}

    try:
        resp = requests.get(_CROSSREF_URL, params=params,
                            headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return None
        data  = resp.json()
        items = (data.get("message") or {}).get("items") or []
        if not items:
            return None
        top = items[0]
        if top.get("score", 0) < _CROSSREF_SCORE_THRESHOLD:
            return None
        return top
    except Exception:
        return None


def _strategy_a(
    entries:    List[Dict[str, Any]],
    result:     DOICheckResult,
    email:      Optional[str],
    delay:      float,
    timeout:    int,
) -> None:
    """
    Run CrossRef lookups only for entries already flagged by Strategy B
    as having no DOI.  Upgrades or annotates those issues in-place.
    """
    missing_ids = {iss.ref_id for iss in result.issues if iss.issue_type == "missing"}
    if not missing_ids:
        return

    entry_map = {e.get("id", ""): e for e in entries}

    for ref_id in missing_ids:
        entry  = entry_map.get(ref_id)
        if not entry:
            continue
        parsed = entry.get("parsed") or {}
        title  = (parsed.get("title") or "").strip()
        author = ""
        authors = parsed.get("authors") or []
        if authors:
            # Use surname of first author for better CrossRef matching
            author = authors[0].split()[-1]

        if not title:
            continue

        work = _query_crossref(title, author, email, timeout)
        time.sleep(delay)   # polite rate-limiting

        for iss in result.issues:
            if iss.ref_id != ref_id or iss.issue_type != "missing":
                continue

            if work:
                doi_found = (work.get("DOI") or "").strip()
                iss.issue_type = "crossref_found"
                iss.doi_found  = doi_found
                iss.detail     = (
                    f"CrossRef found a DOI for this work that is not "
                    f"present in the entry: {doi_found}"
                )
                iss.suggestion = f"Add: https://doi.org/{doi_found}"
            else:
                # CrossRef has no record — keep as advisory, add note
                iss.detail += (
                    " (CrossRef query returned no confident match — "
                    "the work may not have a registered DOI.)"
                )
                iss.issue_type = "crossref_no_match"
            break


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_DEFAULT_CHECK_TYPES: FrozenSet[str] = frozenset({"article", "chapter"})


def check_doi(
    entries:          List[Dict[str, Any]],
    check_types:      FrozenSet[str] = _DEFAULT_CHECK_TYPES,
    deep_check:       bool           = False,
    crossref_email:   Optional[str]  = None,
    crossref_delay:   float          = 1.0,
    crossref_timeout: int            = 10,
) -> DOICheckResult:
    """
    Parameters
    ----------
    entries          : enriched reference dicts (post-Grobid).
    check_types      : reference types to check for DOI presence.
                       Default: {"article", "chapter"}.
    deep_check       : if True, run Strategy A (CrossRef API) after
                       Strategy B.  Requires network.
    crossref_email   : mailto address for CrossRef polite-pool header.
                       Strongly recommended when deep_check=True.
    crossref_delay   : seconds to wait between CrossRef requests (default 1s).
    crossref_timeout : per-request timeout in seconds.

    Returns
    -------
    DOICheckResult with DOIIssue items.
    """
    result = DOICheckResult()

    # Strategy B — always run (fast, offline)
    _strategy_b(entries, result, set(check_types))

    # Strategy A — optional online deep check
    if deep_check:
        _strategy_a(
            entries  = entries,
            result   = result,
            email    = crossref_email,
            delay    = crossref_delay,
            timeout  = crossref_timeout,
        )

    return result
