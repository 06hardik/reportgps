import os
import tempfile
import traceback
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import json

from checker import analyze_pdf
from annotator import annotate_pdf

app = FastAPI(title="Report GPS - Regex Checker Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok", "service": "regex-checker"}

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    """
    Accepts a PDF file, runs language/regex/structural analysis.
    Returns issues list + document_checks.
    """
    temp_path = None
    try:
        contents = await file.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(contents)
            temp_path = tmp.name
        results = analyze_pdf(temp_path)
        if "error" in results:
            raise HTTPException(status_code=500, detail=results["error"])
        return results
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)

class AnnotationRequest(BaseModel):
    issues: List[Dict[str, Any]] = []
    llm_issues: List[Dict[str, Any]] = []

@app.post("/annotate")
async def annotate(
    file: UploadFile = File(...),
    issues: str = "",
    llm_issues: str = ""
):
    """
    Accepts a PDF + issues JSON strings, returns annotated PDF bytes.
    """
    try:
        pdf_bytes = await file.read()
        issues_list = json.loads(issues) if issues else []
        llm_issues_list = json.loads(llm_issues) if llm_issues else []
        annotated_bytes = annotate_pdf(pdf_bytes, issues_list, llm_issues_list)
        return Response(
            content=annotated_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=annotated_report.pdf"}
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
