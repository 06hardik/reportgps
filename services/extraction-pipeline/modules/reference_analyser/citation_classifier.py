"""
Citation Style Identifier
=========================
Purely rule-based system to identify which of the 5 major citation styles
a reference list entry belongs to:
  IEEE | APA | MLA | Harvard | Vancouver

Input  : a single reference list entry string
Output : predicted style + list of matched rules + scores per style
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RuleMatch:
    rule_id: str
    description: str
    style: str
    weight: float


@dataclass
class ClassificationResult:
    predicted_style: str
    confidence: str          # HIGH / MEDIUM / LOW
    scores: Dict[str, float]
    matched_rules: List[RuleMatch]

    def __str__(self):
        lines = [
            f"\n{'='*60}",
            f"  PREDICTED STYLE : {self.predicted_style}",
            f"  CONFIDENCE      : {self.confidence}",
            f"{'='*60}",
            "\n  SCORES PER STYLE:",
        ]
        for style, score in sorted(self.scores.items(), key=lambda x: -x[1]):
            bar = "█" * int(score * 2)
            lines.append(f"    {style:<12} {score:5.1f}  {bar}")

        lines.append("\n  MATCHED RULES:")
        for rm in sorted(self.matched_rules, key=lambda x: -x.weight):
            lines.append(f"    [{rm.style:<10}] +{rm.weight:.1f}  {rm.rule_id}")
            lines.append(f"               → {rm.description}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------

def classify(entry: str) -> ClassificationResult:
    """
    Classify a single reference list entry string into one of the 6 styles.
    Returns a ClassificationResult with scores and matched rules.
    """
    text = entry.strip()
    matched: List[RuleMatch] = []

    def add(rule_id, description, style, weight):
        matched.append(RuleMatch(rule_id, description, style, weight))

    # ------------------------------------------------------------------ #
    #  HARD FILTERS — if a definitive signal is found, restrict scoring   #
    #  to only the styles that can possibly match. All other styles are   #
    #  eliminated before any rules fire.                                  #
    # ------------------------------------------------------------------ #

    all_styles = {"IEEE", "APA", "MLA", "Harvard", "Vancouver"}

    # Determine which styles are allowed (None means all are allowed)
    allowed_styles: set = set(all_styles)  # start open, narrow down below

    # HF-01: [n] at start → IEEE or Vancouver only
    if re.match(r'^\[\d+\]', text):
        allowed_styles &= {"IEEE", "Vancouver"}

    # HF-02: Year;Volume(Issue):pages → Vancouver only
    if re.search(r'\d{4};\d+\(\d+\):\d+', text):
        allowed_styles &= {"Vancouver"}

    # HF-03: https://doi.org/ full URL → APA only.
    if re.search(r'https://doi\.org/10\.\d{4}', text):
        allowed_styles &= {"APA"}

    # HF-A: "[cited DATE]" — NLM/Vancouver bibliography syntax → Vancouver only.
    if re.search(r'\[cited\s+\d{4}\b', text, re.IGNORECASE):
        allowed_styles &= {"Vancouver"}

    # HF-B: "[Internet]" medium-type tag → Vancouver only.
    if re.search(r'\[Internet\]', text, re.IGNORECASE):
        allowed_styles &= {"Vancouver"}

    # HF-C: "Publisher; YEAR" — semicolon separating publisher from year → Vancouver only.
    if re.search(r'[A-Za-z]\s*;\s*\d{4}[.\s]', text):
        allowed_styles &= {"Vancouver"}

    # HF-07: NLM author format Surname AB, (no periods/spaces between initials) → Vancouver only
    if re.search(r'\b[A-Z][a-z]+\s+[A-Z]{2,4},\s+[A-Z][a-z]+\s+[A-Z]{1,4}[,.]', text):
        allowed_styles &= {"Vancouver"}

    # HF-08: "Retrieved from" → APA only
    if re.search(r'\bRetrieved\b.{0,30}\bfrom\b', text, re.IGNORECASE):
        allowed_styles &= {"APA"}

    # HF-09: Plain number at start "1. Smith" (no brackets) → Vancouver only
    if re.match(r'^\d+\.\s+[A-Z]', text) and not re.match(r'^\[\d+\]', text):
        allowed_styles &= {"Vancouver"}

    # HF-D: Entry starts with inverted full name "Surname, Firstname" → excludes Vancouver
    if (re.match(r'^[A-Z][a-z]+,\s+[A-Z][a-z]{2,}', text) and
            not re.match(r'^\[\d+\]', text)):
        allowed_styles -= {"Vancouver"}

    # HF-10: Ampersand + inverted name with initials "& Surname, I." → APA only
    if re.search(r'&\s+[A-Z][a-z]+,\s+[A-Z]\.', text):
        allowed_styles &= {"APA"}

    # HF-11: Quoted article title + vol. + no. together → MLA only
    if (re.search(r'"[^"]{5,}"', text) and
            re.search(r'\bvol\.\s*\d+', text, re.IGNORECASE) and
            re.search(r'\bno\.\s*\d+', text, re.IGNORECASE)):
        allowed_styles &= {"MLA"}

    # HF-12: Uninverted full name at start → MLA only.
    _hf12_fired = False
    if not re.match(r'^\[\d+\]', text):
        _hf12 = re.match(
            r'^([A-Z][\w\-]+)'
            r'(?:\s+[A-Z]\.?)?\s+'
            r'([A-Z][\w\-]+)\.\s*'
            r'("|\b[A-Z])',
            text
        )
        if _hf12:
            first_token = _hf12.group(0)
            if ',' not in first_token:
                allowed_styles &= {"MLA"}
                _hf12_fired = True

    # HF-13: Quoted title + URL + Accessed keyword, no [n] at start → MLA only
    _hf13_has_quoted_title  = bool(re.search(r'"[^"]{5,}"', text))
    _hf13_has_url           = bool(re.search(r'https?://|www\.', text))
    _hf13_has_access        = bool(re.search(r'\b(Accessed|Retrieved)\b', text, re.IGNORECASE))
    _hf13_no_bracket        = not re.match(r'^\[\d+\]', text)
    _hf13_no_available      = not re.search(r'Available (at|from):', text, re.IGNORECASE)
    _hf13_fired = False
    if _hf13_has_quoted_title and _hf13_has_url and _hf13_has_access and _hf13_no_bracket and _hf13_no_available:
        allowed_styles &= {"MLA"}
        _hf13_fired = True

    # HF-14: Inverted name with double-period + Patent keyword → MLA only.
    if re.match(r'^[A-Z][a-z]+,\s+[A-Z]\.\.\s', text) and re.search(r'\bPatent\b', text, re.IGNORECASE):
        allowed_styles &= {"MLA"}

    # HF-15: Standards/specification code present
    _hf15_p1 = r'\b(?:ISO|IEC|ANSI(?:/\w+)?|AS/NZS|NZS|ASTM|IETF|RFC)\b[\s/\w.\-]*\d{4,}'
    _hf15_p2 = r'\b(?:W3C|WCAG|IEEE\s+\d{3})\b'
    _hf15_has_standards_code = bool(re.search(
        '(?:' + _hf15_p1 + '|' + _hf15_p2 + ')', text, re.IGNORECASE
    ))
    if _hf15_has_standards_code and not re.match(r'^\[\d+\]', text):
        allowed_styles -= {"IEEE"}

    # HF-16: Compound/org name + (Year) mid-entry → Harvard only.
    if not re.match(r'^\[\d+\]', text):
        _hf16_year_m = re.search(r'\(\d{4}\)', text)
        if _hf16_year_m:
            _hf16_pre = text[:_hf16_year_m.start()]
            if ',' not in _hf16_pre and len(_hf16_pre) < len(text) * 0.45:
                if not re.search(r'\(\d{4}\)\.\s+[A-Z]', text):
                    allowed_styles &= {"Harvard"}

    # If hard filters produced empty set (contradictory signals), fall back to all styles
    if not allowed_styles:
        allowed_styles = set(all_styles)

    # Wrap add() so rules for eliminated styles are silently ignored
    _add_unrestricted = add
    def add(rule_id, description, style, weight):  # noqa: F811
        if style in allowed_styles:
            _add_unrestricted(rule_id, description, style, weight)

    # ------------------------------------------------------------------ #
    #  IEEE RULES                                                          #
    # ------------------------------------------------------------------ #

    if re.match(r'^\[\d+\]', text):
        add("IEEE-01", "Entry starts with [n] numeric label", "IEEE", 10.0)

    if re.search(r'"[^"]{10,}"', text):
        add("IEEE-02", "Article/chapter title enclosed in double quotes", "IEEE", 6.0)

    if re.search(r'\b[A-Z][a-z]+\.\s+[A-Z]', text):
        add("IEEE-03", "Abbreviated journal/conference title detected (Cap-word. Cap-word)", "IEEE", 1.5)

    if re.search(r'\b(IEEE|Trans\.|Proc\.|Conf\.|Lett\.|Mag\.)\b', text):
        add("IEEE-04", "IEEE-specific publication keyword (IEEE/Trans./Proc./Conf./Lett./Mag.)", "IEEE", 4.0)

    if re.search(r'\[\d+,\s*pp?\.\s*\d+', text):
        add("IEEE-05", "IEEE inline page reference pattern [n, p. X]", "IEEE", 5.0)

    if re.search(r'([A-Z]\.\s*){2,}.*et al\.', text, re.IGNORECASE):
        add("IEEE-06", "et al. used (consistent with IEEE 6-author truncation rule)", "IEEE", 2.0)

    if re.search(r'\bdoi:\s*10\.\d{4}', text, re.IGNORECASE):
        add("IEEE-07", "DOI in 'doi: 10.xxxx' format (IEEE/Vancouver style)", "IEEE", 2.0)

    # ------------------------------------------------------------------ #
    #  APA RULES                                                           #
    # ------------------------------------------------------------------ #

    if re.search(r'[A-Z][a-z]+,\s+[A-Z]\.\s*[A-Z]?\.\s*[\(&]?\s*\(?\d{4}\)?', text):
        add("APA-01", "Author initials + (Year) pattern directly after author name", "APA", 8.0)

    if re.search(r'&\s+[A-Z][a-z]+,\s+[A-Z]\.', text):
        add("APA-02", "Ampersand (&) used before final author (APA convention)", "APA", 6.0)

    if re.search(r'https://doi\.org/10\.\d{4}', text):
        add("APA-03", "DOI formatted as full URL https://doi.org/... (APA 7th edition)", "APA", 7.0)

    title_match = re.search(r'\(?\d{4}\)?\.?\s+([A-Z][^.!?]{20,}?)[\.\n]', text)
    if title_match:
        title_candidate = title_match.group(1)
        words = title_candidate.split()
        if len(words) > 4:
            mid_caps = sum(1 for w in words[1:] if w[0].isupper() and not w.isupper())
            if mid_caps <= 2:
                add("APA-04", "Article title appears to use sentence case (APA style)", "APA", 4.0)

    if re.search(r'\bRetrieved\b.{0,30}\bfrom\b', text, re.IGNORECASE):
        add("APA-07", "'Retrieved ... from' web citation pattern (APA format)", "APA", 7.0)

    if re.search(r'\bAccessed\b.{0,30}\bfrom\b', text, re.IGNORECASE):
        add("APA-07B", "'Accessed ... from' web citation pattern (APA format)", "APA", 7.0)

    if re.search(r'\[(Map|Image|Photograph|Video|Film|Illustration)\]\.\s*\(\d{4}\)', text, re.IGNORECASE):
        add("APA-08", "Bracketed media type [Map/Image/etc.] + (Year) → APA media citation format", "APA", 8.0)

    if re.search(r'\(\d{4}\)\.\s+[A-Z]', text):
        add("APA-09", "Period after (Year) — APA uses '(Year). Title' format", "APA", 5.0)

    if re.search(r'\(\w+\.?\s+\d+,\s+\d{4}\)', text):
        add("APA-10", "Month Day, Year date format in parens — APA social media/video citation", "APA", 6.0)

    if re.search(r'\(pp\.\s*\d+', text):
        add("APA-06", "(pp. X–Y) page range in parentheses (APA book chapter format)", "APA", 5.0)

    # ------------------------------------------------------------------ #
    #  MLA RULES                                                           #
    # ------------------------------------------------------------------ #

    mla01_m = re.match(r'^.{1,30},\s+(\S+)', text)
    if mla01_m:
        first_word = mla01_m.group(1).rstrip('.')
        if len(first_word) >= 3 and not re.match(r'^[A-Z]{1,2}$', first_word):
            add("MLA-01", "Author listed with full first name (not initials) — MLA style", "MLA", 7.0)

    if re.search(r'\bvol\.\s*\d+', text, re.IGNORECASE) and re.search(r'\bno\.\s*\d+', text, re.IGNORECASE):
        add("MLA-02", "Both 'vol.' and 'no.' labels present (MLA container format)", "MLA", 7.0)

    if re.search(r'YouTube,\s*(uploaded by|dir\.)', text, re.IGNORECASE):
        add("MLA-07", "'YouTube, uploaded by' format — MLA online video citation", "MLA", 9.0)

    if (re.search(r'"[^"]{5,}"', text) and
        re.search(r'\bAccessed\b', text) and
        not re.match(r'^\[\d+\]', text) and
        not re.search(r'Available (at|from):', text, re.IGNORECASE)):
        add("MLA-08", "Quoted title + URL + 'Accessed' (no [n], no 'Available at:') — MLA web", "MLA", 4.0)

    if re.search(r'\bAccessed\b', text):
        add("MLA-03", "'Accessed' keyword for URL access date (MLA web citation)", "MLA", 6.0)

    if re.search(r'[A-Z][a-zA-Z\s]+,\s+vol\.\s*\d+', text, re.IGNORECASE):
        add("MLA-04", "Journal title followed by vol. (MLA container structure)", "MLA", 4.0)

    if re.search(r'\b(Print|Web)\s*\.$', text):
        add("MLA-05", "'Print' or 'Web' medium descriptor at end (MLA 8th or earlier)", "MLA", 5.0)

    year_pos = None
    year_m = re.search(r'\b(19|20)\d{2}\b', text)
    if year_m:
        year_pos = year_m.start() / max(len(text), 1)
    author_end = re.search(r'^[A-Z][a-z]+,\s+[A-Z][a-z]+\s*\.', text)
    if year_pos is not None and year_pos > 0.45 and author_end:
        add("MLA-06", "Year appears in second half of entry (MLA places year late)", "MLA", 3.0)

    # ------------------------------------------------------------------ #
    #  HARVARD RULES                                                       #
    # ------------------------------------------------------------------ #

    if re.match(r'^[A-Z][a-z]+,\s+[A-Z]{2,}', text):
        add("HAR-01", "Initials run together without spaces after surname (Harvard convention)", "Harvard", 5.0)

    if re.search(r'\w[\w\-]+,\s+\w[\.\s]*\(?\d{4}\)?', text):
        if re.search(r'\(\d{4}\)\.', text):
            add("HAR-02", "Author initial + year pattern (but period after year suggests APA)", "Harvard", 2.0)
        else:
            add("HAR-02", "Author initial + year in parentheses, no trailing period (Harvard style)", "Harvard", 7.0)

    if re.search(r'\w[\w\-]+,\s+\w\.?\s+et al[.,]?\s+\(\d{4}\)', text, re.IGNORECASE):
        add("HAR-02B", "Author et al. + (Year) — Harvard multi-author date pattern", "Harvard", 7.0)

    if re.search(r'\w[\w\-]+,\s+\w\.?\s+et al\s+\(\d{4}\)', text, re.IGNORECASE):
        add("HAR-02C", "Author et al (Year) without period — Harvard variant", "Harvard", 7.0)

    if re.search(r'^[A-Z][a-zA-Z\s\-\.]+\s+\(\d{4}\)\s+[A-Z]', text):
        add("HAR-02D", "Organisation name as author + (Year) — Harvard institutional citation", "Harvard", 6.0)

    if re.search(r'\d{4}:\s*\d+', text):
        add("HAR-03", "Year:page colon notation (common in Harvard variants)", "Harvard", 6.0)

    if re.search(r'[A-Z][a-z]+:\s+[A-Z][a-zA-Z\s]+(?:Press|Publishing|Publishers|Books|Ltd|Inc)', text):
        add("HAR-04", "Place of publication: Publisher format (traditional Harvard books)", "Harvard", 4.0)

    if re.search(r'Available (at|from):', text, re.IGNORECASE):
        add("HAR-05", "'Available at/from:' URL prefix (Harvard web source format)", "Harvard", 8.0)

    if re.search(r'Available (at|from):.+\(Accessed', text, re.IGNORECASE | re.DOTALL):
        add("HAR-05B", "'Available at:' + '(Accessed:' combo — strong Harvard web citation", "Harvard", 4.0)

    journal_seg = re.search(r',\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){2,}),\s+\d+', text)
    if journal_seg:
        seg = journal_seg.group(1)
        if not re.search(r'\b[A-Z][a-z]+\.', seg):
            add("HAR-06", "Full (non-abbreviated) journal name detected (Harvard uses full names)", "Harvard", 3.0)

    # ------------------------------------------------------------------ #
    #  VANCOUVER RULES                                                     #
    # ------------------------------------------------------------------ #

    if re.match(r'^\d+[\.\s]\s*[A-Z]', text) and not re.match(r'^\[\d+\]', text):
        add("VAN-01", "Plain number at entry start (Vancouver numbered list, no brackets)", "Vancouver", 8.0)

    if re.search(r'\b[A-Z][a-z]+\s+[A-Z]{1,4},', text):
        add("VAN-02", "NLM author format: Surname Initials (no periods, no spaces) — Vancouver", "Vancouver", 8.0)

    if re.search(r'\b\d{3,4}[-–]\d{1,2}\b', text):
        add("VAN-03", "Truncated page range (e.g. 284-7, 1037-42) — Vancouver convention", "Vancouver", 7.0)

    if re.search(r'\b(N Engl J Med|J Am|Ann\s+[A-Z]|Br\s+[A-Z]|Am\s+J\s+[A-Z]|Clin\s+[A-Z]|Int\s+J\s+[A-Z])\b', text):
        add("VAN-04", "NLM-style abbreviated journal name (Vancouver/ICMJE biomedical format)", "Vancouver", 8.0)

    if re.search(r'\d{4};\d+\(\d+\):\d+', text):
        add("VAN-05", "Year;Volume(Issue):pages format — defining Vancouver reference structure", "Vancouver", 10.0)

    if re.search(r'[A-Z]{1,3},\s+[A-Z]{1,3},\s+[A-Z]{1,3},\s+et al', text, re.IGNORECASE):
        add("VAN-06", "Multiple NLM-format authors followed by et al. (Vancouver 6-author rule)", "Vancouver", 5.0)

    if re.search(
        r'\[(Internet|vle online|serial online|dissertation on the Internet|'
        r'monograph on the Internet|homepage on the Internet|serial on the Internet)\]',
        text, re.IGNORECASE
    ):
        add("VAN-07", "Bracketed NLM medium-type descriptor (e.g. [Internet], [vle online]) — Vancouver", "Vancouver", 8.0)

    if re.search(r'\b\d+\s+p\.\s*$', text):
        add("VAN-08", "Total page count 'N p.' at end of entry — Vancouver monograph format", "Vancouver", 5.0)

    # ------------------------------------------------------------------ #
    #  CROSS-STYLE DISAMBIGUATION ADJUSTMENTS                             #
    # ------------------------------------------------------------------ #

    bracket_start = re.match(r'^\[\d+\]', text)
    nlm_author = re.search(r'\b[A-Z][a-z]+\s+[A-Z]{1,4},', text)
    if bracket_start and nlm_author:
        add("DIS-01", "[n] label + NLM author format → likely Vancouver (Elsevier/bracket variant)", "Vancouver", 4.0)

    full_name_start = re.match(r'^[A-Z][a-z]+,\s+[A-Z][a-z]+', text)
    year_in_parens = re.search(r'\(\d{4}\)', text)
    if full_name_start and not year_in_parens and not bracket_start:
        add("DIS-02", "Full first name but no (Year) parentheses → leaning MLA over Harvard", "MLA", 2.0)

    # ------------------------------------------------------------------ #
    #  SCORE AGGREGATION                                                   #
    # ------------------------------------------------------------------ #

    styles = ["IEEE", "APA", "MLA", "Harvard", "Vancouver"]
    scores: Dict[str, float] = {s: 0.0 for s in styles}
    for rm in matched:
        scores[rm.style] += rm.weight

    candidate_scores = {s: scores[s] for s in allowed_styles}

    # HF-15 post-processing
    if _hf15_has_standards_code and "Harvard" in candidate_scores:
        candidate_scores["Harvard"] = max(0.0, candidate_scores["Harvard"] - 6.0)

    if (_hf15_has_standards_code and
            all(v == 0.0 for v in candidate_scores.values()) and
            "MLA" in candidate_scores):
        candidate_scores["MLA"] = 1.0

    # HF-13 post-processing
    if _hf13_fired and "MLA" in candidate_scores:
        _hf13_inverted = bool(re.match(r'^[A-Z][\w\-]+,\s+[A-Z]', text))
        _hf13_surname_dot_quote = bool(re.match(r'^[A-Z][\w\-]+\.\s+"', text))
        if _hf13_inverted or _hf13_surname_dot_quote:
            candidate_scores["MLA"] = candidate_scores.get("MLA", 0.0) + 7.0

    best_style = max(candidate_scores, key=lambda s: candidate_scores[s])
    best_score = candidate_scores[best_style]

    sorted_scores = sorted(candidate_scores.values(), reverse=True)
    second_score = sorted_scores[1] if len(sorted_scores) > 1 else 0.0

    if best_score == 0.0:
        if len(allowed_styles) == 1:
            best_style = next(iter(allowed_styles))
            confidence = "LOW"
        else:
            confidence = "LOW"
            best_style = "Unknown"
    elif best_score - second_score >= 8.0:
        confidence = "HIGH"
    elif best_score - second_score >= 4.0:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    return ClassificationResult(
        predicted_style=best_style,
        confidence=confidence,
        scores=scores,
        matched_rules=matched,
    )


# ---------------------------------------------------------------------------
# Test data (used for standalone testing only)
# ---------------------------------------------------------------------------

TEST_ENTRIES = {
    "IEEE": [
        '[1] A. Smith, B. Jones, and C. Lee, "Deep learning for signal processing," IEEE Trans. Neural Netw., vol. 31, no. 4, pp. 1234-1245, Apr. 2020, doi: 10.1109/TNN.2020.123456.',
        '[7] R. Kumar et al., "A novel approach to edge computing," in Proc. IEEE Int. Conf. Cloud Comput., Chicago, IL, USA, 2021, pp. 45-52.',
    ],
    "APA": [
        'Smith, J. A., & Jones, B. C. (2020). Deep learning approaches in natural language processing. Journal of Artificial Intelligence Research, 45(3), 112-134. https://doi.org/10.1234/jair.2020.001',
    ],
    "MLA": [
        'Smith, John. "Deep Learning Approaches in Modern Computing." Journal of Computer Science, vol. 12, no. 3, 2020, pp. 45-67.',
    ],
    "Harvard": [
        'Smith, AB (2020) Deep learning approaches in natural language processing. Journal of Artificial Intelligence Research, 45(3): 112-134.',
    ],
    "Vancouver": [
        '1. Smith AB, Jones BC, Lee CD. Deep learning for medical image analysis. N Engl J Med. 2020;383(5):456-63.',
    ],
}


if __name__ == "__main__":
    # Quick smoke test
    for style, entries in TEST_ENTRIES.items():
        for entry in entries:
            result = classify(entry)
            status = "OK" if result.predicted_style == style else "FAIL"
            print(f"[{status}] expected={style:<10} got={result.predicted_style:<10} conf={result.confidence}  {entry[:60]}...")
