import os
import tempfile
import traceback
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from analyser import grade_pdf

# Path to the JAR file (must be in same directory as this app.py)
JAR_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdffigures2.jar")

app = FastAPI(title="Report GPS - Figure Analyser Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok", "service": "figure-analyser", "jar_found": os.path.exists(JAR_PATH)}

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    """
    Accepts a PDF file, runs pdffigures2, returns figure/table caption issues.
    """
    temp_path = None
    try:
        contents = await file.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(contents)
            temp_path = tmp.name
        issue_list = grade_pdf(temp_path, JAR_PATH)
        return issue_list
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
