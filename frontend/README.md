# ReportGPS Frontend

This package contains the Vite + React client for ReportGPS.

## Development

```powershell
cd d:\reportgps\frontend
npm install
npm run dev
```

The dev server runs on `http://localhost:3000` and proxies `/api` to the backend at `http://localhost:5000`.

## Environment

If you need to point the client at a different backend URL, copy `.env.example` to `.env` and set `VITE_API_BASE_URL`.

## Build

```powershell
npm run build
```

See the root README for the full system setup and backend/service instructions.
