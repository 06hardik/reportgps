"""
typography_checker.py
=====================
Fast regex-based typography checks on the body text of a PDF paper.

Covers checks 26–28:
  26. En-dash for numeric ranges  (hyphen used where en-dash expected)
  27. Number-unit spacing         (missing space between number and unit)
  28. Percent/degree spacing      (missing space or incorrect usage)

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
# Excludes: negative numbers, version strings, ISBNs (multiple hyphens), and ISSNs (slash suffix)
_HYPHEN_RANGE = re.compile(r'(?<!\w|[-–])(\d+)-(\d+)(?!\w|\.\d|[-–/])')

# Double-dash used as range separator
_DOUBLE_DASH = re.compile(r'(\d)\s*--\s*(\d)')

# DOI strings — blanked out before en-dash scanning so hyphens inside
# DOIs (e.g. doi:10.1109/NET.2021.3050-3070) are never flagged.
# Covers: "doi:10.xxxx/..." and "https://doi.org/10.xxxx/..."
_DOI_STRIP_RE = re.compile(
    r'(?:'
    r'(?:https?://)?doi\.org/'   # https://doi.org/ or doi.org/ or ttps://doi.org/
    r'|doi:\s*'                   # doi: prefix
    r')'
    r'10\.\d{4,}[^\s]*',        # 10.NNNN/... rest of DOI path
    re.IGNORECASE,
)

# Number directly followed by a unit (no space).
#
# DESIGN DECISIONS — to prevent false positives on figure/table labels
# like "1a", "4b", "Fig. 1g" etc.:
#
#   1. NO re.IGNORECASE — SI units are case-sensitive (mW ≠ MW, ms ≠ MS).
#      Without IGNORECASE, 'a','b','c','g' etc. no longer match 'A','B','C','G'.
#
#   2. All ambiguous single-letter units (g, A, L, K, W, V, s) are REMOVED
#      because they are indistinguishable from figure/table sub-part labels
#      and common prose letters.
#
#   3. Negative lookahead (?![a-zA-Z0-9]) after the unit — the matched unit
#      must NOT be immediately followed by another alphanumeric character.
#      This stops "Fig. 4b" matching because 'b' is followed by more letters.
_UNIT_LIST = (
    # Time (compound only; bare 's' excluded)
    "ms|\u00b5s|\u03bcs|ns|ps|fs"
    # Mass (compound only; bare 'g' excluded)
    "|kg|mg|\u00b5g|\u03bcg|ng"
    # Distance (compound only; bare 'm' excluded)
    "|km|cm|mm|nm|\u00b5m|\u03bcm|pm|\u00c5"
    # Frequency (longer first)
    "|MHz|GHz|kHz|THz|Hz"
    # Digital storage
    "|KB|MB|GB|TB|kB|PB"
    # Power (compound only; bare 'W' excluded)
    "|kW|MW|GW|mW|\u00b5W|\u03bcW"
    # Voltage (compound only; bare 'V' excluded)
    "|kV|MV|mV|\u00b5V|\u03bcV"
    # Current (compound only; bare 'A' excluded)
    "|mA|\u00b5A|\u03bcA|nA"
    # Decibels
    "|dBm|dBi|dB"
    # Magnetic flux density (compound; bare 'T' excluded)
    "|mT|\u00b5T|\u03bcT"
    # Chemical (compound only; bare 'mol' can be ambiguous but kept as it
    # is multi-character and always a scientific term)
    "|mmol|\u00b5mol|\u03bcmol"
    # Volume (compound only; bare 'L' excluded)
    "|mL|\u00b5L|\u03bcL|nL|dL"
    # Temperature — degree symbol required, prevents bare 'C'/'F' match
    "|\u00b0C|\u00b0F"
    # Angle
    "|rad|sr"
    # Pressure
    "|kPa|MPa|GPa|bar|atm|Pa"
    # Speed (compound, avoids bare 'm')
    "|km/h|m/s"
    # Resistance
    "|k\u03a9|M\u03a9|\u03a9"
    # Capacitance / Inductance
    "|\u00b5F|\u03bcF|nF|pF|mH|\u00b5H|\u03bcH|nH"
)
# Case-sensitive (no re.IGNORECASE).
# Negative lookahead (?![a-zA-Z0-9]) blocks alphanumeric-suffix false positives.
_NO_SPACE_UNIT = re.compile(
    rf'\b(\d+(?:\.\d+)?)({_UNIT_LIST})(?![a-zA-Z0-9])'
)

# Percent: digit(s) immediately followed by % then a letter (no space before text)
# Correct: "99%" at end, "99 %" with space, "99% ". Wrong: "99%accuracy"
_PERCENT_NOSPACE = re.compile(r'\b(\d+(?:\.\d+)?)(%)(?=[A-Za-z])')

# Degree without unit: "45°something" where something is not C/F/K (those are OK)
_DEGREE_NOSPACE = re.compile(r'\b(\d+°)(?![CFK\s°\d])')


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
    }


# ─────────────────────────────────────────────────────────────────────────────
# Check 26: En-dash for numeric ranges
# ─────────────────────────────────────────────────────────────────────────────

def _check_en_dash(text: str) -> List[Dict[str, Any]]:
    # Step 1: Strip DOI strings — replace with spaces of same length so all
    # other character positions remain intact.
    scan_text = _DOI_STRIP_RE.sub(lambda m: ' ' * len(m.group(0)), text)

    # Step 2: Strip citation brackets like [23-25], [1, 2], [3–5] — these are
    # valid citation syntax, not numeric range formatting errors.  Replace the
    # entire bracket content (up to 40 chars) with spaces.
    scan_text = re.sub(r'\[[^\]]{1,40}\]', lambda m: ' ' * len(m.group(0)), scan_text)

    violations: List[Dict] = []
    seen: set = set()

    for m in _HYPHEN_RANGE.finditer(scan_text):
        key = m.group(0)
        if key in seen:
            continue
        seen.add(key)
        violations.append({
            "found":   key,
            "correct": f"{m.group(1)}\u2013{m.group(2)}",
            "snippet": _snippet(text, m.start(), m.end()),
            "detail":  f"Use en-dash (\u2013) for range: '{key}' \u2192 '{m.group(1)}\u2013{m.group(2)}'",
        })
        if len(violations) >= MAX_VIOLATIONS:
            break

    for m in _DOUBLE_DASH.finditer(scan_text):
        key = m.group(0)
        if key in seen:
            continue
        seen.add(key)
        violations.append({
            "found":   key,
            "correct": f"{m.group(1)}\u2013{m.group(2)}",
            "snippet": _snippet(text, m.start(), m.end()),
            "detail":  f"Use en-dash (\u2013) instead of double-hyphen (--): '{key}'",
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
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _snippet(text: str, start: int, end: int, window: int = 30) -> str:
    """Return ±window chars around [start:end], with newlines collapsed."""
    s = max(0, start - window)
    e = min(len(text), end + window)
    return re.sub(r'\s+', ' ', text[s:e]).strip()
