"""
check_ordering.py
=================
Check 1 — Verifies that reference list entries are in the correct order
for the detected citation style.

  IEEE / Vancouver  →  sequential numeric order (1, 2, 3 …)
  APA / MLA / Harvard  →  alphabetical by first-author surname

Returns a list of OrderIssue dataclasses, one per out-of-order entry.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class OrderIssue:
    ref_id:   str          # e.g. "ref_003"
    position: int          # 1-based index in the list
    issue:    str          # human-readable description
    expected: str          # what we expected at this position
    found:    str          # what we actually found


@dataclass
class OrderingResult:
    style:       str
    order_type:  str           # "numeric" | "alphabetical" | "unknown"
    issues:      List[OrderIssue] = field(default_factory=list)
    checked:     int = 0        # how many entries were evaluated

    @property
    def passed(self) -> bool:
        return len(self.issues) == 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Surname prefixes that are IGNORED when alphabetising (APA, MLA, Harvard)
_IGNORABLE_PREFIXES = {
    "de", "del", "della", "degli", "di", "du", "da",
    "van", "van de", "van den", "van der",
    "von", "von der",
    "le", "la", "les",
    "el", "al",
    "mac", "mc",           # treated as "mac" after normalisation
    "o'",
}

# Matches a leading [N] or bare N. at the start of a citation
_NUMERIC_LABEL_RE = re.compile(r"^\[?(\d+)\]?\.?\s")


def _normalise_str(s: str) -> str:
    """
    Lowercase, strip accents, collapse whitespace.
    Used for accent-insensitive alphabetic comparison.
    e.g. "García" → "garcia"
    """
    nfkd = unicodedata.normalize("NFKD", s)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    return ascii_str.lower().strip()


def _sort_key_from_surname(surname: str) -> str:
    """
    Produce a normalised sort key from a surname string.
    Strips ignorable prefixes so "van Gogh" sorts as "gogh".
    "Mc" / "Mac" are kept as-is (most style guides treat them literally).
    """
    norm = _normalise_str(surname)
    # Strip a single ignorable prefix if present
    for prefix in sorted(_IGNORABLE_PREFIXES, key=len, reverse=True):
        if norm.startswith(prefix + " "):
            norm = norm[len(prefix):].strip()
            break
    return norm


def _extract_sort_surname(ref: dict) -> Optional[str]:
    """
    Return the surname used for alphabetic ordering.

    Priority:
      1. parsed.authors[0] — Grobid gives "Forename Surname"; take last token.
      2. raw_text heuristic — try to extract first author surname from the
         raw citation text (handles "Surname, First …" patterns).

    Returns None if we cannot determine a surname.
    """
    parsed  = ref.get("parsed") or {}
    authors = parsed.get("authors") or []

    if authors:
        # Grobid normalises authors as "Forename Surname"
        first_author = authors[0].strip()
        # Last non-empty token is the surname
        tokens = first_author.split()
        if tokens:
            return tokens[-1]

    # Fallback: parse raw_text
    raw = (ref.get("raw_text") or "").strip()
    if not raw:
        return None

    # Pattern: "Surname, First …"  (APA / MLA / Harvard bibliography)
    m = re.match(r"^([A-Z][a-z\-\u00C0-\u024F]+),", raw)
    if m:
        return m.group(1)

    # Pattern: "Firstname Surname." at start (uninverted — MLA uninverted variant)
    m2 = re.match(r"^[A-Z][a-z\-\u00C0-\u024F]+\s+([A-Z][a-z\-\u00C0-\u024F]+)\.", raw)
    if m2:
        return m2.group(1)

    return None


def _extract_numeric_label(raw_text: str) -> Optional[int]:
    """
    Return the integer label from "[3]" or "3. " at the start.
    Returns None if no label found.
    """
    m = _NUMERIC_LABEL_RE.match(raw_text.strip())
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_ordering(refs: List[dict], style: str) -> OrderingResult:
    """
    Parameters
    ----------
    refs  : list of enriched reference dicts (after Grobid + classifier).
            Each dict must have at minimum:
              "id"       — reference ID string
              "raw_text" — original citation text
    style : detected style string, e.g. "IEEE", "APA", "MLA" …

    Returns
    -------
    OrderingResult with any OrderIssue items found.
    """
    style_upper = style.upper()

    # ── Numeric styles ─────────────────────────────────────────────────
    if style_upper in ("IEEE", "VANCOUVER"):
        return _check_numeric_order(refs, style_upper)

    # ── Alphabetic styles ──────────────────────────────────────────────
    if style_upper in ("APA", "MLA", "HARVARD"):
        return _check_alpha_order(refs, style_upper)

    # Unknown style — skip ordering check
    return OrderingResult(
        style      = style,
        order_type = "unknown",
        issues     = [],
        checked    = 0,
    )


# ---------------------------------------------------------------------------
# Numeric-order checker (IEEE / Vancouver)
# ---------------------------------------------------------------------------

def _check_numeric_order(refs: List[dict], style: str) -> OrderingResult:
    issues: List[OrderIssue] = []
    checked = 0
    expected_next = 1

    for pos, ref in enumerate(refs, start=1):
        raw    = (ref.get("raw_text") or "").strip()
        ref_id = ref.get("id", f"ref_{pos:03d}")
        label  = _extract_numeric_label(raw)

        if label is None:
            # No numeric label found — flag as missing label
            issues.append(OrderIssue(
                ref_id   = ref_id,
                position = pos,
                issue    = "Missing numeric label",
                expected = f"[{expected_next}]" if style == "IEEE" else f"{expected_next}.",
                found    = raw[:60],
            ))
            # Don't advance expected_next — we don't know what this entry's number is
            continue

        checked += 1

        if label != expected_next:
            # Label is wrong or out of sequence
            issues.append(OrderIssue(
                ref_id   = ref_id,
                position = pos,
                issue    = f"Numeric label out of sequence (gap or duplicate)",
                expected = str(expected_next),
                found    = str(label),
            ))

        # Advance expected regardless so we don't cascade errors
        expected_next = label + 1

    return OrderingResult(
        style      = style,
        order_type = "numeric",
        issues     = issues,
        checked    = checked,
    )


# ---------------------------------------------------------------------------
# Alphabetic-order checker (APA / MLA / Harvard)
# ---------------------------------------------------------------------------

def _check_alpha_order(refs: List[dict], style: str) -> OrderingResult:
    """
    Compare adjacent entries: each entry's sort-surname must be >= the
    previous one. Flag any entry that is alphabetically before its
    predecessor (i.e., list is not non-decreasing).

    When two entries share the same first-author surname the tie is broken
    by publication year (ascending), which is the convention for all four
    alphabetic styles.
    """
    issues: List[OrderIssue] = []
    checked = 0

    prev_key      = ""
    prev_display  = ""
    prev_id       = ""

    for pos, ref in enumerate(refs, start=1):
        ref_id  = ref.get("id", f"ref_{pos:03d}")
        surname = _extract_sort_surname(ref)

        if surname is None:
            # Can't determine surname — skip without flagging (may be org/anon)
            continue

        sort_key = _sort_key_from_surname(surname)

        # Tie-break: append year so "Smith (2019)" before "Smith (2021)"
        parsed = ref.get("parsed") or {}
        year   = (parsed.get("pub_date") or "9999")[:4]
        full_key = f"{sort_key}_{year}"

        checked += 1

        if full_key < prev_key:
            issues.append(OrderIssue(
                ref_id   = ref_id,
                position = pos,
                issue    = (
                    f"Out of alphabetical order: '{surname}' should come "
                    f"after '{prev_display}' but appears before it"
                ),
                expected = f"Entry by '{prev_display}' should precede this one",
                found    = f"'{surname}' at position {pos} precedes '{prev_display}' at position {pos-1}",
            ))

        prev_key     = full_key
        prev_display = surname
        prev_id      = ref_id

    return OrderingResult(
        style      = style,
        order_type = "alphabetical",
        issues     = issues,
        checked    = checked,
    )
