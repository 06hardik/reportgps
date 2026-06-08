import traceback
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, List, Optional

from analyser import referenceErrorParser

app = FastAPI(title="Report GPS - Reference Analyser Service", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReferenceRequest(BaseModel):
    bibtex_string:    str
    coordinate_str:   str
    # New: raw reference strings from PDF extraction (for 5-check pipeline)
    raw_ref_strings:  Optional[List[str]] = None


@app.get("/health")
def health():
    return {"status": "ok", "service": "reference-analyser", "version": "2.0.0"}


@app.post("/analyze")
def analyze(request: ReferenceRequest):
    """
    Accepts:
      - bibtex_string    : BibTeX from GROBID /api/processReferences
      - coordinate_str   : JSON from GROBID /api/referenceAnnotations
      - raw_ref_strings  : (optional) list of raw reference strings from PDF

    Returns list of reference entries enriched with:
      - asterikError / consistencyError  (BibTeX field checks)
      - quality_issues                   (ordering, DOI, casing, completeness, style)
      - page, coordinates                (fitz-ready annotation coords)
    """
    try:
        results = referenceErrorParser(
            bibtex_string   = request.bibtex_string,
            coordinate_str  = request.coordinate_str,
            raw_ref_strings = request.raw_ref_strings,
        )
        return results
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
