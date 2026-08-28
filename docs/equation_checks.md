# Equation Validation — Developer Reference

## Overview

Equation validation is split across two modules:

| Module | Responsibility |
|---|---|
| `equation_extractor.py` | Scan PDF text layer → find numbered equation labels → return structured list |
| `equation_checker.py` | Validate the equation list → produce violation reports |

Both run in `orchestrator.py` at Steps 2.5 and 3e respectively.

---

## Equation Extractor (`equation_extractor.py`)

### Entry Point
```python
from equation_extractor import extract_equations
equations = extract_equations(pdf_path)  # < 0.3 s for any size PDF
```

### Output Schema
```python
{
    "number":         1,        # parsed integer, e.g. (1) → 1; None if unlabelled
    "number_format":  "(1)",    # always standard parens, e.g. "(1)" / "(A.1)"
    "latex":          "",       # always empty — LaTeX not extracted
    "page_number":    3,        # 1-based page index
    "bbox": {
        "page": 3,
        "x0": 510.5, "y0": 320.1, "x1": 528.3, "y1": 332.4,
    },
    "context_before": "...",    # up to 400 chars of text before the label on the page
    "context_after":  "...",    # up to 400 chars of text after the label on the page
}
```

### How Label Detection Works

**Step 1 — Word grouping by line:**  
PyMuPDF's `get_text("words")` returns `(x0, y0, x1, y1, text, block_no, line_no, word_no)` for each word. Words are grouped by `(block_no, line_no)` to reconstruct logical lines.

**Step 2 — Last-word-on-line check:**  
Only the last word of each logical line is considered. Equation labels are always the rightmost token on their line.

**Step 3 — Right-margin threshold:**  
`x0 > 0.35 * page_width`

This value was chosen to support **two-column layouts** where:
- Left column equation labels sit at ~46% of the page width
- Right column equation labels sit at ~88–90% of the page width
- In-text equation mentions (`"see Eq. (3) above"`) are at < 35% when mid-sentence

**Step 4 — Pattern matching:**  
Labels must match: `^[\(\xf0]([A-Za-z]?\d+[A-Za-z]?(?:\.\d+)?)[\)\xde]$`

The `\xf0` / `\xde` variants handle a common PDF font encoding where parentheses are stored as non-ASCII bytes in the text layer. The extracted `number_format` is always normalised back to standard `(N)`.

**Step 5 — Gap filter (anti-false-positive):**  
When the label is not the only word on its line, the gap between it and the previous word must be `> 10 points`. Real equation labels are pushed far to the right margin; in-text citations have normal word spacing.

**Step 6 — Filters:**
- Years `(1900)–(2099)` → skipped
- Numbers > 200 → skipped (bibliography citation numbers)
- Numbers < 1 → skipped
- Header / footer zone (first/last 50pt of page) → skipped

**Step 7 — Global deduplication:**  
After collecting all candidates, deduplicate by integer `number`, keeping only the first occurrence. This prevents running page headers that re-print equation labels from creating duplicates.

---

## Equation Checker (`equation_checker.py`)

### Entry Point
```python
from equation_checker import run_all_checks
results = run_all_checks(
    equations=equations,
    full_text=full_text,        # complete document text joined across all pages
    page_offsets=page_offsets,  # list[int]: char offset where each page starts in full_text
)
```

`page_offsets` is computed in `orchestrator.py`:
```python
page_offsets = []
pos = 0
for pt in page_texts:
    page_offsets.append(pos)
    pos += len(pt) + 1
```

### Output Schema
```python
{
    "equation_sequential_numbering":   { "passed": bool, "violations": [...], "detail": str },
    "equation_punctuation":            { "passed": bool, "violations": [...], "detail": str },
    "in_text_reference_consistency":   { "passed": bool, "violations": [...], "detail": str },
}
```

---

## Check 15 — Sequential Numbering

**Rule:** Numbered equations must form a gapless sequence.

**Logic:**
1. Collect all `equation["number"]` values that are integers ≥ 1.
2. Sort them.
3. Only check if there are **≥ 3** numbered equations (shorter sequences are often intentionally non-sequential).
4. For each adjacent pair `(a, b)`:
   - If `b - a == 2`: exactly one number is missing → report a gap for `a+1`
   - If `b - a > 2`: a range is missing → report `(a+1)–(b-1)`

**Violation fields:**
```python
{
    "type":     "gap",
    "number":   9,                  # the missing equation number
    "page":     4,                  # page of the equation before the gap
    "evidence": "Sequence jumps from (8) on page 4 to (10) on page 5. Equation (9) is missing.",
    "detail":   "Equation (9) is missing — sequence jumps from (8) to (10)."
}
```

---

## Check 16 — Punctuation

**Rule:** A comma is required after a display equation when the following text immediately continues with a "where" or "with" clause.

**Logic:**
1. Check `context_after` (first 80 chars) for a match against `where | with | in which | such that`
2. Check `context_before` for a trailing comma or period — if present, skip (already punctuated)
3. Check `context_after` starts with a comma — if present, skip

**Only flags missing commas.** Missing periods are deliberately not checked — false positive rate is too high without LaTeX source.

**Violation fields:**
```python
{
    "equation":      "(5)",
    "page":          7,
    "issue":         "missing_comma",
    "evidence":      "On page 7, after Equation (5) the text continues with 'where x is the...' without a comma.",
    "context_after": "where x is the position vector and...",
    "detail":        "Missing comma after Equation (5) — sentence continues with 'where...'"
}
```

---

## Check 17 — In-text Citation Style Consistency

**Rule:** All equation call-outs must use one consistent style throughout the paper.

**Styles detected:**

| Style Name | Example Match |
|---|---|
| `Equation (N)` | `"equation (3)"`, `"Equation (12)"` |
| `Eq. (N)` | `"Eq. (3)"`, `"Eqs. (4) and (5)"` |
| `Eq (N)` | `"Eq (3)"` |
| `eqn. (N)` | `"eqn. (3)"` |
| `eqn (N)` | `"eqn (3)"` |

`Eqs. (N)` is merged with `Eq. (N)` (same style, plural form).

**Logic:**
1. Find all matches of each style across the full document text.
2. Determine the **dominant style** (most occurrences).
3. Report each individual occurrence of a **minority style** as its own violation, including:
   - The exact matched text
   - The page number (computed via `page_offsets` + `bisect`)
   - 80-char surrounding context snippet

**Violation fields:**
```python
{
    "style":    "Equation (N)",
    "page":     7,
    "evidence": '"...update its solution using equation (6), if rand..."',
    "detail":   'Inconsistent citation style: found "equation (6)" (style: "Equation (N)") instead of dominant style "Eq. (N)".'
}
```

---

## Adding a New Equation Check

1. Add a new function `check_N_name(equations, ...)` in `equation_checker.py`
2. Return a dict: `{"passed": bool, "violations": [...], "detail": str}`
3. Each violation dict **must** include `page` and `evidence` keys for frontend highlighting
4. Add the check to `run_all_checks()` return dict
5. Add parsing in the frontend `parseIssues()` function in `frontend/src/App.jsx`
6. Add a row to [`docs/checks_reference.md`](checks_reference.md)
