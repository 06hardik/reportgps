# ReportGPS 🔍

**AI-powered research paper validator** — checks your academic PDF for grammar, reference, figure/table, and structural issues, then delivers a downloadable annotated PDF with every issue marked at its exact location.

---

## Architecture

```
d:\reportgps\
├── frontend/          React 18 + Vite + Redux + pdfjs-dist
├── backend/           Express.js orchestration server (port 5000)
└── services/
    ├── regex-checker/       FastAPI :8001 — language, grammar, regex checks
    ├── reference-analyser/  FastAPI :8002 — BibTeX field/consistency checks
    └── figure-analyser/     FastAPI :8003 — pdffigures2 caption placement
```

External: **GROBID** (HF Space) — reference extraction (BibTeX + coordinates)

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Node.js | v18+ | v22 confirmed working |
| Python | 3.10+ | For microservices |
| Java | 11+ | Required by LanguageTool + pdffigures2 |

---

## Setup & Running

### 1. Install backend dependencies

```powershell
cd d:\reportgps\backend
npm install
```

### 2. Install Python service dependencies

Run each in a separate terminal:

```powershell
# Service 1: Regex + Language Checker
cd d:\reportgps\services\regex-checker
pip install -r requirements.txt
python app.py   # starts on :8001
```

```powershell
# Service 2: Reference Analyser
cd d:\reportgps\services\reference-analyser
pip install -r requirements.txt
python app.py   # starts on :8002
```

```powershell
# Service 3: Figure/Table Analyser (requires Java 11)
cd d:\reportgps\services\figure-analyser
pip install -r requirements.txt
python app.py   # starts on :8003
```

### 3. Start the backend

```powershell
cd d:\reportgps\backend
npm run dev   # starts on :5000
```

### 4. Start the frontend

```powershell
cd d:\reportgps\frontend
npm run dev   # starts on :3000
```

Open **http://localhost:3000**

---

## API Overview

### `POST /api/documents/upload`
Upload a PDF for full analysis.

**Request:** `multipart/form-data` with field `document` (PDF file)

**Response:**
```json
{
  "issues": [...],
  "regex_issues": { "metadata": {...}, "disclosures": {...}, ... },
  "llm_issues": [...],
  "annotated_pdf": "/api/documents/annotated/annotated_<filename>.pdf",
  "meta": { "total_issues": 42, "processed_at": "..." }
}
```

### `GET /api/documents/annotated/:filename`
Download the annotated PDF with all issues highlighted.

---

## What Gets Checked

| Category | How |
|----------|-----|
| Grammar & Spelling | LanguageTool (Java) |
| Formatting | Regex: space-before-bracket, etc. |
| Reference Fields | GROBID → BibTeX → ConsistencyHandler |
| Reference Order | Regex on citation numbers |
| Figure Caption Placement | pdffigures2.jar (Java) |
| Disclosures | Keyword search (conflict of interest, funding, etc.) |
| IMRAD Structure | Section heading detection |
| Metadata | Email, keywords, author list regex |

---

## Issue Color Coding (in PDF viewer)

| Color | Category |
|-------|----------|
| 🔴 Red | Spelling/Typos |
| 🟢 Green | Grammar |
| 🔵 Blue | Typography |
| 🟠 Orange | Formatting |
| 🔵 Cyan | References |
| 🟣 Purple | Figure/Table captions |

---

## Environment Variables (backend)

See `backend/.env.example`:

```
PORT=5000
REGEX_SERVICE_URL=http://localhost:8001
REFERENCE_SERVICE_URL=http://localhost:8002
FIGURE_SERVICE_URL=http://localhost:8003
GROBID_URL=https://tmkc-100bar-extraction-engine.hf.space
UPLOADS_DIR=./uploads
```

---

## Notes

- The `regex-checker` service also handles **annotated PDF generation** via `POST /annotate`
- GROBID calls are made in parallel with other analysis for faster total time
- Each service fails gracefully — one failure won't crash the entire pipeline
- Annotated PDFs are stored in `backend/uploads/anonymous/` and served on demand

---

## Extending Checks

All new regex/language rules go in `services/regex-checker/checker.py`.
New reference field requirements go in `services/reference-analyser/analyser.py`.
Publisher-specific rule configs will live in `publisher-rules/` (planned).
