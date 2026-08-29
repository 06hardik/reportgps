"""
check_journal_casing.py
=======================
Check 3 — Verifies that journal/container titles use consistent casing
across the reference list, and that casing matches the detected style's
convention.

Two-layer check:
  Layer A — Cross-list consistency: same journal appearing in different
             entries must use identical casing.
  Layer B — Per-style correctness: each style mandates a specific casing
             convention which is validated entry by entry.

Casing conventions by style:
  APA       → Title Case   (all major words capitalised)
  MLA       → Title Case
  Harvard   → Title Case

  IEEE      → Title Case (often abbreviated — abbreviation check is advisory)
  Vancouver → Abbreviated, UPPERCASE initials  e.g. "N Engl J Med"
              Full words also acceptable in non-medical contexts.

Returns a list of CasingIssue dataclasses.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CasingIssue:
    ref_id:         str
    position:       int
    journal:        str           # journal title as found
    issue_type:     str           # "inconsistent" | "wrong_case" | "all_caps"
    detail:         str           # human-readable explanation
    suggestion:     Optional[str] = None


@dataclass
class CasingResult:
    style:       str
    issues:      List[CasingIssue] = field(default_factory=list)
    checked:     int = 0

    @property
    def passed(self) -> bool:
        return len(self.issues) == 0


# ---------------------------------------------------------------------------
# Small-word sets for title case validation
# ---------------------------------------------------------------------------

# Words that should remain lowercase in title case (unless first/last word)
_TITLE_CASE_EXCEPTIONS: Set[str] = {
    "a", "an", "the",
    "and", "but", "for", "nor", "or", "so", "yet",
    "at", "by", "in", "of", "off", "on", "out",
    "to", "up", "as", "if",
    "into", "onto", "upon", "with", "from", "over",
    "between", "through",
}

# Words that Vancouver/IEEE abbreviations typically keep
_COMMON_ABBREVIATION_WORDS: Set[str] = {
    "j", "n", "am", "int", "med", "sci", "res", "rev",
    "proc", "trans", "lett", "ann", "arch", "eur", "clin",
    "engl", "brit", "can", "aust",
}


# ---------------------------------------------------------------------------
# GROBID concatenation fix
# ---------------------------------------------------------------------------
# GROBID sometimes puts "Article subtitle. Journal Name" into container_title.
# e.g. "Fog computing and the Internet of Things: A review. Big Data and Cognitive Computing"
# We detect this by looking for a '. Capitalised segment' near the end of a long string
# and extract only the last segment as the real journal name.

_CONCAT_RE = re.compile(r'\.\s+([A-Z][^.]{4,})$')


def _extract_actual_journal(raw: str) -> str:
    """
    GROBID sometimes returns container_title as:
      "Article subtitle. Real Journal Name"
    If the raw title is short (<= 60 chars) or has no sentence structure, return as-is.
    Otherwise extract only the last capitalised segment after '. '.
    """
    raw = raw.strip()
    if len(raw) <= 60:
        return raw
    m = _CONCAT_RE.search(raw)
    if m:
        candidate = m.group(1).strip()
        words = candidate.split()
        # Must look like a real journal name (at least 2 words OR 1 long word)
        if len(words) >= 2 or (len(words) == 1 and len(candidate) > 5):
            return candidate
    return raw


# ---------------------------------------------------------------------------
# Casing detection helpers
# ---------------------------------------------------------------------------

def _normalise_for_grouping(title: str) -> str:
    """
    Create a normalised key for grouping the same journal across entries:
    lowercase, strip punctuation, collapse whitespace, strip accents.
    """
    nfkd = unicodedata.normalize("NFKD", title)
    ascii_s = "".join(c for c in nfkd if not unicodedata.combining(c))
    lowered = ascii_s.lower()
    no_punct = re.sub(r"[^a-z0-9\s]", "", lowered)
    return re.sub(r"\s+", " ", no_punct).strip()


def _is_title_case(title: str) -> bool:
    """
    Returns True if the title follows conventional title casing:
    - First word is capitalised
    - All major words (not in exception list) are capitalised
    - Minor words (in exception list) are lowercase unless first/last word
    Allows for italics markers (*) and quoted markers (") to be stripped.
    """
    clean = re.sub(r"[*_\"']", "", title).strip()
    words = clean.split()
    if not words:
        return True

    for i, word in enumerate(words):
        # Strip leading/trailing punctuation for the check
        core = word.strip(".,;:!?()[]")
        if not core:
            continue

        is_first_or_last = (i == 0 or i == len(words) - 1)
        core_lower = core.lower()

        if core_lower in _TITLE_CASE_EXCEPTIONS and not is_first_or_last:
            # Should be lowercase
            if core[0].isupper():
                return False
        else:
            # Should be capitalised (unless it's an abbreviation like "pH")
            if core[0].islower() and not (len(core) <= 2 and core_lower in _COMMON_ABBREVIATION_WORDS):
                return False

    return True


def _is_sentence_case(title: str) -> bool:
    """
    Returns True if only the first word (and proper nouns) are capitalised.
    We approximate this as: first word is capital, all other words are lowercase
    (allowing proper nouns which we can't detect without NLP).
    """
    clean = re.sub(r"[*_\"']", "", title).strip()
    words = clean.split()
    if len(words) <= 1:
        return True
    # Check that at least 50% of non-first words start lowercase
    non_first = [w.strip(".,;:!?()[]") for w in words[1:] if w.strip(".,;:!?()[]")]
    if not non_first:
        return True
    lowercase_count = sum(1 for w in non_first if w and w[0].islower())
    return (lowercase_count / len(non_first)) >= 0.5


def _is_all_caps(title: str) -> bool:
    """Returns True if the title is entirely uppercase (possible OCR artifact)."""
    letters = [c for c in title if c.isalpha()]
    if not letters:
        return False
    return all(c.isupper() for c in letters)


def _is_all_lowercase(title: str) -> bool:
    """Returns True if the title is entirely lowercase."""
    letters = [c for c in title if c.isalpha()]
    if not letters:
        return False
    return all(c.islower() for c in letters)


def _casing_label(title: str) -> str:
    """Return a human-readable casing label for a journal title."""
    if _is_all_caps(title):
        return "ALL_CAPS"
    if _is_all_lowercase(title):
        return "all_lowercase"
    if _is_title_case(title):
        return "Title Case"
    if _is_sentence_case(title):
        return "Sentence case"
    return "Mixed/inconsistent case"


def _to_title_case(s: str) -> str:
    """
    Convert a string to proper title case, respecting exception words.
    """
    words = s.split()
    result_words = []
    for i, word in enumerate(words):
        core = word.strip(".,;:!?()[]")
        core_lower = core.lower()

        is_first_or_last = (i == 0 or i == len(words) - 1)

        if core_lower in _TITLE_CASE_EXCEPTIONS and not is_first_or_last:
            # Preserve original punctuation wrapping, but lowercase core
            result_words.append(word.lower())
        else:
            # Capitalise first letter, keep rest as-is
            if core:
                capitalised = core[0].upper() + core[1:]
                result_words.append(word.replace(core, capitalised, 1))
            else:
                result_words.append(word)

    return " ".join(result_words)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_journal_casing(refs: List[dict], style: str) -> CasingResult:
    """
    Parameters
    ----------
    refs  : enriched reference dicts. Each must have:
              "id"       — reference ID
              "parsed"   — Grobid parsed fields (container_title is used)
              "raw_text" — original text (fallback)
    style : detected citation style

    Returns
    -------
    CasingResult with any CasingIssue items found.
    """
    result = CasingResult(style=style)
    style_upper = style.upper()

    # ── Collect (position, ref_id, journal_title) tuples ───────────────
    entries: List[Tuple[int, str, str]] = []   # (pos, ref_id, journal_title)

    for pos, ref in enumerate(refs, start=1):
        ref_id = ref.get("id", f"ref_{pos:03d}")
        parsed = ref.get("parsed") or {}
        raw_journal = (parsed.get("container_title") or "").strip()

        if not raw_journal:
            continue

        # Strip GROBID article-title prefix: "subtitle. Real Journal Name" → "Real Journal Name"
        journal = _extract_actual_journal(raw_journal)

        entries.append((pos, ref_id, journal))
        result.checked += 1

    if not entries:
        return result

    # ── Layer A: Cross-list consistency ────────────────────────────────
    # Group entries by normalised journal name; flag any group with >1 surface form
    groups: Dict[str, List[Tuple[int, str, str]]] = defaultdict(list)
    for pos, ref_id, journal in entries:
        key = _normalise_for_grouping(journal)
        groups[key].append((pos, ref_id, journal))

    for key, group in groups.items():
        # Collect distinct surface forms
        surface_forms = list({j for _, _, j in group})
        if len(surface_forms) > 1:
            # Sort so the most common form is listed first
            form_counts: Dict[str, int] = defaultdict(int)
            for _, _, j in group:
                form_counts[j] += 1
            sorted_forms = sorted(surface_forms, key=lambda f: -form_counts[f])

            # Flag every entry that uses a non-dominant form
            dominant = sorted_forms[0]
            for pos, ref_id, journal in group:
                if journal != dominant:
                    result.issues.append(CasingIssue(
                        ref_id     = ref_id,
                        position   = pos,
                        journal    = journal,
                        issue_type = "inconsistent",
                        detail     = (
                            f"Journal '{journal}' uses different casing than "
                            f"'{dominant}' elsewhere in the list"
                        ),
                        suggestion = dominant,
                    ))

    # ── Layer B: Per-style casing correctness ──────────────────────────
    for pos, ref_id, journal in entries:
        _check_style_casing(
            ref_id      = ref_id,
            position    = pos,
            journal     = journal,
            style_upper = style_upper,
            result      = result,
        )

    return result


def _check_style_casing(
    ref_id:      str,
    position:    int,
    journal:     str,
    style_upper: str,
    result:      CasingResult,
) -> None:
    """
    Emit a CasingIssue if `journal` does not conform to `style_upper`'s
    casing rule. Appends directly to `result.issues`.
    """
    label = _casing_label(journal)

    # ALL_CAPS is almost always an OCR artifact — flag for all styles
    if _is_all_caps(journal) and len(journal) > 4:
        result.issues.append(CasingIssue(
            ref_id     = ref_id,
            position   = position,
            journal    = journal,
            issue_type = "all_caps",
            detail     = (
                f"Journal title '{journal}' appears to be all-caps — "
                f"likely an OCR artifact or incorrect formatting"
            ),
            suggestion = journal.title(),
        ))
        return   # Don't double-report

    # All-lowercase is wrong for every style
    if _is_all_lowercase(journal) and len(journal.split()) > 1:
        result.issues.append(CasingIssue(
            ref_id     = ref_id,
            position   = position,
            journal    = journal,
            issue_type = "wrong_case",
            detail     = (
                f"Journal title '{journal}' is all-lowercase — "
                f"expected Title Case for {style_upper}"
            ),
            suggestion = _to_title_case(journal),
        ))
        return

    if style_upper in ("APA", "MLA", "HARVARD", "IEEE"):
        # These styles all require Title Case for journal names
        if not _is_title_case(journal) and not _is_all_caps(journal):
            result.issues.append(CasingIssue(
                ref_id     = ref_id,
                position   = position,
                journal    = journal,
                issue_type = "wrong_case",
                detail     = (
                    f"Journal title '{journal}' is in {label} but "
                    f"{style_upper} requires Title Case"
                ),
                suggestion = _to_title_case(journal),
            ))

    elif style_upper == "VANCOUVER":
        # Vancouver medical journals use abbreviated titles with no periods
        # e.g. "N Engl J Med" not "New England Journal of Medicine"
        # We flag sentence case as incorrect; title case is acceptable
        if _is_all_lowercase(journal):
            result.issues.append(CasingIssue(
                ref_id     = ref_id,
                position   = position,
                journal    = journal,
                issue_type = "wrong_case",
                detail     = (
                    f"Journal title '{journal}' is all-lowercase — "
                    f"Vancouver expects abbreviated title case (e.g. 'N Engl J Med')"
                ),
                suggestion = journal.title(),
            ))
        # Note: we do NOT flag full-name journals for Vancouver since many
        # non-medical Vancouver users write out full journal names.
