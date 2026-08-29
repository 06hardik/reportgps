# ReportGPS — React Frontend

The React + Vite single-page application that provides the user interface for the ReportGPS academic paper validation platform.

## Quick Start

```bash
npm install
npm run dev
# → http://localhost:3000
```

## Features

- **Drag-and-drop PDF upload** with file size validation
- **Embedded PDF viewer** using `pdfjs-dist` with page-accurate navigation
- **Violation highlighting** — each flagged finding links to its exact page and highlights the relevant text region
- **Category tabs** — results organized into: Figures & Tables / Equations / References / Formatting & Structure
- **Per-check accordion panels** — expand to see individual violations with evidence and fix suggestions
- **Severity badges** — Error / Warning / Info / Pass with color-coded indicators
- **Dark glassmorphism UI** with smooth micro-animations

## Architecture

The entire frontend is a single React component in `src/App.jsx` (~2000 LOC). It communicates with the Node.js backend proxy via `POST /api/upload`.

### Data Flow

```
User drops PDF
  → POST http://localhost:5001/api/upload
  → Backend proxies to http://localhost:8004/extract
  → JSON response drives all UI state
  → PDF.js renders the PDF
  → Violations are overlaid as clickable markers
```

## Scripts

| Command | Description |
|---|---|
| `npm run dev` | Start Vite dev server on port 3000 (hot reload) |
| `npm run build` | Build production bundle to `dist/` |
| `npm run preview` | Preview production build locally |
| `npm run lint` | Run ESLint |

## Key Dependencies

| Package | Purpose |
|---|---|
| `react` / `react-dom` | UI framework |
| `pdfjs-dist` | PDF rendering in the browser |
| `axios` | HTTP requests to backend |
| `lucide-react` | Icon library |
| `vite` | Build tool & dev server |

## Environment

The frontend uses Vite's default config. The backend API URL is hardcoded to `http://localhost:5001` for local development. For production deployment, update the `axios` base URL in `src/App.jsx` to point to your deployed backend.

## Production Build

```bash
npm run build
# Output in dist/ — serve with any static file server
```
