"""
syntax_grammar_checker.py
=========================
Checks 17–24: Typography, Syntax & Grammar validation.

Check 17 – Acronym Definition
Check 18 – En-dash for Ranges
Check 19 – Non-breaking Space for Units
Check 20 – No Space for Percentages/Degrees
Check 21 – Double Spaces
Check 22 – Consistent Punctuation Spacing
Check 23 – Quote Style Consistency
Check 24 – English Spelling Consistency

All checks are implemented using Unicode-aware Regular Expressions only.
No ML, NLP, or external libraries are used.

Integration:
  Called from orchestrator.py as Step 3d.
  Results stored under result["syntax_grammar_checks"].

Data used:
  full_text  – complete concatenated page text (all pages, includes references).
               Used by checks that need document-wide first-occurrence context
               (Check 17: Acronym, Check 23: Quote Style).
  body_text  – full_text with the references/bibliography section excluded.
               Used by all other checks to avoid flagging reference-list text.

Returns:
  Dict[str, Dict] keyed by check name; each value contains at minimum:
    {"passed": bool, "violations": List[dict], "detail": str}
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set, Tuple

MAX_VIOLATIONS = 25


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def check_syntax_grammar(
    full_text: str,
    body_text: str,
) -> Dict[str, Any]:
    """
    Run all 8 Typography / Syntax / Grammar checks.

    Args:
        full_text:  Complete paper text (all pages joined), references included.
        body_text:  Paper text with references section excluded.

    Returns:
        Dict keyed by check name. Each value is that check's result dict.
    """
    return {
        "acronym_definition":            _check_acronym_definition(full_text),
        "en_dash_ranges":                _check_en_dash_ranges(body_text),
        "nonbreaking_space_units":       _check_nonbreaking_space_units(body_text),
        "no_space_percent_degree":       _check_no_space_percent_degree(body_text),
        "double_spaces":                 _check_double_spaces(body_text),
        "punctuation_spacing":           _check_punctuation_spacing(body_text),
        "quote_style_consistency":       _check_quote_style_consistency(full_text),
        "english_spelling_consistency":  _check_english_spelling_consistency(body_text),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Check 17: Acronym Definition
# ─────────────────────────────────────────────────────────────────────────────

# Acronyms so universally understood in scientific writing that they need no
# parenthetical definition in a research paper.
_SKIP_ACRONYMS: Set[str] = {
    # Internet / computing
    "PDF", "URL", "HTTP", "HTTPS", "HTML", "CSS", "API", "XML", "JSON", "SQL",
    "TCP", "UDP", "IP", "DNS", "RAM", "ROM", "CPU", "GPU", "USB", "LAN", "WAN",
    "LED", "LCD", "OLED", "RGB", "HSV", "HSL",
    # Organisations / standards bodies
    "IEEE", "ACM", "ISO", "ANSI",
    # Countries / regions
    "USA", "UK", "EU", "UN", "WHO",
    # Publishing / academic
    "DOI", "ISBN", "ISSN",
    # Signal processing / RF
    "RMS", "SNR", "MIMO", "OFDM",
    # Time
    "UTC", "GMT",
    # Common statistical / math shorthand (not acronyms per se)
    "MAX", "MIN", "AVG", "STD",
    # Common English words that appear all-caps in headings / captions
    "FOR", "AND", "THE", "NOT", "ALL", "TWO", "ONE", "TEN",
    "NEW", "OLD", "LAB", "FIG", "TAB", "SEC", "EQN", "REF", "APP",
    # IEEE / computer-science shorthand used without expansion in the field
    "NaN", "INF",
}

# "(ACRONYM)" – acronym inside parentheses after prose text.
# e.g. "Wireless Sensor Network (WSN)"
_PAREN_ACRONYM_RE = re.compile(r'\(([A-Z]{3,})\)')

# "ACRONYM (Full Name)" – acronym followed by a definition in parentheses.
# Requires the definition to start with a letter and be 5–60 chars.
# e.g. "CNN (Convolutional Neural Network)"
_DEFINE_AFTER_RE = re.compile(
    r'\b([A-Z]{3,})\s+\([a-zA-Z][a-zA-Z\s\-]{5,60}\)'
)

# All standalone 3+ uppercase-letter sequences (the "all acronyms" scanner).
_ACRONYM_ALL_RE = re.compile(r'\b([A-Z]{3,})\b')


def _initials_match(text: str, paren_start: int, acronym: str) -> bool:
    """
    Return True if any window of len(acronym) consecutive alpha-starting words
    in the 200 chars preceding *paren_start* has initials that spell *acronym*.

    Example: "Wireless Sensor Network (WSN)" → words W·S·N → initials = WSN ✓
    Counter: "See Figure 3 (WSN)" → alpha-words S·F → too short for 3-char WSN ✓
    """
    n = len(acronym)
    pre = text[max(0, paren_start - 200): paren_start]
    # Keep only words that start with a letter (drop pure numbers, symbols).
    words = [w for w in pre.split() if w and w[0].isalpha()]
    if len(words) < n:
        return False
    # Slide a window of size n over the last (n + 3) candidate words.
    start_i = max(0, len(words) - n - 3)
    for i in range(start_i, len(words) - n + 1):
        window = words[i: i + n]
        initials = "".join(w[0].upper() for w in window)
        if initials == acronym:
            return True
    return False


def _check_acronym_definition(text: str) -> Dict[str, Any]:
    """
    Check 17 – Acronym Definition.

    Every 3+ uppercase-letter acronym must have its definition (in parentheses)
    AT or BEFORE its very first occurrence in the document.

    Violation cases:
      (a) The acronym appears but is NEVER parenthetically defined anywhere.
      (b) The acronym appears and IS defined, but the definition appears
          AFTER the first standalone usage.

    The initials-matching heuristic (used for "Long Name (ACR)" pattern) checks
    whether the N preceding words have initials spelling the acronym, which
    distinguishes true definitions from incidental occurrences like "(WSN)" in
    a table cell header.
    """
    # ── Step 1: collect all positions where each acronym is defined ──────────
    defined_at: Dict[str, List[int]] = {}

    # Pattern 1: "(ACRONYM)" where the preceding words' initials match
    for m in _PAREN_ACRONYM_RE.finditer(text):
        acr = m.group(1)
        if acr in _SKIP_ACRONYMS:
            continue
        if _initials_match(text, m.start(), acr):
            defined_at.setdefault(acr, []).append(m.start())

    # Pattern 2: "ACRONYM (Full Definition Text)"
    for m in _DEFINE_AFTER_RE.finditer(text):
        acr = m.group(1)
        if acr in _SKIP_ACRONYMS:
            continue
        defined_at.setdefault(acr, []).append(m.start())

    # ── Step 2: find first standalone occurrence of every acronym ────────────
    first_occ: Dict[str, int] = {}
    for m in _ACRONYM_ALL_RE.finditer(text):
        acr = m.group(1)
        if acr not in first_occ:
            first_occ[acr] = m.start()

    # ── Step 3: check each acronym ───────────────────────────────────────────
    violations: List[Dict[str, Any]] = []
    for acr, first_pos in sorted(first_occ.items(), key=lambda x: x[1]):
        if acr in _SKIP_ACRONYMS:
            continue

        defs = defined_at.get(acr, [])

        if not defs:
            snippet = _snippet(text, first_pos, first_pos + len(acr))
            violations.append({
                "found":   acr,
                "snippet": snippet,
                "detail":  (
                    f"'{acr}' is never defined — add '(Full Name)' "
                    f"at its first use."
                ),
            })
        else:
            earliest_def = min(defs)
            if earliest_def > first_pos:
                snippet = _snippet(text, first_pos, first_pos + len(acr))
                violations.append({
                    "found":   acr,
                    "snippet": snippet,
                    "detail":  (
                        f"'{acr}' is used (char {first_pos}) before its "
                        f"definition (char {earliest_def}). "
                        f"Define at first occurrence."
                    ),
                })

        if len(violations) >= MAX_VIOLATIONS:
            break

    passed = not violations
    detail = (
        "All detected acronyms are defined at or before their first occurrence."
        if passed else
        f"{len(violations)} acronym(s) undefined or defined after first use. "
        f"First: {violations[0]['detail']}"
    )
    return {"passed": passed, "violations": violations, "detail": detail}


# ─────────────────────────────────────────────────────────────────────────────
# Check 18: En-dash for Ranges
# ─────────────────────────────────────────────────────────────────────────────

# Digit-hyphen-digit (plain ranges).
# Negative lookbehind (?<!\w) prevents matching the tail of a word like "co-10".
# Negative lookahead (?!\w|\.\d) prevents matching version strings like "3.14-5.0".
_HYPHEN_RANGE_RE = re.compile(
    r'(?<!\w)(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)(?!\w)'
)

# Double-dash used as a range separator: "10--20"
_DOUBLE_DASH_RE = re.compile(r'(\d)\s*--\s*(\d)')


def _check_en_dash_ranges(text: str) -> Dict[str, Any]:
    """
    Check 18 – En-dash for Ranges.

    A standard hyphen (-) or double-dash (--) between two numbers should be
    replaced with an en-dash (–, U+2013).

    Examples of violations: "10-20 kHz", "pages 3--7", "years 2018-2022".
    """
    violations: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    for m in _HYPHEN_RANGE_RE.finditer(text):
        key = m.group(0)
        if key in seen:
            continue
        seen.add(key)
        correct = f"{m.group(1)}\u2013{m.group(2)}"
        violations.append({
            "found":   key,
            "correct": correct,
            "snippet": _snippet(text, m.start(), m.end()),
            "detail":  f"Use en-dash (–) for range: '{key}' → '{correct}'",
        })
        if len(violations) >= MAX_VIOLATIONS:
            break

    for m in _DOUBLE_DASH_RE.finditer(text):
        key = m.group(0)
        if key in seen:
            continue
        seen.add(key)
        correct = f"{m.group(1)}\u2013{m.group(2)}"
        violations.append({
            "found":   key,
            "correct": correct,
            "snippet": _snippet(text, m.start(), m.end()),
            "detail":  f"Use en-dash (–) instead of double-hyphen: '{key}'",
        })
        if len(violations) >= MAX_VIOLATIONS:
            break

    passed = not violations
    detail = (
        "All number ranges correctly use en-dash (–)."
        if passed else
        f"{len(violations)} range(s) use hyphen/double-hyphen instead of en-dash. "
        f"First: {violations[0]['detail']}"
    )
    return {"passed": passed, "violations": violations, "detail": detail}


# ─────────────────────────────────────────────────────────────────────────────
# Check 19: Non-breaking Space for Units
# ─────────────────────────────────────────────────────────────────────────────

# Units matched as complete tokens (word-boundary protected).
# Deliberately excludes standalone "m" (metres) and "g" (grams) to minimise
# false positives from common abbreviations in prose.
_UNIT_ALTS = (
    # Time
    r"ms|µs|μs|ns|ps|fs"
    # Mass
    r"|kg|mg|µg|μg|ng"
    # Distance (longer forms first to beat greedy alternation)
    r"|km|cm|mm|nm|µm|μm|pm"
    # Frequency
    r"|MHz|GHz|kHz|THz|Hz"
    # Digital storage
    r"|KB|MB|GB|TB|kB|PB"
    # Power
    r"|kW|MW|GW|mW|µW|μW"
    # Voltage
    r"|kV|MV|mV|µV|μV"
    # Current
    r"|mA|µA|μA|nA"
    # Decibels
    r"|dBm|dBi|dB"
    # Chemical / biological
    r"|mmol|µmol|μmol|mol"
    # Volume (longer before shorter)
    r"|mL|µL|μL|nL|dL"
    # Temperature (with degree symbol)
    r"|°C|°F"
    # Angle / solid angle
    r"|rad|sr"
    # Pressure (longer before shorter)
    r"|kPa|MPa|GPa|atm|bar|Pa"
    # Data
    r"|Bytes?|bits?"
)

# Matches number + REGULAR ASCII space (U+0020) + unit.
# A non-breaking space (U+00A0 = \xa0) does NOT match \x20, so correctly
# formatted "10\xa0kg" is NOT flagged.
_REGULAR_SPACE_UNIT_RE = re.compile(
    rf"\b(\d+(?:\.\d+)?)\x20({_UNIT_ALTS})\b",
    re.IGNORECASE,
)


def _check_nonbreaking_space_units(text: str) -> Dict[str, Any]:
    """
    Check 19 – Non-breaking Space for Units.

    A non-breaking space (U+00A0) MUST be used between a number and its unit.
    A regular ASCII space (U+0020) is a violation.
    Already-correct non-breaking spaces (\xa0) are silently ignored.

    Note: PyMuPDF preserves \xa0 characters from the PDF, so the distinction
    is meaningful when the source document uses proper non-breaking spaces.
    """
    violations: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    for m in _REGULAR_SPACE_UNIT_RE.finditer(text):
        key = m.group(0)
        if key in seen:
            continue
        seen.add(key)
        correct = f"{m.group(1)}\xa0{m.group(2)}"  # U+00A0
        violations.append({
            "found":   key,
            "correct": correct,
            "snippet": _snippet(text, m.start(), m.end()),
            "detail":  (
                f"'{key}' uses a regular space; replace with "
                f"non-breaking space (U+00A0): '{correct}'"
            ),
        })
        if len(violations) >= MAX_VIOLATIONS:
            break

    passed = not violations
    detail = (
        "All number-unit pairs use non-breaking spaces (U+00A0)."
        if passed else
        f"{len(violations)} number-unit pair(s) use a regular space "
        f"instead of non-breaking space. "
        f"First: {violations[0]['detail']}"
    )
    return {"passed": passed, "violations": violations, "detail": detail}


# ─────────────────────────────────────────────────────────────────────────────
# Check 20: No Space for Percentages/Degrees
# ─────────────────────────────────────────────────────────────────────────────

# Any whitespace between the number and % is a violation ("10 %", "10  %").
_SPACE_BEFORE_PERCENT_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s+(%)"
)

# Any whitespace between the number and ° (with optional C/F/K unit) is a violation.
# Matches: "90 °C", "45 °", "90 °F", "273 °K"
_SPACE_BEFORE_DEGREE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s+(°(?:[CFK]?))"
)


def _check_no_space_percent_degree(text: str) -> Dict[str, Any]:
    """
    Check 20 – No Space for Percentages/Degrees.

    No space should appear between a number and a % or ° symbol.
    Correct: "10%", "90°C", "45°".
    Violations: "10 %", "90 °C", "45 °".
    """
    violations: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    for pattern in (_SPACE_BEFORE_PERCENT_RE, _SPACE_BEFORE_DEGREE_RE):
        for m in pattern.finditer(text):
            key = m.group(0)
            if key in seen:
                continue
            seen.add(key)
            correct = f"{m.group(1)}{m.group(2)}"
            violations.append({
                "found":   key,
                "correct": correct,
                "snippet": _snippet(text, m.start(), m.end()),
                "detail":  f"Remove space: '{key}' → '{correct}'",
            })
            if len(violations) >= MAX_VIOLATIONS:
                break

    passed = not violations
    detail = (
        "No incorrect spaces before % or ° symbols."
        if passed else
        f"{len(violations)} case(s) of space before %/°. "
        f"First: {violations[0]['detail']}"
    )
    return {"passed": passed, "violations": violations, "detail": detail}


# ─────────────────────────────────────────────────────────────────────────────
# Check 21: Double Spaces
# ─────────────────────────────────────────────────────────────────────────────

# Two or more ASCII spaces between non-whitespace characters (within a line).
# The lookbehind and lookahead exclude newlines and tabs so that indented
# paragraph starts and OCR line-margin artefacts are not flagged.
_DOUBLE_SPACE_RE = re.compile(
    r"(?<=[^\n\r\t ]) {2,}(?=[^\n\r\t ])"
)


def _check_double_spaces(text: str) -> Dict[str, Any]:
    """
    Check 21 – Double Spaces.

    Detects two or more consecutive ASCII spaces between non-whitespace
    characters within a line.  Excludes spaces at line-starts (OCR
    indentation artefacts) and tabs.
    """
    violations: List[Dict[str, Any]] = []

    for m in _DOUBLE_SPACE_RE.finditer(text):
        n_spaces = len(m.group(0))
        snippet = _snippet(text, m.start(), m.end())
        violations.append({
            "found":   f"{n_spaces} consecutive space(s)",
            "snippet": snippet,
            "detail":  f"Double/multiple space ({n_spaces}) found: …{snippet}…",
        })
        if len(violations) >= MAX_VIOLATIONS:
            break

    passed = not violations
    detail = (
        "No double spaces detected."
        if passed else
        f"{len(violations)} double-space occurrence(s). "
        f"First: {violations[0]['snippet']}"
    )
    return {"passed": passed, "violations": violations, "detail": detail}


# ─────────────────────────────────────────────────────────────────────────────
# Check 22: Consistent Punctuation Spacing
# ─────────────────────────────────────────────────────────────────────────────

# Sub-check A: space before comma or semicolon.
# Requires a letter or digit immediately before the space(s).
# Example violation: "result , however" or "Table 1 ;"
_SPACE_BEFORE_COMMA_RE = re.compile(r"(?<=[a-zA-Z0-9]) +[,;]")

# Sub-check B: no space after comma where a word immediately follows.
# Pattern: comma then letter + at least 1 more lowercase letter.
# Exclusions handled implicitly:
#   "[1,2,3]" → digit after comma → [a-zA-Z] won't match digits ✓
#   ",." → punctuation after comma → [a-zA-Z] won't match ✓
#   ",A" (single capital) → [a-z]{1,} after 'A' required → usually won't match ✓
_NO_SPACE_AFTER_COMMA_RE = re.compile(r",(?=[a-zA-Z][a-z]{1,})")

# Sub-check C: multiple ASCII spaces after comma, period, or semicolon
# (followed by a letter, so this is mid-sentence context).
_MULTI_SPACE_AFTER_PUNCT_RE = re.compile(r"(?<=[,\.;]) {2,}(?=[A-Za-z])")


def _check_punctuation_spacing(text: str) -> Dict[str, Any]:
    """
    Check 22 – Consistent Punctuation Spacing.

    Detects:
      A. Space(s) before a comma or semicolon.
      B. Missing space after a comma between words.
      C. Multiple spaces after a comma, period, or semicolon.
    """
    violations: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    # Sub-check A
    for m in _SPACE_BEFORE_COMMA_RE.finditer(text):
        key = f"sbc::{m.start() // 150}"
        if key in seen:
            continue
        seen.add(key)
        violations.append({
            "type":    "space_before_comma",
            "snippet": _snippet(text, m.start(), m.end()),
            "detail":  f"Space before comma/semicolon: '…{m.group(0)}…'",
        })
        if len(violations) >= MAX_VIOLATIONS:
            break

    # Sub-check B
    for m in _NO_SPACE_AFTER_COMMA_RE.finditer(text):
        key = f"nsac::{m.start() // 150}"
        if key in seen:
            continue
        seen.add(key)
        violations.append({
            "type":    "no_space_after_comma",
            "snippet": _snippet(text, m.start(), m.end()),
            "detail":  (
                f"Missing space after comma: "
                f"'…{_snippet(text, m.start() - 5, m.end() + 12)}…'"
            ),
        })
        if len(violations) >= MAX_VIOLATIONS:
            break

    # Sub-check C
    for m in _MULTI_SPACE_AFTER_PUNCT_RE.finditer(text):
        key = f"msp::{m.start() // 150}"
        if key in seen:
            continue
        seen.add(key)
        violations.append({
            "type":    "multiple_spaces_after_punct",
            "snippet": _snippet(text, m.start(), m.end()),
            "detail":  f"Multiple spaces after punctuation: '…{m.group(0)}…'",
        })
        if len(violations) >= MAX_VIOLATIONS:
            break

    passed = not violations
    detail = (
        "Punctuation spacing is consistent."
        if passed else
        f"{len(violations)} punctuation spacing issue(s). "
        f"First: {violations[0]['detail']}"
    )
    return {"passed": passed, "violations": violations, "detail": detail}


# ─────────────────────────────────────────────────────────────────────────────
# Check 23: Quote Style Consistency
# ─────────────────────────────────────────────────────────────────────────────

_STRAIGHT_DBL_RE    = re.compile(r'"')       # ASCII U+0022
_CURLY_LEFT_DBL_RE  = re.compile(r"\u201C")  # LEFT DOUBLE QUOTATION MARK
_CURLY_RIGHT_DBL_RE = re.compile(r"\u201D")  # RIGHT DOUBLE QUOTATION MARK
_CURLY_LEFT_SGL_RE  = re.compile(r"\u2018")  # LEFT SINGLE QUOTATION MARK
_CURLY_RIGHT_SGL_RE = re.compile(r"\u2019")  # RIGHT SINGLE QUOTATION MARK


def _check_quote_style_consistency(text: str) -> Dict[str, Any]:
    """
    Check 23 – Quote Style Consistency.

    Detects mixing of ASCII straight quotes (U+0022) and Unicode typographic
    curly/smart quotes (U+201C LEFT DOUBLE QUOTATION MARK, U+201D RIGHT DOUBLE
    QUOTATION MARK, U+2018, U+2019).

    A violation is raised when BOTH straight and curly double-quote characters
    are found in the same document, indicating inconsistent quote style.
    """
    has_straight_dbl = bool(_STRAIGHT_DBL_RE.search(text))
    has_curly_dbl    = bool(
        _CURLY_LEFT_DBL_RE.search(text) or _CURLY_RIGHT_DBL_RE.search(text)
    )
    has_curly_sgl    = bool(
        _CURLY_LEFT_SGL_RE.search(text) or _CURLY_RIGHT_SGL_RE.search(text)
    )

    violations: List[Dict[str, Any]] = []

    if has_straight_dbl and has_curly_dbl:
        violations.append({
            "type":   "mixed_double_quotes",
            "detail": (
                'Both straight double quotes (") and curly double quotes '
                "(\u201C\u201D) found in the document. "
                "Use one style consistently throughout."
            ),
        })

    # Flag when curly singles appear alongside straight doubles but no curly doubles —
    # suggests a mixed style from different text sources or pasted content.
    if has_curly_sgl and has_straight_dbl and not has_curly_dbl:
        violations.append({
            "type":   "mixed_single_and_straight_double",
            "detail": (
                "Curly single quotes (\u2018\u2019) and straight double "
                'quotes (") found together. '
                "Unify quote style throughout the document."
            ),
        })

    passed = not violations
    detail = (
        "Quote style is consistent throughout the document."
        if passed else
        f"Inconsistent quote style detected. {violations[0]['detail']}"
    )
    return {"passed": passed, "violations": violations, "detail": detail}


# ─────────────────────────────────────────────────────────────────────────────
# Check 24: English Spelling Consistency
# ─────────────────────────────────────────────────────────────────────────────

# Each tuple: (american_form, british_form).
# All comparisons are case-insensitive whole-word matches.
# Both the base form and common inflected forms are listed explicitly to
# ensure inflected usages (past tense, plural) are also caught.
_AM_BR_PAIRS: List[Tuple[str, str]] = [
    # ─ -ize vs -ise verbs (present tense) ───────────────────────────────────
    ("analyze",        "analyse"),
    ("organization",   "organisation"),
    ("organize",       "organise"),
    ("recognize",      "recognise"),
    ("optimize",       "optimise"),
    ("minimize",       "minimise"),
    ("maximize",       "maximise"),
    ("characterize",   "characterise"),
    ("utilize",        "utilise"),
    ("realize",        "realise"),
    ("emphasize",      "emphasise"),
    ("prioritize",     "prioritise"),
    ("parameterize",   "parameterise"),
    # ─ -ize vs -ise (past tense / participial) ───────────────────────────────
    ("analyzed",       "analysed"),
    ("organized",      "organised"),
    ("recognized",     "recognised"),
    ("optimized",      "optimised"),
    ("minimized",      "minimised"),
    ("maximized",      "maximised"),
    ("utilized",       "utilised"),
    ("realized",       "realised"),
    ("emphasized",     "emphasised"),
    ("characterized",  "characterised"),
    ("parameterized",  "parameterised"),
    # ─ -ize vs -ise (gerund / present participle) ────────────────────────────
    ("analyzing",      "analysing"),
    ("organizing",     "organising"),
    ("optimizing",     "optimising"),
    ("utilizing",      "utilising"),
    ("realizing",      "realising"),
    # ─ -or vs -our ──────────────────────────────────────────────────────────
    ("color",          "colour"),
    ("colors",         "colours"),
    ("behavior",       "behaviour"),
    ("behaviors",      "behaviours"),
    ("neighbor",       "neighbour"),
    ("labor",          "labour"),
    ("honor",          "honour"),
    ("humor",          "humour"),
    ("favor",          "favour"),
    ("flavor",         "flavour"),
    # ─ -er vs -re ────────────────────────────────────────────────────────────
    ("center",         "centre"),
    ("fiber",          "fibre"),
    ("meter",          "metre"),
    ("caliber",        "calibre"),
    # ─ -se vs -ce ────────────────────────────────────────────────────────────
    ("defense",        "defence"),
    ("offense",        "offence"),
    ("license",        "licence"),
    # ─ -log vs -logue ────────────────────────────────────────────────────────
    ("catalog",        "catalogue"),
    ("dialog",         "dialogue"),
    ("analog",         "analogue"),
    # ─ -gram vs -gramme ──────────────────────────────────────────────────────
    ("program",        "programme"),
    # ─ doubled consonant differences ─────────────────────────────────────────
    ("modeling",       "modelling"),
    ("traveling",      "travelling"),
    ("labeled",        "labelled"),
    ("fulfillment",    "fulfilment"),
    ("enrollment",     "enrolment"),
    ("skillful",       "skilful"),
    # ─ Other common pairs ────────────────────────────────────────────────────
    ("artifact",       "artefact"),
    ("artifacts",      "artefacts"),
    ("sulfur",         "sulphur"),
    ("gray",           "grey"),
    ("aging",          "ageing"),
    ("acknowledgment", "acknowledgement"),
]

# Pre-compile all patterns once at module load.
_SPELLING_PATTERNS: List[Tuple[re.Pattern, re.Pattern, str, str]] = [
    (
        re.compile(rf"\b{am}\b", re.IGNORECASE),
        re.compile(rf"\b{br}\b", re.IGNORECASE),
        am,
        br,
    )
    for am, br in _AM_BR_PAIRS
]


def _check_english_spelling_consistency(text: str) -> Dict[str, Any]:
    """
    Check 24 – English Spelling Consistency.

    Detects mixing of American English and British English spellings by
    scanning for a controlled set of known spelling-variant pairs.

    A violation is raised only when BOTH the American and British forms of
    the same word appear in the document.  If only one variant is used,
    the document is considered consistent (regardless of which dialect).
    """
    violations: List[Dict[str, Any]] = []

    for am_re, br_re, am_word, br_word in _SPELLING_PATTERNS:
        am_m = am_re.search(text)
        br_m = br_re.search(text)
        if am_m and br_m:
            violations.append({
                "american":   am_word,
                "british":    br_word,
                "am_snippet": _snippet(text, am_m.start(), am_m.end()),
                "br_snippet": _snippet(text, br_m.start(), br_m.end()),
                "detail": (
                    f"Mixed spelling: '{am_word}' (American) and '{br_word}' "
                    f"(British) both appear. Standardize to one variant."
                ),
            })
        if len(violations) >= MAX_VIOLATIONS:
            break

    passed = not violations
    detail = (
        "No American/British spelling inconsistencies detected."
        if passed else
        f"{len(violations)} spelling inconsistency(ies) found. "
        f"First: {violations[0]['detail']}"
    )
    return {"passed": passed, "violations": violations, "detail": detail}


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _snippet(text: str, start: int, end: int, window: int = 35) -> str:
    """Return ±window chars around [start:end], with whitespace collapsed."""
    s = max(0, start - window)
    e = min(len(text), end + window)
    return re.sub(r"\s+", " ", text[s:e]).strip()
