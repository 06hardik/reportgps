"""
syntax_grammar_checker.py
=========================
Checks 17-24: Typography, Syntax & Grammar validation.

Check 17 - Acronym Definition
Check 18 - En-dash for Ranges
Check 19 - Non-breaking Space for Units
Check 20 - No Space for Percentages/Degrees
Check 21 - Double Spaces
Check 22 - Consistent Punctuation Spacing
Check 23 - Quote Style Consistency
Check 24 - English Spelling Consistency

All checks are implemented using Unicode-aware Regular Expressions only.
No ML, NLP, or external libraries are used.

Integration:
  Called from orchestrator.py as Step 3d.
  Results stored under result["syntax_grammar_checks"].

Data used:
  full_text  - complete concatenated page text (all pages, includes references).
               Used by checks that need document-wide first-occurrence context
               (Check 17: Acronym, Check 23: Quote Style).
  body_text  - full_text with the references/bibliography section excluded.
               Used by all other checks to avoid flagging reference-list text.

Returns:
  Dict[str, Dict] keyed by check name; each value contains at minimum:
    {"passed": bool, "violations": List[dict], "detail": str}
"""

from __future__ import annotations

import bisect
import re
from typing import Any, Dict, List, Set, Tuple

MAX_VIOLATIONS = 25

# DOI strings - blanked out before en-dash scanning so hyphens inside
# DOIs (e.g. doi:10.1109/NET.2021.3050-3070) are never flagged as ranges.
# Covers: "doi:10.xxxx/...", "https://doi.org/10.xxxx/..."
_DOI_STRIP_RE = re.compile(
    r'(?:'
    r'(?:https?://)?doi\.org/'   # https://doi.org/ or doi.org/
    r'|doi:\s*'                   # doi: prefix
    r')'
    r'10\.\d{4,}[^\s]*',         # 10.NNNN/... rest of DOI path
    re.IGNORECASE,
)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _find_page(char_pos: int, page_offsets: List[int]) -> int:
    """
    Return the 1-based page number for a character offset into full_text.
    page_offsets[i] is the start offset of page i+1.
    """
    if not page_offsets:
        return 1
    idx = bisect.bisect_right(page_offsets, char_pos) - 1
    return max(1, idx + 1)


# -----------------------------------------------------------------------------
# Public entry point
# -----------------------------------------------------------------------------

def check_syntax_grammar(full_text: str, body_text: str, page_offsets: List[int] = None) -> Dict[str, Any]:
    """
    Main entry point for syntax and grammar checks.
    Uses body_text for checks that should exclude references/bibliography.
    """
    def _add_page(violations: List[Dict[str, Any]]) -> None:
        if not page_offsets:
            return
        for v in violations:
            if "first_pos" in v:
                v["page"] = _find_page(v["first_pos"], page_offsets)

    acronym = _check_acronym_definition(body_text)
    _add_page(acronym.get("violations", []))

    quote = _check_quote_style_consistency(body_text)
    _add_page(quote.get("violations", []))

    spelling = _check_english_spelling_consistency(body_text)
    _add_page(spelling.get("violations", []))

    endash = _check_en_dash_ranges(body_text)
    _add_page(endash.get("violations", []))

    nbsp = _check_nonbreaking_space_units(body_text)
    _add_page(nbsp.get("violations", []))

    pct_deg = _check_no_space_percent_degree(body_text)
    _add_page(pct_deg.get("violations", []))

    spaces = _check_double_spaces(body_text)
    _add_page(spaces.get("violations", []))

    punct = _check_punctuation_spacing(body_text)
    _add_page(punct.get("violations", []))

    return {
        "acronym_definition":           acronym,
        "quote_style_consistency":      quote,
        "english_spelling_consistency": spelling,
        "en_dash_ranges":               endash,
        "nonbreaking_space_units":      nbsp,
        "no_space_percent_degree":      pct_deg,
        "double_spaces":                spaces,
        "punctuation_spacing":          punct,
    }


# -----------------------------------------------------------------------------
# Check 17: Acronym Definition
# -----------------------------------------------------------------------------

# Acronyms so universally understood in scientific writing that they need no
# parenthetical definition in a research paper.
_SKIP_ACRONYMS: Set[str] = {
    # Internet / networking / computing
    "PDF", "URL", "HTTP", "HTTPS", "HTML", "CSS", "API", "XML", "JSON", "SQL",
    "TCP", "UDP", "IP", "DNS", "RAM", "ROM", "CPU", "GPU", "USB", "LAN", "WAN",
    "LED", "LCD", "OLED", "RGB", "HSV", "HSL", "GUI", "CLI", "SDK", "IDE",
    "FTP", "SSH", "SSL", "TLS", "VPN", "NAT", "MAC", "NIC", "SSD", "HDD",
    "OS", "VM", "IoT", "ICS",
    # Organisations / standards bodies
    "IEEE", "ACM", "ISO", "ANSI", "IETF", "ITU", "NIST",
    # Countries / regions
    "USA", "UK", "EU", "UN", "WHO",
    # Publishing / academic
    "DOI", "ISBN", "ISSN",
    # Signal processing / RF / comms
    "RMS", "SNR", "MIMO", "OFDM", "SINR", "BER", "QoS", "QoE",
    "CDMA", "FDMA", "TDMA", "WLAN", "WPAN", "WBAN",
    # Machine learning / AI — widely used without expansion in the field
    "AI", "ML", "DL", "NN", "ANN", "CNN", "RNN", "LSTM", "GRU", "GAN",
    "SVM", "KNN", "PCA", "NLP", "NLU", "NLG",
    # Optimisation and metaheuristics — standard in CS papers
    "PSO", "ACO", "GA", "DE", "SA", "TS",
    # Statistics / evaluation metrics — widely used without expansion
    "RMSE", "MAE", "MSE", "MAPE", "MASE", "AUC", "ROC", "MAP",
    "FPR", "TPR", "FNR", "TNR", "TP", "TN", "FP", "FN",
    "ACC", "AUC",
    # Cloud / distributed systems
    "SaaS", "PaaS", "IaaS", "SOA", "REST", "RPC",
    "VM", "VMs",
    # Time
    "UTC", "GMT",
    # Common statistical / math shorthand (not acronyms per se)
    "MAX", "MIN", "AVG", "STD",
    # Common English words that appear all-caps in headings / captions
    "FOR", "AND", "THE", "NOT", "ALL", "TWO", "ONE", "TEN",
    "NEW", "OLD", "LAB", "FIG", "TAB", "SEC", "EQN", "REF", "APP",
    "VRP", "VRPTW", "TSP",          # classic combinatorial problems
    "ABC",                           # Artificial Bee Colony (classic metaheuristic)
    # IEEE / computer-science shorthand used without expansion in the field
    "NaN", "INF",
}

# Pattern 1: "(ACRONYM)" - acronym inside parentheses after an expanded form.
# e.g. "Wireless Sensor Network (WSN)"
_PAREN_ACRONYM_RE = re.compile(r'\(([A-Z]{3,})\)')

# Pattern 2: "ACRONYM (Full Definition Text)" - acronym written first,
# followed by its expansion in parentheses.
# The definition content is more permissive: allows letters, spaces,
# hyphens, commas, periods, slashes, digits, and apostrophes so that
# definitions like "CPU (Central Processing Unit, 32-bit)" are accepted.
# Minimum 3 chars, maximum 80 chars.
_DEFINE_AFTER_RE = re.compile(
    r'\b([A-Z]{3,})\s+\([a-zA-Z][a-zA-Z0-9\s\-,./\']{3,80}\)'
)

# All standalone 3+ uppercase-letter sequences (the "all acronyms" scanner).
_ACRONYM_ALL_RE = re.compile(r'\b([A-Z]{3,})\b')



def _initials_match(text: str, paren_start: int, acronym: str) -> bool:
    """
    Return True if any window of len(acronym) consecutive alpha-starting words
    in the 600 chars preceding *paren_start* has initials that spell *acronym*.

    Multi-column PDFs assembled by PyMuPDF often interleave column text, so
    the expanded form of an acronym might appear quite far from the opening
    parenthesis in the extracted text string.  We use a 600-char lookback
    (doubled from the original 200, upgraded from 400) and a sliding window
    of n+15 candidate words.

    Hyphenated compound words (e.g. "Self-Learning" for SL) are split on
    hyphens so each hyphen-separated part contributes its initial letter.

    Example: "Wireless Sensor Network (WSN)" -> W.S.N -> initials = WSN  OK
    Example: "use of Wireless Sensor Network technology (WSN)" -> OK
    Counter: "See Figure 3 (WSN)" -> alpha-words S.F -> too short for 3-char WSN
    """
    n = len(acronym)
    pre = text[max(0, paren_start - 600): paren_start]

    # Split on whitespace then further split hyphenated tokens so that
    # "Self-Learning" contributes two initials: S, L.
    raw_tokens = pre.split()
    words = []
    for tok in raw_tokens:
        # strip leading punctuation from each token
        parts = tok.split('-')
        for p in parts:
            p = p.strip(".,;:\"'()")
            if p and p[0].isalpha():
                words.append(p)

    if len(words) < n:
        return False
    # Slide a window of size n over the last (n + 15) candidate words.
    start_i = max(0, len(words) - n - 15)
    for i in range(start_i, len(words) - n + 1):
        window = words[i: i + n]
        initials = "".join(w[0].upper() for w in window)
        if initials == acronym:
            return True
    return False



def _check_acronym_definition(text: str) -> Dict[str, Any]:
    """
    Check 17 - Acronym Definition.

    Every 3+ uppercase-letter acronym must have its definition (in parentheses)
    AT or BEFORE its very first occurrence in the document.

    Violation cases:
      (a) The acronym appears but is NEVER parenthetically defined anywhere.
      (b) The acronym appears and IS defined, but the definition appears
          AFTER the first standalone usage.

    BUG FIXES:
      1. _initials_match window expanded from n+3 to n+10 words and lookback
         from 200 to 400 chars to catch definitions where filler words
         separate the expanded form from the parenthesis.
      2. _DEFINE_AFTER_RE made more permissive (allows digits/commas/slashes
         inside the definition text).
      3. When building first_occ (Step 2), positions that fall INSIDE a
         parenthetical "(ACR)" span are skipped so the acronym inside its
         own definition is not treated as the first standalone usage.
    """
    # -- Step 1: collect all positions where each acronym is defined ----------
    defined_at: Dict[str, List[int]] = {}

    # Collect the spans of every "(ACR)" occurrence so we can exclude those
    # positions from the first-occurrence scan in Step 2.
    paren_def_spans: List[tuple] = []  # (start, end) of each "(ACR)" match

    # Pattern 1: "(ACRONYM)" where the preceding words' initials match
    for m in _PAREN_ACRONYM_RE.finditer(text):
        acr = m.group(1)
        if acr in _SKIP_ACRONYMS:
            continue
        # Record the span regardless of initials match so Step 2 can skip it.
        paren_def_spans.append((m.start(), m.end()))
        if _initials_match(text, m.start(), acr):
            defined_at.setdefault(acr, []).append(m.start())

    # Pattern 2: "ACRONYM (Full Definition Text)"
    for m in _DEFINE_AFTER_RE.finditer(text):
        acr = m.group(1)
        if acr in _SKIP_ACRONYMS:
            continue
        defined_at.setdefault(acr, []).append(m.start())

    # -- Step 2: find first standalone occurrence of every acronym ------------
    # Skip positions inside a parenthetical "(ACR)" span so that the acronym
    # inside its own definition is not treated as the first standalone use.
    paren_def_spans.sort()

    def _in_paren_def(pos: int) -> bool:
        """Return True if pos falls inside any recorded '(ACR)' span."""
        for span_start, span_end in paren_def_spans:
            if span_start <= pos < span_end:
                return True
            if span_start > pos:
                break
        return False

    first_occ: Dict[str, int] = {}
    for m in _ACRONYM_ALL_RE.finditer(text):
        acr = m.group(1)
        if acr in first_occ:
            continue
        # Skip the acronym if it falls inside a "(ACR)" parenthetical;
        # we want the first *standalone* usage, not the definition instance.
        if _in_paren_def(m.start()):
            continue
        first_occ[acr] = m.start()

    # -- Step 3: check each acronym -------------------------------------------
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
                "first_pos": first_pos,
                "detail":  (
                    f"'{acr}' is never defined -- add '(Full Name)' "
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
                    "first_pos": first_pos,
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


# -----------------------------------------------------------------------------
# Check 18: En-dash for Ranges
# -----------------------------------------------------------------------------

# Digit-hyphen-digit (plain ranges).
# Negative lookbehind (?<!\w) prevents matching the tail of a word like "co-10".
# Negative lookahead (?!\w|\.d) prevents matching version strings like "3.14-5.0".
_HYPHEN_RANGE_RE = re.compile(
    r'(?<!\w)(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)(?!\w)'
)

# Double-dash used as a range separator: "10--20"
_DOUBLE_DASH_RE = re.compile(r'(\d)\s*--\s*(\d)')


def _check_en_dash_ranges(text: str) -> Dict[str, Any]:
    """
    Check 18 - En-dash for Ranges.

    A standard hyphen (-) or double-dash (--) between two numbers should be
    replaced with an en-dash (U+2013).

    BUG FIX: DOI strings (e.g. doi:10.1109/NET.2021.3050-3070) are now
    blanked out before scanning so hyphens in DOI paths are never flagged as
    numeric ranges.  The DOI of the paper being scanned (which may appear in
    headers, footers, or the abstract) is now completely excluded.

    Examples of violations: "10-20 kHz", "pages 3--7", "years 2018-2022".
    """
    # Strip DOI strings first - replace each matched DOI with spaces of the
    # same length so all other character positions remain intact for snippet
    # extraction from the original text.
    scan_text = _DOI_STRIP_RE.sub(lambda m: ' ' * len(m.group(0)), text)

    # Strip citation brackets like [23-25], [1, 2], [3-5] — these are valid
    # citation syntax, not range formatting errors.
    scan_text = re.sub(r'\[[^\]]{1,40}\]', lambda m: ' ' * len(m.group(0)), scan_text)

    violations: List[Dict[str, Any]] = []
    seen: Set[str] = set()


    for m in _HYPHEN_RANGE_RE.finditer(scan_text):
        key = m.group(0)
        if key in seen:
            continue
        seen.add(key)
        correct = f"{m.group(1)}\u2013{m.group(2)}"
        violations.append({
            "found":   key,
            "correct": correct,
            # Use original text for the snippet so the context is readable.
            "snippet": _snippet(text, m.start(), m.end()),
            "detail":  f"Use en-dash (\u2013) for range: '{key}' -> '{correct}'",
        })
        if len(violations) >= MAX_VIOLATIONS:
            break

    for m in _DOUBLE_DASH_RE.finditer(scan_text):
        key = m.group(0)
        if key in seen:
            continue
        seen.add(key)
        correct = f"{m.group(1)}\u2013{m.group(2)}"
        violations.append({
            "found":   key,
            "correct": correct,
            "snippet": _snippet(text, m.start(), m.end()),
            "detail":  f"Use en-dash (\u2013) instead of double-hyphen: '{key}'",
        })
        if len(violations) >= MAX_VIOLATIONS:
            break

    passed = not violations
    detail = (
        "All number ranges correctly use en-dash (\u2013)."
        if passed else
        f"{len(violations)} range(s) use hyphen/double-hyphen instead of en-dash. "
        f"First: {violations[0]['detail']}"
    )
    return {"passed": passed, "violations": violations, "detail": detail}


# -----------------------------------------------------------------------------
# Check 19: Non-breaking Space for Units
# -----------------------------------------------------------------------------

# Units matched as complete tokens (word-boundary protected).
# Deliberately excludes standalone "m" (metres) and "g" (grams) to minimise
# false positives from common abbreviations in prose.
_UNIT_ALTS = (
    # Time
    r"ms|\xb5s|\u03bcs|ns|ps|fs"
    # Mass
    r"|kg|mg|\xb5g|\u03bcg|ng"
    # Distance (longer forms first to beat greedy alternation)
    r"|km|cm|mm|nm|\xb5m|\u03bcm|pm"
    # Frequency
    r"|MHz|GHz|kHz|THz|Hz"
    # Digital storage
    r"|KB|MB|GB|TB|kB|PB"
    # Power
    r"|kW|MW|GW|mW|\xb5W|\u03bcW"
    # Voltage
    r"|kV|MV|mV|\xb5V|\u03bcV"
    # Current
    r"|mA|\xb5A|\u03bcA|nA"
    # Decibels
    r"|dBm|dBi|dB"
    # Chemical / biological
    r"|mmol|\xb5mol|\u03bcmol|mol"
    # Volume (longer before shorter)
    r"|mL|\xb5L|\u03bcL|nL|dL"
    # Temperature (with degree symbol)
    r"|\xb0C|\xb0F"
    # Angle / solid angle
    r"|rad|sr"
    # Pressure (longer before shorter)
    r"|kPa|MPa|GPa|atm|bar|Pa"
    # Data
    r"|Bytes?|bits?"
)

# Matches number directly adjacent to a unit with NO space at all.
#
# BUG FIX: The previous pattern matched number + ASCII space + unit, which
# produced 100% false positives because PyMuPDF does not reliably preserve
# U+00A0 (non-breaking space) from the PDF source -- it often emits a regular
# ASCII space (U+0020) for both types.  The new pattern only matches the
# genuinely bad case: number immediately adjacent to unit with NO space at all
# (e.g. "10kg", "3ms", "100MHz"), which is unambiguously wrong regardless of
# space type.
#
# NOTE: re.IGNORECASE is intentionally NOT used -- unit symbols are
# case-sensitive (mW != MW, ms != MS).  Without IGNORECASE, single-letter
# suffixes like 'a', 'b', 'g' no longer incorrectly match figure labels.
_MISSING_SPACE_UNIT_RE = re.compile(
    rf"\b(\d+(?:\.\d+)?)({_UNIT_ALTS})(?![a-zA-Z0-9])"
)


def _check_nonbreaking_space_units(text: str) -> Dict[str, Any]:
    """
    Check 19 - Non-breaking Space for Units.

    The canonical rule is that a non-breaking space (U+00A0) must be used
    between a number and its unit.  However, PyMuPDF does not reliably
    preserve U+00A0; it often emits a regular ASCII space (U+0020) for both
    types.  Checking for \\x20 therefore flags every correctly-formatted
    "10 kg" pair, producing 100% false positives.

    This check instead flags only the genuinely bad case: a number immediately
    adjacent to its unit with NO space at all (e.g. "10kg", "3ms", "100MHz").
    Those are unambiguously wrong regardless of space type.
    """
    violations: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    for m in _MISSING_SPACE_UNIT_RE.finditer(text):
        key = m.group(0)
        if key in seen:
            continue
        seen.add(key)
        # Suggest non-breaking space as the correct fix
        correct = f"{m.group(1)}\xa0{m.group(2)}"  # U+00A0
        violations.append({
            "found":   key,
            "correct": correct,
            "snippet": _snippet(text, m.start(), m.end()),
            "detail":  (
                f"'{key}' has no space between number and unit; "
                f"insert a non-breaking space (U+00A0): '{correct}'"
            ),
        })
        if len(violations) >= MAX_VIOLATIONS:
            break

    passed = not violations
    detail = (
        "All number-unit pairs have a space between the number and unit."
        if passed else
        f"{len(violations)} number-unit pair(s) are missing a space. "
        f"First: {violations[0]['detail']}"
    )
    return {"passed": passed, "violations": violations, "detail": detail}


# -----------------------------------------------------------------------------
# Check 20: No Space for Percentages/Degrees
# -----------------------------------------------------------------------------

# Any whitespace between the number and % is a violation ("10 %", "10  %").
_SPACE_BEFORE_PERCENT_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s+(%)"
)

# Any whitespace between the number and degree symbol (with optional C/F/K unit).
# Matches: "90 \xb0C", "45 \xb0", "90 \xb0F", "273 \xb0K"
_SPACE_BEFORE_DEGREE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s+(\xb0(?:[CFK]?))"
)


def _check_no_space_percent_degree(text: str) -> Dict[str, Any]:
    """
    Check 20 - No Space for Percentages/Degrees.

    No space should appear between a number and a % or degree symbol.
    Correct: "10%", "90\xb0C", "45\xb0".
    Violations: "10 %", "90 \xb0C", "45 \xb0".
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
                "detail":  f"Remove space: '{key}' -> '{correct}'",
            })
            if len(violations) >= MAX_VIOLATIONS:
                break

    passed = not violations
    detail = (
        "No incorrect spaces before % or \xb0 symbols."
        if passed else
        f"{len(violations)} case(s) of space before %/\xb0. "
        f"First: {violations[0]['detail']}"
    )
    return {"passed": passed, "violations": violations, "detail": detail}


# -----------------------------------------------------------------------------
# Check 21: Double Spaces
# -----------------------------------------------------------------------------

# DESIGN DECISION: PDF justified text extracted via PyMuPDF with the
# TEXT_PRESERVE_WHITESPACE flag consistently produces 2-3 spaces between
# ordinary words in justified paragraphs — this is a rendering artifact, not
# an authoring error.  Flagging those produces dozens of false positives per
# page.
#
# Genuine double-space authoring errors (e.g. the author accidentally pressed
# Space twice) typically manifest as exactly 2 spaces in manuscripts written
# in word processors.  However, because we cannot distinguish these from the
# 2-space PDF artifact, we raise the threshold to 4+ consecutive spaces.
# A run of 4+ spaces between two non-whitespace characters is almost never
# a PDF rendering artifact — it is a genuine alignment/formatting error.
#
# Additionally, spaces inside citation brackets like [23, 25] or inside
# parentheses are excluded to avoid false-flagging reference lists.
_DOUBLE_SPACE_RE = re.compile(
    r"(?<=[^\n\r\t ]) {4,}(?=[^\n\r\t ])"
)

# Pattern to detect if a double-space match falls inside [...] or (...)
_INSIDE_BRACKETS_RE = re.compile(r"[\[(][^\]\)]*  +[^\]\)]*[\]\)]")


def _check_double_spaces(text: str) -> Dict[str, Any]:
    """
    Check 21 - Double Spaces.

    Detects 4 or more consecutive ASCII spaces between non-whitespace
    characters within a line.  The threshold is 4 (not 2) because PyMuPDF's
    TEXT_PRESERVE_WHITESPACE flag produces 2-3 spaces between every word in
    justified PDF text — those are rendering artifacts, not author errors.
    Runs of 4+ spaces reliably indicate genuine formatting problems.
    """
    # Pre-process: collapse citation brackets like [23-25] or [1, 2, 3] to a
    # single space so spaces INSIDE the brackets don't trigger the check.
    clean = re.sub(r'\[[^\]]{1,40}\]', ' ', text)

    violations: List[Dict[str, Any]] = []

    for m in _DOUBLE_SPACE_RE.finditer(clean):
        n_spaces = len(m.group(0))
        snippet = _snippet(text, m.start(), m.end())  # snippet from original
        violations.append({
            "found":   f"{n_spaces} consecutive space(s)",
            "snippet": snippet,
            "detail":  f"Double/multiple space ({n_spaces}) found: ...{snippet}...",
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


# -----------------------------------------------------------------------------
# Check 22: Consistent Punctuation Spacing
# -----------------------------------------------------------------------------

# Sub-check A: space before comma or semicolon.
# Requires a letter or digit immediately before the space(s).
# Example violation: "result , however" or "Table 1 ;"
_SPACE_BEFORE_COMMA_RE = re.compile(r"(?<=[a-zA-Z0-9]) +[,;]")

# Sub-check B: no space after comma where a word immediately follows.
# Pattern: comma then letter + at least 1 more lowercase letter.
_NO_SPACE_AFTER_COMMA_RE = re.compile(r",(?=[a-zA-Z][a-z]{1,})")

# Sub-check C: multiple ASCII spaces after comma, period, or semicolon
# (followed by a letter, so this is mid-sentence context).
_MULTI_SPACE_AFTER_PUNCT_RE = re.compile(r"(?<=[,\.;]) {2,}(?=[A-Za-z])")


def _check_punctuation_spacing(text: str) -> Dict[str, Any]:
    """
    Check 22 - Consistent Punctuation Spacing.

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
            "detail":  f"Space before comma/semicolon: '...{m.group(0)}...'",
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
                f"'...{_snippet(text, m.start() - 5, m.end() + 12)}...'"
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
            "detail":  f"Multiple spaces after punctuation: '...{m.group(0)}...'",
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


# -----------------------------------------------------------------------------
# Check 23: Quote Style Consistency
# -----------------------------------------------------------------------------

_STRAIGHT_DBL_RE    = re.compile(r'"')       # ASCII U+0022
_CURLY_LEFT_DBL_RE  = re.compile(r"\u201C")  # LEFT DOUBLE QUOTATION MARK
_CURLY_RIGHT_DBL_RE = re.compile(r"\u201D")  # RIGHT DOUBLE QUOTATION MARK
_CURLY_LEFT_SGL_RE  = re.compile(r"\u2018")  # LEFT SINGLE QUOTATION MARK
_CURLY_RIGHT_SGL_RE = re.compile(r"\u2019")  # RIGHT SINGLE QUOTATION MARK


def _check_quote_style_consistency(text: str) -> Dict[str, Any]:
    """
    Check 23 - Quote Style Consistency.

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

    # Flag when curly singles appear alongside straight doubles but no curly
    # doubles -- suggests a mixed style from different text sources.
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


# -----------------------------------------------------------------------------
# Check 24: English Spelling Consistency
# -----------------------------------------------------------------------------

# Each tuple: (american_form, british_form).
# All comparisons are case-insensitive whole-word matches.
_AM_BR_PAIRS: List[Tuple[str, str]] = [
    # -ize vs -ise verbs (present tense)
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
    # -ize vs -ise (past tense / participial)
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
    # -ize vs -ise (gerund / present participle)
    ("analyzing",      "analysing"),
    ("organizing",     "organising"),
    ("optimizing",     "optimising"),
    ("utilizing",      "utilising"),
    ("realizing",      "realising"),
    # -or vs -our
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
    # -er vs -re
    ("center",         "centre"),
    ("fiber",          "fibre"),
    ("meter",          "metre"),
    ("caliber",        "calibre"),
    # -se vs -ce
    ("defense",        "defence"),
    ("offense",        "offence"),
    ("license",        "licence"),
    # -log vs -logue
    ("catalog",        "catalogue"),
    ("dialog",         "dialogue"),
    ("analog",         "analogue"),
    # -gram vs -gramme
    ("program",        "programme"),
    # doubled consonant differences
    ("modeling",       "modelling"),
    ("traveling",      "travelling"),
    ("labeled",        "labelled"),
    ("fulfillment",    "fulfilment"),
    ("enrollment",     "enrolment"),
    ("skillful",       "skilful"),
    # Other common pairs
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
    Check 24 - English Spelling Consistency.

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


# -----------------------------------------------------------------------------
# Helper
# -----------------------------------------------------------------------------

def _snippet(text: str, start: int, end: int, window: int = 35) -> str:
    """Return +/-window chars around [start:end], with whitespace collapsed."""
    s = max(0, start - window)
    e = min(len(text), end + window)
    return re.sub(r"\s+", " ", text[s:e]).strip()
