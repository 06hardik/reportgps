# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: Builder — installs all Python dependencies
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# System deps needed by PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: Runtime — lean image with only what's needed to run
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /install /usr/local

# Copy application source (excludes everything in .dockerignore)
COPY . .

# Expose the FastAPI port
EXPOSE 8004

# Run with uvicorn — host 0.0.0.0 so Docker can reach it
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8004", "--log-level", "info"]
