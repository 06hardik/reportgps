"""
check_style_conformity.py
=========================
Check 5 — Style conformity.

A reference list must use a single, consistent citation style throughout.
This check flags any entry whose individually-predicted style does NOT
match the dominant (majority) style detected across the whole list.

Only MEDIUM- and HIGH-confidence individual predictions are flagged —
LOW-confidence predictions are too ambiguous to report as violations
because the classifier may simply be uncertain about that entry.

Returns a StyleConformityResult with one StyleConformityIssue per
non-conforming entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class StyleConformityIssue:
    ref_id:            str
    position:          int
    entry_style:       str        # what this entry was classified as
    entry_confidence:  str        # HIGH / MEDIUM / LOW
    dominant_style:    str        # the expected style for the list
    detail:            str
    suggestion:        Optional[str] = None


@dataclass
class StyleConformityResult:
    dominant_style: str
    issues:         List[StyleConformityIssue] = field(default_factory=list)
    checked:        int = 0
    skipped_low:    int = 0       # entries skipped because confidence was LOW

    @property
    def passed(self) -> bool:
        return len(self.issues) == 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_style_conformity(
    entries:        List[Dict[str, Any]],
    dominant_style: str,
) -> StyleConformityResult:
    """
    Parameters
    ----------
    entries        : enriched reference dicts, each with a 'style' key
                     populated by the classifier step.  The 'style' dict
                     contains keys: 'predicted', 'confidence', 'scores'.
    dominant_style : the majority style detected across the list (already
                     computed in pipeline._detect_dominant_style).

    Returns
    -------
    StyleConformityResult with one StyleConformityIssue per non-conforming
    entry whose individual classification was MEDIUM or HIGH confidence.
    """
    result         = StyleConformityResult(dominant_style=dominant_style)
    dominant_upper = dominant_style.upper()

    for pos, entry in enumerate(entries, start=1):
        ref_id   = entry.get("id", f"ref_{pos:03d}")
        sty_info = entry.get("style") or {}

        predicted  = (sty_info.get("predicted")  or "").upper()
        confidence = (sty_info.get("confidence") or "LOW").upper()

        if not predicted:
            continue   # classifier did not run on this entry

        result.checked += 1

        # Skip LOW-confidence classifications — too unreliable to report
        if confidence == "LOW":
            result.skipped_low += 1
            continue

        if predicted == dominant_upper:
            continue   # entry matches the list style — all good

        # Build a readable score summary for the detail message
        scores    = sty_info.get("scores") or {}
        score_str = ""
        if scores:
            top = sorted(scores.items(), key=lambda x: -x[1])[:3]
            score_str = " (top scores: " + ", ".join(
                f"{s}={v:.1f}" for s, v in top
            ) + ")"

        result.issues.append(StyleConformityIssue(
            ref_id           = ref_id,
            position         = pos,
            entry_style      = predicted,
            entry_confidence = confidence,
            dominant_style   = dominant_upper,
            detail           = (
                f"Entry looks like {predicted} style ({confidence} confidence) "
                f"but the list uses {dominant_upper}.{score_str}"
            ),
            suggestion = (
                f"Reformat this entry to match {dominant_upper} style — "
                f"check author format, year placement, and punctuation."
            ),
        ))

    return result
