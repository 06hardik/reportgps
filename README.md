# ReportGPS — Extraction Pipeline & Core Architecture

This repository contains the local, offline, high-fidelity hybrid extraction pipeline microservice (`services/extraction-pipeline`) that integrates layout parsing, coordinate mapping, and schema-based LLM extraction.

## Prerequisites

- **Node.js**: 18+ (for frontend and backend testing UIs)
- **Python**: 3.10+ (for extraction services)
- **Ghostscript**: Installed on system (required by Camelot for table parsing)
- **Model cache**: `numind/NuExtract3-GGUF:Q4_K_M` model downloaded locally

---

## Getting Started

### 1. Start the Llama Server (Sequential Context Protected)
To prevent context overflow and memory contention, launch the local `llama.cpp` serve instance sequentially (`--parallel 1`) with a context window of `16384` tokens:
```bash
llama serve -hf numind/NuExtract3-GGUF:Q4_K_M --n-gpu-layers 99 -c 16384 --parallel 1
```

### 2. Start the Python Extraction Microservice
Navigate to the microservice directory, activate the virtual environment, install requirements, and run the FastAPI server on port `8004`:
```bash
cd services/extraction-pipeline
source ../../env/bin/activate
pip install -r requirements.txt
python app.py
```

### 3. Start Backend & Frontend Test UIs (Optional)
Run the Node.js test applications in the root workspace directory.

**Terminal 1 (Backend - port 5000)**:
```bash
cd backend
npm install && npm start
```

**Terminal 2 (Frontend - port 3000)**:
```bash
cd frontend
npm install && npm run dev
```

---

## Core Pipeline Modules

The extraction pipeline in `services/extraction-pipeline` consists of the following core modules:

*   **`app.py`**: The FastAPI server wrapper exposing the `POST /extract` microservice endpoint.
*   **`orchestrator.py`**: The central controller coordinating the 4-stage pipeline execution: base parsing, references/citations extraction, LLM page extraction, and coordinate mapping.
*   **`regex_extractor.py`**: Implements **Stage 2** (citations matching) and the **style-agnostic hybrid layout reference extractor** which segments bibliographies column-by-column using PyMuPDF page-line structures.
*   **`nuextract_client.py`**: Handles API requests to the local Llama server on port `8080` with json formatting and Length recovery.
*   **`nuextract_schema.py`**: Defines the metadata and body JSON schemas. *Note: `body_text` is excluded from the LLM schema to prevent truncation and speed up generation.*
*   **`coordinate_mapper.py`**: Fallback loop algorithm that queries PyMuPDF to search character strings and map absolute coordinate bounding-boxes.
*   **`camelot_extractor.py`**: Invokes Camelot to trace lattice and stream table grid boundaries.
*   **`pymupdf_extractor.py`**: Lower-level fitz reader parsing pages into TextLine objects.
*   **`merger.py`**: Normalizes and consolidates structured objects from different stages into a single JSON schema.

---

## Design Optimizations

1.  **Dynamic Metadata Detection**: The orchestrator scans the first 5 pages for the `\babstract\b` keyword, ensuring that cover sheets or highlights pages are bypassed and the abstract page is correctly processed with the metadata schema.
2.  **References Skipping**: The pipeline detects the references start page during Stage 2 and completely skips LLM extraction on any pages after it, saving substantial processing time and preventing truncation errors on dense bibliography pages.
3.  **Zero-Truncation Body Slicing**: Rather than forcing NuExtract to copy/paste thousands of words of body text verbatim (which caused output context overflows), the pipeline uses python string slicing between heading coordinates in `full_text` to reconstruct `body_text` with 100% precision.
