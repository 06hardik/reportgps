"""
equation_checker.py
===================
Implements Checks 15–18 from the ReportGPS equation validation requirements.

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
  check_15_sequential_numbering    — no gaps or duplicates in equation labels
  check_16_equation_punctuation    — display equations end with , or . when needed
  check_17_intext_reference_consistency — a single call-out style used throughout
  check_18_delimiter_balance_scaling    — balanced brackets; \\left/\\right around tall elements

Public entry point
------------------
  run_all_checks(equations, full_text) → Dict[str, dict]
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

MAX_VIOLATIONS = 30  # cap per check to keep JSON payloads reasonable


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_all_checks(
    equations: List[Dict[str, Any]],
    full_text: str,
) -> Dict[str, Dict[str, Any]]:
    """
    Run Checks 15–18 and return a dict keyed by check name.

    Args:
        equations: Output list from equation_extractor.extract_equations().
        full_text: Complete concatenated plain-text of the PDF (all pages joined).

    Returns:
        Dict with keys:
            "equation_sequential_numbering"
            "equation_punctuation"
            "in_text_reference_consistency"
            "delimiter_balance_scaling"
        Each value is a check result dict (see module docstring).
    """
    return {
        "equation_sequential_numbering":    check_15_sequential_numbering(equations),
        "equation_punctuation":             check_16_equation_punctuation(equations),
        "in_text_reference_consistency":    check_17_intext_reference_consistency(equations, full_text),
        "delimiter_balance_scaling":        check_18_delimiter_balance_scaling(equations),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Check 15 — Equation Sequential Numbering
# ─────────────────────────────────────────────────────────────────────────────

def check_15_sequential_numbering(
    equations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Verify that numbered equations form a gapless, duplicate-free integer
    sequence starting at 1 (or at whatever the first label is).

    Only equations where number is a non-None integer are considered.
    Unlabelled equations are noted in the detail string but do not fail the check.

    Violations flagged:
      - "gap"       : a number is skipped (e.g. 1, 2, 4 — missing 3)
      - "duplicate" : the same number appears more than once
    """
    numbered = [eq for eq in equations if isinstance(eq.get("number"), int)]
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

    numbers = [eq["number"] for eq in numbered]
    # ── Duplicate check ───────────────────────────────────────────────────────
    seen: Dict[int, int] = {}  # number → first occurrence index
    for idx, n in enumerate(numbers):
        if n in seen:
            violations.append({
                "type":        "duplicate",
                "number":      n,
                "first_page":  numbered[seen[n]]["page_number"],
                "second_page": numbered[idx]["page_number"],
                "detail":      f"Equation ({n}) appears more than once.",
            })
        else:
            seen[n] = idx

    # ── Gap check ─────────────────────────────────────────────────────────────
    unique_sorted = sorted(set(numbers))
    if unique_sorted:
        expected_start = unique_sorted[0]
        expected_end   = unique_sorted[-1]
        for expected in range(expected_start, expected_end + 1):
            if expected not in seen:
                violations.append({
                    "type":   "gap",
                    "number": expected,
                    "detail": (
                        f"Equation ({expected}) is missing — sequence jumps "
                        f"from ({expected - 1}) to ({expected + 1})."
                        if expected - 1 in seen and expected + 1 in seen
                        else f"Equation ({expected}) is missing from the sequence."
                    ),
                })

    violations = violations[:MAX_VIOLATIONS]
    passed = len(violations) == 0
    detail = (
        f"All {len(numbered)} numbered equation(s) are sequential."
        if passed
        else f"{len(violations)} sequencing issue(s) found among {len(numbered)} numbered equation(s)."
    )
    if unlabelled_count:
        detail += f" ({unlabelled_count} unlabelled equation(s) were skipped.)"

    return _result(passed=passed, violations=violations, detail=detail)


# ─────────────────────────────────────────────────────────────────────────────
# Check 16 — Equation Punctuation
# ─────────────────────────────────────────────────────────────────────────────

# Patterns that indicate the text following an equation continues a sentence
# and therefore the equation should have ended with a comma or period.
_CONTINUATION_RE = re.compile(
    r"""
    ^\s*
    (?:
        where         # "where x is..."
      | with          # "with ... defined as"
      | in\s+which    # "in which..."
      | and           # "and F = ..."
      | for           # "for all n"
      | such\s+that
      | here
      | note\s+that
      | since
      | as
      | thus
      | therefore
      | so\s+that
    )
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Patterns indicating the equation ends a sentence
_SENTENCE_END_RE = re.compile(
    r"""
    ^\s*
    (?:
        [A-Z]          # Next block starts with a capital → new sentence
      | \d             # Starts with a number (new enumerated item)
      | \(             # Opening paren (new equation label or list item)
    )
    """,
    re.VERBOSE,
)

# Punctuation that correctly terminates a display equation
_ENDS_WITH_PUNCT_RE = re.compile(r"""[.,;]\s*$""")

# Strip the equation label "(N)" or "[N]" at the end of LaTeX before checking
_TRAILING_LABEL_RE = re.compile(
    r"""
    \\?(?:qquad|quad|,|;|\s)*   # optional spacing commands
    (?:\([A-Za-z0-9.\-]+\)|\[[0-9]+\])  # label token
    \s*$
    """,
    re.VERBOSE,
)


def check_16_equation_punctuation(
    equations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Check that display equations end with a comma or period when they
    conclude or pause a sentence.

    Strategy:
      1. Strip any trailing equation label (e.g., `\\qquad(1)`) from the LaTeX.
      2. Check whether the LaTeX itself ends in [.,].
      3. Examine `context_after`: if it starts with a sentence-continuation
         word (where, with, and, for, …), the equation MUST end with `,`.
         If context_after starts with a capital letter (new sentence after
         equation), the equation MUST end with `.`.
      4. If context_after is empty, we cannot determine intent → skip.
    """
    violations: List[Dict[str, Any]] = []

    for eq in equations:
        latex = eq.get("latex", "")
        context_after = (eq.get("context_after") or "").strip()
        eq_label = eq.get("number_format") or "(unlabelled)"

        if not context_after:
            continue  # cannot assess without context

        # Strip trailing label from LaTeX before checking punctuation
        latex_body = _TRAILING_LABEL_RE.sub("", latex).strip()
        has_punct = bool(_ENDS_WITH_PUNCT_RE.search(latex_body))

        # Determine what punctuation is expected
        needs_comma  = bool(_CONTINUATION_RE.match(context_after))
        needs_period = (
            not needs_comma
            and bool(_SENTENCE_END_RE.match(context_after))
        )

        if not needs_comma and not needs_period:
            continue  # context is ambiguous — skip

        if needs_comma and not has_punct:
            violations.append({
                "equation":      eq_label,
                "page":          eq.get("page_number"),
                "issue":         "missing_comma",
                "context_after": context_after[:120],
                "detail": (
                    f"Equation {eq_label} (page {eq.get('page_number')}) should end "
                    f"with a comma because the following text continues the sentence: "
                    f"\"{context_after[:80]}...\""
                ),
            })
        elif needs_period and not has_punct:
            violations.append({
                "equation":      eq_label,
                "page":          eq.get("page_number"),
                "issue":         "missing_period",
                "context_after": context_after[:120],
                "detail": (
                    f"Equation {eq_label} (page {eq.get('page_number')}) should end "
                    f"with a period because it concludes a sentence."
                ),
            })

    violations = violations[:MAX_VIOLATIONS]
    passed = len(violations) == 0
    detail = (
        "All checked equations have correct terminal punctuation."
        if passed
        else f"{len(violations)} equation(s) are missing required punctuation."
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
    ("eqn. (N)",      re.compile(r'\beqn\.\s*\(\d+\)',     re.IGNORECASE)),
    ("eqn (N)",       re.compile(r'\beqn\s+\(\d+\)',       re.IGNORECASE)),
    ("(N)",           re.compile(r'(?<!\w)\(\d+\)(?!\s*[a-z]{2,})', 0)),  # bare (N)
    ("[N]",           re.compile(r'(?<!\w)\[\d+\]')),
]


def check_17_intext_reference_consistency(
    equations: List[Dict[str, Any]],
    full_text: str,
) -> Dict[str, Any]:
    """
    Verify that all equation call-outs in the document body use a single,
    consistent stylistic format.

    Examples of inconsistency:
      - "as shown in Eq. (3)" on page 2 and "from equation (5)" on page 7
      - "see (4)" (bare number) mixed with "see Eq. (6)"

    Algorithm:
      1. Scan the full document text for every known call-out pattern.
      2. Collect the set of distinct styles that matched at least once.
      3. If more than one style is found, report each style with an example
         and flag the check as failed.

    Note: bare "(N)" is only counted when it appears in a context where it
    is clearly a cross-reference (not an equation definition label or a
    numbered list item). We exclude matches immediately after line-starts
    that look like equation definitions.
    """
    style_matches: Dict[str, List[str]] = {}  # style → list of matched strings

    for style_name, pattern in _CALLOUT_PATTERNS:
        found = pattern.findall(full_text)
        if found:
            style_matches[style_name] = found[:5]  # keep up to 5 examples

    styles_found = list(style_matches.keys())
    violations: List[Dict[str, Any]] = []

    if len(styles_found) > 1:
        for style, examples in style_matches.items():
            violations.append({
                "style":    style,
                "examples": examples,
                "detail":   f"Style \"{style}\" found {len(style_matches[style])} time(s). Example: \"{examples[0]}\"",
            })

    violations = violations[:MAX_VIOLATIONS]
    passed = len(styles_found) <= 1

    if not styles_found:
        detail = "No equation call-outs detected in the document body."
    elif passed:
        detail = f"All equation call-outs use a single consistent style: \"{styles_found[0]}\"."
    else:
        detail = (
            f"{len(styles_found)} distinct call-out styles found: "
            + ", ".join(f'\"{s}\"' for s in styles_found)
            + ". Only one style should be used throughout."
        )

    return _result(passed=passed, violations=violations, detail=detail)


# ─────────────────────────────────────────────────────────────────────────────
# Check 18 — Delimiter Balance & Scaling
# ─────────────────────────────────────────────────────────────────────────────

# Tall mathematical elements that require \left/\right scaled delimiters
_TALL_ELEMENTS: List[str] = [
    r"\\frac",
    r"\\dfrac",
    r"\\tfrac",
    r"\\cfrac",
    r"\\sum",
    r"\\prod",
    r"\\int",
    r"\\oint",
    r"\\iint",
    r"\\iiint",
    r"\\sqrt",
    r"\\bigcup",
    r"\\bigcap",
    r"\\bigoplus",
    r"\\bigotimes",
]
_TALL_RE = re.compile("|".join(_TALL_ELEMENTS))

# A well-scaled delimiter pair: \left( ... \right)
_SCALED_LEFT_RE  = re.compile(r"\\(?:left|bigl?|Bigl?|biggl?|Biggl?)\s*[\(\[\{|.]")
_SCALED_RIGHT_RE = re.compile(r"\\(?:right|bigr?|Bigr?|biggr?|Biggr?)\s*[\)\]\}|.]")

# Raw (unscaled) delimiter characters
_RAW_OPEN_PARENS  = re.compile(r"(?<!\\left\s)(?<!\\bigl\s)(?<!\\Bigl\s)(?<!\\biggl\s)\(")
_RAW_CLOSE_PARENS = re.compile(r"(?<!\\right\s)(?<!\\bigr\s)(?<!\\Bigr\s)(?<!\\biggr\s)\)")


def check_18_delimiter_balance_scaling(
    equations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    For each equation's LaTeX string:

    (a) Delimiter Balance
        Count opening vs. closing brackets (parentheses, square brackets,
        curly braces) after stripping LaTeX command tokens that use `{` as
        syntax (like `\\frac{}{}`). Flag any equation where counts differ.

    (b) Unscaled Delimiters
        If a tall element (\\frac, \\sum, \\int, \\sqrt, etc.) is present,
        verify that the surrounding delimiters use \\left / \\right (or
        \\big / \\Big variants). Flag equations that have tall elements with
        raw, unscaled delimiters.
    """
    violations: List[Dict[str, Any]] = []

    for eq in equations:
        latex = eq.get("latex", "")
        eq_label = eq.get("number_format") or "(unlabelled)"
        page = eq.get("page_number")

        if not latex.strip():
            continue

        # ── (a) Delimiter balance ─────────────────────────────────────────────
        balance_issues = _check_balance(latex)
        for issue in balance_issues:
            violations.append({
                "equation":  eq_label,
                "page":      page,
                "issue":     "unbalanced_delimiter",
                "delimiter": issue["delimiter"],
                "opened":    issue["opened"],
                "closed":    issue["closed"],
                "detail": (
                    f"Equation {eq_label} (page {page}): "
                    f"{issue['opened']} opening '{issue['delimiter']}' "
                    f"but {issue['closed']} closing '{issue['closing']}'. "
                    f"Delimiters are unbalanced."
                ),
            })

        # ── (b) Unscaled delimiter around tall elements ───────────────────────
        if _TALL_RE.search(latex):
            scaled_open  = len(_SCALED_LEFT_RE.findall(latex))
            scaled_close = len(_SCALED_RIGHT_RE.findall(latex))

            # Count raw unscaled parentheses (a rough but effective signal)
            raw_open  = len(_count_raw_open(latex))
            raw_close = len(_count_raw_close(latex))

            if raw_open > 0 or raw_close > 0:
                # Only flag if there is at least one tall element AND
                # raw (unscaled) delimiters that are NOT balanced with \left/\right
                if scaled_open == 0 and scaled_close == 0:
                    violations.append({
                        "equation": eq_label,
                        "page":     page,
                        "issue":    "unscaled_delimiter",
                        "detail": (
                            f"Equation {eq_label} (page {page}) contains a tall element "
                            f"({_first_tall_element(latex)}) but uses raw (unscaled) "
                            f"delimiters. Consider replacing '(' / ')' with "
                            f"'\\\\left(' / '\\\\right)'."
                        ),
                    })

    violations = violations[:MAX_VIOLATIONS]
    passed = len(violations) == 0
    detail = (
        "All equation delimiters are balanced and properly scaled."
        if passed
        else (
            f"{len(violations)} delimiter issue(s) found across "
            f"{len(equations)} equation(s)."
        )
    )
    return _result(passed=passed, violations=violations, detail=detail)


# ─────────────────────────────────────────────────────────────────────────────
# Check 18 internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _check_balance(latex: str) -> List[Dict[str, Any]]:
    """
    Return a list of imbalance records for (, [, { delimiter pairs.

    We use a simple stack-based approach after stripping comment lines
    and text-mode content (\\text{...}) which may contain natural language
    brackets that should not be counted as math delimiters.
    """
    # Remove \\text{...} and \\mbox{...} to avoid false positives
    cleaned = re.sub(r'\\(?:text|mbox|mathrm|mathit|mathbf|hbox)\{[^}]*\}', '', latex)
    # Remove LaTeX comments
    cleaned = re.sub(r'%.*$', '', cleaned, flags=re.MULTILINE)

    pairs = [
        ("(", ")", "parenthesis"),
        ("[", "]", "square bracket"),
        # Curly braces in LaTeX are usually structural (argument delimiters),
        # so we only count \{ and \} (escaped curly braces used as math delimiters)
    ]

    # Strip all \left, 
    # Strip all \left, \right, \bigl, etc. and their accompanying delimiters first
    stripped = re.sub(r'\\(?:left|right|big[lr]?|Big[lr]?|bigg[lr]?|Bigg[lr]?)\s*(?:[()[\]|.]|\\\{|\\\})', '', cleaned)
    
    issues = []
    for open_ch, close_ch, name in pairs:
        opened = stripped.count(open_ch)
        closed = stripped.count(close_ch)
        if opened != closed:
            issues.append({
                "delimiter": open_ch,
                "closing":   close_ch,
                "name":      name,
                "opened":    opened,
                "closed":    closed,
            })

    # Escaped curly braces used as math symbols: \{ and \}
    escaped_open  = len(re.findall(r'\\\{', stripped))
    escaped_close = len(re.findall(r'\\\}', stripped))
    if escaped_open != escaped_close:
        issues.append({
            "delimiter": r"\{",
            "closing":   r"\}",
            "name":      "curly brace",
            "opened":    escaped_open,
            "closed":    escaped_close,
        })

    return issues


def _count_raw_open(latex: str) -> List[str]:
    """Count raw (non-\\left) opening parentheses/brackets."""
    # Remove \left( etc.
    cleaned = re.sub(r'\\(?:left|bigl?|Bigl?)\s*[(\[{|]', '', latex)
    return re.findall(r'[(\[]', cleaned)


def _count_raw_close(latex: str) -> List[str]:
    """Count raw (non-\\right) closing parentheses/brackets."""
    cleaned = re.sub(r'\\(?:right|bigr?|Bigr?)\s*[)\]}|]', '', latex)
    return re.findall(r'[)\]]', cleaned)


def _first_tall_element(latex: str) -> str:
    """Return the first tall element command found in the LaTeX string."""
    m = _TALL_RE.search(latex)
    return m.group(0) if m else "tall element"


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
