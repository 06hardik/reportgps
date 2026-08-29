# ReportGPS — Node.js Backend Proxy

A minimal **Express.js proxy** that bridges the React frontend and the Python extraction pipeline. Its sole responsibility is to receive a PDF file from the browser and forward it to the Python service.

## Why This Layer Exists

The React frontend runs on Vite's dev server (`localhost:3000`). Direct browser → Python requests are blocked by CORS. Rather than configuring CORS on the Python FastAPI service for all possible origins, this Node.js proxy:
1. Receives the file from the browser
2. Buffers it in memory
3. Repackages it as a `multipart/form-data` request
4. Forwards it to `http://localhost:8004/extract`
5. Streams the JSON response back to the browser

## Quick Start

```bash
npm install
npm start
# → Backend server listening on port 5001
```

## Environment Variables

Create a `.env` file in this directory (optional):

```
PORT=5001
EXTRACTION_SERVICE_URL=http://localhost:8004
```

| Variable | Default | Description |
|---|---|---|
| `PORT` | `5001` | Port the Express server listens on |
| `EXTRACTION_SERVICE_URL` | `http://localhost:8004` | URL of the Python extraction pipeline |

## API

### `POST /api/upload`

Accepts a PDF file upload and returns the full structured JSON from the extraction pipeline.

**Request:**
```
Content-Type: multipart/form-data
Body: file=<PDF binary>
```

**Responses:**
- `200 OK` — Structured JSON from extraction pipeline
- `400 Bad Request` — No file uploaded
- `503 Service Unavailable` — Python pipeline unreachable

## Dependencies

| Package | Purpose |
|---|---|
| `express` | HTTP server |
| `cors` | CORS middleware |
| `multer` | Multipart file upload handling |
| `axios` | HTTP client to forward to Python service |
| `form-data` | Build multipart request to Python |
| `dotenv` | Load `.env` config |
