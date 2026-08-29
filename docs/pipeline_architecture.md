# ReportGPS — Pipeline Architecture (v5, Prototype 1)

## Overview

The extraction pipeline is a **multi-step PDF analysis service** implemented as a FastAPI application at `services/extraction-pipeline/`. It runs in under 1 second per paper (excluding optional AI verification). Every step uses deterministic text and regex analysis — no deep-learning OCR or ML models in the core path.

All modules are organized under the `modules/` package, grouped by responsibility.

---

## Step-by-Step Architecture

### Step 1 — PyMuPDF Full-Document Pass (`modules/extractors/pymupdf_extractor.py`)
**Typical time: ~0.3–0.7 s**

Opens the PDF with PyMuPDF (`pymupdf` package, imported as `fitz`) and collects, for every page:
- `plain_text` — raw UTF-8 text used by all subsequent steps
- Per-span metadata: `font_size`, `is_bold`, `bbox` (used for heading detection in Step 2)
- Image block bounding boxes `{x0, y0, x1, y1}` (used for figure detection)
- `image_count` — number of image blocks on the page

**Outputs:** `page_chunks[]`, `page_texts[]`, `full_text`

---

### Step 2 — Structural Analysis (`modules/extractors/structural_analyzer.py`)
**Typical time: ~0.03–0.1 s**

Uses font-size heuristics and regex patterns on the `page_chunks` to detect document structure.

#### Heading Detection
Three heading detection strategies are tried in order:
1. **Font-size heading:** `font_size >= body_font_size * 1.15`
2. **Bold heading:** `is_bold AND font_size >= body_font_size AND len <= 80 AND not sentence-like`
3. **All-caps heading:** `ALL_CAPS AND len <= 50 AND font_size >= body_font_size * 0.9`

Exclusions: text in the top 55pt (header zone) or bottom 55pt (footer zone) of the page, and caption lines, are always excluded from heading candidates.

Body font size is estimated as the **length-weighted mode** of all text spans with `font_size > 7pt` — footnote-sized text doesn't bias the estimate.

#### Manuscript Metadata (page-1 heuristics)
- **Title:** Largest font size text on the first page
- **Abstract / Keywords / Authors:** Pattern match on section labels and relative position to title

#### Figures
`"Fig. N"` or `"Figure N"` caption regex, followed by a nearest-image-bbox lookup to pair each caption with its image.

#### Tables
`"Table N"` or `"Tab. N"` caption regex.

**Outputs:** `sections[]`, `figures[]`, `tables[]`, `manuscript{}`

---

### Step 2.5 — Equation Extraction (`modules/extractors/equation_extractor.py`)
**Typical time: ~0.05–0.3 s**

Scans every page's word-level data (from `page.get_text("words")` in PyMuPDF) to find right-margin equation labels.

#### Pattern Matched
`(N)`, `(N.M)`, `(Na)` — where N is an integer and the full match is right-aligned on the line.

Also handles alternate PDF encodings: `\xf0...\xde` → `(N)`.

#### False-Positive Filters (in order)
1. **Right-margin threshold:** `x0 > 35% of page_width` (`_LABEL_X_THRESHOLD = 0.35`). Covers right-column labels (~90% of page) and left-column labels in 2-column layouts (~46% of page).
2. **Year filter:** Labels matching `(1900)–(2099)` are skipped.
3. **Large number filter:** Labels with integer > 200 (`_MAX_EQ_NUMBER`) are skipped (bibliography citation numbers).
4. **Gap filter:** A real equation label has a large gap from the preceding word (`> 10pt`). In-text citations like `"as shown in (3)"` have normal word spacing and are rejected.
5. **Header/footer zone filter:** Ignores text in the top and bottom 50pt of the page.
6. **Global deduplication:** First occurrence of each integer equation number is kept; subsequent occurrences (running headers, caption repetitions) are discarded.

**Outputs:** `equations[]` — each with `number`, `number_format`, `page_number`, `bbox`, `context_before`, `context_after`

---

### Step 3a — Reference & Citation Extraction (`modules/extractors/regex_extractor.py`)
**Typical time: ~0.05–0.15 s**

Layout-aware extraction that handles two-column PDFs, page headers/footers, and multi-line references.

#### Supported Reference Styles
| Style | Example |
|---|---|
| Numbered bracket | `[1] Smith, A. et al. Title. Journal, 2020.` |
| Dot number | `1. Smith, A. et al. Title. Journal, 2020.` |
| APA author-year | `Smith, A. (2020). Title. Journal, 12(3), 45–67.` |

#### In-text Citation False-Positive Filtering
The extractor uses the already-extracted reference list to avoid marking table data or year numbers as citations:
- If no references have numeric prefixes (document uses author-year style), all `[N]` patterns are ignored
- If numeric style: brackets containing numbers far exceeding the reference list size are ignored (e.g. `[250,500]` with only 50 references)

**Outputs:** `references[]`, `in_text_citations[]`

---

### Step 3b — Typography Checks (`modules/checkers/typography_checker.py`)
**Typical time: <0.03 s**

Runs on body text (full text with reference section removed). Flags:
- En-dash usage in ranges (`1-5` → should be `1–5`)
- Number-unit spacing (`10ms` → should be `10 ms`)
- Percent/degree spacing (`10 %` → should be `10%`)

---

### Step 3c — Figures & Tables Checks (`modules/checkers/figures_tables_checker.py`)
**Typical time: <0.03 s**

Runs validation on the `figures[]` and `tables[]` from Step 2:
- Sequential numbering without gaps (Checks 7, 8)
- Chronological order of first mention in the text (Checks 9, 10)
- Caption position: table captions above table body, figure captions below image (Checks 11, 12)
- Figure sub-part label completeness: (a), (b) … starting from (a) (Check 13)

---

### Step 3d — Syntax & Grammar Checks (`modules/checkers/syntax_grammar_checker.py`)
**Typical time: <0.02 s**

Implements 8 formatting rules using regex on `body_text`:
- Acronym definition at first occurrence
- En-dash in numeric ranges
- Non-breaking spaces before units
- No space before `%` / `°`
- Double spaces
- Punctuation spacing
- Consistent quote style
- British/American spelling consistency

---

### Step 3e — Equation Checks (`modules/checkers/equation_checker.py`)
**Typical time: <0.01 s**

Validates the `equations[]` from the extractor:

**Check 15 — Sequential Numbering:**  
Looks for gaps in the sequence. Only reports single-step gaps (e.g. 3 → 5) on sequences of ≥ 3 equations. Does not report duplicates — the extractor already deduplicates at source.

**Check 16 — Punctuation:**  
Flags a missing comma only when `context_after` starts with `where`, `with`, `in which`, or `such that` within 80 chars, and `context_before` doesn't already end with a comma or period.

**Check 17 — In-text Citation Style:**  
Finds all equation call-outs in the document body using a combined regex:
- `Eq. (N)`, `Eqs. (N)–(M)`
- `equation (N)`, `equations (N) and (M)`
- `eqn. (N)`, `expression (N)`

Determines the dominant style by count. Reports every individual instance of a minority style with its page number and surrounding sentence context.

---

### Step 3f — Reference Quality Checks (`modules/reference_analyser/analyser.py`)
**Typical time: ~0.1–0.5 s**

Runs 6 checks on the extracted reference strings:

| Check | Module |
|---|---|
| 1 — Style Compliance | `check_style_conformity.py` + `citation_classifier.py` |
| 2 — Bidirectional Match | `orchestrator.py::_check_bidirectional_match` |
| 3 — Metadata Completeness | `check_completeness.py` |
| 4 — DOI / URL | `check_doi.py` |
| 5 — Sequential Ordering | `check_ordering.py` |
| 6 — Field Consistency | `check_journal_casing.py` |

`citation_classifier.py` classifies each reference into one of: IEEE, APA, MLA, Harvard, Vancouver, Chicago, UNKNOWN — using a rule-based scoring engine with heuristic patterns for each style.

---

### Step 4 — AI Verifier (`modules/verifier/verifier.py`, optional)
**Typical time: ~1–3 s (API latency bound)**

When `VERIFIER_ENABLED=true` in `.env`:

1. All flagged violations are collected into a **candidate batch**
2. Candidates classified as `skip_verifier=True` (high-confidence deterministic checks) bypass the LLM and are returned as-is
3. Remaining candidates are sent to the LLM in a structured prompt
4. LLM returns: `CONFIRMED`, `FALSE_POSITIVE`, or `UNCERTAIN`
5. `FALSE_POSITIVE` violations are silently discarded
6. Returned violations include AI-generated `evidence` and `suggestion` strings

#### LLM Provider Waterfall
```
Groq (GROQ_API_KEY, _2, _3, _4 — round-robin, 30 RPM each free)
  ↓ on failure / rate limit
Cerebras (CEREBRAS_API_KEY — free tier: 30 RPM, 1M tokens/day)
  ↓ on failure
Gemini (GOOGLE_API_KEY — last resort)
```

#### Verifier Rules
All per-check LLM instructions are declared in `modules/verifier/verifier_rules.py` as a Python dict. Adding a new check's rule never requires touching `verifier.py`. The rule schema:

```python
{
    "check_id":            "acronym_definition",
    "check_name":          "Acronym Definition",
    "rule":                "Every acronym must be spelled out in full at its first occurrence...",
    "category":            "Structure",
    "skip_verifier":       False,   # True = bypass LLM, return as-is
    "detector_confidence": 0.68,    # used by skip threshold routing
}
```

---

## Module Status (Prototype 1)

| Module | Path | Status | Notes |
|---|---|---|---|
| `app.py` | root | ✅ Active | FastAPI server, port 8004 |
| `orchestrator.py` | root | ✅ Active | Pipeline coordinator |
| `pymupdf_extractor.py` | modules/extractors | ✅ Active | Page text + font + image bboxes |
| `structural_analyzer.py` | modules/extractors | ✅ Active | Headings, metadata, figures, tables |
| `equation_extractor.py` | modules/extractors | ✅ Active | Fast PyMuPDF-based equation label scan |
| `regex_extractor.py` | modules/extractors | ✅ Active | References + citations with smart filtering |
| `equation_checker.py` | modules/checkers | ✅ Active | Checks 15–17 |
| `typography_checker.py` | modules/checkers | ✅ Active | Typography violation checks |
| `figures_tables_checker.py` | modules/checkers | ✅ Active | Checks 7–13 |
| `syntax_grammar_checker.py` | modules/checkers | ✅ Active | Checks 17–24 |
| `verifier.py` | modules/verifier | ✅ Active | AI verifier (optional) |
| `verifier_rules.py` | modules/verifier | ✅ Active | Verifier rule registry |
| `verifier_config.py` | modules/verifier | ✅ Active | Verifier on/off, provider selection |
| `analyser.py` | modules/reference_analyser | ✅ Active | Reference quality checks entry point |
| `citation_classifier.py` | modules/reference_analyser | ✅ Active | Reference style classifier |
| `reference_quality.py` | modules/reference_analyser | ✅ Active | Enriched reference builder |
| `check_style_conformity.py` | modules/reference_analyser | ✅ Active | Check 1 |
| `check_completeness.py` | modules/reference_analyser | ✅ Active | Check 3 |
| `check_doi.py` | modules/reference_analyser | ⚠️ Partial | Check 4 (format only; HTTP probe off by default) |
| `check_ordering.py` | modules/reference_analyser | ✅ Active | Check 5 |
| `check_journal_casing.py` | modules/reference_analyser | ✅ Active | Check 6 |
| `section_extractor.py` | modules/reference_analyser | ✅ Active | PyMuPDF section text extraction |
