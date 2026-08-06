# Inspection Report & Fix Plan — 4 New Papers Analysis (v3.1)

This report details the mistakes, root causes, and planned fixes for the extraction pipeline when run on the 4 new papers from `new_papers/`.

---

## 1. Summary of Current Performance

| Paper | Title | Authors | Sections | Tables | Figures |
|---|---|---|---|---|---|
| **`AEO.pdf`** | ❌ Wrong (Got author line) | ❌ Partial (Zhao only) | ⚠️ Mixed (Title parts as headings) | ❌ Truncated (Table 16, etc.) | ✅ Correct |
| **`abualigah2021.pdf`** | ✅ Correct | ⚠️ Extra keyword | ❌ Overlooked (Only 7 metadata headers) | ❌ Truncated (Table 8, etc.) | ✅ Correct |
| **`arithmatic optimization...`** | ❌ Wrong (Got author line) | ❌ Empty list | ❌ Exploded (2,479 headings!) | ❌ Truncated & false refs | ✅ Correct |
| **`dsa.pdf`** | ✅ Correct | ✅ Empty (None present) | ⚠️ Partial (Includes Table of Contents) | ✅ Correct | ✅ Correct |

---

## 2. Root Cause Analysis

### Issue 1: Title and Author Confusion
- **Superdescriptor Spans**: In papers like `AEO.pdf` and `arithmatic optimization...`, PyMuPDF extracts superscript characters (affiliation indicators like `a`, `1,2`, `*`) as part of the text word (e.g. `Laith Abualigaha,∗`). When split on commas, this creates non-capitalized single-letter parts (like `c`, `e`, `g`), lowering the name capitalization ratio and making the author list checker fail.
- **Score Domination by Body/Abstract**: The title heuristic `score = size * min(words, 10)` allowed long abstract lines at body size (10.0pt) to score higher than short titles at larger sizes (16.0pt). 
- **Region Overlap**: Heuristics did not check the `abstract_y0` boundary on Page 1 when selecting title candidates, causing lines from the abstract and introduction to pollute candidates.

### Issue 2: Heading Explosion (2,479 headings) & Missing Headings
- **Global Body Font Size Underestimation**: In `arithmatic optimization...`, the bibliography (70 references) and large tables contain more total text characters than the main body paragraphs. The length-weighted estimator selected `8.0pt` (the reference size) as the body size. Since the actual body text is `10.0pt`, the threshold `body_fs * 1.15 = 9.2pt` fell below it, classifying *every single body text line* as a heading.
- **Float Comparison Precision**: Minor float differences (e.g. actual font size `7.96pt` vs rounded estimated size `8.0pt`) caused genuine bold headings to fail the `max_size >= body_font_size` check.
- **Non-Bold Numbered Subsections**: Section headings like `2.1. Swarm Intelligence` are rendered in normal weight and size, making them indistinguishable from body text without numbered prefix checks.
- **Pseudo-code Bold Text**: In-line pseudo-code algorithms (using bold loops/keywords) were picked up as headings.

### Issue 3: Truncated Table Captions
- **Flat-Text Regex Limits**: Plain-text regex on `full_text` uses `.` which does not match newlines (`\n`). Academic tables (especially Elsevier/Springer) often place `Table N` on one line and the description on the next, leading to truncated captions (e.g. `Table 16: 'Comparisons of'`).

---

## 3. Foolproof Layout Heuristic Plan (No LLM Required)

Instead of using heavy models like NuExtract which increase extraction times from 0.3s to 20s+, we can solve these problems with layout heuristics:

### Fix 1: Title & Author Extraction Refinements
1. **Geometric Restriction**: On Page 1, pre-calculate the abstract top vertical coordinate (`abstract_y0`). Restrict both Title and Author candidates strictly to the region `y < abstract_y0`.
2. **Clean Superscripts First**: Reconstruct line texts by inspecting `TextSpan.size`. If `max_size - span.size > 1.5` and `span.size < 11.0`, it is a superscript/footnote marker and is stripped. This turns `Laith Abualigaha,∗` into `Laith Abualigah` *before* comma checks.
3. **Pure Font Size Title Priority**: Prioritize title candidates primarily by `max_font_size` (descending) and `y` position (ascending) to pick the largest, topmost text block on the page, using word count only as a minimum filter (≥ 3 words).

### Fix 2: Heading Detection Refinements
1. **Targeted Body Size Estimation**: Run the length-weighted estimator only on Pages 2 to 5. This avoids bibliography blocks and table appendixes at the end of the document, ensuring `body_font_size` is always estimated accurately.
2. **Float Tolerance**: Add a `-0.25pt` tolerance to all font size comparisons to prevent float precision mismatches.
3. **Numbered Subsection Regex**: Match numbered sections explicitly using `^[1-9]\d*(?:\.\d+)+\.?\s+[A-Z]` (matches `2.1.`, `3.2.1.`, but ignores `0.005.`).
4. **Code Keyword Rejection**: Reject heading candidates containing common algorithm keywords: `while`, `do`, `then`, `else`, `end if`, `end for`, `end while`.

### Fix 3: Layout-Aware Figure & Table Captioning
1. **Multi-line Block Collector**: Replace flat-text regex with a layout block scanner:
   - Find lines starting with `Table N` or `Fig N`.
   - Collect consecutive lines on the same page if their vertical gap is small (`< 16pt`) and font size is uniform (`abs(next_size - max_size) < 0.5`).
   - Stop immediately if a line contains table column indicators (multiple wide spaces), section breaks, or matches table header keywords (e.g. `Methods`, `Worst`, `Mean`).
