# ReportGPS — Academic Paper Extraction Pipeline

A fast, offline, zero-LLM PDF extraction pipeline for academic papers.  
Extracts structure, figures, tables, equations, references, and typography checks in **< 2 seconds**.

---

## Quick Start

### 1 — Python Extraction Service (port 8004)

```bash
cd services/extraction-pipeline
python3 -m venv env
source env/bin/activate
pip install -r requirements.txt      # fastapi uvicorn pymupdf httpx
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
Browser (React, port 3000)
        │ POST /api/upload (multipart PDF)
        ▼
Node.js Backend (Express, port 5001)
        │ Proxies to http://localhost:8004/extract
        ▼
Python Extraction Service (FastAPI, port 8004)
        │
        ├─ Step 1: PyMuPDF  (~0.3–0.7 s)
        │     Text + font metadata + image bboxes
        │
        ├─ Step 2: structural_analyzer.py  (~0.03–0.1 s)
        │     Headings, manuscript metadata, figures, tables, equations
        │
        ├─ Step 3a: regex_extractor + typography_checker  (~0.05–0.15 s)
        │     References, citations, typography violations
        │
        ├─ Step 3b: figures_tables_checker.py  (~0.01–0.03 s)
        │     Sequential numbering, chronological order, caption positioning,
        │     sub-part label validation for figures and tables
        │
        └─ Step 3d: syntax_grammar_checker.py  (~0.01–0.02 s)
              Typography, Syntax & Grammar Checks 17-24 (Acronyms, En-dashes,
              Spacing, Quotes, English Spelling Consistency)
```

**Average total: ~0.87 s per paper.**

---

## Pipeline Modules

| File | Purpose |
|---|---|
| `app.py` | FastAPI server — `POST /extract`, `GET /health` |
| `orchestrator.py` | 3-step pipeline coordinator |
| `pymupdf_extractor.py` | PyMuPDF page text + font + image bboxes |
| `structural_analyzer.py` | Heading detection, metadata, figure/table/equation discovery |
| `regex_extractor.py` | References + in-text citations |
| `typography_checker.py` | En-dash, unit-space, percent/degree, latin abbreviation checks |
| `figures_tables_checker.py` | Figure/table sequential numbering, chronological order, caption positioning, sub-part validation |
| `syntax_grammar_checker.py` | Implementation of Checks 17–24 (Acronym definitions, double spaces, quote styles, spelling, etc.) |

---

## Output JSON Schema

```json
{
  "manuscript":  { "title", "abstract_text", "abstract_word_count", "keywords", "authors" },
  "sections":    [{ "heading_text", "heading_level", "page_number", "bbox" }],
  "figures":     [{ "number", "caption_text", "caption_page", "image_bbox", "caption_bbox", "first_mention_page" }],
  "tables":      [{ "number", "caption_text", "caption_page", "caption_bbox", "table_body_y0", "first_mention_page" }],
  "equations":   [{ "number", "number_format", "raw_text", "page_number" }],
  "references":  [{ "raw_string", "number", "year", "doi", "bbox" }],
  "in_text_citations": [{ "marker", "page_number" }],
  "typography":  { "en_dash_violations", "number_unit_violations", "percent_degree_violations", "latin_abbrev_violations" },
  "figures_tables_checks": {
    "figure_sequential_numbering": { "passed", "found_sequence", "missing_numbers", "duplicate_numbers", "detail" },
    "table_sequential_numbering":  { "passed", "found_sequence", "missing_numbers", "duplicate_numbers", "detail" },
    "figure_chronological_order":  { "passed", "violations", "detail" },
    "table_chronological_order":   { "passed", "violations", "detail" },
    "table_caption_above":         { "passed", "violations", "skipped", "detail" },
    "figure_caption_below":        { "passed", "violations", "skipped", "detail" },
    "figure_parts_mention":        { "passed", "violations", "detail" }
  },
  "syntax_grammar_checks": {
    "acronym_definition":          { "passed", "violations", "detail" },
    "en_dash_ranges":              { "passed", "violations", "detail" },
    "nonbreaking_space_units":     { "passed", "violations", "detail" },
    "no_space_percent_degree":     { "passed", "violations", "detail" },
    "double_spaces":               { "passed", "violations", "detail" },
    "punctuation_spacing":         { "passed", "violations", "detail" },
    "quote_style_consistency":     { "passed", "violations", "detail" },
    "english_spelling_consistency":{ "passed", "violations", "detail" }
  },
  "estimated_word_count": 11260,
  "total_pages_processed": 19,
  "pipeline_timings": { "pymupdf_s", "structural_s", "regex_s", "typography_s", "figures_tables_s", "syntax_grammar_s", "total_s" }
}
```

---

## Figures & Tables Validation Checks

All checks run via `figures_tables_checker.py` after structural analysis. Each check returns `passed` (bool) and `detail` (human-readable verdict).

| Check | Rule | Data Used |
|---|---|---|
| **Check 7** — Figure Sequential Numbering | Figures must be numbered 1, 2, 3 … with no gaps or duplicates | `figures[i]["number"]` |
| **Check 8** — Table Sequential Numbering | Tables must be numbered 1, 2, 3 … with no gaps or duplicates | `tables[i]["number"]` |
| **Check 9** — Figure Chronological Order | Figures must be first mentioned in ascending order in body text | `figures[i]["first_mention_page"]` |
| **Check 10** — Table Chronological Order | Tables must be first mentioned in ascending order in body text | `tables[i]["first_mention_page"]` |
| **Check 11** — Table Caption Above Table | Table caption must be positioned above the table body (y-coordinate comparison) | `tables[i]["caption_bbox"]["y1"]`, `tables[i]["table_body_y0"]` |
| **Check 12** — Figure Caption Below Figure | Figure caption must be positioned below the image (y-coordinate comparison) | `figures[i]["caption_bbox"]["y0"]`, `figures[i]["image_bbox"]["y1"]` |
| **Check 13** — Figure Parts Mention | Sub-part labels `(a)`, `(b)`, `(c)` … in figure captions must be consecutive starting from `(a)` | `figures[i]["caption_text"]` via regex |

---

## Typography, Syntax & Grammar Validation Checks

All checks run via `syntax_grammar_checker.py` after structural analysis. Each check returns `passed` (bool) and `detail` (human-readable verdict), along with detailed `violations`. 

| Check | Rule | Data Used |
|---|---|---|
| **Check 17** — Acronym Definition | Any acronym (3+ capital letters) must be fully defined in parentheses at its first occurrence | `full_text` (regex + initials matching heuristic) |
| **Check 18** — En-dash for Ranges | En-dash (`–`) must be used for number ranges instead of hyphen/double-hyphen (`10-20`) | `body_text` |
| **Check 19** — Non-breaking Space for Units | Non-breaking space (U+00A0) must be used between numbers and standard units (`10 kg`) | `body_text` |
| **Check 20** — No Space for Percentages/Degrees | No space should occur before `%` or degree notation (`10%`, `90°C`) | `body_text` |
| **Check 21** — Double Spaces | No accidental double ASCII spaces between non-whitespace characters | `body_text` |
| **Check 22** — Consistent Punctuation Spacing | Space after (but not before) commas and semicolons. Only 1 space after sentence boundaries | `body_text` |
| **Check 23** — Quote Style Consistency | Consistent use of either straight (`"`) or typographic curly (`“”`) double quotes | `full_text` |
| **Check 24** — English Spelling Consistency | American and British English spelling shouldn't be mixed within the document | `body_text` (via predefined Am/Br word pairs) |

---

## Performance (5 test papers)

| Paper | Pages | Time |
|---|---|---|
| Fog Computing + WOA | 18 | 0.55 s |
| GG-GSA | 16 | 0.98 s |
| GOA | 18 | 1.17 s |
| Giza | 19 | 0.81 s |
| WOA + MFO image | 34 | 0.82 s |
| **Average** | **21** | **0.87 s** |

Previous pipeline (NuExtract LLM): 50–175 s per paper.

---

## API Reference

```
POST http://localhost:8004/extract
  Content-Type: multipart/form-data
  file: <PDF binary>
  → returns structured JSON (< 2s typical)

GET  http://localhost:8004/health
  → { status: "ok", version: "3.2.0" }
```
