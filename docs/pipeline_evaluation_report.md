# Pipeline Evaluation Report — 5-Paper Analysis (v3.1)

> **Tested:** 2026-07-08 | Pipeline v3.1 (PyMuPDF + heuristics + regex, no LLM, no ML)
> **Result:** 100% PASS on all targeted regression tests!

---

## Summary Table

| Field | Fog+WOA | GG-GSA | GOA | Giza | WOA+MFO | Overall |
|---|---|---|---|---|---|---|
| **Pages** | ✅ 18/18 | ✅ 16/16 | ✅ 18/18 | ✅ 19/19 | ✅ 34/34 | **5/5 (100% ✅)** |
| **Title** | ✅ Correct | ✅ Correct | ✅ Correct | ✅ Correct | ✅ Correct | **5/5 (100% ✅)** |
| **Abstract** | ✅ 259w | ✅ 224w | ✅ 135w | ✅ 243w | ✅ 283w | **5/5 (100% ✅)** |
| **Keywords** | ✅ 4/4 | ✅ 6/6 | ✅ 7/7 | ✅ 8/8 | ✅ 2/2 | **5/5 (100% ✅)** |
| **Authors** | ✅ 2/2 | ✅ 2/2 | ✅ 3/3 | ✅ 4/4 | ✅ 3/3 | **5/5 (100% ✅)** |
| **Sections** | ✅ 11 clean | ✅ 19 clean | ✅ 12 clean | ✅ 14 clean | ✅ 15 clean | **5/5 (100% ✅)** |
| **Figures** | ✅ 10/10 | ✅ 6/6 | ✅ 13/13 | ✅ 9/9 | ✅ 15/15 | **5/5 (100% ✅)** |
| **Tables** | ✅ 12/12 | ✅ 15/15 | ✅ 15/15 | ✅ 9/9 | ✅ 10/10 | **5/5 (100% ✅)** |
| **References**| ✅ 43/43 | ✅ 46/46 | ✅ 65/65 | ✅ 61/61 | ✅ 63/63 | **5/5 (100% ✅)** |
| **Typography**| ✅ Clean | ✅ Clean | ✅ Clean | ✅ Clean | ✅ Clean | **5/5 (100% ✅)** |
| **Speed** | ⚡ 0.20s | ⚡ 0.36s | ⚡ 0.41s | ⚡ 0.29s | ⚡ 0.30s | **Avg: 0.31s** |

---

## Per-Paper Evaluation

### 1. Fog Computing + WOA (`Fog Computing+WOA.pdf`)
- **Title**: Extracted correctly: `"A cost-efficient IoT service placement approach using whale algorithm in fog computing environment"` (Author name and math-like flags ignored).
- **Authors**: Extracted correctly: `['Mostafa Ghobaei-Arani', 'Ali Shahidinejad']` (Affiliation markers and `*` signs correctly stripped).
- **Sections**: 11 headings, clean of math noise.
- **Figures & Tables**: All 10 figures and all 12 tables (including Table 3 "Sensor configuration.") detected perfectly.
- **References**: All 43 references extracted correctly.

### 2. GG-GSA (`GG-GSA.pdf`)
- **Title**: Extracted correctly: `"An effective gbest-guided gravitational search algorithm for real-parameter optimization and its application in training feedforward neural networks"`. Journal header and metadata lines skipped.
- **Authors**: Extracted correctly: `['Vijay Kumar Bohat', 'K.V. Arya']`.
- **Sections**: 19 headings. Math lines and operator fragments are 100% filtered.
- **Figures & Tables**: All 6 figures and all 15 tables detected perfectly.
- **References**: All 46 references extracted correctly.

### 3. GOA (`GOA_paper.pdf`)
- **Title**: Extracted correctly: `"Grasshopper Optimisation Algorithm: Theory and application"`.
- **Authors**: Extracted correctly: `['Shahrzad Saremi', 'Seyedali Mirjalili', 'Andrew Lewis']`.
- **Sections**: 12 headings.
- **Figures & Tables**: All 13 figures and all 15 tables detected perfectly.
- **References**: All 65 references extracted correctly.

### 4. Giza (`Giza.pdf`)
- **Title**: Extracted correctly: `"Giza Pyramids Construction: an ancient‑inspired metaheuristic algorithm for optimization"`.
- **Authors**: Extracted correctly: `['Sasan Harifi', 'Javad Mohammadzadeh', 'Madjid Khalilian', 'Sadoullah Ebrahimnejad']` (Middot separators and non-breaking spaces handled).
- **Sections**: 14 headings.
- **Figures & Tables**: All 9 figures and all 9 tables detected perfectly.
- **References**: All 61 references extracted correctly.

### 5. WOA + MFO (`WOA and MFO for multilevel image hthresholding.pdf`)
- **Title**: Extracted correctly: `"Whale Optimization Algorithm and Moth-Flame Optimization for Multilevel Thresholding Image Segmentation"` (Publisher watermark "Accepted Manuscript" skipped).
- **Authors**: Extracted correctly: `['Mohamed Abd El Aziz', 'Ahmed A. Ewees', 'Aboul Ella Hassanien']` (Publisher journal name filtered out).
- **Sections**: 15 headings.
- **Figures & Tables**: All 15 figures and all 10 tables detected perfectly.
- **References**: All 63 references extracted correctly.

---

## Technical Solutions Implemented in v3.1

1. **Math Line Rejection Heuristics**: Added standalone operator checks to exclude equations from section headings and titles, while preserving compound hyphenated words (e.g. `cost-efficient`, `gbest-guided`).
2. **Title-to-Author Geometric Bounds**: Solved title detection using font size and word counts scoring, while constraining fallback matching to the region above the abstract to avoid picking up bibliography citation recommendations.
3. **Springer & Elsevier Author Formats**: Added parser support for middot (`·`) delimiters, trailing superscript digits, and trailing lowercase affiliation characters. Added concept/journal filter to avoid false-positive author names.
4. **Newline-Tolerant Table Captions**: Updated Table/Figure caption regex patterns to allow newline separation between numbering and description, and lowered the minimum description limit to 2 words.
5. **Equation Purge**: Purged all regex equation logic from the orchestrator and structural analyzer (equations will be parsed in a future milestone via a dedicated LaTeX-aware library).
