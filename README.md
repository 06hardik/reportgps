# ReportGPS 🔍

AI-powered research paper validator for PDF manuscripts. Upload a paper, run language, metadata, disclosure, reference, and figure/table checks, then download the annotated PDF with issue locations marked in the document.

## Architecture

```text
d:\reportgps\
├── frontend/              React 19 + Vite + Redux Toolkit + pdfjs-dist
├── backend/               Express orchestration API (port 5000)
├── services/
│   ├── regex-checker/     FastAPI :8001 - language, regex, structure, annotation
│   ├── reference-analyser/   FastAPI :8002 - BibTeX consistency and reference QA
│   └── figure-analyser/   FastAPI :8003 - pdffigures2 caption placement checks
└── research-papers/       Local sample PDFs used for testing and demos
```

External dependency: GROBID is used for reference extraction and coordinates, currently pointed at the HF Space configured in `backend/.env.example`.

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Node.js | 18+ | The app has been tested with Node 22 |
| Python | 3.10+ | Required for the FastAPI services |
| Java | 11+ | Required by LanguageTool and pdffigures2 |

## Setup

### 1. Install backend dependencies

```powershell
cd d:\reportgps\backend
npm install
```

### 2. Install frontend dependencies

```powershell
cd d:\reportgps\frontend
npm install
```

### 3. Configure environment files

Copy the templates and adjust them only if you need custom endpoints:

```powershell
Copy-Item backend\.env.example backend\.env
Copy-Item frontend\.env.example frontend\.env
```

### 4. Install Python service dependencies

Run each service in its own terminal:

```powershell
cd d:\reportgps\services\regex-checker
pip install -r requirements.txt
python app.py
```

```powershell
cd d:\reportgps\services\reference-analyser
pip install -r requirements.txt
python app.py
```

```powershell
cd d:\reportgps\services\figure-analyser
pip install -r requirements.txt
python app.py
```

### 5. Place the pdffigures2 JAR

The figure analyser requires `pdffigures2.jar` to be copied into `services/figure-analyser/` before it can run:

```powershell
Copy-Item pdffigures2.jar -Destination services\figure-analyser\pdffigures2.jar
```

### 6. Start the backend

```powershell
cd d:\reportgps\backend
npm run dev
```

The API runs on `http://localhost:5000`.

### 7. Start the frontend

```powershell
cd d:\reportgps\frontend
npm run dev
```

The Vite dev server runs on `http://localhost:3000` and proxies `/api` requests to the backend.

## API

### `POST /api/documents/upload`

Uploads a PDF and runs the full analysis pipeline.

Request: `multipart/form-data` with a `document` field containing the PDF.

Response shape:

```json
{
  "issues": [],
  "regex_issues": {},
  "llm_issues": [],
  "annotated_pdf": "/api/documents/annotated/annotated_<filename>.pdf",
  "meta": {
    "filename": "paper.pdf",
    "total_issues": 12,
    "processed_at": "2026-06-08T12:00:00.000Z"
  }
}
```

### `GET /api/documents/annotated/:filename`

Downloads the generated annotated PDF.

### Health checks

Backend: `GET /health`

Services:
- `http://localhost:8001/health`
- `http://localhost:8002/health`
- `http://localhost:8003/health`

## What Gets Checked

| Category | Implementation |
|----------|----------------|
| Grammar and spelling | LanguageTool, filtered to prose text only |
| Metadata | Author email, author list, keyword presence, word count |
| Disclosures | Conflict of interest, ethics, funding, data access, and author contribution statements |
| Structure | IMRAD section detection, abstract, conclusion, and references presence |
| Reference extraction | GROBID BibTeX and reference coordinates |
| Reference quality | Ordering, DOI, journal casing, completeness, and BibTeX consistency |
| Figure/table checks | pdffigures2 caption placement plus figure/table summary checks |

## UI Workflow

1. Drag and drop a PDF or click the upload card.
2. The viewer renders the document immediately from the in-memory file data.
3. Analysis runs in the background while issues populate the sidebar.
4. Clicking an issue jumps to the matching page and overlay.
5. Download the annotated PDF once processing completes.

## Issue Colors

| Color | Category |
|-------|----------|
| Red | Spelling |
| Green | Grammar |
| Blue | Typography |
| Orange | Formatting |
| Cyan | References |
| Purple | Figures and tables |

## Environment Variables

Backend: see `backend/.env.example`

```env
PORT=5000
REGEX_SERVICE_URL=http://localhost:8001
REFERENCE_SERVICE_URL=http://localhost:8002
FIGURE_SERVICE_URL=http://localhost:8003
GROBID_URL=https://tmkc-100bar-extraction-engine.hf.space
UPLOADS_DIR=./uploads
```

Frontend: see `frontend/.env.example`

```env
VITE_API_BASE_URL=http://localhost:5000/api
```

## Notes

- The regex-checker service also handles annotated PDF generation through `POST /annotate`.
- The backend runs the regex, GROBID, and figure services in parallel where possible.
- Annotated PDFs are written to `backend/uploads/anonymous/` and served on demand.
- `backend/test-grobid.mjs` can be used to validate the external GROBID endpoints with a local PDF.

## Extending Checks

- Add new regex or language rules in `services/regex-checker/checker.py`.
- Add new BibTeX or reference rules in `services/reference-analyser/analyser.py`.
- Add new figure/table rules in `services/figure-analyser/analyser.py`.
