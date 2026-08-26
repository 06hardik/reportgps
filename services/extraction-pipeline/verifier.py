"""
verifier.py
===========
AI Verifier Layer for ReportGPS.

Architecture:
  existing pipeline output (raw check results)
      |
      v
  build_candidates()   -- converts raw violations -> ErrorCandidate list
      |
      v
  VerifierService.verify_all()  -- routes each candidate:
      | skip_verifier=True  ->  pass-through (no LLM)
      | skip_verifier=False ->  GeminiProvider.verify_candidate()
      v
  ValidatedFinding list
      |
      v  (if PHRASING_ENABLED)
  GeminiProvider.phrase_finding()
      |
      v
  FrontendFinding list  -- stored in result["validated_findings"]

IMPORTANT:
  - Does NOT scan the document for new errors.
  - Only validates / reinterprets candidates from the existing pipeline.
  - Gemini receives only the specific evidence for each candidate.
  - All LLM failures return VERIFIER_FAILED (never silently discard candidates).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from verifier_config import (
    VERIFIER_ENABLED, VERIFIER_PROVIDER, VERIFIER_MODEL, PHRASING_MODEL,
    GROQ_API_KEY, GROQ_API_KEYS, CEREBRAS_API_KEY, GOOGLE_API_KEY,
    VERIFIER_TEMPERATURE, PHRASING_TEMPERATURE,
    VERIFIER_TIMEOUT_S, VERIFIER_MAX_RETRIES,
    SKIP_VERIFIER_CONFIDENCE_THRESHOLD,
    PHRASING_ENABLED, DEBUG_EMIT_CANDIDATES, VERIFIER_LOG_PATH,
)
from verifier_rules import get_rule, RULES


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ErrorCandidate:
    """A possible violation detected by the existing deterministic pipeline."""
    candidate_id:        str
    check_id:            str
    check_name:          str
    rule:                str
    category:            str
    page:                Optional[int]
    document_context:    Dict   # layout hints, page_count, etc.
    evidence:            List[Dict]  # all data needed to verify this candidate
    detector_raw:        Dict   # the original violation dict verbatim
    detector_confidence: float  # 0.0 – 1.0
    skip_verifier:       bool   # True = deterministic, no LLM needed
    status:              str = "UNVERIFIED"


@dataclass
class ValidatedFinding:
    """The result after the verifier has processed an ErrorCandidate."""
    finding_id:           str
    source_candidate_id:  str
    decision:             str   # VALID | FALSE_POSITIVE | VALID_REINTERPRETED | UNCERTAIN | VERIFIER_FAILED
    check_id:             str
    check_name:           str
    category:             str
    page:                 Optional[int]
    actual_issue:         Optional[str]
    confidence:           float
    # User-facing phrased fields (populated by phrasing layer)
    title:                str = ""
    why_flagged:          str = ""
    evidence_summary:     str = ""
    recommendation:       str = ""
    # Debug / traceability fields
    detector_raw:         Dict = field(default_factory=dict)
    verifier_response:    Dict = field(default_factory=dict)
    verifier_model:       str  = ""
    latency_s:            float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Candidate ID counter
# ─────────────────────────────────────────────────────────────────────────────

_CANDIDATE_COUNTER: int = 0

def _next_candidate_id(check_id: str) -> str:
    global _CANDIDATE_COUNTER
    _CANDIDATE_COUNTER += 1
    prefix = check_id[:6].upper().replace("_", "")
    return f"{prefix}-{str(_CANDIDATE_COUNTER).zfill(3)}"


# ─────────────────────────────────────────────────────────────────────────────
# Evidence builders (one per check family)
# ─────────────────────────────────────────────────────────────────────────────

def _evidence_figure_caption(fig_raw: Dict, violation: Dict) -> List[Dict]:
    return [
        {"id": "violation_detail", "content": violation.get("detail", "")},
        {"id": "figure_number",    "content": str(fig_raw.get("number", "?"))},
        {"id": "caption_text",     "content": fig_raw.get("caption_text", "")},
        {"id": "caption_page",     "content": str(violation.get("page", "?"))},
        {"id": "image_y0",         "content": str(violation.get("image_y0", "?"))},
        {"id": "caption_y1",       "content": str(violation.get("caption_y1", "?"))},
    ]


def _evidence_table_caption(tbl_raw: Dict, violation: Dict) -> List[Dict]:
    return [
        {"id": "violation_detail", "content": violation.get("detail", "")},
        {"id": "table_number",     "content": str(tbl_raw.get("number", "?"))},
        {"id": "caption_text",     "content": tbl_raw.get("caption_text", "")},
        {"id": "caption_page",     "content": str(violation.get("page", "?"))},
        {"id": "caption_y0",       "content": str(violation.get("caption_y0", "?"))},
        {"id": "table_body_y0",    "content": str(violation.get("table_body_y0", "?"))},
    ]


def _evidence_chronological(violation: Dict, obj_type: str) -> List[Dict]:
    return [
        {"id": "violation_detail",   "content": violation.get("detail", "")},
        {"id": "object_type",        "content": obj_type},
        {"id": "object_number",      "content": str(violation.get(obj_type, violation.get("figure", violation.get("table", "?"))))},
        {"id": "first_mention_page", "content": str(violation.get("mentioned_on_page", "?"))},
        {"id": "previous_object",    "content": str(violation.get(f"before_{obj_type}", violation.get("before_table", violation.get("before_figure", "?"))))},
        {"id": "previous_page",      "content": str(violation.get("before_page", "?"))},
    ]


def _evidence_parts(violation: Dict) -> List[Dict]:
    return [
        {"id": "violation_detail", "content": violation.get("detail", "")},
        {"id": "figure_number",    "content": str(violation.get("figure", "?"))},
        {"id": "found_parts",      "content": str(violation.get("found_parts", []))},
        {"id": "missing_parts",    "content": str(violation.get("missing_parts", []))},
    ]


def _evidence_acronym(violation: Dict) -> List[Dict]:
    return [
        {"id": "violation_detail",  "content": violation.get("detail", "")},
        {"id": "acronym",           "content": violation.get("acronym", "")},
        {"id": "first_occurrence",  "content": violation.get("context", "")},
    ]


def _evidence_generic(violation: Dict) -> List[Dict]:
    return [
        {"id": "violation_detail", "content": violation.get("detail", str(violation))},
        {"id": "context",          "content": violation.get("context", "")},
        {"id": "found",            "content": str(violation.get("found", ""))},
    ]


def _evidence_reference(violation: Dict) -> List[Dict]:
    return [
        {"id": "violation_detail", "content": violation.get("detail", "")},
        {"id": "ref_id",           "content": str(violation.get("ref_id", violation.get("number", "?")))},
        {"id": "page",             "content": str(violation.get("page", "?"))},
        {"id": "context",          "content": violation.get("context", "")},
        {"id": "suggestion",       "content": violation.get("suggestion", "")},
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Candidate builder — converts raw pipeline output into ErrorCandidate list
# ─────────────────────────────────────────────────────────────────────────────

def build_candidates(raw_result: Dict) -> List[ErrorCandidate]:
    """
    Convert the orchestrator raw result dict into a flat list of ErrorCandidates.

    Only checks marked skip_verifier=False are emitted for LLM verification.
    Deterministic checks are still emitted but with skip_verifier=True so they
    pass straight through without an LLM call.
    """
    candidates: List[ErrorCandidate] = []

    doc_ctx = {
        "page_count":    raw_result.get("total_pages_processed", 0),
        "document_type": "research_paper",
    }

    ft = raw_result.get("figures_tables_checks", {})
    sg = raw_result.get("syntax_grammar_checks", {})
    rc = raw_result.get("reference_checks", {})
    figs   = {f["number"]: f for f in raw_result.get("figures", []) if isinstance(f.get("number"), int)}
    tables = {t["number"]: t for t in raw_result.get("tables",  []) if isinstance(t.get("number"), int)}

    # ── Figures & Tables checks ───────────────────────────────────────────────

    # Check 12: Figure caption below
    for v in (ft.get("figure_caption_below") or {}).get("violations", []):
        rule = get_rule("figure_caption_below")
        fig_obj = figs.get(v.get("figure"), {})
        candidates.append(ErrorCandidate(
            candidate_id=        _next_candidate_id("figure_caption_below"),
            check_id=            "figure_caption_below",
            check_name=          rule["check_name"],
            rule=                rule["rule"],
            category=            rule["category"],
            page=                v.get("page"),
            document_context=    doc_ctx,
            evidence=            _evidence_figure_caption(fig_obj, v),
            detector_raw=        v,
            detector_confidence= rule["detector_confidence"],
            skip_verifier=       rule["skip_verifier"],
        ))

    # Check 11: Table caption above
    for v in (ft.get("table_caption_above") or {}).get("violations", []):
        rule = get_rule("table_caption_above")
        tbl_obj = tables.get(v.get("table"), {})
        candidates.append(ErrorCandidate(
            candidate_id=        _next_candidate_id("table_caption_above"),
            check_id=            "table_caption_above",
            check_name=          rule["check_name"],
            rule=                rule["rule"],
            category=            rule["category"],
            page=                v.get("page"),
            document_context=    doc_ctx,
            evidence=            _evidence_table_caption(tbl_obj, v),
            detector_raw=        v,
            detector_confidence= rule["detector_confidence"],
            skip_verifier=       rule["skip_verifier"],
        ))

    # Checks 7 & 8: Sequential numbering (deterministic)
    for check_id, key in [("figure_sequential_numbering", "figure_sequential_numbering"),
                          ("table_sequential_numbering",  "table_sequential_numbering")]:
        chk = ft.get(key, {})
        if not chk.get("passed", True):
            rule = get_rule(check_id)
            candidates.append(ErrorCandidate(
                candidate_id=        _next_candidate_id(check_id),
                check_id=            check_id,
                check_name=          rule["check_name"],
                rule=                rule["rule"],
                category=            rule["category"],
                page=                None,
                document_context=    doc_ctx,
                evidence=            [{"id": "detail", "content": chk.get("detail", "")}],
                detector_raw=        chk,
                detector_confidence= rule["detector_confidence"],
                skip_verifier=       rule["skip_verifier"],
            ))

    # Chronological order checks
    for check_id, key, obj_type in [
        ("figure_chronological_order", "figure_chronological_order", "figure"),
        ("table_chronological_order",  "table_chronological_order",  "table"),
    ]:
        rule = get_rule(check_id)
        for v in (ft.get(key) or {}).get("violations", []):
            candidates.append(ErrorCandidate(
                candidate_id=        _next_candidate_id(check_id),
                check_id=            check_id,
                check_name=          rule["check_name"],
                rule=                rule["rule"],
                category=            rule["category"],
                page=                v.get("mentioned_on_page"),
                document_context=    doc_ctx,
                evidence=            _evidence_chronological(v, obj_type),
                detector_raw=        v,
                detector_confidence= rule["detector_confidence"],
                skip_verifier=       rule["skip_verifier"],
            ))

    # Figure parts mention
    rule = get_rule("figure_parts_mention")
    for v in (ft.get("figure_parts_mention") or {}).get("violations", []):
        candidates.append(ErrorCandidate(
            candidate_id=        _next_candidate_id("figure_parts_mention"),
            check_id=            "figure_parts_mention",
            check_name=          rule["check_name"],
            rule=                rule["rule"],
            category=            rule["category"],
            page=                None,
            document_context=    doc_ctx,
            evidence=            _evidence_parts(v),
            detector_raw=        v,
            detector_confidence= rule["detector_confidence"],
            skip_verifier=       rule["skip_verifier"],
        ))

    # ── Syntax & Grammar checks ───────────────────────────────────────────────

    _sg_map = [
        ("acronym_definition",           _evidence_acronym),
        ("quote_style_consistency",      _evidence_generic),
        ("english_spelling_consistency", _evidence_generic),
        ("en_dash_ranges",               _evidence_generic),
        ("nonbreaking_space_units",      _evidence_generic),
        ("no_space_percent_degree",      _evidence_generic),
        ("double_spaces",                _evidence_generic),
        ("punctuation_spacing",          _evidence_generic),
    ]
    for check_id, ev_builder in _sg_map:
        rule = get_rule(check_id)
        for v in (sg.get(check_id) or {}).get("violations", []):
            candidates.append(ErrorCandidate(
                candidate_id=        _next_candidate_id(check_id),
                check_id=            check_id,
                check_name=          rule["check_name"],
                rule=                rule["rule"],
                category=            rule["category"],
                page=                None,
                document_context=    doc_ctx,
                evidence=            ev_builder(v),
                detector_raw=        v,
                detector_confidence= rule["detector_confidence"],
                skip_verifier=       rule["skip_verifier"],
            ))

    # ── Reference checks ──────────────────────────────────────────────────────

    _rc_keys = [
        "style_compliance", "bidirectional_match", "metadata_completeness",
        "doi_url", "sequential_ordering", "field_consistency",
    ]
    for check_id in _rc_keys:
        rule = get_rule(check_id)
        for v in (rc.get(check_id) or {}).get("violations", []):
            candidates.append(ErrorCandidate(
                candidate_id=        _next_candidate_id(check_id),
                check_id=            check_id,
                check_name=          rule["check_name"],
                rule=                rule["rule"],
                category=            rule["category"],
                page=                v.get("page"),
                document_context=    doc_ctx,
                evidence=            _evidence_reference(v),
                detector_raw=        v,
                detector_confidence= rule["detector_confidence"],
                skip_verifier=       rule["skip_verifier"],
            ))

    # ── Equation checks ───────────────────────────────────────────────────────

    eqc = raw_result.get("equation_checks", {})
    _eq_keys = [
        "equation_sequential_numbering", "equation_punctuation",
        "in_text_reference_consistency", "delimiter_balance_scaling"
    ]
    for check_id in _eq_keys:
        rule = get_rule(check_id)
        # Note: check 15 (sequential numbering) is deterministic, so skip_verifier=True
        # However, it returns violations if there are missing/duplicate numbers
        chk = eqc.get(check_id) or {}
        # if the check didn't pass but there are no explicit violations, fallback
        if not chk.get("passed", True) and not chk.get("violations", []):
             candidates.append(ErrorCandidate(
                candidate_id=        _next_candidate_id(check_id),
                check_id=            check_id,
                check_name=          rule["check_name"],
                rule=                rule["rule"],
                category=            rule["category"],
                page=                None,
                document_context=    doc_ctx,
                evidence=            chk.get("detail", ""),
                detector_raw=        {"detail": chk.get("detail", "")},
                detector_confidence= rule["detector_confidence"],
                skip_verifier=       rule["skip_verifier"],
            ))
        else:
            for v in chk.get("violations", []):
                candidates.append(ErrorCandidate(
                    candidate_id=        _next_candidate_id(check_id),
                    check_id=            check_id,
                    check_name=          rule["check_name"],
                    rule=                rule["rule"],
                    category=            rule["category"],
                    page=                v.get("page"),
                    document_context=    doc_ctx,
                    evidence=            _evidence_generic(v),
                    detector_raw=        v,
                    detector_confidence= rule["detector_confidence"],
                    skip_verifier=       rule["skip_verifier"],
                ))

    return candidates


_SYSTEM_PROMPT_VERIFY = """You are the final validation layer for ReportGPS, an academic paper analysis tool.
The upstream detection system has identified POSSIBLE issues. You will receive a compact JSON list of candidates.
Each candidate has: id, check (check name), rule, page, issue (detected problem), found (evidence text).

For EACH candidate, determine if it is a genuine violation.

Decision types:
VALID              - Genuine rule violation.
FALSE_POSITIVE     - The detector was wrong.
VALID_REINTERPRETED - Genuine issue, but described incorrectly.
UNCERTAIN          - Insufficient evidence.

Return ONLY a valid JSON array, one object per candidate, in the same order:
[
  {
    "candidate_id": "<the id field from input>",
    "decision": "VALID" | "FALSE_POSITIVE" | "VALID_REINTERPRETED" | "UNCERTAIN",
    "confidence": <float 0.0-1.0>,
    "actual_issue": "<concise description, or null if FALSE_POSITIVE>",
    "reason": "<one sentence>",
    "phrased_title": "<short user-facing title>",
    "phrased_why_flagged": "<one sentence explaining why>",
    "phrased_evidence": "<one sentence of specific evidence. IMPORTANT: You MUST explicitly include the exact Figure or Table number (e.g., 'Figure 2', 'Table 4') if applicable. For reference checks, you MUST include the page number where the citation/reference was found.>",
    "phrased_recommendation": "<one clear action>"
  }
]"""


class LLMProvider:
    """Abstract interface — swap providers without touching business logic."""
    def verify_candidates_batch(self, candidates: List[ErrorCandidate]) -> List[Dict]:
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI-compatible base provider (Groq and Cerebras both use this)
# ─────────────────────────────────────────────────────────────────────────────

class OpenAICompatProvider(LLMProvider):
    """
    Base class for any OpenAI-compatible endpoint.
    Subclasses only need to set _api_key, _base_url, _default_model, _name.
    """
    _api_key:      str = ""
    _base_url:     str = ""
    _default_model: str = ""
    _name:         str = "OpenAI-compat"

    def __init__(self) -> None:
        self._client = None
        self._available = False
        self._model = VERIFIER_MODEL or self._default_model
        if not self._api_key:
            print(f"[Verifier] {self._name}: API key not set — skipped.")
            return
        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=self._api_key, base_url=self._base_url)
            self._available = True
            print(f"[Verifier] {self._name} provider ready (model={self._model})")
        except ImportError:
            print("[Verifier] openai package not installed. Run: pip install openai")
        except Exception as exc:
            print(f"[Verifier] {self._name} init error: {exc}")

    def _call(self, system_prompt: str, user_content: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system",  "content": system_prompt},
                {"role": "user",    "content": user_content},
            ],
            temperature=VERIFIER_TEMPERATURE,
            max_tokens=8192,
            response_format={"type": "json_object"},
            timeout=VERIFIER_TIMEOUT_S,
        )
        return resp.choices[0].message.content.strip()

    def _extract_json(self, raw: str) -> Any:
        clean = raw.strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            clean = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        # Handle wrapped {"results": [...]} format some models return
        parsed = json.loads(clean)
        if isinstance(parsed, dict):
            # Try to find the array inside
            for v in parsed.values():
                if isinstance(v, list):
                    return v
        return parsed

    def _build_payload(self, c: "ErrorCandidate") -> Dict:
        """Full-context payload — no trimming, quality preserved."""
        return {
            "candidate_id": c.candidate_id,
            "check": {
                "id":   c.check_id,
                "name": c.check_name,
                "rule": c.rule,
            },
            "document_context": c.document_context,
            "evidence":         c.evidence,
            "detector_raw":     c.detector_raw,
        }

    def _try_batch(self, candidates: List[ErrorCandidate]) -> List[Dict]:
        """Attempt a single batch call. Raises on 429/413."""
        payload = [self._build_payload(c) for c in candidates]
        user_content = json.dumps(payload, indent=2)
        for attempt in range(VERIFIER_MAX_RETRIES + 1):
            try:
                raw = self._call(_SYSTEM_PROMPT_VERIFY, user_content)
                result = self._extract_json(raw)
                if not isinstance(result, list):
                    result = [result]
                return result
            except Exception as exc:
                err = str(exc)
                if "429" in err or "413" in err or "rate" in err.lower() \
                        or "RESOURCE_EXHAUSTED" in err or "too large" in err.lower():
                    raise
                if attempt < VERIFIER_MAX_RETRIES:
                    time.sleep(1.5 * (attempt + 1))
                else:
                    raise
        raise RuntimeError("Exhausted retries")

    def verify_candidates_batch(self, candidates: List[ErrorCandidate]) -> List[Dict]:
        """Send batch. On 413 (too large) split in half; on 429 raise for rotator."""
        if not self._available or not candidates:
            return [{"candidate_id": c.candidate_id, "decision": "VERIFIER_FAILED"}
                    for c in candidates]
        try:
            return self._try_batch(candidates)
        except Exception as exc:
            err = str(exc)
            if ("413" in err or "too large" in err.lower()) and len(candidates) > 1:
                mid   = len(candidates) // 2
                left  = self.verify_candidates_batch(candidates[:mid])
                right = self.verify_candidates_batch(candidates[mid:])
                return left + right
            elif "429" in err or "rate" in err.lower() or "RESOURCE_EXHAUSTED" in err:
                raise  # GroqKeyRotator handles this
            else:
                print(f"[Verifier] {self._name} error: {exc}")
                return [{"candidate_id": c.candidate_id, "decision": "VERIFIER_FAILED"}
                        for c in candidates]


# ─────────────────────────────────────────────────────────────────────────────
# Groq single-key provider
# ─────────────────────────────────────────────────────────────────────────────

class GroqSingleKeyProvider(OpenAICompatProvider):
    """One Groq API key, groq/compound-mini."""
    _base_url      = "https://api.groq.com/openai/v1"
    _default_model = "groq/compound-mini"

    def __init__(self, api_key: str, index: int) -> None:
        self._name    = f"Groq-{index}"
        self._api_key = api_key
        super().__init__()


# ─────────────────────────────────────────────────────────────────────────────
# Groq Key Rotator — round-robins across multiple API keys
# ─────────────────────────────────────────────────────────────────────────────

class GroqKeyRotator(LLMProvider):
    """
    Distributes batches across N Groq API keys in round-robin order.
    Each key gets 30 RPM free. With 4 keys => 120 RPM effective.
    When a key hits 429, it is cooled-down and the next key is used immediately.
    """

    # How long to cool a key down after a 429 (seconds)
    _COOLDOWN_S = 62

    def __init__(self, api_keys: List[str]) -> None:
        from openai import OpenAI
        self._keys: List[Dict] = []
        for i, key in enumerate(api_keys):
            if not key.strip():
                continue
            try:
                client = OpenAI(api_key=key.strip(),
                                base_url="https://api.groq.com/openai/v1")
                self._keys.append({
                    "name":       f"Groq-{i+1}",
                    "client":     client,
                    "cooldown_until": 0.0,   # epoch time when key is usable again
                })
                print(f"[Verifier] Groq key {i+1}/{len(api_keys)} registered.")
            except Exception as exc:
                print(f"[Verifier] Groq key {i+1} init error: {exc}")

        self._model = VERIFIER_MODEL or "groq/compound-mini"
        self._idx   = 0   # round-robin pointer

        if not self._keys:
            print("[Verifier] WARNING: No Groq keys available.")
        else:
            print(f"[Verifier] GroqKeyRotator ready — {len(self._keys)} key(s), "
                  f"model={self._model}, effective RPM={len(self._keys)*30}")

    @property
    def _available(self) -> bool:
        return bool(self._keys)

    def _next_key(self) -> Optional[Dict]:
        """Return the next available (non-cooled) key, cycling through all."""
        now = time.monotonic()
        n   = len(self._keys)
        for _ in range(n):
            self._idx = (self._idx + 1) % n
            k = self._keys[self._idx]
            if k["cooldown_until"] <= now:
                return k
        return None  # all keys are cooling down

    def _cooldown_remaining(self) -> float:
        """Seconds until the first key recovers."""
        now = time.monotonic()
        return max(0.0, min(k["cooldown_until"] - now for k in self._keys))

    def _call_with_key(self, key_dict: Dict, user_content: str) -> str:
        resp = key_dict["client"].chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT_VERIFY},
                {"role": "user",   "content": user_content},
            ],
            temperature=VERIFIER_TEMPERATURE,
            max_tokens=8192,
            response_format={"type": "json_object"},
            timeout=VERIFIER_TIMEOUT_S,
        )
        return resp.choices[0].message.content.strip()

    def _build_payload(self, c: "ErrorCandidate") -> Dict:
        """Full-context payload — no trimming."""
        return {
            "candidate_id":     c.candidate_id,
            "check":            {"id": c.check_id, "name": c.check_name, "rule": c.rule},
            "document_context": c.document_context,
            "evidence":         c.evidence,
            "detector_raw":     c.detector_raw,
        }

    def _extract_json(self, raw: str) -> Any:
        clean = raw.strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            clean = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        parsed = json.loads(clean)
        if isinstance(parsed, dict):
            for v in parsed.values():
                if isinstance(v, list):
                    return v
        return parsed

    def verify_candidates_batch(self, candidates: List["ErrorCandidate"]) -> List[Dict]:
        if not self._available or not candidates:
            return [{"candidate_id": c.candidate_id, "decision": "VERIFIER_FAILED"}
                    for c in candidates]

        payload      = [self._build_payload(c) for c in candidates]
        user_content = json.dumps(payload, indent=2)

        # Try all keys before giving up on this batch
        tried = 0
        while tried < len(self._keys) + 1:
            key = self._next_key()
            if key is None:
                # All keys cooling — wait for the fastest recovery
                wait = self._cooldown_remaining()
                print(f"[Verifier] All Groq keys cooling. Waiting {wait:.0f}s...")
                time.sleep(wait + 1)
                continue

            try:
                raw    = self._call_with_key(key, user_content)
                result = self._extract_json(raw)
                if not isinstance(result, list):
                    result = [result]
                return result

            except Exception as exc:
                err = str(exc)
                tried += 1

                if "429" in err or "rate" in err.lower() or "RESOURCE_EXHAUSTED" in err:
                    # Parse retry_after from the error message
                    import re
                    m = re.search(r"(\d+\.?\d*)\s*s", err)
                    cooldown = float(m.group(1)) + 2 if m else self._COOLDOWN_S
                    key["cooldown_until"] = time.monotonic() + cooldown
                    avail = sum(1 for k in self._keys if k["cooldown_until"] <= time.monotonic())
                    print(f"[Verifier] {key['name']} rate-limited ({cooldown:.0f}s). "
                          f"{avail}/{len(self._keys)} keys still available.")
                    continue  # try next key immediately

                elif "413" in err or "too large" in err.lower():
                    if len(candidates) > 1:
                        # Split batch and recurse
                        mid   = len(candidates) // 2
                        left  = self.verify_candidates_batch(candidates[:mid])
                        right = self.verify_candidates_batch(candidates[mid:])
                        return left + right
                    # Single candidate still 413 — it's a bad candidate, skip
                    print(f"[Verifier] Single candidate too large, marking FAILED.")
                    return [{"candidate_id": candidates[0].candidate_id,
                             "decision": "VERIFIER_FAILED"}]

                else:
                    # Generic error — log and fail this batch
                    print(f"[Verifier] {key['name']} error: {exc}")
                    return [{"candidate_id": c.candidate_id, "decision": "VERIFIER_FAILED"}
                            for c in candidates]

        # All keys exhausted
        print("[Verifier] All Groq keys failed for this batch.")
        return [{"candidate_id": c.candidate_id, "decision": "VERIFIER_FAILED"}
                for c in candidates]


# ─────────────────────────────────────────────────────────────────────────────
# Gemini fallback (last resort)
# ─────────────────────────────────────────────────────────────────────────────

class GeminiProvider(OpenAICompatProvider):
    """Gemini via its OpenAI-compatible endpoint (last resort only)."""
    _name          = "Gemini"
    _base_url      = "https://generativelanguage.googleapis.com/v1beta/openai/"
    _default_model = "gemini-3.6-flash"

    def __init__(self) -> None:
        self._api_key = GOOGLE_API_KEY
        super().__init__()


class FallbackProvider(LLMProvider):
    """
    Tries GroqKeyRotator first, then Gemini as absolute last resort.
    """
    def __init__(self, providers: List[LLMProvider]) -> None:
        self._providers = [p for p in providers if p._available]
        if not self._providers:
            print("[Verifier] WARNING: No providers available.")

    @property
    def _available(self) -> bool:
        return bool(self._providers)

    def verify_candidates_batch(self, candidates: List[ErrorCandidate]) -> List[Dict]:
        for provider in self._providers:
            try:
                return provider.verify_candidates_batch(candidates)
            except Exception as exc:
                print(f"[Verifier] Provider error, trying next: {exc}")
                continue
        return [{"candidate_id": c.candidate_id, "decision": "VERIFIER_FAILED"}
                for c in candidates]






# ─────────────────────────────────────────────────────────────────────────────
# Verifier Service
# ─────────────────────────────────────────────────────────────────────────────

class VerifierService:
    """
    Orchestrates the batch validate → phrase flow for a list of candidates.
    """
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def verify_all(self, candidates: List[ErrorCandidate]) -> List[ValidatedFinding]:
        findings: List[ValidatedFinding] = []
        
        # 1. Process deterministic checks instantly
        llm_candidates = []
        for cand in candidates:
            if cand.skip_verifier:
                f = self._build_deterministic_finding(cand)
                if f: findings.append(f)
            else:
                llm_candidates.append(cand)
                
        # 2. Process LLM checks in batches of 5 (keeps payloads small, avoids 413)
        batch_size = 5
        for i in range(0, len(llm_candidates), batch_size):
            batch = llm_candidates[i : i + batch_size]
            t0 = time.monotonic()
            results = self._provider.verify_candidates_batch(batch)
            latency = round(time.monotonic() - t0, 3)
            
            # Match results back to candidates
            res_map = {r.get("candidate_id"): r for r in results if isinstance(r, dict)}
            for cand in batch:
                verifier_resp = res_map.get(cand.candidate_id, {})
                f = self._build_llm_finding(cand, verifier_resp, latency)
                if f: findings.append(f)

            if i + batch_size < len(llm_candidates):
                time.sleep(2)  # 2s between batches — 5 candidates/batch stays well under 30 RPM
                
        return findings

    def _build_deterministic_finding(self, candidate: ErrorCandidate) -> Optional[ValidatedFinding]:
        verifier_resp = {"decision": "VALID", "reason": "Deterministic check — skipped LLM."}
        return self._build_finding(candidate, verifier_resp, "VALID", candidate.detector_confidence, candidate.detector_raw.get("detail", ""), 0.0)

    def _build_llm_finding(self, candidate: ErrorCandidate, verifier_resp: Dict, latency: float) -> Optional[ValidatedFinding]:
        decision     = verifier_resp.get("decision", "VERIFIER_FAILED")
        confidence   = float(verifier_resp.get("confidence", 0.5))
        actual_issue = verifier_resp.get("actual_issue") or candidate.detector_raw.get("detail", "")
        return self._build_finding(candidate, verifier_resp, decision, confidence, actual_issue, latency)

    def _build_finding(self, candidate: ErrorCandidate, verifier_resp: Dict, decision: str, confidence: float, actual_issue: str, latency: float) -> Optional[ValidatedFinding]:
        if decision == "FALSE_POSITIVE":
            _log_verifier_call(candidate, verifier_resp, latency)
            return None

        # Build the ValidatedFinding
        finding = ValidatedFinding(
            finding_id=          str(uuid.uuid4())[:8],
            source_candidate_id= candidate.candidate_id,
            decision=            decision,
            check_id=            candidate.check_id,
            check_name=          verifier_resp.get("corrected_check_name") or candidate.check_name,
            category=            candidate.category,
            page=                candidate.page,
            actual_issue=        actual_issue,
            confidence=          confidence,
            detector_raw=        candidate.detector_raw,
            verifier_response=   verifier_resp,
            verifier_model=      VERIFIER_MODEL,
            latency_s=           latency,
        )

        # Populate phrased fields from verifier response
        if "phrased_title" in verifier_resp:
            finding.title          = verifier_resp.get("phrased_title", candidate.check_name)
            finding.why_flagged    = verifier_resp.get("phrased_why_flagged", actual_issue)
            finding.evidence_summary = verifier_resp.get("phrased_evidence", "")
            finding.recommendation = verifier_resp.get("phrased_recommendation", "")

        # Fallback if phrasing failed or was skipped
        if not finding.title:
            finding.title          = candidate.check_name
            finding.why_flagged    = actual_issue or candidate.detector_raw.get("detail", "")
            finding.evidence_summary = ""
            finding.recommendation = candidate.detector_raw.get("suggestion", "Review and correct this issue.")

        _log_verifier_call(candidate, verifier_resp, latency)
        return finding


# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────

def _log_verifier_call(candidate: ErrorCandidate, response: Dict, latency_s: float) -> None:
    if not VERIFIER_LOG_PATH:
        return
    record = {
        "ts":           time.time(),
        "candidate_id": candidate.candidate_id,
        "check_id":     candidate.check_id,
        "decision":     response.get("decision"),
        "confidence":   response.get("confidence"),
        "latency_s":    latency_s,
        "model":        VERIFIER_MODEL,
    }
    try:
        with open(VERIFIER_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point (called from orchestrator.py)
# ─────────────────────────────────────────────────────────────────────────────

_PROVIDER: Optional[FallbackProvider] = None


def verify_candidates(raw_result: Dict) -> List[Dict]:
    """
    Main entry point called from orchestrator.py.

    Args:
        raw_result: The complete orchestrator result dict.

    Returns:
        A list of FrontendFinding dicts (serialisable, safe for JSON).
        Returns empty list if verifier is disabled or fails globally.
    """
    global _CANDIDATE_COUNTER, _PROVIDER
    _CANDIDATE_COUNTER = 0   # reset per document

    if not VERIFIER_ENABLED:
        return []

    if _PROVIDER is None:
        rotator = GroqKeyRotator(GROQ_API_KEYS)
        _PROVIDER = FallbackProvider([
            rotator,           # all Groq keys, round-robin
            GeminiProvider(),  # absolute last resort
        ])

    try:
        candidates = build_candidates(raw_result)
        print(f"[Verifier] Built {len(candidates)} candidate(s). "
              f"LLM-routed: {sum(1 for c in candidates if not c.skip_verifier)}")

        service  = VerifierService(_PROVIDER)
        findings = service.verify_all(candidates)

        # Convert to plain dicts for JSON serialisation
        result_list = []
        for f in findings:
            result_list.append({
                "finding_id":      f.finding_id,
                "source_candidate": f.source_candidate_id,
                "decision":        f.decision,
                "check_id":        f.check_id,
                "category":        f.category,
                "page":            f.page,
                "severity":        "error" if f.decision == "VALID" else "warning",
                "status":          "validated",
                # User-facing
                "title":           f.title,
                "why_flagged":     f.why_flagged,
                "evidence":        f.evidence_summary,
                "recommendation":  f.recommendation,
                # Debug
                "confidence":      f.confidence,
                "actual_issue":    f.actual_issue,
                "verifier_model":  f.verifier_model,
                "latency_s":       f.latency_s,
            })

        print(f"[Verifier] {len(result_list)} validated finding(s) "
              f"({len(candidates) - len(result_list)} false positive(s) discarded).")
        return result_list

    except Exception as exc:
        print(f"[Verifier] Global error (non-fatal): {exc}")
        return []
