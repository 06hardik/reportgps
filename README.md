# ReportGPS — Academic Paper Validation Pipeline

A multi-layer PDF analysis and validation system for academic research papers.  
It combines fast deterministic extraction (PyMuPDF) with an optional AI Verifier (Groq/Gemini) to catch formatting, structural, and equation issues with high accuracy and minimal false positives.

---

## Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+

### 1 — Python Extraction Service (port 8004)

```bash
cd services/extraction-pipeline
python -m venv env
source env/bin/activate          # Windows: env\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then fill in API keys
python app.py
```

### 2 — Node.js Backend (port 5001)

```bash
cd backend
npm install && npm start
```

### 3 — React Frontend (port 3000)

```bash
cd frontend
npm install && npm run dev
```

Open **http://localhost:3000** → drag & drop a PDF → click **Analyse Document**.

---

## Architecture

```
Browser (React + Vite, port 3000)
        │ POST /api/upload (multipart PDF)
        ▼
Node.js Backend (Express, port 5001)
        │ Proxies to http://localhost:8004/extract
        ▼
Python Extraction Service (FastAPI, port 8004)
        │
        ├─ Step 1: PyMuPDF  (~0.3–0.7 s)
        │     Text + font metadata + image bboxes for every page
        │
        ├─ Step 2: structural_analyzer.py  (~0.03–0.1 s)
        │     Headings, manuscript metadata (title/abstract/keywords/authors),
        │     figure & table discovery, section detection
        │
        ├─ Step 2.5: equation_extractor.py  (~0.05–0.3 s)
        │     Right-margin label scan (supports 1- and 2-column layouts)
        │     Produces equation list with page number, bbox, context
        │
        ├─ Step 3a: regex_extractor.py  (~0.05–0.15 s)
        │     References (numbered, APA) + in-text citations
        │
        ├─ Step 3b: typography_checker.py  (~0.01–0.03 s)
        │     En-dash, unit-space, percent/degree formatting
        │
        ├─ Step 3c: figures_tables_checker.py  (~0.01–0.03 s)
        │     Sequential numbering, chronological order, caption position,
        │     sub-part label validation for figures and tables
        │
        ├─ Step 3d: syntax_grammar_checker.py  (~0.01–0.02 s)
        │     Acronym definitions, double spaces, quote styles, en-dash ranges,
        │     non-breaking spaces, spelling consistency
        │
        ├─ Step 3e: equation_checker.py  (~0.01 s)
        │     Sequential numbering (Check 15), punctuation (Check 16),
        │     in-text citation style consistency (Check 17)
        │
        └─ Step 4: verifier.py  (optional, ~1–3 s)
              Groq (Llama-3) / Gemini AI validates flagged violations,
              filters false positives, generates human-readable evidence
```

**Typical total:** ~1–2 s per paper (with LLM) / < 0.5 s (without).

---

## Pipeline Modules

| File | Purpose |
|---|---|
| `app.py` | FastAPI server — `POST /extract`, `GET /health` |
| `orchestrator.py` | Full pipeline coordinator |
| `pymupdf_extractor.py` | PyMuPDF page text + font + image bboxes |
| `structural_analyzer.py` | Heading detection, manuscript metadata, figure/table discovery |
| `equation_extractor.py` | PDF right-margin label scan for equation numbers |
| `equation_checker.py` | Equation validation checks (15–17) |
| `regex_extractor.py` | References + in-text citations |
| `typography_checker.py` | En-dash, unit-space, percent/degree checks |
| `figures_tables_checker.py` | Figure/table numbering, order, caption positioning |
| `syntax_grammar_checker.py` | Acronym, spacing, quote style, spelling checks |
| `verifier.py` | AI-powered false-positive filter (Groq / Gemini) |
| `verifier_rules.py` | Declarative rule registry for the verifier |
| `verifier_config.py` | Enable/disable verifier, select LLM provider |

---

## Environment Variables

Copy `.env.example` to `.env` and fill in your keys:

```
VERIFIER_ENABLED=true         # false = skip AI verification (faster)
GROQ_API_KEY=gsk_...          # Groq API key (for Llama-3 verification)
GOOGLE_API_KEY=AIza...        # Gemini API key (fallback verifier)
```

The pipeline works without API keys — set `VERIFIER_ENABLED=false` to run in pure deterministic mode.

---

## Validation Checks Reference

### Figures & Tables (figures_tables_checker.py)

| Check | Rule |
|---|---|
| **7** — Figure Sequential Numbering | Figures must be numbered 1, 2, 3 … without gaps or duplicates |
| **8** — Table Sequential Numbering | Tables must be numbered 1, 2, 3 … without gaps or duplicates |
| **9** — Figure Chronological Order | Figures must be first mentioned in ascending numeric order |
| **10** — Table Chronological Order | Tables must be first mentioned in ascending numeric order |
| **11** — Table Caption Above | Table caption must be positioned above the table body |
| **12** — Figure Caption Below | Figure caption must be positioned below the image |
| **13** — Figure Sub-part Labels | Sub-part labels (a), (b) … must be consecutive starting from (a) |

### Syntax & Grammar (syntax_grammar_checker.py)

| Check | Rule |
|---|---|
| **17** — Acronym Definition | Acronyms (3+ capitals) must be defined at their first occurrence |
| **18** — En-dash for Ranges | Use en-dash (–) not hyphen (-) for number ranges |
| **19** — Non-breaking Space | Use non-breaking space between numbers and units |
| **20** — No Space % / ° | No space before `%` or degree symbols |
| **21** — Double Spaces | No double ASCII spaces in running text |
| **22** — Punctuation Spacing | Single space after commas, semicolons, sentence-end periods |
| **23** — Quote Style Consistency | Use either straight (`"`) or curly (`"`) quotes, not both |
| **24** — Spelling Consistency | Don't mix American and British English spellings |

### Equations (equation_extractor.py + equation_checker.py)

| Check | Rule |
|---|---|
| **15** — Sequential Numbering | Equation labels must form a gapless integer sequence |
| **16** — Punctuation | Comma required after equation when text continues with "where", "with", "in which" |
| **17** — In-text Citation Style | All equation references must use one consistent style (e.g. "Eq. (N)") |

---

## Output JSON Schema

```json
{
  "manuscript":  { "title", "abstract_text", "abstract_word_count", "keywords", "authors" },
  "sections":    [{ "heading_text", "heading_level", "page_number", "bbox" }],
  "figures":     [{ "number", "caption_text", "caption_page", "image_bbox", "caption_bbox", "first_mention_page" }],
  "tables":      [{ "number", "caption_text", "caption_page", "caption_bbox", "table_body_y0", "first_mention_page" }],
  "equations":   [{ "number", "number_format", "latex", "page_number", "bbox", "context_before", "context_after" }],
  "references":  [{ "raw_string", "number", "year", "doi", "bbox" }],
  "in_text_citations": [{ "marker", "page_number" }],
  "figures_tables_checks": {
    "figure_sequential_numbering": { "passed", "violations", "detail" },
    "table_sequential_numbering":  { "passed", "violations", "detail" },
    "figure_chronological_order":  { "passed", "violations", "detail" },
    "table_chronological_order":   { "passed", "violations", "detail" },
    "table_caption_above":         { "passed", "violations", "detail" },
    "figure_caption_below":        { "passed", "violations", "detail" },
    "figure_parts_mention":        { "passed", "violations", "detail" }
  },
  "syntax_grammar_checks": {
    "acronym_definition":           { "passed", "violations", "detail" },
    "en_dash_ranges":               { "passed", "violations", "detail" },
    "nonbreaking_space_units":      { "passed", "violations", "detail" },
    "no_space_percent_degree":      { "passed", "violations", "detail" },
    "double_spaces":                { "passed", "violations", "detail" },
    "punctuation_spacing":          { "passed", "violations", "detail" },
    "quote_style_consistency":      { "passed", "violations", "detail" },
    "english_spelling_consistency": { "passed", "violations", "detail" }
  },
  "equation_checks": {
    "equation_sequential_numbering":  { "passed", "violations", "detail" },
    "equation_punctuation":           { "passed", "violations", "detail" },
    "in_text_reference_consistency":  { "passed", "violations", "detail" }
  },
  "estimated_word_count": 11260,
  "total_pages_processed": 19,
  "pipeline_timings": { "pymupdf_s", "structural_s", "equation_extraction_s", "regex_s", "typography_s", "figures_tables_s", "syntax_grammar_s", "equation_checks_s", "total_s" }
}
```

---

## API Reference

```
POST http://localhost:8004/extract
  Content-Type: multipart/form-data
  file: <PDF binary>
  → returns structured JSON (< 2s typical)

GET  http://localhost:8004/health
  → { "status": "ok", "version": "3.2.0" }
```

---

## Performance

| Paper | Pages | Time |
|---|---|---|
| AEO (43 pages) | 43 | ~0.6 s |
| WOA + MFO | 34 | 0.82 s |
| Fog Computing | 18 | 0.55 s |
| **Average** | **~25** | **~0.7 s** |

*(Times are without the optional AI verifier. With LLM: +1–3 s depending on API.)*

---

## For New Developers

See [`docs/pipeline_architecture.md`](docs/pipeline_architecture.md) for a deep dive into each pipeline step.

See [`docs/equation_checks.md`](docs/equation_checks.md) for details on how equation labels are extracted from 2-column PDFs and what each equation check does.

See [`docs/checks_reference.md`](docs/checks_reference.md) for a complete quick-reference of all validation checks.
