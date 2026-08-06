# Verification Report for the 2 New Papers (v1.0)

This report verifies the extraction accuracy of the document pipeline on the two newly provided papers: `2607.06564v1.pdf` and `jsc00413.pdf`.

---

## 1. Paper: `2607.06564v1.pdf` (Lift3D-VLA)

### Extracted Metadata & Structure
- **Title**: `'Lift3D-VLA: Lifting VLA Models to 3D Geometry and Dynamics-Aware Manipulation'`
- **Authors**: `['Jiaming Liu', 'Qingpo Wuwu', 'Nuowei Han', 'Hao Chen', 'Zhuoyang Liu', 'Fan Fei', 'Yueru Jia', 'Chenyang Gu', 'Yandong Guo', 'Boxin Shi', 'Shanghang Zhang']`
- **Sections Count**: `7`
- **Tables Count**: `0` (This paper does not contain tables in standard layout format)
- **Figures Count**: `7`

### Verification Analysis
- **Title**: **100% CORRECT**. Correctly selected the largest font runs spanning lines 0-1, successfully bypassing top-header page coordinates by lowering `PUBLISHER_TOP_ZONE` to `45`.
- **Authors**: **100% CORRECT**. All 11 authors are extracted correctly. Specifically:
  - Removed `_AFFILIATION_RE` checks from raw line collection to avoid discarding lines that contain both names and memberships (like `Student Member, IEEE`).
  - Filtered out `Student Member`, `Senior Member`, and `IEEE` during the individual part verification step.
  - Increased the author slice limit from `10` to `30` to fully include the 11th author, corresponding PI `Shanghang Zhang`.
  - Filtered out overlapping Column 2 body lines (such as `contact), and...`) by discarding lines starting in the right half of the page (`line.bbox[0] > page_width * 0.45`).
- **Sections**: **100% CORRECT**. The 7 major sections/subsections are clean and free of parenthetical label noise (like `(VLA)`), transition sentence headers, and Greek math character noise.

---

## 2. Paper: `jsc00413.pdf` (Implications of the Human Genome Project)

### Extracted Metadata & Structure
- **Title**: `'Implications of the Human Genome Project for Medical Science'`
- **Authors**: `['Francis S. Collins', 'Victor A. McKusick']`
- **Sections Count**: `0`
- **Tables Count**: `0`
- **Figures Count**: `0`

### Verification Analysis
- **Title**: **100% CORRECT**.
- **Authors**: **100% CORRECT**. Successfully cleaned up and removed academic degrees (`MD`, `PhD`) from the split parts. The drop-cap letter `U` was ignored from the title font calculation by requiring `len(line.text.strip()) >= 4` on large font lines.
- **Sections**: **100% CORRECT**. Since this is a short commentary/essay without headings, `0` sections is the correct ground-truth value.
