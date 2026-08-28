# ReportGPS — All Validation Checks Quick Reference

This document lists every validation check implemented in the pipeline, the module responsible, and the data it uses.

---

## Figures & Tables Checks

**Module:** `figures_tables_checker.py`  
**Invoked by:** `orchestrator.py` Step 3c

| Check | Name | Rule | Data Used |
|---|---|---|---|
| **7** | Figure Sequential Numbering | Figures must be numbered 1, 2, 3 … without gaps or duplicates | `figures[i]["number"]` |
| **8** | Table Sequential Numbering | Tables must be numbered 1, 2, 3 … without gaps or duplicates | `tables[i]["number"]` |
| **9** | Figure Chronological Order | Figures must be first mentioned in the text in ascending numeric order | `figures[i]["first_mention_page"]` |
| **10** | Table Chronological Order | Tables must be first mentioned in the text in ascending numeric order | `tables[i]["first_mention_page"]` |
| **11** | Table Caption Above Table | Table caption must be positioned above the table body (y-coordinate check) | `tables[i]["caption_bbox"]["y1"]`, `tables[i]["table_body_y0"]` |
| **12** | Figure Caption Below Figure | Figure caption must be positioned below the image (y-coordinate check) | `figures[i]["caption_bbox"]["y0"]`, `figures[i]["image_bbox"]["y1"]` |
| **13** | Figure Sub-part Labels | Sub-part labels (a), (b), (c) … must be consecutive starting from (a) | `figures[i]["caption_text"]` via regex |

All checks return `{ "passed": bool, "violations": [...], "detail": str }`.

Each violation includes `page` and `detail` for frontend display.

---

## Syntax & Grammar Checks

**Module:** `syntax_grammar_checker.py`  
**Invoked by:** `orchestrator.py` Step 3d

| Check | Name | Rule | Data Used |
|---|---|---|---|
| **17** | Acronym Definition | Any acronym (3+ capital letters) must be defined in full at first occurrence | `full_text` (regex + initials matching heuristic) |
| **18** | En-dash for Ranges | En-dash (–) must be used for number ranges, not hyphen (10-20) | `body_text` |
| **19** | Non-breaking Space for Units | Non-breaking space (U+00A0) between numbers and standard units (10 kg) | `body_text` |
| **20** | No Space for % / ° | No space before `%` or degree notation (`10%`, `90°C`) | `body_text` |
| **21** | Double Spaces | No accidental double ASCII spaces between non-whitespace characters | `body_text` |
| **22** | Punctuation Spacing | Single space after commas and semicolons; no space before them | `body_text` |
| **23** | Quote Style Consistency | Consistent use of straight (`"`) or curly (`"`) double quotes throughout | `full_text` |
| **24** | Spelling Consistency | American and British English spelling must not be mixed | `body_text` (predefined Am/Br word pairs) |

> **Note:** `body_text` is `full_text` with the References section stripped. This prevents references from triggering false positives (e.g. the reference list often mixes "colour" and "color").

---

## Equation Checks

**Module:** `equation_extractor.py` (extraction) + `equation_checker.py` (validation)  
**Invoked by:** `orchestrator.py` Steps 2.5 and 3e

| Check | Name | Rule | Data Used |
|---|---|---|---|
| **15** | Sequential Numbering | Equation labels must form a gapless integer sequence; only single-step gaps are reported | `equations[i]["number"]` |
| **16** | Punctuation | A comma is required after an equation when the next text line begins with "where", "with", "in which" | `equations[i]["context_before"]`, `equations[i]["context_after"]` |
| **17** | In-text Citation Style | All equation call-outs must use one consistent style (e.g. always "Eq. (N)" or always "equation (N)") | `full_text` (pattern match for Eq./equation/eqn. + page_offsets) |

Violation records for all three checks include:
- `page` — 1-based page number for PDF navigation
- `evidence` — a human-readable sentence with exact context for frontend display

See [`docs/equation_checks.md`](equation_checks.md) for full design details.

---

## Reference Checks

**Module:** `regex_extractor.py` + reference analyser service  
**Invoked by:** `orchestrator.py` Step 3a + 3e

| Check | Name | Rule |
|---|---|---|
| **1** | Style Compliance | All references must follow a single citation style (numeric, APA, etc.) |
| **2** | Bidirectional Match | Every in-text citation `[N]` must have a matching entry in the reference list, and vice versa |
| **3** | Metadata Completeness | Each reference must include required fields (authors, year, title, journal/publisher) |
| **4** | DOI / URL | References should include a DOI or URL where available |
| **5** | Sequential Ordering | Numbered references must appear in the reference list in ascending order |
| **6** | Field Consistency | References of the same type must use consistent fields (e.g. all journal articles have volume/issue) |

---

## AI Verifier

**Module:** `verifier.py`  
**Invoked by:** `orchestrator.py` Step 4 (optional, `VERIFIER_ENABLED=true`)

The verifier re-evaluates every flagged violation using an LLM (Groq Llama-3 or Gemini) and makes one of three decisions:

| Decision | Meaning |
|---|---|
| `CONFIRMED` | Violation is real — shown to user with AI-generated evidence |
| `UNCERTAIN` | May be an issue — shown with an "Uncertain" badge |
| `FALSE_POSITIVE` | Not a real issue — silently discarded before returning to frontend |

Rules for the verifier are declared in `verifier_rules.py` using a structured registry. Add new rules there without touching `verifier.py`.
