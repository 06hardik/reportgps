"""
nuextract_schema.py
===================
Two targeted schemas for NuExtract3:

  SCHEMA_METADATA  →  page 1 (title, abstract, authors, keywords)
  SCHEMA_BODY      →  body pages (sections + body_text, equations, captions,
                       acronyms, typography)

References and in-text citations are handled by regex_extractor.py —
they are mechanical pattern-matching tasks where regex gives 100% recall
with zero token cost, while NuExtract truncates/misses entries.

TOKEN BUDGETS:
  SCHEMA_METADATA: ~400–600 tokens → safe with -c 16384
  SCHEMA_BODY:     ~800–3000 tokens → safe with -c 16384
"""

import json

# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA_METADATA  (page 1 — title, abstract, authors, keywords)
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA_METADATA: dict = {
    "title": "",
    "abstract_text": "",
    "abstract_word_count": 0,
    "keywords": [],
    "authors": [
        {
            "name": "",
            "affiliation": "",
            "email": "",
            "is_corresponding": False
        }
    ],
    "conflict_of_interest": False,
    "funding_statement": False,
    "ethics_statement": False,
    "data_access_statement": False,
    "sections": [
        {
            "heading_text": "",       # VERBATIM
            "heading_number": "",     # "3.1" or ""
            "heading_level": 1,       # 1=top 2=sub 3=sub-sub
            "body_text": "",          # ALL paragraph text under this heading — VERBATIM
            "page_number": 0
        }
    ],
    "equations": [
        {
            "number": 0,              # integer — the N from the (N) label
            "number_format": "",      # "(3)" — VERBATIM as printed
            "raw_text": "",           # the equation text itself, VERBATIM
            "page_number": 0
        }
    ],
    "figures": [
        {
            "label": "",              # "Fig. 3" — VERBATIM
            "number": 0,
            "caption_text": "",       # VERBATIM full caption
            "caption_position": "",   # "above" | "below"
            "page_number": 0
        }
    ],
    "tables": [
        {
            "label": "",
            "number": 0,
            "caption_text": "",       # VERBATIM full caption
            "caption_position": "",   # "above" | "below"
            "page_number": 0
        }
    ],
    "acronyms": [
        {
            "acronym": "",
            "definition": "",
            "page_number": 0
        }
    ]
}

# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA_BODY  (body pages — structure, equations, captions, acronyms)
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA_BODY: dict = {
    "sections": [
        {
            "heading_text": "",       # VERBATIM
            "heading_number": "",     # "3.1" or ""
            "heading_level": 1,       # 1=top 2=sub 3=sub-sub
            "body_text": "",          # ALL paragraph text under this heading — VERBATIM
            "page_number": 0
        }
    ],
    "equations": [
        {
            "number": 0,              # integer — the N from the (N) label
            "number_format": "",      # "(3)" — VERBATIM as printed
            "raw_text": "",           # the equation text itself, VERBATIM
            "page_number": 0
        }
    ],
    "figures": [
        {
            "label": "",              # "Fig. 3" — VERBATIM
            "number": 0,
            "caption_text": "",       # VERBATIM full caption
            "caption_position": "",   # "above" | "below"
            "page_number": 0
        }
    ],
    "tables": [
        {
            "label": "",
            "number": 0,
            "caption_text": "",       # VERBATIM full caption
            "caption_position": "",   # "above" | "below"
            "page_number": 0
        }
    ],
    "acronyms": [
        {
            "acronym": "",
            "definition": "",
            "page_number": 0
        }
    ]
}

# ─────────────────────────────────────────────────────────────────────────────
# Serialised template strings
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA_METADATA_STR: str = json.dumps(SCHEMA_METADATA, indent=2)
SCHEMA_BODY_STR:     str = json.dumps(SCHEMA_BODY,     indent=2)

# ─────────────────────────────────────────────────────────────────────────────
# System instructions per schema
# ─────────────────────────────────────────────────────────────────────────────

INSTRUCTIONS_METADATA: str = """You are a JSON extraction engine for academic paper metadata and structure on the first page.

RULES:
1. VERBATIM ONLY. Do NOT correct spelling, capitalisation, or grammar.
2. title: copy the FULL paper title exactly. If it spans multiple lines, join them.
3. abstract_text: copy the FULL abstract text exactly as written. Do NOT truncate.
   Include EVERY sentence until the abstract ends.
4. abstract_word_count: count words in the abstract (integer).
5. keywords: list each keyword as a separate string.
6. authors: list ALL authors in order with their affiliations.
7. sections: extract EVERY numbered section heading on this page (e.g. "1. Introduction").
   heading_number must be the number prefix (e.g. "1").
   body_text: include ALL paragraph text under the heading until the next heading. VERBATIM.
   body_text MUST be a string, never an array.
8. equations: ONLY extract mathematical equations that have an explicit numbered label
   like (1), (2), etc. printed at the right margin or end of the equation on this page.
9. figures/tables/acronyms: extract captions/acronyms if any exist on this page.
10. Emit ONLY valid JSON matching the template. No prose, no explanation."""

INSTRUCTIONS_BODY: str = """You are a JSON extraction engine for academic paper structure.

RULES:
1. VERBATIM ONLY. Do NOT correct, paraphrase, or summarise anything.
2. sections: extract EVERY numbered section heading on this page (e.g. "1. Introduction",
   "3.1 Limitations"). heading_number must be the number prefix (e.g. "3.1").
   body_text: include ALL paragraph text under the heading until the next heading. VERBATIM.
   body_text MUST be a string, never an array.
3. equations: ONLY extract mathematical equations that have an explicit numbered label
   like (1), (2), (14) etc. printed at the right margin or end of the equation.
   - number: the integer N from the (N) label.
   - number_format: the label as printed, e.g. "(14)".
   - raw_text: the equation text VERBATIM.
   - Do NOT extract: parameter values (α = 20), exponents (10⁻³), table entries,
     references to equations ("Eq. (14)"), or benchmark function definitions (f₁, f₂).
4. figures/tables: copy the FULL caption text verbatim. caption_position is "above" or "below".
5. Only populate fields for content that ACTUALLY appears on this page.
6. Emit ONLY valid JSON matching the template. No prose."""

# Backward compat
TEMPLATE_TOP_KEYS: list = list(SCHEMA_BODY.keys())
# Let's ensure TEMPLATE_TOP_KEYS contains keys from both schemas
TEMPLATE_TOP_KEYS = list(set(list(SCHEMA_METADATA.keys()) + list(SCHEMA_BODY.keys())))
