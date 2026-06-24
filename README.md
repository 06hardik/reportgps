# ReportGPS (Testing UI)

This is a simplified UI and backend for testing the new hybrid extraction pipeline (`services/extraction-pipeline`).

## Prerequisites

- Node.js 18+
- Python 3.10+
- Ghostscript (for Camelot)
- Local NuExtract3 instance running via `llama.cpp`

## Running the extraction pipeline

```bash
# 1. Start NuExtract in a separate terminal:
llama serve -hf numind/NuExtract3-GGUF:Q4_K_M --n-gpu-layers 99

# 2. Start the Python extraction service:
cd services/extraction-pipeline
source ../../env/bin/activate
pip install -r requirements.txt
python app.py
```

## Running the backend and frontend

Open two terminals in the `reportgps` root directory.

Terminal 1 (Backend):
```bash
cd backend
npm install
npm start
```
The backend runs on `http://localhost:5000`.

Terminal 2 (Frontend):
```bash
cd frontend
npm run dev
```
The frontend runs on `http://localhost:3000`. Open this URL in your browser to test PDF uploads.
