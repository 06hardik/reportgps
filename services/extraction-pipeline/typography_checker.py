"""
typography_checker.py
=====================
Fast regex-based typography checks on the body text of a PDF paper.

Covers checks 26–29:
  26. En-dash for numeric ranges  (hyphen used where en-dash expected)
  27. Number-unit spacing         (missing space between number and unit)
  28. Percent/degree spacing      (missing space or incorrect usage)
  29. Latin abbreviations         (e.g., i.e., et al. formatting)

All patterns operate on the full body text (references section excluded by
the caller).  Each function returns a list of violation dicts:
  {"found": str, "snippet": str}
where "snippet" is ±25 chars of context for display.

A maximum of MAX_VIOLATIONS per category is returned to avoid flooding the
output for papers with widespread issues.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

MAX_VIOLATIONS = 25

# ─────────────────────────────────────────────────────────────────────────────
# Compiled patterns
# ─────────────────────────────────────────────────────────────────────────────

# En-dash: hyphen between two integers (ranges)
# Excludes: negative numbers, page references in citations, DOIs
_HYPHEN_RANGE = re.compile(r'(?<!\w)(\d+)-(\d+)(?!\w|\.\d)')

# Double-dash used as range separator
_DOUBLE_DASH = re.compile(r'(\d)\s*--\s*(\d)')

# Number directly followed by a unit (no space)
_UNIT_LIST = (
    "ms|µs|μs|ns|ps|fs"
    "|kg|g|mg|µg|μg|ng"
    "|km|cm|mm|nm|µm|μm|pm|Å"
    "|MHz|GHz|kHz|THz|Hz"
    "|KB|MB|GB|TB|kB|PB"
    "|kW|MW|GW|W|mW|µW|μW"
    "|kV|MV|V|mV|µV|μV"
    "|A|mA|µA|μA|nA"
    "|dB|dBm|dBi"
    "|mol|mmol|µmol|μmol"
    "|L|mL|µL|μL|nL|dL"
    "|K|°C|°F"            # temperature
    "|rad|sr"
    "|Pa|kPa|MPa|GPa|bar|atm"
    "|bits?|bytes?|Bytes?"
)
_NO_SPACE_UNIT = re.compile(
    rf'\b(\d+(?:\.\d+)?)({_UNIT_LIST})\b',
    re.IGNORECASE,
)

# Percent: digit(s) immediately followed by % then a letter (no space before text)
# Correct: "99%" at end, "99 %" with space, "99% ". Wrong: "99%accuracy"
_PERCENT_NOSPACE = re.compile(r'\b(\d+(?:\.\d+)?)(%)(?=[A-Za-z])')

# Degree without unit: "45°something" where something is not C/F/K (those are OK)
_DEGREE_NOSPACE = re.compile(r'\b(\d+°)(?![CFK\s°\d])')

# Latin abbreviations without proper period / comma formatting
# Bad: "eg", "ie" (no periods), "etc" (no period), "et al" (no period)
# Also flag "i.e.," or "e.g.," not followed by space
_LATIN_BAD: List[tuple] = [
    (re.compile(r'\beg\b(?!\.)'), "e.g."),
    (re.compile(r'\bie\b(?!\.)'), "i.e."),
    (re.compile(r'\betc\b(?!\.)'), "etc."),
    (re.compile(r'\bet\s+al\b(?!\.)'), "et al."),
    (re.compile(r'\bcf\b(?!\.)'), "cf."),
    (re.compile(r'\bviz\b(?!\.)'), "viz."),
    # "i.e.," or "e.g.," not followed by a space
    (re.compile(r'i\.e\.,(?!\s)'), "i.e., "),
    (re.compile(r'e\.g\.,(?!\s)'), "e.g., "),
]


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def check_typography(body_text: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Run all typography checks on body_text.

    Args:
        body_text: Full document text (references section already excluded
                   by the caller — pass orchestrator's body_text, not full_text).

    Returns:
        {
          "en_dash_violations":        [...],
          "number_unit_violations":    [...],
          "percent_degree_violations": [...],
          "latin_abbrev_violations":   [...],
        }
    """
    return {
        "en_dash_violations":        _check_en_dash(body_text),
        "number_unit_violations":    _check_number_unit(body_text),
        "percent_degree_violations": _check_percent_degree(body_text),
        "latin_abbrev_violations":   _check_latin_abbrev(body_text),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Check 26: En-dash for numeric ranges
# ─────────────────────────────────────────────────────────────────────────────

def _check_en_dash(text: str) -> List[Dict[str, Any]]:
    violations: List[Dict] = []
    seen: set = set()

    for m in _HYPHEN_RANGE.finditer(text):
        key = m.group(0)
        if key in seen:
            continue
        seen.add(key)
        violations.append({
            "found":   key,
            "correct": f"{m.group(1)}–{m.group(2)}",
            "snippet": _snippet(text, m.start(), m.end()),
            "detail":  f"Use en-dash (–) for range: '{key}' → '{m.group(1)}–{m.group(2)}'",
        })
        if len(violations) >= MAX_VIOLATIONS:
            break

    for m in _DOUBLE_DASH.finditer(text):
        key = m.group(0)
        if key in seen:
            continue
        seen.add(key)
        violations.append({
            "found":   key,
            "correct": f"{m.group(1)}–{m.group(2)}",
            "snippet": _snippet(text, m.start(), m.end()),
            "detail":  f"Use en-dash (–) instead of double-hyphen (--): '{key}'",
        })
        if len(violations) >= MAX_VIOLATIONS:
            break

    return violations


# ─────────────────────────────────────────────────────────────────────────────
# Check 27: Number-unit spacing
# ─────────────────────────────────────────────────────────────────────────────

def _check_number_unit(text: str) -> List[Dict[str, Any]]:
    violations: List[Dict] = []
    seen: set = set()

    for m in _NO_SPACE_UNIT.finditer(text):
        key = m.group(0)
        if key in seen:
            continue
        seen.add(key)
        correct = f"{m.group(1)} {m.group(2)}"
        violations.append({
            "found":   key,
            "correct": correct,
            "snippet": _snippet(text, m.start(), m.end()),
            "detail":  f"Add space between number and unit: '{key}' → '{correct}'",
        })
        if len(violations) >= MAX_VIOLATIONS:
            break

    return violations


# ─────────────────────────────────────────────────────────────────────────────
# Check 28: Percent / degree spacing
# ─────────────────────────────────────────────────────────────────────────────

def _check_percent_degree(text: str) -> List[Dict[str, Any]]:
    violations: List[Dict] = []
    seen: set = set()

    for m in _PERCENT_NOSPACE.finditer(text):
        key = m.group(0)
        if key in seen:
            continue
        seen.add(key)
        violations.append({
            "found":   key,
            "snippet": _snippet(text, m.start(), m.end()),
            "detail":  f"Percent sign '{m.group(2)}' directly followed by letter — add space or rewrite.",
        })
        if len(violations) >= MAX_VIOLATIONS:
            break

    for m in _DEGREE_NOSPACE.finditer(text):
        key = m.group(0)
        if key in seen:
            continue
        seen.add(key)
        violations.append({
            "found":   key,
            "snippet": _snippet(text, m.start(), m.end()),
            "detail":  f"Degree symbol without unit: '{key}' — should be e.g. '45 °C'.",
        })
        if len(violations) >= MAX_VIOLATIONS:
            break

    return violations


# ─────────────────────────────────────────────────────────────────────────────
# Check 29: Latin abbreviations
# ─────────────────────────────────────────────────────────────────────────────

def _check_latin_abbrev(text: str) -> List[Dict[str, Any]]:
    violations: List[Dict] = []
    seen: set = set()

    for pattern, correct in _LATIN_BAD:
        for m in pattern.finditer(text):
            # Use a region-based key to avoid flooding with every occurrence
            region_key = m.group(0) + str(m.start() // 200)
            if region_key in seen:
                continue
            seen.add(region_key)
            violations.append({
                "found":   m.group(0),
                "correct": correct,
                "snippet": _snippet(text, m.start(), m.end()),
                "detail":  f"'{m.group(0)}' should be '{correct}'",
            })
            if len(violations) >= MAX_VIOLATIONS:
                return violations

    return violations


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _snippet(text: str, start: int, end: int, window: int = 30) -> str:
    """Return ±window chars around [start:end], with newlines collapsed."""
    s = max(0, start - window)
    e = min(len(text), end + window)
    return re.sub(r'\s+', ' ', text[s:e]).strip()
