"""
figures_tables_checker.py
=========================
Regex / heuristic validation checks for Figures and Tables.

Each check is an isolated function operating solely on data already
produced by the existing extraction pipeline (structural_analyzer +
pymupdf_extractor). No extra extraction, no ML, no LLM.

Checks implemented (one at a time per project rules):
  Check 7 -- Figure Sequential Numbering
             Figures must be numbered 1, 2, 3 ... without skipping or repeating.

Integration:
  Called from orchestrator.py after structural analysis.
  Result merged into the final JSON under key "figures_tables_checks".
"""

from __future__ import annotations

from typing import Any, Dict, List

# Strategy B: Spatial tolerance for caption position checks.
# PyMuPDF image block bboxes include rendering padding while text bboxes are
# tight. A caption that is visually below/above its figure/table can appear to
# overlap by a few points due to this padding. The tolerance prevents those
# near-miss false positives.
# Value: 15 PDF points ≈ 5 mm on a standard A4/US-Letter page.
CAPTION_POSITION_TOLERANCE = 15  # pts  (configurable — increase if false-positives persist)


# -------------------------------------------------------------------------
# Public entry point
# -------------------------------------------------------------------------

def check_figures_and_tables(
    figures: List[Dict[str, Any]],
    tables: List[Dict[str, Any]],
    page_texts: List[str],
) -> Dict[str, Any]:
    """
    Run all implemented Figures & Tables validation checks.

    Args:
        figures:    List of figure dicts from structural_analyzer.
                    Each dict contains at least {"number": int, ...}
        tables:     List of table dicts from structural_analyzer.
                    Each dict contains at least {"number": int, ...}
        page_texts: Per-page plain text strings (list, 1 entry per page).

    Returns:
        Dict keyed by check name; each value is that check's result dict.
    """
    return {
        "figure_sequential_numbering": _check_figure_sequential_numbering(figures),
        "table_sequential_numbering":      _check_table_sequential_numbering(tables),
        "figure_chronological_order":      _check_figure_chronological_order(figures),
        "table_chronological_order":       _check_table_chronological_order(tables),
        "table_caption_above":             _check_table_caption_above(tables),
        "figure_caption_below":            _check_figure_caption_below(figures),
        "figure_parts_mention":            _check_figure_parts_mention(figures),
    }


# -------------------------------------------------------------------------
# Check 7: Figure Sequential Numbering
# -------------------------------------------------------------------------

def _check_figure_sequential_numbering(
    figures: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Check 7 - Figure Sequential Numbering.

    Validates that detected figures are numbered 1, 2, 3 ... with no gaps
    and no repeated numbers.

    Data used:
        figures[i]["number"] -- int extracted by structural_analyzer via regex.

    Returns:
        {
          "passed":            bool,
          "found_sequence":    List[int],
          "missing_numbers":   List[int],
          "duplicate_numbers": List[int],
          "detail":            str,
        }
    """
    if not figures:
        return {
            "passed": True,
            "found_sequence": [],
            "missing_numbers": [],
            "duplicate_numbers": [],
            "detail": "No figures detected in the document.",
        }

    raw_numbers: List[int] = [
        fig["number"]
        for fig in figures
        if isinstance(fig.get("number"), int)
    ]

    if not raw_numbers:
        return {
            "passed": True,
            "found_sequence": [],
            "missing_numbers": [],
            "duplicate_numbers": [],
            "detail": "No numbered figures detected.",
        }

    sorted_numbers = sorted(raw_numbers)

    # Detect duplicates
    freq: Dict[int, int] = {}
    for n in sorted_numbers:
        freq[n] = freq.get(n, 0) + 1
    duplicate_numbers: List[int] = sorted(k for k, v in freq.items() if v > 1)

    # Detect gaps: expected sequence from 1 to max
    unique_sorted = sorted(set(sorted_numbers))
    expected = list(range(1, unique_sorted[-1] + 1))
    missing_numbers: List[int] = [n for n in expected if n not in freq]

    passed = not missing_numbers and not duplicate_numbers

    if passed:
        detail = (
            f"Figure numbering is sequential: "
            f"{unique_sorted[0]}-{unique_sorted[-1]} ({len(unique_sorted)} figure(s))."
        )
    else:
        parts: List[str] = []
        if missing_numbers:
            parts.append(f"Missing figure number(s): {missing_numbers}")
        if duplicate_numbers:
            parts.append(f"Duplicate figure number(s): {duplicate_numbers}")
        detail = "Figure numbering is NOT sequential. " + "; ".join(parts) + "."

    return {
        "passed":            passed,
        "found_sequence":    sorted_numbers,
        "missing_numbers":   missing_numbers,
        "duplicate_numbers": duplicate_numbers,
        "detail":            detail,
    }


# -------------------------------------------------------------------------
# Check 8: Table Sequential Numbering
# -------------------------------------------------------------------------

def _check_table_sequential_numbering(
    tables: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Check 8 - Table Sequential Numbering.

    Validates that detected tables are numbered sequentially starting from 1,
    with no gaps and no repeated numbers.

    Data used:
        tables[i]["number"] -- int extracted by structural_analyzer via regex
                               on "Table N" caption lines.

    Returns:
        {
          "passed":            bool,
          "found_sequence":    List[int],
          "missing_numbers":   List[int],
          "duplicate_numbers": List[int],
          "detail":            str,
        }
    """
    if not tables:
        return {
            "passed": True,
            "found_sequence": [],
            "missing_numbers": [],
            "duplicate_numbers": [],
            "detail": "No tables detected in the document.",
        }

    raw_numbers: List[int] = [
        tbl["number"]
        for tbl in tables
        if isinstance(tbl.get("number"), int)
    ]

    if not raw_numbers:
        return {
            "passed": True,
            "found_sequence": [],
            "missing_numbers": [],
            "duplicate_numbers": [],
            "detail": "No numbered tables detected.",
        }

    sorted_numbers = sorted(raw_numbers)

    freq: Dict[int, int] = {}
    for n in sorted_numbers:
        freq[n] = freq.get(n, 0) + 1
    duplicate_numbers: List[int] = sorted(k for k, v in freq.items() if v > 1)

    unique_sorted = sorted(set(sorted_numbers))
    expected = list(range(1, unique_sorted[-1] + 1))
    missing_numbers: List[int] = [n for n in expected if n not in freq]

    passed = not missing_numbers and not duplicate_numbers

    if passed:
        detail = (
            f"Table numbering is sequential: "
            f"{unique_sorted[0]}-{unique_sorted[-1]} ({len(unique_sorted)} table(s))."
        )
    else:
        parts: List[str] = []
        if missing_numbers:
            parts.append(f"Missing table number(s): {missing_numbers}")
        if duplicate_numbers:
            parts.append(f"Duplicate table number(s): {duplicate_numbers}")
        detail = "Table numbering is NOT sequential. " + "; ".join(parts) + "."

    return {
        "passed":            passed,
        "found_sequence":    sorted_numbers,
        "missing_numbers":   missing_numbers,
        "duplicate_numbers": duplicate_numbers,
        "detail":            detail,
    }


# -------------------------------------------------------------------------
# Check 9: Chronological Appearance of Figures
# -------------------------------------------------------------------------

def _check_figure_chronological_order(
    figures: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Check 9 - Chronological Appearance of Figures.

    Validates that figures are first mentioned in the body text in ascending
    numerical order (Figure 1 before Figure 2, etc.).

    Data used:
        figures[i]["number"]             -- figure number (int)
        figures[i]["first_mention_page"] -- page of first in-text mention,
                                           computed by structural_analyzer via
                                           _FIG_MENTION_RE on full_text.

    Logic:
        Sort figures by number, then walk the sorted list checking that
        first_mention_page is non-decreasing.  Any figure N+1 whose
        first_mention_page is strictly less than figure N's first_mention_page
        is a violation.

    Returns:
        {
          "passed":     bool,
          "violations": List[dict],   # [{figure, mentioned_on_page, before_figure, ...}]
          "detail":     str,
        }
    """
    # Only consider figures that have both a number and a first_mention_page
    valid = sorted(
        [f for f in figures
         if isinstance(f.get("number"), int)
         and isinstance(f.get("first_mention_page"), int)],
        key=lambda f: f["number"],
    )

    if len(valid) < 2:
        return {
            "passed": True,
            "violations": [],
            "detail": "Fewer than 2 figures with in-text mentions; order check not applicable.",
        }

    violations: List[Dict[str, Any]] = []
    for i in range(1, len(valid)):
        prev = valid[i - 1]
        curr = valid[i]
        if curr["first_mention_page"] < prev["first_mention_page"]:
            violations.append({
                "figure":          curr["number"],
                "mentioned_on_page": curr["first_mention_page"],
                "before_figure":   prev["number"],
                "before_page":     prev["first_mention_page"],
                "detail": (
                    f"Figure {curr['number']} is first mentioned on page "
                    f"{curr['first_mention_page']}, before Figure {prev['number']} "
                    f"(first mentioned on page {prev['first_mention_page']})."
                ),
            })

    passed = not violations
    if passed:
        detail = "All figures appear in chronological (numerical) order in the text."
    else:
        detail = (
            f"Figure chronological order violated in {len(violations)} case(s). "
            + violations[0]["detail"]
        )

    return {"passed": passed, "violations": violations, "detail": detail}


# -------------------------------------------------------------------------
# Check 10: Chronological Appearance of Tables
# -------------------------------------------------------------------------

def _check_table_chronological_order(
    tables: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Check 10 - Chronological Appearance of Tables.

    Validates that tables are first mentioned in the body text in ascending
    numerical order (Table 1 before Table 2, etc.).

    Data used:
        tables[i]["number"]             -- table number (int)
        tables[i]["first_mention_page"] -- page of first in-text mention,
                                          computed by structural_analyzer via
                                          _TABLE_MENTION_RE on full_text.

    Returns:
        {
          "passed":     bool,
          "violations": List[dict],
          "detail":     str,
        }
    """
    valid = sorted(
        [t for t in tables
         if isinstance(t.get("number"), int)
         and isinstance(t.get("first_mention_page"), int)],
        key=lambda t: t["number"],
    )

    if len(valid) < 2:
        return {
            "passed": True,
            "violations": [],
            "detail": "Fewer than 2 tables with in-text mentions; order check not applicable.",
        }

    violations: List[Dict[str, Any]] = []
    for i in range(1, len(valid)):
        prev = valid[i - 1]
        curr = valid[i]
        if curr["first_mention_page"] < prev["first_mention_page"]:
            violations.append({
                "table":           curr["number"],
                "mentioned_on_page": curr["first_mention_page"],
                "before_table":    prev["number"],
                "before_page":     prev["first_mention_page"],
                "detail": (
                    f"Table {curr['number']} is first mentioned on page "
                    f"{curr['first_mention_page']}, before Table {prev['number']} "
                    f"(first mentioned on page {prev['first_mention_page']})."
                ),
            })

    passed = not violations
    if passed:
        detail = "All tables appear in chronological (numerical) order in the text."
    else:
        detail = (
            f"Table chronological order violated in {len(violations)} case(s). "
            + violations[0]["detail"]
        )

    return {"passed": passed, "violations": violations, "detail": detail}


# -------------------------------------------------------------------------
# Check 13: Figure Parts Mention
# -------------------------------------------------------------------------
import re as _re

# Matches a labeled sub-figure reference: (a), (b), (A), (B), etc.
_SUBFIG_PART_RE = _re.compile(r'\(([a-zA-Z])\)')

def _check_figure_parts_mention(
    figures: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Check 13 - Figure Parts Mention.

    For every figure whose caption contains labeled sub-parts (a), (b), (c)...,
    verifies that ALL parts form a complete, consecutive alphabetical sequence
    starting from 'a' (or 'A').

    Examples:
        Caption: "... (a) network layout, (b) results, (c) comparison"
          -> parts found: {a,b,c}  expected: {a,b,c}  -> PASS

        Caption: "... (a) diagram, (c) overview"
          -> parts found: {a,c}  expected: {a,b,c}  -> FAIL  missing: (b)

        Caption: no sub-part labels -> skipped (not applicable)

    Data used:
        figures[i]["number"]       -- int
        figures[i]["caption_text"] -- str  (already extracted by structural_analyzer)

    Regex:
        _SUBFIG_PART_RE = re.compile(r'[(]([a-zA-Z])[)]')
        Finds all single-letter labels in parentheses within the caption.

    Returns:
        {
          "passed":     bool,
          "violations": List[dict],   # figures with incomplete part labeling
          "detail":     str,
        }
    """
    violations: List[Dict[str, Any]] = []

    for fig in figures:
        num = fig.get("number")
        caption = fig.get("caption_text", "")
        if not caption:
            continue

        # Extract all single-letter labels in parens from caption
        raw_labels = _SUBFIG_PART_RE.findall(caption)
        if not raw_labels:
            continue  # No sub-part labels -> not applicable for this figure

        # Normalize to lowercase for uniformity
        labels = [lbl.lower() for lbl in raw_labels]
        unique_labels = sorted(set(labels))

        # ── Guard: ignore math/variable false positives ───────────────────────
        # A genuine sub-figure sequence must either:
        #   (a) start with 'a', OR
        #   (b) have 2+ consecutive letters
        # Single isolated letters like (m), (n), (r) are math variables, not parts.
        is_consecutive = len(unique_labels) >= 2 and all(
            ord(unique_labels[i+1]) - ord(unique_labels[i]) == 1
            for i in range(len(unique_labels)-1)
        )
        if 'a' not in unique_labels and not is_consecutive:
            continue  # Math variable in parens — not a sub-figure label
        # ─────────────────────────────────────────────────────────────────────

        # Must start from 'a'
        first = unique_labels[0]
        last  = unique_labels[-1]

        # Build expected consecutive sequence: a, b, c ... up to last found
        expected = [chr(ord('a') + i) for i in range(ord(last) - ord('a') + 1)]
        missing  = [lbl for lbl in expected if lbl not in set(unique_labels)]

        if first != 'a':
            violations.append({
                "figure":         num,
                "page":           fig.get("caption_bbox", {}).get("page"),
                "found_parts":    unique_labels,
                "missing_parts":  [],
                "detail": (
                    f"Figure {num}: sub-part labels do not start from '(a)'. "
                    f"Found: {unique_labels}."
                ),
            })
        elif missing:
            violations.append({
                "figure":        num,
                "page":          fig.get("caption_bbox", {}).get("page"),
                "found_parts":   unique_labels,
                "missing_parts": missing,
                "detail": (
                    f"Figure {num}: sub-part label(s) {missing} are missing "
                    f"from the caption. Found: {unique_labels}."
                ),
            })

    passed = not violations
    if passed:
        detail = (
            "All figures with sub-part labels have complete, "
            "consecutive part sequences in their captions."
        )
    else:
        detail = (
            f"{len(violations)} figure(s) have incomplete sub-part labeling. "
            + violations[0]["detail"]
        )

    return {"passed": passed, "violations": violations, "detail": detail}


# -------------------------------------------------------------------------
# Check 11: Caption Positioning of Table  (caption must be ABOVE the table)
# -------------------------------------------------------------------------

def _check_table_caption_above(
    tables: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Check 11 - Caption Positioning of Table.

    Validates that each table's caption line is physically located ABOVE
    the first row of the table body on the same PDF page.

    Data used:
        tables[i]["caption_bbox"]["y1"]  -- bottom y of the last caption line,
                                            now saved by structural_analyzer.
        tables[i]["table_body_y0"]       -- top y of the first detected table-
                                            body line (header keyword, column-
                                            formatted row, or gap-separated line).
        Both values are on the same page (caption_page).

    Rule:
        caption_y1 < table_body_y0  --> caption is above  --> PASS
        caption_y1 >= table_body_y0 --> caption is below  --> FAIL

    A table is skipped when table_body_y0 is None (body not detectable on
    the same page from the extracted text lines).

    Returns:
        {
          "passed":     bool,
          "violations": List[dict],
          "skipped":    int,
          "detail":     str,
        }
    """
    violations: List[Dict[str, Any]] = []
    skipped = 0

    for tbl in tables:
        num          = tbl.get("number")
        caption_bbox = tbl.get("caption_bbox")
        body_y0      = tbl.get("table_body_y0")

        # Skip if either coordinate is unavailable
        if caption_bbox is None or body_y0 is None:
            skipped += 1
            continue

        cap_y0 = caption_bbox["y0"]   # top edge of caption

        # In PDF coordinate space y increases downward.
        # We check if the caption STARTS below the table body top.
        # This allows side-by-side captions (where cap_y0 ~ body_y0) to pass,
        # while catching captions that are genuinely placed below the table.
        if cap_y0 > (body_y0 + CAPTION_POSITION_TOLERANCE):
            violations.append({
                "table":           num,
                "page":            caption_bbox["page"],
                "caption_y0":      round(cap_y0, 2),
                "table_body_y0":   round(body_y0, 2),
                "detail": (
                    f"Table {num} (page {caption_bbox['page']}): caption top "
                    f"(y={cap_y0:.1f}) is below the table body top "
                    f"(y={body_y0:.1f})."
                ),
            })

    passed = not violations
    if passed:
        detail = (
            f"All verifiable table captions are positioned above their tables"
            f" ({skipped} table(s) skipped — body position not detectable)."
        )
    else:
        detail = (
            f"{len(violations)} table(s) have caption NOT above the table body. "
            + violations[0]["detail"]
        )

    return {
        "passed":     passed,
        "violations": violations,
        "skipped":    skipped,
        "detail":     detail,
    }


# -------------------------------------------------------------------------
# Check 12: Caption Positioning of Figure  (caption must be BELOW the figure)
# -------------------------------------------------------------------------

def _check_figure_caption_below(
    figures: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Check 12 - Caption Positioning of Figure.

    Validates that each figure's caption line is physically located BELOW
    the image block on the same PDF page.

    Data used:
        figures[i]["image_bbox"]["y1"]   -- bottom y of the matched image block,
                                            extracted by PyMuPDF image_info.
        figures[i]["caption_bbox"]["y0"] -- top y of the caption text,
                                            now saved by structural_analyzer.
        figures[i]["image_bbox"]["page"] -- must equal caption_bbox["page"].

    Rule:
        caption_y0 > image_y1  --> caption is below  --> PASS
        caption_y0 <= image_y1 --> caption is above  --> FAIL

    A figure is skipped when the image and caption are on different pages, or
    when either bbox is unavailable.

    Returns:
        {
          "passed":     bool,
          "violations": List[dict],
          "skipped":    int,
          "detail":     str,
        }
    """
    violations: List[Dict[str, Any]] = []
    skipped = 0

    for fig in figures:
        num          = fig.get("number")
        image_bbox   = fig.get("image_bbox")
        caption_bbox = fig.get("caption_bbox")

        if image_bbox is None or caption_bbox is None:
            skipped += 1
            continue

        # Only check when image and caption are on the same page
        if image_bbox.get("page") != caption_bbox.get("page"):
            skipped += 1
            continue

        cap_y1  = caption_bbox["y1"]   # bottom edge of caption
        img_y0  = image_bbox["y0"]     # top edge of image

        # "caption below image" means the caption should not be placed above the image.
        # We check if the caption ENDS above the top of the image.
        # This allows side-by-side captions to pass.
        if cap_y1 < (img_y0 - CAPTION_POSITION_TOLERANCE):
            violations.append({
                "figure":       num,
                "page":         caption_bbox["page"],
                "image_y0":     round(img_y0, 2),
                "caption_y1":   round(cap_y1, 2),
                "detail": (
                    f"Figure {num} (page {caption_bbox['page']}): caption bottom "
                    f"(y={cap_y1:.1f}) is placed above the image top "
                    f"(y={img_y0:.1f})."
                ),
            })

    passed = not violations
    if passed:
        detail = (
            f"All verifiable figure captions are positioned below their figures"
            f" ({skipped} figure(s) skipped — cross-page or bbox unavailable)."
        )
    else:
        detail = (
            f"{len(violations)} figure(s) have caption NOT below the image. "
            + violations[0]["detail"]
        )

    return {
        "passed":     passed,
        "violations": violations,
        "skipped":    skipped,
        "detail":     detail,
    }
