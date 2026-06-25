"""
nuextract_client.py
===================
NuExtract3 client — two modes: METADATA (page 1) and BODY (all other pages).
References are handled by regex_extractor, not NuExtract.
"""

from __future__ import annotations

import json
import time
from enum import Enum
from typing import Optional, Tuple

import httpx

from nuextract_schema import (
    SCHEMA_METADATA_STR, SCHEMA_BODY_STR,
    INSTRUCTIONS_METADATA, INSTRUCTIONS_BODY,
)

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

NUEXTRACT_BASE_URL: str  = "http://127.0.0.1:8080/v1"
COMPLETION_ENDPOINT: str = f"{NUEXTRACT_BASE_URL}/chat/completions"
MODEL_NAME: str          = "NuExtract3-GGUF"

DEFAULT_TIMEOUT_SECONDS: int   = 300    # generous — some pages take a while
MAX_TOKENS_PER_CALL:     int   = 8000   # with -c 16384 we have plenty of room
TEMPERATURE:             float = 0.0
MAX_RETRIES:             int   = 2
RETRY_BACKOFF_BASE:      float = 3.0


class ExtractionMode(str, Enum):
    METADATA = "metadata"
    BODY     = "body"


_MODE_SCHEMA = {
    ExtractionMode.METADATA: (SCHEMA_METADATA_STR, INSTRUCTIONS_METADATA),
    ExtractionMode.BODY:     (SCHEMA_BODY_STR,     INSTRUCTIONS_BODY),
}


# ─────────────────────────────────────────────────────────────────────────────
# Payload builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_payload(schema_str: str, instructions: str, page_text: str) -> dict:
    user_msg = (
        "<|input|>\n"
        "### Template:\n"
        f"{schema_str}\n\n"
        "### Text:\n"
        f"{page_text}\n"
        "<|output|>"
    )
    return {
        "model":   MODEL_NAME,
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user",   "content": user_msg},
        ],
        "max_tokens":      MAX_TOKENS_PER_CALL,
        "temperature":     TEMPERATURE,
        "response_format": {"type": "json_object"},
        "stream":          False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Client
# ─────────────────────────────────────────────────────────────────────────────

class NuExtractClient:
    def __init__(self, base_url: str = NUEXTRACT_BASE_URL, timeout: int = DEFAULT_TIMEOUT_SECONDS):
        self._endpoint = f"{base_url}/chat/completions"
        self._timeout  = timeout
        self._client   = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=15.0),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "NuExtractClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def health_check(self) -> bool:
        try:
            r = self._client.get(f"{NUEXTRACT_BASE_URL}/models", timeout=httpx.Timeout(10.0))
            return r.status_code < 300
        except Exception as exc:
            print(f"[NuExtractClient] Health check failed: {exc}")
            return False

    def extract(
        self,
        page_text:   str,
        mode:        ExtractionMode,
        page_number: int = 0,
    ) -> Tuple[Optional[dict], Optional[str]]:
        if not page_text or not page_text.strip():
            return {}, None

        schema_str, instructions = _MODE_SCHEMA[mode]
        return self._call(schema_str, instructions, page_text, page_number, mode.value)

    def _call(
        self,
        schema_str:   str,
        instructions: str,
        page_text:    str,
        page_number:  int,
        label:        str,
    ) -> Tuple[Optional[dict], Optional[str]]:
        payload    = _build_payload(schema_str, instructions, page_text)
        last_error = "unknown"

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._client.post(
                    self._endpoint,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )

                if response.status_code != 200:
                    last_error = "http_error"
                    print(f"[NuExtractClient] p{page_number}/{label} attempt {attempt}: HTTP {response.status_code}")
                    _backoff(attempt)
                    continue

                data = response.json()

                try:
                    content_str   = data["choices"][0]["message"]["content"]
                    finish_reason = data["choices"][0].get("finish_reason", "")
                except (KeyError, IndexError, TypeError) as e:
                    last_error = "bad_json"
                    print(f"[NuExtractClient] p{page_number}/{label} attempt {attempt}: bad shape: {e}")
                    _backoff(attempt)
                    continue

                if finish_reason == "length":
                    print(
                        f"[NuExtractClient] p{page_number}/{label}: output TRUNCATED "
                        f"(finish_reason=length). Attempting partial recovery."
                    )
                    recovered = _try_recover_json(content_str)
                    if recovered:
                        print(f"[NuExtractClient] p{page_number}/{label}: partial recovery OK ({len(content_str)} chars).")
                        return recovered, None
                    return None, "truncated"

                try:
                    extracted = json.loads(content_str)
                    if not isinstance(extracted, dict):
                        raise ValueError(f"Expected dict, got {type(extracted)}")
                    print(f"[NuExtractClient] p{page_number}/{label}: OK ({len(content_str)} chars)")
                    return extracted, None

                except (json.JSONDecodeError, ValueError) as json_err:
                    last_error = "bad_json"
                    print(
                        f"[NuExtractClient] p{page_number}/{label} attempt {attempt}: "
                        f"JSON error: {json_err}\n  Snippet: {content_str[:200]}"
                    )
                    recovered = _try_recover_json(content_str)
                    if recovered:
                        print(f"[NuExtractClient] p{page_number}/{label}: recovered.")
                        return recovered, None
                    _backoff(attempt)
                    continue

            except httpx.TimeoutException:
                last_error = "timeout"
                print(f"[NuExtractClient] p{page_number}/{label} attempt {attempt}: Timeout ({self._timeout}s)")
                _backoff(attempt)

            except httpx.ConnectError as exc:
                last_error = "connection"
                print(f"[NuExtractClient] p{page_number}/{label}: Connection refused: {exc}")
                _backoff(attempt)

            except Exception as exc:
                last_error = "unknown"
                print(f"[NuExtractClient] p{page_number}/{label}: {type(exc).__name__}: {exc}")
                _backoff(attempt)

        print(f"[NuExtractClient] p{page_number}/{label}: ALL ATTEMPTS FAILED ({last_error})")
        return None, last_error

    # Legacy wrapper
    def extract_page(self, page_text, page_number=0, is_first_page=False):
        mode = ExtractionMode.METADATA if is_first_page else ExtractionMode.BODY
        return self.extract(page_text, mode=mode, page_number=page_number)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _backoff(attempt: int) -> None:
    wait = min(RETRY_BACKOFF_BASE ** attempt, 15.0)
    print(f"[NuExtractClient] Waiting {wait:.1f}s before retry …")
    time.sleep(wait)


def _try_recover_json(text: str) -> Optional[dict]:
    start = text.find("{")
    if start == -1:
        return None
        
    text_clean = text[start:].strip()
    
    # Try json_repair first (handles incomplete brackets, strings, arrays)
    try:
        import json_repair
        res = json_repair.loads(text_clean)
        if isinstance(res, dict):
            return res
    except Exception:
        pass

    # Try parsing the raw text directly in case it's already valid
    try:
        res = json.loads(text_clean)
        if isinstance(res, dict):
            return res
    except json.JSONDecodeError:
        pass
        
    # Backtrack through '}' brackets from the end
    pos = len(text_clean)
    closures = ["", "}", "]}", "]]}", '"}]}', '"]}]}', '"}', '"]}', '"]]}']
    
    while True:
        pos = text_clean.rfind("}", 0, pos)
        if pos == -1:
            break
            
        candidate = text_clean[:pos + 1]
        for closure in closures:
            try:
                res = json.loads(candidate + closure)
                if isinstance(res, dict):
                    return res
            except json.JSONDecodeError:
                continue
        pos -= 1
        
    return None
