"""
app.py
======
FastAPI service wrapper for the lean extraction pipeline (v3.0).

Endpoints:
  POST /extract      — accepts a PDF, runs the full pipeline, returns JSON
  GET  /health       — liveness probe
  GET  /health/llm   — returns 'archived' (NuExtract LLM has been archived)

Port: 8004  (distinct from existing services: 8001, 8002, 8003)

The JSON response from POST /extract is the full structured document dict
produced by orchestrator.extract_document().  The downstream Node.js backend
(documentProcessor.js) will consume this response and pass the structured data
to each linting service.

Typical response time: < 2 seconds per paper.
"""

import os
import tempfile
import traceback

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from orchestrator import extract_document

app = FastAPI(
    title="ReportGPS — Extraction Pipeline",
    description=(
        "Lean PDF extraction service (v3.0). "
        "PyMuPDF + heuristic structural analysis + regex. "
        "No LLM. Accepts a PDF and returns a structured JSON document."
    ),
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Health checks
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status":  "ok",
        "service": "extraction-pipeline",
        "version": "3.0.0",
    }


@app.get("/health/llm")
def health_llm():
    """NuExtract LLM has been archived — this endpoint now always returns 'archived'."""
    return JSONResponse(
        status_code=200,
        content={
            "status":       "archived",
            "llm_reachable": False,
            "detail": (
                "NuExtract LLM client has been archived. "
                "The pipeline now uses pure heuristic/regex extraction (~1s per paper)."
            ),
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main extraction endpoint
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/extract")
async def extract(file: UploadFile = File(...)):
    """
    Accepts a PDF file upload and runs the lean extraction pipeline.

    Returns the structured document JSON.  Typical time: < 2 seconds.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are accepted (.pdf extension required).",
        )

    temp_path: str = ""
    try:
        # Write to a temporary file — orchestrator needs a file path (not bytes)
        pdf_bytes = await file.read()
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".pdf",
            prefix="reportgps_",
        ) as tmp:
            tmp.write(pdf_bytes)
            temp_path = tmp.name

        result = extract_document(temp_path)

        # Surface fatal errors as HTTP 500
        if "error" in result and not result.get("references") and not result.get("figures"):
            raise HTTPException(
                status_code=500,
                detail=result["error"],
            )

        return result

    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Extraction pipeline error: {exc}",
        )
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Dev server entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004, log_level="info")
