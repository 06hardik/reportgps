# ReportGPS — Extraction Pipeline

The Python FastAPI service that powers all PDF analysis. This is the core of the entire platform.

## Overview

This service runs a **6-step deterministic extraction pipeline** followed by an optional **AI verification step**. It accepts a PDF and returns a structured JSON document with all extracted content and validation results.

**Port:** `8004`  
**Entry point:** `python app.py`

---

## Quick Start

```bash
# 1. Create & activate virtual environment
python -m venv env
source env/bin/activate   # Windows: env\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure API keys
cp .env.example .env
# Edit .env — add at least GROQ_API_KEY for AI verification
# (or set VERIFIER_ENABLED=false to skip AI entirely)

# 4. Start the server
python app.py
# → Uvicorn running on http://0.0.0.0:8004
```

---

## Directory Structure

```
extraction-pipeline/
├── app.py                        ← FastAPI server entry point
├── orchestrator.py               ← Full pipeline coordinator (the main brain)
├── requirements.txt
├── .env.example                  ← Environment variable template
└── modules/
    ├── __init__.py
    ├── extractors/               ← PDF data extraction
    │   ├── __init__.py
    │   ├── pymupdf_extractor.py  ← Step 1: raw page text, fonts, image bboxes
    │   ├── structural_analyzer.py ← Step 2: headings, metadata, figures, tables
    │   ├── regex_extractor.py    ← Step 3a: references & in-text citations
    │   └── equation_extractor.py ← Step 2.5: equation label scan
    ├── checkers/                 ← Deterministic validation rules
    │   ├── __init__.py
    │   ├── typography_checker.py ← Step 3b: en-dash, unit-space, percent/degree
    │   ├── figures_tables_checker.py ← Step 3c: Checks 7–13
    │   ├── syntax_grammar_checker.py ← Step 3d: Checks 17–24 (acronyms, spacing)
    │   └── equation_checker.py   ← Step 3e: Checks 15–17
    ├── verifier/                 ← AI false-positive filter (optional)
    │   ├── __init__.py
    │   ├── verifier.py           ← Groq / Cerebras / Gemini LLM verification
    │   ├── verifier_config.py    ← Provider selection, feature flags
    │   └── verifier_rules.py     ← Declarative rule registry for each check
    └── reference_analyser/       ← Reference quality checks (Checks 1–6)
        ├── __init__.py
        ├── analyser.py           ← Step 3f entry point
        ├── citation_classifier.py ← Classifies refs as IEEE/APA/MLA/etc.
        ├── reference_quality.py  ← Builds enriched reference objects
        ├── check_style_conformity.py ← Check 1: style consistency
        ├── check_completeness.py ← Check 3: required metadata fields
        ├── check_doi.py          ← Check 4: DOI/URL format & liveness
        ├── check_ordering.py     ← Check 5: sequential ordering
        ├── check_journal_casing.py ← Check 6: field consistency
        └── section_extractor.py  ← PyMuPDF-based section text extraction
```

---

## Pipeline Steps

### Step 1 — PyMuPDF Extraction (`modules/extractors/pymupdf_extractor.py`)

Opens the PDF with PyMuPDF and collects for every page:
- Raw UTF-8 `plain_text`
- Per-span metadata: `font_size`, `is_bold`, `bbox`
- Image block bounding boxes (for figure detection)

**Output:** `page_chunks[]`, `page_texts[]`, `full_text`

---

### Step 2 — Structural Analysis (`modules/extractors/structural_analyzer.py`)

Detects document structure using font-size heuristics:
- **Headings:** Font-size > 115% of body, or bold + not sentence-like, or ALL-CAPS
- **Manuscript metadata:** Title (largest text on page 1), Abstract, Keywords, Authors
- **Figures:** `"Fig. N"` / `"Figure N"` caption regex + nearest image bbox
- **Tables:** `"Table N"` / `"Tab. N"` caption regex

**Output:** `sections[]`, `figures[]`, `tables[]`, `manuscript{}`

---

### Step 2.5 — Equation Extraction (`modules/extractors/equation_extractor.py`)

Scans word-level PDF data for right-margin equation labels `(N)`, `(A.1)`, etc.

Key filters to avoid false positives:
- Right-margin threshold: `x0 > 65% of page_width` (covers both 1-column and 2-column)
- Skips years `(1900)–(2099)` and numbers > 999
- Skips labels with small gap from preceding word (in-text citations have normal spacing)
- Global deduplication: first occurrence of each integer wins

**Output:** `equations[]`

---

### Step 3a — Reference & Citation Extraction (`modules/extractors/regex_extractor.py`)

Layout-aware extraction supporting:
- **Numbered bracket:** `[1] Smith, A. ...`
- **Dot number:** `1. Smith, A. ...`
- **APA author-year:** `Smith, A. (2020). Title. Journal...`

In-text citation extraction uses the reference list to filter false positives:
- If the document uses author-year style, numeric brackets like `[2020]` are ignored
- If numeric style, brackets with numbers exceeding the reference count are ignored

**Output:** `references[]`, `in_text_citations[]`

---

### Step 3b — Typography Checks (`modules/checkers/typography_checker.py`)

Runs on body text (references section excluded). Flags:
- En-dash in ranges (`1-5` should be `1–5`)
- Number-unit spacing (`10ms` should be `10 ms`)
- Percent/degree spacing (`10 %` should be `10%`)

---

### Step 3c — Figures & Tables Checks (`modules/checkers/figures_tables_checker.py`)

Implements **Checks 7–13**:
| Check | Rule |
|---|---|
| 7 | Figures numbered sequentially without gaps |
| 8 | Tables numbered sequentially without gaps |
| 9 | Figures mentioned in ascending numeric order |
| 10 | Tables mentioned in ascending numeric order |
| 11 | Table captions positioned above the table body |
| 12 | Figure captions positioned below the image |
| 13 | Figure sub-part labels (a), (b) … consecutive from (a) |

---

### Step 3d — Syntax & Grammar Checks (`modules/checkers/syntax_grammar_checker.py`)

Implements **Checks 19–26** (labelled 17–24 in some spec versions):
| Check | Rule |
|---|---|
| Acronym Definition | 3+ capital letter acronyms must be defined at first occurrence |
| En-dash Ranges | Numeric ranges must use en-dash, not hyphen |
| Non-breaking Space | Space between number and unit must be U+00A0 |
| No Space % / ° | No space before percent or degree symbols |
| Double Spaces | No double ASCII spaces |
| Punctuation Spacing | Single space after comma/semicolon, no space before |
| Quote Style | Straight or curly quotes, not both |
| Spelling Consistency | American and British spellings must not be mixed |

---

### Step 3e — Equation Checks (`modules/checkers/equation_checker.py`)

Validates the extracted equations:
| Check | Rule |
|---|---|
| **15** Sequential Numbering | Equation labels form a gapless integer sequence |
| **16** Punctuation | Comma required after equation when text continues with "where", "with", "in which" |
| **17** In-text Citation Style | All equation call-outs use one consistent style ("Eq. (N)" vs "equation (N)") |

---

### Step 3f — Reference Quality (`modules/reference_analyser/analyser.py`)

Runs **Checks 1–6** on extracted reference strings:
| Check | Rule |
|---|---|
| **1** Style Compliance | All references follow a single citation style |
| **2** Bidirectional Match | Every citation maps to a reference and vice versa |
| **3** Metadata Completeness | All required fields present |
| **4** DOI / URL | DOIs formatted correctly; optional HTTP liveness probe |
| **5** Sequential Ordering | References in ascending order (numbered styles) |
| **6** Field Consistency | Same fields used across references of the same type |

---

### Step 4 — AI Verifier (`modules/verifier/verifier.py`, optional)

When `VERIFIER_ENABLED=true`:
1. All flagged violations are collected into a batch of **candidates**
2. Each candidate is sent to the LLM (Groq first, Cerebras fallback, Gemini last resort)
3. LLM returns one of: `CONFIRMED`, `FALSE_POSITIVE`, `UNCERTAIN`
4. `FALSE_POSITIVE` candidates are silently discarded
5. Remaining violations are returned with AI-generated evidence

**LLM Provider Waterfall:** Groq (up to 4 keys, round-robin) → Cerebras → Gemini

---

## Environment Variables

See `.env.example` for full documentation with comments.

| Variable | Required | Description |
|---|---|---|
| `VERIFIER_ENABLED` | No (default: `true`) | Set `false` to skip LLM verification |
| `GROQ_API_KEY` | If verifier on | Primary Groq API key |
| `GROQ_API_KEY_2`–`_4` | No | Additional Groq keys for load balancing |
| `CEREBRAS_API_KEY` | No | Cerebras fallback |
| `GOOGLE_API_KEY` | No | Gemini last resort |
| `VERIFIER_TEMPERATURE` | No (default: `0.1`) | LLM sampling temperature |
| `VERIFIER_TIMEOUT` | No (default: `60`) | Per-LLM-request timeout in seconds |
| `PHRASING_ENABLED` | No (default: `true`) | Rewrite violations into human-readable language |

---

## API Endpoints

### `POST /extract`

Accepts a PDF file upload. Runs the full pipeline. Returns structured JSON.

```bash
curl -X POST http://localhost:8004/extract \
  -F "file=@paper.pdf" \
  | python -m json.tool
```

### `GET /health`

```json
{ "status": "ok", "service": "extraction-pipeline", "version": "3.1.0" }
```

---

## Dependencies

See `requirements.txt` for pinned versions. Key packages:

| Package | Purpose |
|---|---|
| `fastapi` | HTTP server framework |
| `uvicorn[standard]` | ASGI server |
| `python-multipart` | Multipart form upload parsing |
| `pymupdf>=1.24.0` | PDF text + image extraction |
| `groq>=0.9.0` | Groq LLM API client |
| `google-genai>=0.1.0` | Gemini AI client |
| `httpx>=0.27.0` | Async HTTP client (internal use) |
| `bibtexparser` | BibTeX parsing for reference analysis |
| `python-dotenv>=1.0.0` | `.env` file loader |

---

## Adding New Checks

1. Add detection logic in the appropriate `modules/checkers/` file
2. Return violations in the standard format:
   ```python
   { "page": int, "detail": str, "evidence": str, "suggestion": str }
   ```
3. Call your checker from `orchestrator.py`
4. Add a rule entry to `modules/verifier/verifier_rules.py`
5. Update `docs/checks_reference.md`

---

## Known Limitations (Phase 2 Work)

- **Check 14** (Equation Placement After Mention): Requires cross-referencing equation bbox positions against in-text citation positions
- **Check 18** (Delimiter Balance): Requires LaTeX/MathML; PDF text layer drops raw math symbols
- **Check 30** (Heading Style): Requires per-journal style guide as ground truth
- **DOI liveness probe** (Check 4): HTTP validation is disabled by default to avoid slowing the pipeline for every paper
