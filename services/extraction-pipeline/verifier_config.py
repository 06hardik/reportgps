"""
verifier_config.py
==================
Configuration constants for the AI Verifier layer.
All values read from environment variables. Safe defaults keep verifier OFF.
"""
from __future__ import annotations
import os

# ── Master switch
VERIFIER_ENABLED: bool = os.getenv("VERIFIER_ENABLED", "false").strip().lower() == "true"

# ── Primary provider ("groq" | "cerebras" | "gemini")
VERIFIER_PROVIDER: str = os.getenv("VERIFIER_PROVIDER", "groq").strip().lower()

# ── Model selection (provider-specific defaults applied in verifier.py)
VERIFIER_MODEL: str  = os.getenv("VERIFIER_MODEL", "")
PHRASING_MODEL: str  = os.getenv("PHRASING_MODEL", VERIFIER_MODEL)

# ── API credentials
GROQ_API_KEY:     str = os.getenv("GROQ_API_KEY",     "")
CEREBRAS_API_KEY: str = os.getenv("CEREBRAS_API_KEY", "")
GOOGLE_API_KEY:   str = os.getenv("GOOGLE_API_KEY",   "")

# ── Multi-key Groq pool (for key rotation / load balancing)
# Collects GROQ_API_KEY plus GROQ_API_KEY_2 ... GROQ_API_KEY_4 (any that are set)
_all_groq_keys = [
    os.getenv("GROQ_API_KEY",   ""),
    os.getenv("GROQ_API_KEY_2", ""),
    os.getenv("GROQ_API_KEY_3", ""),
    os.getenv("GROQ_API_KEY_4", ""),
]
GROQ_API_KEYS: list = [k.strip() for k in _all_groq_keys if k.strip()]

# ── Sampling
VERIFIER_TEMPERATURE: float  = float(os.getenv("VERIFIER_TEMPERATURE", "0.1"))
PHRASING_TEMPERATURE: float  = float(os.getenv("PHRASING_TEMPERATURE", "0.2"))

# ── Reliability
VERIFIER_TIMEOUT_S: int   = int(os.getenv("VERIFIER_TIMEOUT",    "60"))
VERIFIER_MAX_RETRIES: int = int(os.getenv("VERIFIER_MAX_RETRIES", "3"))

# ── Routing: confidence >= threshold + deterministic rule -> skip LLM
# Set to 1.01 to always verify every candidate (benchmarking mode)
SKIP_VERIFIER_CONFIDENCE_THRESHOLD: float = float(
    os.getenv("SKIP_VERIFIER_CONFIDENCE_THRESHOLD", "1.01")
)

# ── Feature flags
PHRASING_ENABLED: bool = os.getenv("PHRASING_ENABLED", "true").strip().lower() == "true"
DEBUG_EMIT_CANDIDATES: bool = os.getenv("VERIFIER_DEBUG_CANDIDATES", "false").strip().lower() == "true"

# ── Logging (JSONL file path; "" to disable)
VERIFIER_LOG_PATH: str = os.getenv("VERIFIER_LOG_PATH", "")
