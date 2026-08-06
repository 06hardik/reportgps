# ReportGPS — Academic Paper Extraction Pipeline

A fast, offline, zero-LLM PDF extraction pipeline for academic papers.  
Extracts structure, figures, tables, equations, references, and typography checks in **< 2 seconds**.

---

## Quick Start

### 1 — Python Extraction Service (port 8004)

```bash
cd services/extraction-pipeline
source ../../env/bin/activate
pip install -r requirements.txt      # fastapi uvicorn pymupdf httpx
python app.py
```

### 2 — Node.js Backend (port 5000)

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
Node.js Backend (Express, port 5000)
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
        └─ Step 3: regex_extractor + typography_checker  (~0.05–0.15 s)
              References, citations, typography violations
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
| `_archive/nuextract_client.py` | Archived — LLM approach (50–175 s, replaced) |

---

## Output JSON Schema

```json
{
  "manuscript":  { "title", "abstract_text", "abstract_word_count", "keywords", "authors" },
  "sections":    [{ "heading_text", "heading_level", "page_number", "bbox" }],
  "figures":     [{ "number", "caption_text", "caption_page", "image_bbox", "first_mention_page" }],
  "tables":      [{ "number", "caption_text", "caption_page", "first_mention_page" }],
  "equations":   [{ "number", "number_format", "raw_text", "page_number" }],
  "references":  [{ "raw_string", "number", "year", "doi", "bbox" }],
  "in_text_citations": [{ "marker", "page_number" }],
  "typography":  { "en_dash_violations", "number_unit_violations", "percent_degree_violations", "latin_abbrev_violations" },
  "estimated_word_count": 11260,
  "total_pages_processed": 19,
  "pipeline_timings": { "pymupdf_s", "structural_s", "regex_s", "typography_s", "total_s" }
}
```

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
