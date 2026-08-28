# ReportGPS — Pipeline Architecture (v4)

## Overview

The extraction pipeline is a **6-step PDF analysis service** that runs in **< 1 second per paper** (excluding optional AI verification). Every step uses deterministic text/regex analysis — no ML models, no LLM calls in the core path.

---

## Step-by-Step Architecture

### Step 1 — PyMuPDF Full-Document Pass (`pymupdf_extractor.py`)
**Time: ~0.3–0.7 s**

Opens the PDF with PyMuPDF (fitz) and collects, for every page:
- `plain_text` — raw UTF-8 text (used by all subsequent steps)
- Per-span metadata: `font_size`, `is_bold`, `bbox` (for heading detection)
- Image block bounding boxes: `{x0, y0, x1, y1}` (for figure detection)
- `image_count` — number of image blocks on the page

Outputs: `page_chunks[]`, `page_texts[]`, `full_text`

---

### Step 2 — Structural Analysis (`structural_analyzer.py`)
**Time: ~0.03–0.1 s**

Uses font-size heuristics and regex patterns on the raw page_chunks to detect:

**Headings:**
- Font-size heading: `font_size >= body_font_size * 1.15`
- Bold heading: `is_bold AND font_size >= body_font_size AND len <= 80 AND not sentence-like`
- All-caps heading: `ALL_CAPS AND len <= 50 AND font_size >= body_font_size * 0.9`
- Exclusions: y0 < 55pt (header zone), y1 > page_height-55pt (footer zone), captions

Body font size is estimated as the **length-weighted mode** across all spans > 7pt, so footnotes don't bias the estimate.

**Manuscript metadata** (page-1 heuristics):
- Title: largest font text on first page
- Abstract / Keywords: pattern match on section labels
- Authors: lines between title and abstract

**Figures:** `"Fig. N"` or `"Figure N"` caption regex + nearest image block bbox

**Tables:** `"Table N"` or `"Tab. N"` caption regex

---

### Step 2.5 — Equation Extraction (`equation_extractor.py`)
**Time: ~0.05–0.3 s**

Scans every page's word-level data to find right-margin equation labels like `(1)`, `(A.1)`.

**Key design decisions:**

**Two-column layout support:** Threshold is `x0 > 0.35 * page_width`. This covers:
- Right column labels at ~90% page width
- Left column labels at ~46% page width (left column ends at ~50%)

**Font encoding fallback:** Some PDF renderers output `\xf0` / `\xde` instead of ASCII `(` / `)`. The extractor regex matches both and normalises back to `(N)`.

**Gap-based false-positive filter:** A real equation label is isolated to the right margin with a large gap from the preceding word (> 10pt). In-text citations like `"as shown in (3)"` have normal spacing and are rejected.

**Year filter:** Labels matching `(1900)–(2099)` are skipped (they are publication year citations).

**Max-number filter:** Labels with number > 200 are skipped (bibliography citation numbers that are right-aligned in reference lists).

**Global deduplication:** The extractor keeps only the first occurrence of each integer equation number, preventing running headers or figure captions from producing phantom duplicates.

Outputs: `equations[]` — each with `number`, `number_format`, `page_number`, `bbox`, `context_before`, `context_after`

---

### Step 3a — Reference & Citation Extraction (`regex_extractor.py`)
**Time: ~0.05–0.15 s**

Layout-aware extraction that handles two-column PDFs, page headers/footers, and multi-line references.

Supported reference styles:
- **Numbered bracket**: `[1] Smith, A. ...`
- **Dot number**: `1. Smith, A. ...`
- **APA author-year**: `Smith, A. (2020). Title. Journal...`

Outputs: `references[]`, `in_text_citations[]`

---

### Step 3b — Typography Checks (`typography_checker.py`)
**Time: < 0.03 s**

Runs on `body_text` (full text with reference section removed). Flags:
- En-dash usage in ranges (`1-5` → should be `1–5`)
- Number-unit spacing (`10ms` → `10 ms`)
- Percent/degree spacing (`10 %` → `10%`)

---

### Step 3c — Figures & Tables Checks (`figures_tables_checker.py`)
**Time: < 0.03 s**

Runs validation on the `figures[]` and `tables[]` from structural analysis:
- Sequential numbering (Check 7, 8)
- Chronological order of first mention (Check 9, 10)
- Caption position: table captions above, figure captions below (Check 11, 12)
- Figure sub-part label completeness (Check 13)

---

### Step 3d — Syntax & Grammar Checks (`syntax_grammar_checker.py`)
**Time: < 0.02 s**

Implements Checks 17–24 using regex on `body_text`:
- Acronym definition at first occurrence (Check 17)
- En-dash in numeric ranges (Check 18)
- Non-breaking spaces before units (Check 19)
- No space before `%` / `°` (Check 20)
- Double spaces (Check 21)
- Punctuation spacing (Check 22)
- Consistent quote style (Check 23)
- British/American spelling consistency (Check 24)

---

### Step 3e — Equation Checks (`equation_checker.py`)
**Time: < 0.01 s**

Validates the `equations[]` from the extractor:

**Check 15 — Sequential Numbering:**
Looks for gaps in the sequence. Only reports single-step gaps (e.g. jumps from (3) to (5)) on sequences of ≥ 3 equations. Does not report duplicates — the extractor already deduplicates.

**Check 16 — Punctuation:**
Flags a missing comma only when `context_after` starts with `where`, `with`, `in which`, or `such that` within 80 chars, and `context_before` doesn't already end with a comma. Does not flag missing periods (too many false positives without LaTeX).

**Check 17 — In-text Citation Style:**
Finds all equation call-outs in the document body (e.g. `"Eq. (3)"`, `"equation (5)"`). Determines the dominant style by count. Reports every individual instance of a minority style with its page number and surrounding sentence context.

---

### Step 4 — AI Verifier (`verifier.py`, optional)
**Time: ~1–3 s (API latency)**

When `VERIFIER_ENABLED=true` in `.env`:
- Each flagged violation is submitted to the LLM (Groq Llama-3 or Gemini)
- The LLM decides: `CONFIRMED`, `FALSE_POSITIVE`, or `UNCERTAIN`
- `FALSE_POSITIVE` violations are discarded before returning to the frontend
- `CONFIRMED` and `UNCERTAIN` violations are returned with AI-generated evidence

When disabled: all deterministic violations are returned as-is.

---

## Module Status

| File | Status | Notes |
|---|---|---|
| `app.py` | ✅ Active | FastAPI server, port 8004 |
| `orchestrator.py` | ✅ Active | Pipeline coordinator |
| `pymupdf_extractor.py` | ✅ Active | Page text + font + image bboxes |
| `structural_analyzer.py` | ✅ Active | Headings, metadata, figures, tables |
| `equation_extractor.py` | ✅ Active | Fast PyMuPDF-based equation label scan |
| `equation_checker.py` | ✅ Active | Checks 15–17 |
| `regex_extractor.py` | ✅ Active | References + citations |
| `typography_checker.py` | ✅ Active | Typography violation checks |
| `figures_tables_checker.py` | ✅ Active | Checks 7–13 |
| `syntax_grammar_checker.py` | ✅ Active | Checks 17–24 |
| `verifier.py` | ✅ Active | AI verifier (optional) |
| `verifier_rules.py` | ✅ Active | Verifier rule registry |
| `verifier_config.py` | ✅ Active | Verifier on/off, provider selection |
