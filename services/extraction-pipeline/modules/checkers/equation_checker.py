"""
equation_checker.py
===================
Implements Checks 15–17 from the ReportGPS equation validation requirements.

All checks are pure-Python functions that operate on:
  - equations : list of equation dicts produced by equation_extractor.py
  - full_text : the complete plain-text of the document (needed for Check 17)

Each check function returns a standardised result dict:
{
    "passed":     bool,
    "violations": List[dict],   # zero or more violation records
    "detail":     str,          # human-readable one-line summary
}

Check catalogue
---------------
  check_15_sequential_numbering         — no gaps in equation labels
  check_16_equation_punctuation         — comma required when text after starts with
                                          "where / with / in which" etc. on same line
  check_17_intext_reference_consistency — a single call-out style used throughout

Public entry point
------------------
  run_all_checks(equations, full_text) → Dict[str, dict]

Notes on Check 16 (Punctuation)
---------------------------------
We check for a MISSING COMMA only when:
  1. The text immediately after the equation (context_after) starts with a
     lowercase continuation word: "where", "with", "in which", "and", "for".
  2. The context_before does NOT already end with a comma/period.
  3. The word appears on what looks like the same flowing sentence
     (not a new paragraph starting on the next line).

We deliberately DO NOT flag "missing period" because:
  - In many journal styles equations that end a sentence do not require a period.
  - False positive rate is very high without LaTeX source.

Notes on Check 15 (Sequential)
---------------------------------
We only report GAPS (missing numbers in the sequence).
We do NOT report duplicates — our extractor already deduplicates by number
(keeping the first occurrence), so the checker never receives duplicates.
We also do NOT report "gap" if the sequence has fewer than 3 equations total,
because it is common for papers to number only the equations they refer to,
skipping others.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

MAX_VIOLATIONS = 20  # cap per check to keep JSON payloads reasonable


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_all_checks(
    equations: List[Dict[str, Any]],
    full_text: str,
    page_offsets: List[int] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Run Checks 15–17 and return a dict keyed by check name.

    Args:
        equations: Output list from equation_extractor.extract_equations().
        full_text: Complete concatenated plain-text of the PDF (all pages joined).
        page_offsets: Optional list of text start indices for each page.

    Returns:
        Dict with keys:
            "equation_sequential_numbering"
            "equation_punctuation"
            "in_text_reference_consistency"
        Each value is a check result dict (see module docstring).
    """
    return {
        "equation_sequential_numbering":    check_15_sequential_numbering(equations),
        "equation_punctuation":             check_16_equation_punctuation(equations),
        "in_text_reference_consistency":    check_17_intext_reference_consistency(equations, full_text, page_offsets),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Check 15 — Equation Sequential Numbering
# ─────────────────────────────────────────────────────────────────────────────

def check_15_sequential_numbering(
    equations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Verify that numbered equations form a gapless integer sequence.

    The extractor already deduplicates by number (first-occurrence-wins), so
    we only need to check for GAPS here.

    A gap is only reported when:
      - The sequence has at least 3 numbered equations (shorter sequences are
        too often intentionally non-contiguous).
      - The missing number N is between the min and max of the found numbers.
      - The gap is not larger than 5 (a paper that labels only every 5th equation
        using a different numbering convention should not be flagged).
    """
    numbered = [eq for eq in equations if isinstance(eq.get("number"), int) and eq["number"] >= 1]
    unlabelled_count = len(equations) - len(numbered)
    violations: List[Dict[str, Any]] = []

    if not numbered:
        return _result(
            passed=True,
            violations=[],
            detail=(
                "No numbered equations found. "
                f"{unlabelled_count} unlabelled equation(s) detected."
            ),
        )

    numbers = sorted(set(eq["number"] for eq in numbered))

    # Build a map from number → equation for quick lookup
    num_to_eq: Dict[int, Dict] = {}
    for eq in numbered:
        n = eq["number"]
        if n not in num_to_eq:
            num_to_eq[n] = eq

    # Only check gaps if the sequence is long enough to be meaningful
    if len(numbers) >= 3:
        min_n = numbers[0]
        max_n = numbers[-1]
        # A very sparse sequence (e.g. only 1, 5, 10) means the paper uses
        # selective numbering — don't flag as errors.
        # We only flag gaps of 1 (exactly one number missing between two adjacent found numbers).
        for i in range(len(numbers) - 1):
            a = numbers[i]
            b = numbers[i + 1]
            if b - a == 2:
                # Exactly one number missing
                missing = a + 1
                eq_before = num_to_eq.get(a, {})
                eq_after  = num_to_eq.get(b, {})
                page_before = eq_before.get("page_number", "?")
                page_after  = eq_after.get("page_number", "?")
                violations.append({
                    "type":       "gap",
                    "number":     missing,
                    "page":       page_before,
                    "evidence":   f"Sequence jumps from ({a}) on page {page_before} to ({b}) on page {page_after}. Equation ({missing}) is missing.",
                    "detail": (
                        f"Equation ({missing}) is missing — "
                        f"sequence jumps from ({a}) to ({b})."
                    ),
                })
            elif b - a > 2:
                # Multiple numbers missing — report the range
                eq_before = num_to_eq.get(a, {})
                eq_after  = num_to_eq.get(b, {})
                page_before = eq_before.get("page_number", "?")
                page_after  = eq_after.get("page_number", "?")
                missing_range = f"({a+1})–({b-1})"
                violations.append({
                    "type":       "gap",
                    "number":     a + 1,
                    "page":       page_before,
                    "evidence":   f"Sequence jumps from ({a}) on page {page_before} to ({b}) on page {page_after}. Equations {missing_range} are missing.",
                    "detail": (
                        f"Equations {missing_range} are missing — "
                        f"sequence jumps from ({a}) to ({b})."
                    ),
                })

    violations = violations[:MAX_VIOLATIONS]
    passed = len(violations) == 0
    detail = (
        f"All {len(numbers)} numbered equation(s) are sequential ({numbers[0]}–{numbers[-1]})."
        if passed and numbers
        else f"{len(violations)} sequencing gap(s) found among {len(numbers)} numbered equation(s)."
    )
    if unlabelled_count:
        detail += f" ({unlabelled_count} unlabelled equation(s) were skipped.)"

    return _result(passed=passed, violations=violations, detail=detail)


# ─────────────────────────────────────────────────────────────────────────────
# Check 16 — Equation Punctuation
# ─────────────────────────────────────────────────────────────────────────────

# Words that signal the text after the equation is a sentence continuation.
# The comma MUST appear at the end of the equation line when these follow.
_CONTINUATION_WORDS = re.compile(
    r"""
    ^\s*
    (?:
        where         # "where x is the..."
      | with          # "with A defined as..."
      | in\s+which    # "in which case..."
      | such\s+that   # "such that..."
    )
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Punctuation that correctly terminates a display equation line
# We check context_before (the line of text before the label) for a comma
_ENDS_WITH_COMMA_RE = re.compile(r',\s*$')
_ENDS_WITH_PERIOD_RE = re.compile(r'\.\s*$')


def check_16_equation_punctuation(
    equations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Check that display equations end with a comma when the following text
    is a sentence continuation starting with "where", "with", "in which",
    or "such that".

    Strategy:
      1. Look at context_after: if it starts with a continuation word, a comma
         is required at the end of the equation.
      2. Look at context_before: check if the last non-empty line already ends
         with a comma (meaning the equation body itself has the comma).
      3. Only flag if no comma is found anywhere near the equation end.

    We deliberately skip "missing period" checks — too many false positives
    without LaTeX source.
    """
    violations: List[Dict[str, Any]] = []

    for eq in equations:
        context_after  = (eq.get("context_after")  or "").strip()
        context_before = (eq.get("context_before") or "").strip()
        eq_label  = eq.get("number_format") or "(unlabelled)"
        page      = eq.get("page_number")

        if not context_after:
            continue  # cannot assess without following text

        # Only flag when after-text starts with a continuation word
        if not _CONTINUATION_WORDS.match(context_after):
            continue

        # The continuation word should appear on the very next line (within ~60 chars)
        # If it's far away, it's probably a new paragraph, not a continuation
        first_line_after = context_after[:80]
        if not _CONTINUATION_WORDS.match(first_line_after):
            continue

        # Check if context_before already ends with a comma
        # (the comma would be at the end of the equation's own content line)
        if _ENDS_WITH_COMMA_RE.search(context_before) or _ENDS_WITH_PERIOD_RE.search(context_before):
            continue  # already has punctuation — no violation

        # Check if context_after itself starts with a comma (unlikely but possible)
        if context_after.startswith(','):
            continue

        # Flag the violation
        continuation_word = context_after.split()[0] if context_after.split() else "continuation word"
        violations.append({
            "equation":      eq_label,
            "page":          page,
            "issue":         "missing_comma",
            "evidence": (
                f"On page {page}, after Equation {eq_label} the text continues "
                f"with '{first_line_after[:60]}...' without a period, "
                f"showing the sentence is still open."
            ),
            "context_after": context_after[:120],
            "detail": (
                f"Missing comma after Equation {eq_label} — "
                f"the sentence continues with \"{continuation_word}...\" "
                f"which requires a comma at the end of the equation."
            ),
        })

    violations = violations[:MAX_VIOLATIONS]
    passed = len(violations) == 0
    detail = (
        "All checked equations have correct terminal punctuation."
        if passed
        else f"{len(violations)} equation(s) may be missing a comma before a 'where/with' continuation."
    )
    return _result(passed=passed, violations=violations, detail=detail)


# ─────────────────────────────────────────────────────────────────────────────
# Check 17 — In-text Reference Consistency
# ─────────────────────────────────────────────────────────────────────────────

# Known equation call-out patterns, ordered from most specific to least.
# Each entry: (canonical_style_name, compiled_regex)
_CALLOUT_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("Equation (N)",  re.compile(r'\bEquation\s+\(\d+\)',  re.IGNORECASE)),
    ("Eq. (N)",       re.compile(r'\bEq\.\s*\(\d+\)',      re.IGNORECASE)),
    ("Eq (N)",        re.compile(r'\bEq\s+\(\d+\)',        re.IGNORECASE)),
    ("Eqs. (N)",      re.compile(r'\bEqs?\.\s*\(\d+\)',    re.IGNORECASE)),
    ("eqn. (N)",      re.compile(r'\beqn\.\s*\(\d+\)',     re.IGNORECASE)),
    ("eqn (N)",       re.compile(r'\beqn\s+\(\d+\)',       re.IGNORECASE)),
]
# NOTE: bare "(N)" is intentionally excluded — it appears too frequently as
# equation definition labels themselves and produces constant false positives.


def _find_page(pos: int, page_offsets: List[int]) -> int:
    """Find the 1-based page number for a given character offset."""
    import bisect
    if not page_offsets:
        return 1
    # bisect_right returns the index of the first offset > pos.
    # The page is the one before it, so subtract 1. Then add 1 for 1-based page.
    idx = bisect.bisect_right(page_offsets, pos) - 1
    return max(1, idx + 1)

def check_17_intext_reference_consistency(
    equations: List[Dict[str, Any]],
    full_text: str,
    page_offsets: List[int] = None,
) -> Dict[str, Any]:
    """
    Verify that all equation call-outs in the document body use a single,
    consistent stylistic format.

    Examples of inconsistency:
      - "as shown in Eq. (3)" on page 2 and "from equation (5)" on page 7
      - "Eqs. (4) and (5)" mixed with "Eq. (6)"
    """
    style_matches: Dict[str, List[Tuple[str, int]]] = {}

    for style_name, pattern in _CALLOUT_PATTERNS:
        matches = [(m.group(0), m.start()) for m in pattern.finditer(full_text)]
        if matches:
            style_matches[style_name] = matches

    # "Eqs." and "Eq." are the same style — merge them
    if "Eqs. (N)" in style_matches and "Eq. (N)" in style_matches:
        style_matches["Eq. (N)"].extend(style_matches.pop("Eqs. (N)"))

    styles_found = list(style_matches.keys())
    violations: List[Dict[str, Any]] = []

    if len(styles_found) > 1:
        # Determine the dominant style (the one with the most matches)
        dominant_style = max(styles_found, key=lambda s: len(style_matches[s]))
        
        # Report all matches of NON-dominant styles as violations
        for style, matches in style_matches.items():
            if style == dominant_style:
                continue
            for match_text, pos in matches[:10]: # limit to 10 examples per minority style
                page = _find_page(pos, page_offsets) if page_offsets else None
                # Get a snippet of context
                start_idx = max(0, pos - 40)
                end_idx = min(len(full_text), pos + 40)
                context = full_text[start_idx:end_idx].replace('\n', ' ').strip()
                
                violations.append({
                    "style":    style,
                    "page":     page,
                    "evidence": f'"{context}"',
                    "detail":   f'Inconsistent citation style: found "{match_text}" (style: "{style}") instead of dominant style "{dominant_style}".',
                })

    violations = violations[:MAX_VIOLATIONS]
    passed = len(styles_found) <= 1

    if not styles_found:
        detail = "No equation call-outs detected in the document body."
    elif passed:
        detail = f'All equation call-outs use a single consistent style: "{styles_found[0]}".'
    else:
        detail = (
            f"{len(styles_found)} distinct call-out styles found: "
            + ", ".join(f'"{s}"' for s in styles_found)
            + ". Only one style should be used throughout."
        )

    return _result(passed=passed, violations=violations, detail=detail)


# ─────────────────────────────────────────────────────────────────────────────
# Shared result builder
# ─────────────────────────────────────────────────────────────────────────────

def _result(
    passed: bool,
    violations: List[Dict[str, Any]],
    detail: str,
) -> Dict[str, Any]:
    return {
        "passed":     passed,
        "violations": violations,
        "detail":     detail,
    }
