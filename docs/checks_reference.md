# ReportGPS — All Validation Checks Reference

This document is the authoritative specification for all 30 validation checks in the platform. Each entry shows the check name, rule, implementation status, the module responsible, and the data it consumes.

> **Legend:**
> - ✅ Implemented and active in Prototype 1
> - ⚠️ Partially implemented (format only, or limited coverage)
> - ❌ Not implemented — planned for Phase 2

---

## Group A — Reference Quality (Checks 1–6)

**Entry point:** `modules/reference_analyser/analyser.py`  
**Invoked by:** `orchestrator.py` Step 3f

| # | Check Name | Rule | Status | Module |
|---|---|---|---|---|
| 1 | **Style Compliance** | All references in the list must conform to a single citation style (IEEE, APA, MLA, Harvard, Chicago, Vancouver) | ✅ | `check_style_conformity.py` via `citation_classifier.py` |
| 2 | **Bidirectional Match** | Every in-text citation marker `[N]` or `(Author, Year)` must have a matching entry in the reference list; every reference must be cited at least once | ✅ | `orchestrator.py::_check_bidirectional_match` |
| 3 | **Metadata Completeness** | All required metadata fields (authors, year, title, journal/publisher) must be present and non-empty in each reference | ✅ | `check_completeness.py` |
| 4 | **DOI / URL Liveness** | DOIs and URLs in the reference list must be properly formatted (regex check) and return a valid HTTP 200 response (liveness probe) | ⚠️ Format check active; live HTTP probe disabled by default (too slow for all papers) | `check_doi.py` |
| 5 | **Sequential Ordering** | For numbered styles (IEEE, Vancouver), references must appear in the reference list in ascending numeric order | ✅ | `check_ordering.py` |
| 6 | **Consistency in References** | References of the same type (journal, conference, book) must use a consistent set of fields (e.g. all journal articles include volume and issue) | ✅ | `ConsistencyHandler` in `analyser.py` (BibTeX field consistency) + `check_journal_casing.py` (journal title casing) |

**Data consumed:**
- `references[i]["raw_string"]` — plain text reference string extracted by regex
- `in_text_citations[]` — all in-text citation markers found in the body

---

## Group B — Figures & Tables (Checks 7–13)

**Module:** `modules/checkers/figures_tables_checker.py`  
**Invoked by:** `orchestrator.py` Step 3c

| # | Check Name | Rule | Status | Data Used |
|---|---|---|---|---|
| 7 | **Figure Sequential Numbering** | Figures must be numbered 1, 2, 3 … without gaps or duplicates | ✅ | `figures[i]["number"]` |
| 8 | **Table Sequential Numbering** | Tables must be numbered 1, 2, 3 … without gaps or duplicates | ✅ | `tables[i]["number"]` |
| 9 | **Figure Chronological Order** | Figures must be first mentioned in the text in ascending numeric order | ✅ | `figures[i]["first_mention_page"]` |
| 10 | **Table Chronological Order** | Tables must be first mentioned in the text in ascending numeric order | ✅ | `tables[i]["first_mention_page"]` |
| 11 | **Table Caption Above Table** | Table caption must be positioned above the table body (y-coordinate comparison) | ✅ | `tables[i]["caption_bbox"]["y1"]`, `tables[i]["table_body_y0"]` |
| 12 | **Figure Caption Below Figure** | Figure caption must be positioned below the image bbox (y-coordinate comparison) | ✅ | `figures[i]["caption_bbox"]["y0"]`, `figures[i]["image_bbox"]["y1"]` |
| 13 | **Figure Sub-part Labels** | Sub-part labels (a), (b), (c) … must be consecutive starting from (a) with no gaps | ✅ | `figures[i]["caption_text"]` via regex |

All checks return `{ "passed": bool, "violations": [...], "detail": str }`.

Each violation includes `page` (1-based) and `detail` for frontend display.

---

## Group C — Equations (Checks 14–18)

**Extractor:** `modules/extractors/equation_extractor.py` (Step 2.5)  
**Checker:** `modules/checkers/equation_checker.py` (Step 3e)

| # | Check Name | Rule | Status | Notes |
|---|---|---|---|---|
| 14 | **Placement After Mention** | An equation must appear in the document after the first in-text call-out that references it | ❌ Not implemented | Requires correlating equation `bbox` page positions with in-text reference positions. Planned for Phase 2 |
| 15 | **Sequential Numbering** | Equation labels must form a gapless integer sequence. Single-step gaps on sequences of ≥ 3 equations are reported | ✅ | `equations[i]["number"]` |
| 16 | **Punctuation** | A comma is required after an equation when the following text line starts with "where", "with", "in which", or "such that" within 80 characters | ✅ | `equations[i]["context_before"]`, `equations[i]["context_after"]` |
| 17 | **In-text Citation Style** | All equation call-outs must use one consistent style (e.g. always "Eq. (N)" or always "equation (N)") | ✅ | `full_text` — regex pattern match for Eq./equation/eqn. with page offsets |
| 18 | **Delimiter Balance** | Opening and closing delimiters (brackets, braces, parentheses) must be balanced and correctly scaled | ❌ Not implemented | Requires LaTeX or MathML source. PDF text layer does not reliably expose raw math symbols |

Violation records for Checks 15–17 include:
- `page` — 1-based page number for PDF navigation
- `evidence` — human-readable sentence with exact context for frontend display

See [`docs/equation_checks.md`](equation_checks.md) for full design details on the extraction strategy.

---

## Group D — Formatting & Typography (Checks 19–26)

**Module:** `modules/checkers/syntax_grammar_checker.py`  
**Invoked by:** `orchestrator.py` Step 3d

> **Note:** `body_text` is `full_text` with the References section stripped. This prevents reference list strings from triggering false positives (e.g. a reference containing "Fig." or a hyphenated author name).

| # | Check Name | Rule | Status | Data Used |
|---|---|---|---|---|
| 19 | **En-dash for Ranges** | En-dash (–, U+2013) must be used for numeric ranges, not a plain hyphen (`10-20` → `10–20`) | ✅ | `body_text` |
| 20 | **Non-breaking Space** | Non-breaking space (U+00A0) must appear between a number and a standard unit (`10 kg`, `3 ms`) | ✅ | `body_text` |
| 21 | **No Space % / °** | No space before percent (`10%`) or degree (`90°C`) symbols | ✅ | `body_text` |
| 22 | **Double Spaces** | No accidental double ASCII spaces between non-whitespace characters in running text | ✅ | `body_text` |
| 23 | **Punctuation Spacing** | Single space after commas and semicolons; no space before them | ✅ | `body_text` |
| 24 | **Quote Style Consistency** | Consistent use of straight (`"`) or curly (`"`) double quotes throughout the document, not both | ✅ | `full_text` |
| 25 | **Spelling Consistency** | American and British English spellings must not be mixed (e.g. "colour" vs "color") | ✅ | `body_text` (predefined Am/Br word pair dictionary) |
| 26 | **Acronym Definition** | Every acronym of 3 or more capital letters must be defined in full at its first occurrence in the text | ✅ | `full_text` (regex + initials-matching heuristic) |

---

## Group E — PDF-Level Typography (Checks 27–30)

**Module:** `modules/checkers/typography_checker.py`  
**Invoked by:** `orchestrator.py` Step 3b

> Typography checks operate at the PDF text-span level (before sentence-level analysis) and catch character-encoding issues that regex on plain text might miss.

| # | Check Name | Rule | Status | Data Used |
|---|---|---|---|---|
| 27 | **En-dash in Ranges (Typography)** | Same as Check 19, applied at the PDF span level to catch mis-encoded dashes | ✅ | `page_chunks[i]["plain_text"]` |
| 28 | **Number-Unit Spacing** | Space between number and unit, checked at the span level | ✅ | `page_chunks[i]["plain_text"]` |
| 29 | **Percent / Degree No-space** | No space before % or ° at the span level | ✅ | `page_chunks[i]["plain_text"]` |
| 30 | **Section Heading Style** | Section headings must use a consistent capitalisation style (title case vs sentence case) throughout the document | ❌ Not implemented | Requires a journal-specific style guide as ground truth. Cannot determine correct style from the document alone |

---

## AI Verifier (post-processing all checks)

**Module:** `modules/verifier/verifier.py`  
**Invoked by:** `orchestrator.py` Step 4 (when `VERIFIER_ENABLED=true`)

After all deterministic checks run, the AI Verifier evaluates every flagged violation:

| Decision | Meaning | Action |
|---|---|---|
| `CONFIRMED` | Violation is genuine | Shown to user with AI-generated evidence and suggestion |
| `UNCERTAIN` | May or may not be an issue | Shown with "Uncertain" badge |
| `FALSE_POSITIVE` | Not a real violation | Silently discarded before returning to frontend |

Rules for each check are declared in `modules/verifier/verifier_rules.py`. To add or tune a rule, edit that file only — `verifier.py` is rule-agnostic.

**LLM provider waterfall:** Groq (up to 4 keys, round-robin) → Cerebras → Gemini (last resort).

---

## Summary: Implementation Status by Count

| Group | Total Checks | Implemented | Partial | Not Implemented |
|---|---|---|---|---|
| A — Reference Quality | 6 | 5 | 1 (Check 4) | 0 |
| B — Figures & Tables | 7 | 7 | 0 | 0 |
| C — Equations | 5 | 3 | 0 | 2 (Checks 14, 18) |
| D — Formatting | 8 | 8 | 0 | 0 |
| E — PDF Typography | 4 | 3 | 0 | 1 (Check 30) |
| **Total** | **30** | **26** | **1** | **3** |
