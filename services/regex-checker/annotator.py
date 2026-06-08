"""
annotator.py — Draw colored rectangles on a PDF at issue locations.

Uses PyMuPDF's shape API (draw_rect) instead of add_highlight_annot because
highlight annotations only work on PDFs with an embedded text layer. Shape
drawing works on ALL PDF types including OCR/scanned documents.
"""
import fitz
import io
from typing import List, Dict, Any

# RGB + fill-opacity per category
CATEGORY_STYLE = {
    "TYPOS":      {"rgb": (0.90, 0.15, 0.15), "alpha": 0.28, "border_w": 1.2},
    "GRAMMAR":    {"rgb": (0.05, 0.72, 0.42), "alpha": 0.25, "border_w": 1.0},
    "TYPOGRAPHY": {"rgb": (0.38, 0.38, 0.90), "alpha": 0.25, "border_w": 1.0},
    "MISC":       {"rgb": (0.90, 0.58, 0.08), "alpha": 0.25, "border_w": 1.0},
    "Formatting": {"rgb": (0.90, 0.58, 0.08), "alpha": 0.28, "border_w": 1.2},
    "ARTICLE":    {"rgb": (0.05, 0.62, 0.90), "alpha": 0.25, "border_w": 1.0},
    "FIGURE":     {"rgb": (0.58, 0.12, 0.82), "alpha": 0.28, "border_w": 1.5},
    "TABLE":      {"rgb": (0.05, 0.58, 0.60), "alpha": 0.28, "border_w": 1.5},
    "DEFAULT":    {"rgb": (0.50, 0.50, 0.50), "alpha": 0.20, "border_w": 1.0},
}


def _get_style(category: str) -> dict:
    return CATEGORY_STYLE.get(category, CATEGORY_STYLE["DEFAULT"])


def _draw_highlight(page: fitz.Page, rect: fitz.Rect, style: dict, note: str = ""):
    """Draw a semi-transparent coloured rectangle using the shape API."""
    rgb  = style["rgb"]
    alph = style["alpha"]
    bw   = style["border_w"]

    shape = page.new_shape()
    shape.draw_rect(rect)
    shape.finish(
        color=rgb,          # border colour
        fill=rgb,           # fill colour
        fill_opacity=alph,  # transparency
        width=bw,
    )
    shape.commit()

    # Add a popup note annotation so users see the message on click
    if note:
        try:
            annot = page.add_text_annot(fitz.Point(rect.x0, rect.y0), note[:500], icon="Note")
            annot.set_info(title="ReportGPS")
            annot.update()
        except Exception:
            pass  # never crash if annotation fails


def annotate_pdf(
    pdf_bytes: bytes,
    issues: List[Dict[str, Any]],
    llm_issues: List[Dict[str, Any]],
) -> bytes:
    """
    Draw issue highlights on every page that has detected problems.

    Priority:
      1. Issues WITH exact coordinates → draw precise rectangle.
      2. Issues WITH page number but no coordinates → draw colour-coded tab
         on the right margin so the page is still visually flagged.
      3. LLM (figure/table) issues → draw rectangle at caption boundary.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    # Collect per-page margin issues (no exact coords)
    margin_issues: Dict[int, List[Dict]] = {}

    # ── Regular language/grammar/reference issues ──────────────────────────
    for issue in issues:
        coords   = issue.get("coordinates", [])
        page_num = int(issue.get("page", 0))

        if page_num < 1 or page_num > doc.page_count:
            continue

        page = doc[page_num - 1]
        category = issue.get("category", "DEFAULT")
        style    = _get_style(category)
        msg      = issue.get("message", "")

        if coords and len(coords) == 4:
            x0, y0, x1, y1 = [float(v) for v in coords]
            # Sanity check: valid non-empty rectangle
            if x1 > x0 and y1 > y0:
                rect = fitz.Rect(x0, y0, x1, y1)
                _draw_highlight(page, rect, style, msg)
                continue

        # No valid coordinates → queue for margin indicator
        margin_issues.setdefault(page_num, []).append(issue)

    # ── Margin indicators for issues without exact coords ─────────────────
    for page_num, page_issue_list in margin_issues.items():
        page      = doc[page_num - 1]
        pw        = page.rect.width
        ph        = page.rect.height
        tab_w     = 10.0                  # width of each margin tab
        max_tabs  = min(len(page_issue_list), 40)
        tab_h     = max(6.0, (ph - 20) / max_tabs)

        for i, issue in enumerate(page_issue_list[:max_tabs]):
            y0   = 10.0 + i * tab_h
            y1   = y0 + tab_h * 0.85
            rect = fitz.Rect(pw - tab_w - 1, y0, pw - 1, y1)
            cat  = issue.get("category", "DEFAULT")
            _draw_highlight(page, rect, _get_style(cat), issue.get("message", ""))

    # ── LLM figure / table caption issues ─────────────────────────────────
    for issue in llm_issues:
        cap   = issue.get("caption_coordinate", {})
        pnum  = int(issue.get("page_number", 0))
        if not cap or pnum < 1 or pnum > doc.page_count:
            continue

        page = doc[pnum - 1]
        x0 = float(cap.get("x1", 0))
        y0 = float(cap.get("y1", 0))
        x1 = float(cap.get("x2", 0))
        y1 = float(cap.get("y2", 0))
        if x1 > x0 and y1 > y0:
            ftype = (issue.get("fig_type", "FIGURE")).upper()
            _draw_highlight(
                page,
                fitz.Rect(x0, y0, x1, y1),
                _get_style(ftype),
                issue.get("description", ""),
            )

    out = io.BytesIO()
    doc.save(out, garbage=4, deflate=True)
    doc.close()
    out.seek(0)
    return out.read()
