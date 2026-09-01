# ReportGPS — Academic Paper Validation Platform

> **Prototype 1 (P1) — Feature-complete handover build.**
> A multi-layer PDF analysis and linting platform for academic research papers.
> Combines fast deterministic extraction (PyMuPDF) with an optional AI Verifier
> (Groq / Cerebras / Gemini) to deliver high-precision, low-false-positive
> formatting, structural, citation, and equation checks in under 2 seconds.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Quick Start](#quick-start)
3. [Repository Structure](#repository-structure)
4. [Service: Extraction Pipeline (Python)](#service-extraction-pipeline)
5. [Service: Backend Proxy (Node.js)](#service-backend-nodejs)
6. [Service: Frontend (React)](#service-frontend-react)
7. [All 30 Validation Checks](#all-30-validation-checks)
8. [Environment Variables Reference](#environment-variables-reference)
9. [API Reference](#api-reference)
10. [Output JSON Schema](#output-json-schema)
11. [Performance](#performance)
12. [Development Notes](#development-notes)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Browser — React + Vite  (port 3000)                        │
│  • PDF drag-and-drop upload                                  │
│  • Interactive PDF viewer with highlighted violation markers │
│  • Per-check accordion results panel                         │
└──────────────────┬──────────────────────────────────────────┘
                   │  POST /api/upload  (multipart PDF)
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  Node.js Express Backend  (port 5001)                       │
│  • Thin proxy — streams PDF to Python extraction service    │
│  • Returns raw JSON from extraction pipeline to frontend    │
└──────────────────┬──────────────────────────────────────────┘
                   │  POST /extract  (multipart PDF)
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  Python Extraction Pipeline — FastAPI  (port 8004)          │
│                                                             │
│  Step 1   PyMuPDF extraction     (~0.3–0.7 s)              │
│  Step 2   Structural analysis    (~0.03–0.1 s)             │
│  Step 2.5 Equation extraction    (~0.05–0.3 s)             │
│  Step 3a  Reference & citations  (~0.05–0.15 s)            │
│  Step 3b  Typography checks      (<0.03 s)                 │
│  Step 3c  Figures & tables       (<0.03 s)                 │
│  Step 3d  Syntax & grammar       (<0.02 s)                 │
│  Step 3e  Equation checks        (<0.01 s)                 │
│  Step 3f  Reference quality      (<0.5 s)                  │
│  Step 4   AI Verifier (optional) (~1–3 s, API latency)     │
└─────────────────────────────────────────────────────────────┘
```

**Typical end-to-end time:** ~1–2 s (with AI verifier) / <0.5 s (without).

---

## Quick Start

### Prerequisites

| Tool | Minimum Version |
|---|---|
| Python | 3.10 |
| Node.js | 18 |
| npm | 9 |

### 1 — Python Extraction Pipeline (port 8004)

```bash
cd services/extraction-pipeline
python -m venv env
source env/bin/activate          # Windows: env\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Fill in your API keys (see §Environment Variables)
python app.py
```

### 2 — Node.js Backend Proxy (port 5001)

```bash
cd backend
npm install
npm start
```

### 3 — React Frontend (port 3000)

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000** → drag & drop a PDF → click **Analyse Document**.

---

## Repository Structure

```
reportgps/
├── README.md                          ← You are here
├── .gitignore
├── docs/
│   ├── pipeline_architecture.md       ← Deep-dive: every pipeline step
│   ├── checks_reference.md            ← All 30 checks, data sources, status
│   └── equation_checks.md             ← Equation extraction & checks design
│
├── backend/                           ← Node.js thin proxy
│   ├── server.js
│   ├── package.json
│   └── .gitignore
│
├── frontend/                          ← React + Vite UI
│   ├── src/
│   │   ├── App.jsx                    ← Entire frontend (single-file SPA)
│   │   ├── main.jsx
│   │   └── index.css
│   ├── index.html
│   ├── vite.config.js
│   └── package.json
│
└── services/
    └── extraction-pipeline/           ← Python FastAPI service (port 8004)
        ├── app.py                     ← FastAPI entry point
        ├── orchestrator.py            ← Full pipeline coordinator
        ├── requirements.txt
        ├── .env.example               ← API key template
        └── modules/
            ├── extractors/            ← PDF data extraction
            │   ├── pymupdf_extractor.py
            │   ├── structural_analyzer.py
            │   ├── regex_extractor.py
            │   └── equation_extractor.py
            ├── checkers/              ← Deterministic rule checkers
            │   ├── typography_checker.py
            │   ├── figures_tables_checker.py
            │   ├── syntax_grammar_checker.py
            │   └── equation_checker.py
            ├── verifier/              ← AI false-positive filter
            │   ├── verifier.py
            │   ├── verifier_config.py
            │   └── verifier_rules.py
            └── reference_analyser/    ← Reference quality checks (1–6)
                ├── analyser.py
                ├── citation_classifier.py
                ├── reference_quality.py
                ├── check_style_conformity.py
                ├── check_completeness.py
                ├── check_doi.py
                ├── check_ordering.py
                ├── check_journal_casing.py
                └── section_extractor.py
```

---

## Service: Extraction Pipeline

The Python FastAPI service at `services/extraction-pipeline/` is the heart of the platform.

### Module Reference

| Module | Path | Responsibility |
|---|---|---|
| `app.py` | root | FastAPI server — `POST /extract`, `GET /health` |
| `orchestrator.py` | root | Coordinates all pipeline steps, builds final JSON |
| `pymupdf_extractor.py` | modules/extractors | PyMuPDF page text, font metadata, image bboxes |
| `structural_analyzer.py` | modules/extractors | Heading detection, manuscript metadata (title/abstract/authors/keywords), figure & table discovery |
| `equation_extractor.py` | modules/extractors | Right-margin label scan; supports 1-column and 2-column layouts |
| `regex_extractor.py` | modules/extractors | IEEE/APA/numbered reference extraction; in-text citation extraction with style-aware false-positive filtering |
| `typography_checker.py` | modules/checkers | En-dash, number-unit spacing, percent/degree formatting |
| `figures_tables_checker.py` | modules/checkers | Sequential numbering, chronological order, caption position checks (Checks 7–13) |
| `syntax_grammar_checker.py` | modules/checkers | Acronym definitions, double spaces, quote styles, en-dash ranges, spelling consistency (Checks 17–24) |
| `equation_checker.py` | modules/checkers | Equation sequential numbering, punctuation, in-text reference style (Checks 15–17) |
| `verifier.py` | modules/verifier | AI false-positive filter (Groq / Cerebras / Gemini), phrasing engine |
| `verifier_config.py` | modules/verifier | Provider selection, API key loading, feature flags |
| `verifier_rules.py` | modules/verifier | Declarative rule registry for every check the LLM verifier evaluates |
| `analyser.py` | modules/reference_analyser | Orchestrates all reference quality checks (Checks 1–6) |
| `citation_classifier.py` | modules/reference_analyser | Classifies individual references into IEEE/APA/MLA/Harvard/Vancouver/Chicago |
| `reference_quality.py` | modules/reference_analyser | Builds enriched reference objects, calls individual check modules |
| `check_style_conformity.py` | modules/reference_analyser | Check 1: style consistency across all references |
| `check_completeness.py` | modules/reference_analyser | Check 3: required metadata fields present |
| `check_doi.py` | modules/reference_analyser | Check 4: DOI/URL format and HTTP liveness |
| `check_ordering.py` | modules/reference_analyser | Check 5: sequential ordering of numbered references |
| `check_journal_casing.py` | modules/reference_analyser | Check 6: consistent field casing across references of same type |
| `section_extractor.py` | modules/reference_analyser | PyMuPDF-based section text extraction for the reference analyser |

---

## Service: Backend (Node.js)

Located at `backend/`. A minimal Express.js proxy — its only job is to receive the PDF from the browser and forward it to the Python extraction pipeline.

**Why a separate Node.js layer?** The frontend runs on Vite's dev server. Direct browser-to-Python requests are blocked by CORS. The Node proxy resolves this cleanly without needing to configure CORS on the Python service for every possible dev origin.

| File | Purpose |
|---|---|
| `server.js` | Express app — `POST /api/upload` proxies to `http://localhost:8004/extract` |
| `package.json` | ESM module; uses `axios`, `multer`, `express`, `form-data`, `cors`, `dotenv` |

**Port:** `5001` (configurable via `PORT` env var)  
**Env var:** `EXTRACTION_SERVICE_URL` (default: `http://localhost:8004`)

---

## Service: Frontend (React)

Located at `frontend/`. A Vite + React 18 single-page application.

**Key features:**
- Drag-and-drop PDF upload
- Embedded PDF viewer (`pdfjs-dist`) with page-accurate violation highlighting
- Per-check expandable accordion panels — each violation links directly to its page
- Category tabs: Figures & Tables / Equations / References / Formatting & Structure
- Severity badges (Error / Warning / Info / Pass)
- Dark, glassmorphism-inspired UI with smooth animations

| File | Purpose |
|---|---|
| `src/App.jsx` | Entire frontend SPA (single file, ~2000 LOC) |
| `src/index.css` | Global CSS resets |
| `src/main.jsx` | Vite entry point |
| `index.html` | HTML shell |
| `vite.config.js` | Vite config with React plugin |

**Dependencies:** `react`, `react-dom`, `axios`, `pdfjs-dist`, `lucide-react`

---

## All 30 Validation Checks

The target specification for this platform defines 30 named checks. The table below maps each check to its implementation status in this prototype.

> **Legend:** ✅ Implemented & active | ⚠️ Partially implemented | ❌ Not implemented (requires future work)

### Group A — Reference Quality (Checks 1–6)

| # | Check Name | Description | Status | Module |
|---|---|---|---|---|
| 1 | Style Compliance | All references in the list must conform to a single citation style (IEEE, APA, MLA, Harvard, Chicago, Vancouver) | ✅ | `reference_analyser/check_style_conformity.py` |
| 2 | Bidirectional Match | Every in-text citation must appear in the reference list, and every reference must be cited at least once | ✅ | `orchestrator.py` (`_check_bidirectional_match`) |
| 3 | Metadata Completeness | All required fields (authors, year, title, venue) must be present in each reference | ✅ | `reference_analyser/check_completeness.py` |
| 4 | DOI / URL Liveness | DOIs and URLs in the reference list must be properly formatted and return HTTP 200 | ⚠️ Format check done; live HTTP probe skipped by default (can be slow) | `reference_analyser/check_doi.py` |
| 5 | Sequential Ordering | For numbered styles (IEEE/Vancouver), references must appear in the list in ascending numeric order | ✅ | `reference_analyser/check_ordering.py` |
| 6 | Consistency in References | References of the same type must use consistent fields (e.g. all journals have volume & issue) | ✅ | `reference_analyser/check_journal_casing.py` |

### Group B — Figures & Tables (Checks 7–13)

| # | Check Name | Description | Status | Module |
|---|---|---|---|---|
| 7 | Figure Sequential Numbering | Figures must be numbered 1, 2, 3 … without gaps or duplicates | ✅ | `checkers/figures_tables_checker.py` |
| 8 | Table Sequential Numbering | Tables must be numbered 1, 2, 3 … without gaps or duplicates | ✅ | `checkers/figures_tables_checker.py` |
| 9 | Figure Chronological Order | Figures must be first mentioned in the text in ascending numeric order | ✅ | `checkers/figures_tables_checker.py` |
| 10 | Table Chronological Order | Tables must be first mentioned in the text in ascending numeric order | ✅ | `checkers/figures_tables_checker.py` |
| 11 | Table Caption Above Table | Table caption must be positioned above the table body | ✅ | `checkers/figures_tables_checker.py` |
| 12 | Figure Caption Below Figure | Figure caption must be positioned below the image | ✅ | `checkers/figures_tables_checker.py` |
| 13 | Figure Sub-part Labels | Sub-part labels (a), (b) … must be consecutive starting from (a) | ✅ | `checkers/figures_tables_checker.py` |

### Group C — Equations (Checks 14–18)

| # | Check Name | Description | Status | Module |
|---|---|---|---|---|
| 14 | Placement After Mention | Equation must appear in the paper after the first in-text reference to it | ❌ Not implemented — requires cross-referencing equation bbox positions with citation positions | — |
| 15 | Sequential Numbering | Equation labels must form a gapless integer sequence | ✅ | `checkers/equation_checker.py` |
| 16 | Punctuation | A comma is required after an equation when the next text begins with "where", "with", "in which" | ✅ | `checkers/equation_checker.py` |
| 17 | In-text Citation Style | All equation call-outs must use one consistent style (e.g. always "Eq. (N)" or always "equation (N)") | ✅ | `checkers/equation_checker.py` |
| 18 | Delimiter Balance | Opening and closing delimiters must be balanced; scaled delimiters must be used where appropriate | ❌ Not implemented — requires LaTeX/MathML; PDF text layer does not expose math symbols reliably | — |

### Group D — Formatting & Typography (Checks 19–26)

| # | Check Name | Description | Status | Module |
|---|---|---|---|---|
| 19 | En-dash for Ranges | En-dash (–) must be used for numeric ranges, not a plain hyphen | ✅ | `checkers/syntax_grammar_checker.py` |
| 20 | Non-breaking Space | Non-breaking space must appear between a number and its unit (e.g. 10 kg) | ✅ | `checkers/syntax_grammar_checker.py` |
| 21 | No Space % / ° | No space before percent or degree symbols (10%, 90°C) | ✅ | `checkers/syntax_grammar_checker.py` |
| 22 | Double Spaces | No double ASCII spaces in running text | ✅ | `checkers/syntax_grammar_checker.py` |
| 23 | Punctuation Spacing | Single space after commas and semicolons; no space before them | ✅ | `checkers/syntax_grammar_checker.py` |
| 24 | Quote Style Consistency | Consistent use of straight (`"`) or curly (`"`) quotes throughout | ✅ | `checkers/syntax_grammar_checker.py` |
| 25 | Spelling Consistency | American and British English spellings must not be mixed | ✅ | `checkers/syntax_grammar_checker.py` |
| 26 | Acronym Definition | Every acronym (3+ capital letters) must be defined at its first occurrence | ✅ | `checkers/syntax_grammar_checker.py` |

### Group E — Typography (PDF-Level Checks, Checks 27–30)

| # | Check Name | Description | Status | Module |
|---|---|---|---|---|
| 27 | En-dash in Ranges (Typography) | PDF-level en-dash vs hyphen check on extracted spans | ✅ | `checkers/typography_checker.py` |
| 28 | Number-Unit Spacing | Space between number and unit (10 ms, not 10ms) | ✅ | `checkers/typography_checker.py` |
| 29 | Percent / Degree No-space | No space before % or ° at the PDF span level | ✅ | `checkers/typography_checker.py` |
| 30 | Section Heading Style | Heading capitalisation must be consistent (title case vs sentence case) | ❌ Not implemented — requires ground-truth for the journal's style guide | — |

---

## Environment Variables Reference

Copy `services/extraction-pipeline/.env.example` to `services/extraction-pipeline/.env` and fill in your keys.

| Variable | Required | Default | Description |
|---|---|---|---|
| `VERIFIER_ENABLED` | No | `false` | Set `true` to enable AI-powered false-positive filtering via LLM |
| `GROQ_API_KEY` | If verifier on | — | Primary Groq API key. Sign up free at https://console.groq.com |
| `GROQ_API_KEY_2` | No | — | Second Groq key — enables load balancing (+30 RPM) |
| `GROQ_API_KEY_3` | No | — | Third Groq key (+30 RPM) |
| `GROQ_API_KEY_4` | No | — | Fourth Groq key (+30 RPM) |
| `CEREBRAS_API_KEY` | No | — | Cerebras fallback key. Sign up free at https://cloud.cerebras.ai |
| `GOOGLE_API_KEY` | No | — | Gemini last-resort key. Get at https://aistudio.google.com/apikey |
| `VERIFIER_TEMPERATURE` | No | `0.1` | LLM sampling temperature for violation verification |
| `VERIFIER_TIMEOUT` | No | `60` | Timeout per LLM request in seconds |
| `VERIFIER_MAX_RETRIES` | No | `3` | Retries on LLM timeout or 500 error |
| `PHRASING_ENABLED` | No | `true` | When true, rewrites violations into human-readable language |

**The pipeline works without any API keys.** Set `VERIFIER_ENABLED=false` to run in pure deterministic mode.

### Backend Environment Variables

Create `backend/.env` if needed:

| Variable | Default | Description |
|---|---|---|
| `PORT` | `5001` | Port for the Express backend |
| `EXTRACTION_SERVICE_URL` | `http://localhost:8004` | URL of the Python extraction pipeline |

---

## API Reference

### Python Extraction Pipeline

```
POST http://localhost:8004/extract
  Content-Type: multipart/form-data
  Body: file=<PDF binary>
  → 200 OK — Structured JSON (see Output JSON Schema below)
  → 400 Bad Request — non-PDF file
  → 500 Internal Server Error — pipeline crash (with detail)

GET http://localhost:8004/health
  → { "status": "ok", "service": "extraction-pipeline", "version": "3.1.0" }

GET http://localhost:8004/health/llm
  → { "status": "archived", "llm_reachable": false, ... }
```

### Node.js Backend

```
POST http://localhost:5001/api/upload
  Content-Type: multipart/form-data
  Body: file=<PDF binary>
  → Proxies to /extract and returns the same structured JSON
  → 503 Service Unavailable — if Python pipeline is unreachable
```

---

## Output JSON Schema

```json
{
  "manuscript": {
    "title": "string",
    "abstract_text": "string",
    "abstract_word_count": 259,
    "keywords": ["string"],
    "authors": ["string"]
  },
  "sections": [
    { "heading_text": "string", "heading_level": 1, "page_number": 2, "bbox": {} }
  ],
  "figures": [
    { "number": 1, "caption_text": "string", "caption_page": 3,
      "image_bbox": {}, "caption_bbox": {}, "first_mention_page": 2 }
  ],
  "tables": [
    { "number": 1, "caption_text": "string", "caption_page": 5,
      "caption_bbox": {}, "table_body_y0": 120, "first_mention_page": 4 }
  ],
  "equations": [
    { "number": 1, "number_format": "(1)", "latex": "",
      "page_number": 3, "bbox": {}, "context_before": "...", "context_after": "..." }
  ],
  "references": [
    { "raw_string": "string", "number": 1, "year": 2020, "doi": "10.1234/...", "bbox": {} }
  ],
  "in_text_citations": [
    { "marker": "[1]", "type": "numeric-bracket", "page_number": 2 }
  ],
  "figures_tables_checks": {
    "figure_sequential_numbering": { "passed": true, "violations": [], "detail": "..." },
    "table_sequential_numbering":  { "passed": true, "violations": [], "detail": "..." },
    "figure_chronological_order":  { "passed": true, "violations": [], "detail": "..." },
    "table_chronological_order":   { "passed": true, "violations": [], "detail": "..." },
    "table_caption_above":         { "passed": true, "violations": [], "detail": "..." },
    "figure_caption_below":        { "passed": true, "violations": [], "detail": "..." },
    "figure_parts_mention":        { "passed": true, "violations": [], "detail": "..." }
  },
  "syntax_grammar_checks": {
    "acronym_definition":           { "passed": true, "violations": [], "detail": "..." },
    "en_dash_ranges":               { "passed": true, "violations": [], "detail": "..." },
    "nonbreaking_space_units":      { "passed": true, "violations": [], "detail": "..." },
    "no_space_percent_degree":      { "passed": true, "violations": [], "detail": "..." },
    "double_spaces":                { "passed": true, "violations": [], "detail": "..." },
    "punctuation_spacing":          { "passed": true, "violations": [], "detail": "..." },
    "quote_style_consistency":      { "passed": true, "violations": [], "detail": "..." },
    "english_spelling_consistency": { "passed": true, "violations": [], "detail": "..." }
  },
  "equation_checks": {
    "equation_sequential_numbering": { "passed": true, "violations": [], "detail": "..." },
    "equation_punctuation":          { "passed": true, "violations": [], "detail": "..." },
    "in_text_reference_consistency": { "passed": true, "violations": [], "detail": "..." }
  },
  "reference_checks": {
    "style_compliance":      { "passed": true, "violations": [], "detail": "..." },
    "bidirectional_match":   { "passed": true, "violations": [], "detail": "..." },
    "metadata_completeness": { "passed": true, "violations": [], "detail": "..." },
    "doi_url_liveness":      { "passed": true, "violations": [], "detail": "..." },
    "sequential_ordering":   { "passed": true, "violations": [], "detail": "..." },
    "field_consistency":     { "passed": true, "violations": [], "detail": "..." }
  },
  "estimated_word_count": 11260,
  "total_pages_processed": 19,
  "pipeline_timings": {
    "pymupdf_s": 0.41, "structural_s": 0.06, "equation_extraction_s": 0.22,
    "regex_s": 0.05, "typography_s": 0.0, "figures_tables_s": 0.01,
    "syntax_grammar_s": 0.01, "equation_checks_s": 0.01,
    "reference_checks_s": 0.35, "total_s": 1.12
  }
}
```

Each **violation** object has:

```json
{
  "page": 7,
  "evidence": "Human-readable evidence string from AI verifier or detector",
  "detail": "Short machine description",
  "suggestion": "How to fix this violation"
}
```

---

## Performance

| Paper | Pages | Without AI Verifier | With AI Verifier |
|---|---|---|---|
| 43-page paper (AEO) | 43 | ~0.6 s | ~62 s (LLM at 30 RPM) |
| 34-page paper | 34 | ~0.55 s | ~45 s |
| 18-page paper | 18 | ~0.35 s | ~25 s |

> **Note on AI Verifier timing:** The verifier processes all candidates in a single batch via Groq's free tier, which is rate-limited at 30 requests per minute. The pipeline is bounded by API rate limits, not computation. With paid Groq keys at higher RPM, total time drops to ~5–10 s.

---

## Development Notes

### Running Without API Keys

Set `VERIFIER_ENABLED=false` in `.env`. The pipeline will return all deterministic violations (~0.4 s per paper). No API keys required.

### Adding a New Check

1. Add your detection logic to the appropriate checker in `modules/checkers/`
2. Call it from `orchestrator.py` in the relevant step
3. Add a declarative rule to `modules/verifier/verifier_rules.py` so the AI verifier knows how to evaluate it
4. Update `docs/checks_reference.md`

### Adding More LLM Capacity

Add up to 4 Groq API keys (`GROQ_API_KEY` through `GROQ_API_KEY_4`). The verifier distributes requests across all keys in a round-robin. Each key adds 30 RPM free capacity.

### Unimplemented Checks (for Phase 2)

- **Check 14** (Equation Placement After Mention): Requires correlating equation `bbox` positions with in-text call-out positions across the PDF.
- **Check 18** (Delimiter Balance): Requires LaTeX or MathML; the PDF text layer does not expose raw math symbols reliably.
- **Check 30** (Section Heading Style): Requires a journal-specific style guide as ground truth.

### Recent Fixes & Improvements

- **Typography Checks (Double Spaces):** Mitigated a major source of false positives from PyMuPDF `TEXT_PRESERVE_WHITESPACE` (which natively extracts justified PDF text with 2-3 spaces between words). The double-space check now explicitly ignores standard justification artifacts and only flags 4+ consecutive spaces, which strongly indicate genuine authoring/formatting errors.
- **En-dash Ranges:** Fixed issues where citation brackets (e.g. `[23-25]`) and DOI links containing hyphens were incorrectly flagged as numerical range errors. The pipeline now cleanly strips brackets and DOIs prior to running the en-dash scanner.
- **Acronym Definitions:** Greatly expanded the domain skip-list (`RMSE`, `CNN`, `PSO`, `NIC`, `AUC`, etc.) to prevent common academic terminology from being flagged as undefined. Increased the lookback window to 600 characters to better support multi-column PDF layouts where expansions appear far from the parenthesis in the extracted text stream.

---

*For detailed pipeline internals, see [`docs/pipeline_architecture.md`](docs/pipeline_architecture.md).*  
*For the full checks specification, see [`docs/checks_reference.md`](docs/checks_reference.md).*  
*For equation extraction design decisions, see [`docs/equation_checks.md`](docs/equation_checks.md).*
