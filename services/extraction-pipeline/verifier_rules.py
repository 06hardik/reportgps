"""
verifier_rules.py
=================
Registry of all checks that the AI Verifier may be asked to validate.

Each entry defines:
  check_id            - machine key matching the key used in the result dict
  check_name          - human-readable name shown in the UI
  rule                - the exact rule text sent verbatim to the verifier LLM
  category            - UI category (matches parseIssues categories in App.jsx)
  skip_verifier       - True for fully deterministic checks that never need LLM
  detector_confidence - default confidence level the detector assigns (0-1)
"""
from __future__ import annotations
from typing import Dict, Any

RULES: Dict[str, Dict[str, Any]] = {

    # ── Figures & Tables ──────────────────────────────────────────────────────

    "figure_caption_below": {
        "check_id":             "figure_caption_below",
        "check_name":           "Caption Positioning",
        "rule":                 "Figure captions must be positioned below the corresponding image.",
        "category":             "Figures",
        "skip_verifier":        False,
        "detector_confidence":  0.72,
    },
    "table_caption_above": {
        "check_id":             "table_caption_above",
        "check_name":           "Caption Positioning",
        "rule":                 "Table captions must be positioned above the table body.",
        "category":             "Tables",
        "skip_verifier":        False,
        "detector_confidence":  0.72,
    },
    "figure_sequential_numbering": {
        "check_id":             "figure_sequential_numbering",
        "check_name":           "Figure Numbering",
        "rule":                 "Figures must be numbered sequentially starting from 1, with no gaps and no repeated numbers.",
        "category":             "Figures",
        "skip_verifier":        True,   # Deterministic: number either exists or not
        "detector_confidence":  0.98,
    },
    "table_sequential_numbering": {
        "check_id":             "table_sequential_numbering",
        "check_name":           "Table Numbering",
        "rule":                 "Tables must be numbered sequentially starting from 1, with no gaps and no repeated numbers.",
        "category":             "Tables",
        "skip_verifier":        True,
        "detector_confidence":  0.98,
    },
    "figure_chronological_order": {
        "check_id":             "figure_chronological_order",
        "check_name":           "Chronological Appearance",
        "rule":                 "Figures must be first mentioned in the body text in ascending numerical order (Figure 1 before Figure 2, etc.).",
        "category":             "Figures",
        "skip_verifier":        False,
        "detector_confidence":  0.70,
    },
    "table_chronological_order": {
        "check_id":             "table_chronological_order",
        "check_name":           "Chronological Appearance",
        "rule":                 "Tables must be first mentioned in the body text in ascending numerical order (Table 1 before Table 2, etc.).",
        "category":             "Tables",
        "skip_verifier":        False,
        "detector_confidence":  0.70,
    },
    "figure_parts_mention": {
        "check_id":             "figure_parts_mention",
        "check_name":           "Figure Parts Mention",
        "rule":                 "If a figure caption labels sub-parts using letters such as (a), (b), (c), the labels must form a complete consecutive alphabetical sequence starting from (a).",
        "category":             "Figures",
        "skip_verifier":        False,
        "detector_confidence":  0.78,
    },

    # ── Syntax & Grammar ─────────────────────────────────────────────────────

    "acronym_definition": {
        "check_id":             "acronym_definition",
        "check_name":           "Acronym Definition",
        "rule":                 "Every acronym must be spelled out in full at its first occurrence in the paper, with the abbreviation following in parentheses, e.g. Convolutional Neural Network (CNN).",
        "category":             "Structure",
        "skip_verifier":        False,
        "detector_confidence":  0.68,
    },
    "en_dash_ranges": {
        "check_id":             "en_dash_ranges",
        "check_name":           "En-dash for Ranges",
        "rule":                 "Numeric ranges must use an en-dash (--) not a hyphen (-). Example: pages 10-20 is incorrect; pages 10--20 is correct.",
        "category":             "Formatting",
        "skip_verifier":        True,   # Pattern is deterministic
        "detector_confidence":  0.95,
    },
    "nonbreaking_space_units": {
        "check_id":             "nonbreaking_space_units",
        "check_name":           "Non-breaking Space",
        "rule":                 "A non-breaking space must appear between a number and its unit of measurement, e.g. 10 kHz not 10kHz.",
        "category":             "Formatting",
        "skip_verifier":        True,
        "detector_confidence":  0.93,
    },
    "no_space_percent_degree": {
        "check_id":             "no_space_percent_degree",
        "check_name":           "Percent/Degree Spacing",
        "rule":                 "No space should appear between a number and the percent (%) or degree symbol. Example: 95% not 95 %.",
        "category":             "Formatting",
        "skip_verifier":        True,
        "detector_confidence":  0.95,
    },
    "double_spaces": {
        "check_id":             "double_spaces",
        "check_name":           "Double Spaces",
        "rule":                 "No consecutive double spaces should appear in the body text.",
        "category":             "Formatting",
        "skip_verifier":        True,
        "detector_confidence":  0.99,
    },
    "punctuation_spacing": {
        "check_id":             "punctuation_spacing",
        "check_name":           "Punctuation Spacing",
        "rule":                 "Punctuation marks must be followed by exactly one space and must not be preceded by a space.",
        "category":             "Formatting",
        "skip_verifier":        True,
        "detector_confidence":  0.92,
    },
    "quote_style_consistency": {
        "check_id":             "quote_style_consistency",
        "check_name":           "Quote Style Consistency",
        "rule":                 "The same style of quotation marks must be used consistently throughout the document. Mixing straight quotes and curly quotes is not allowed.",
        "category":             "Formatting",
        "skip_verifier":        False,
        "detector_confidence":  0.75,
    },
    "english_spelling_consistency": {
        "check_id":             "english_spelling_consistency",
        "check_name":           "Spelling Consistency",
        "rule":                 "American English and British English spelling variants must not be mixed. The document must consistently use one variant throughout.",
        "category":             "Formatting",
        "skip_verifier":        False,
        "detector_confidence":  0.70,
    },

    # ── References ───────────────────────────────────────────────────────────

    "style_compliance": {
        "check_id":             "style_compliance",
        "check_name":           "Style Compliance",
        "rule":                 "All references must conform to a single consistent citation style throughout the document.",
        "category":             "References",
        "skip_verifier":        False,
        "detector_confidence":  0.65,
    },
    "bidirectional_match": {
        "check_id":             "bidirectional_match",
        "check_name":           "Bidirectional Citation Match",
        "rule":                 "Every citation in the body text must have a corresponding entry in the reference list, and every entry in the reference list must be cited at least once in the body text.",
        "category":             "References",
        "skip_verifier":        False,
        "detector_confidence":  0.75,
    },
    "metadata_completeness": {
        "check_id":             "metadata_completeness",
        "check_name":           "Metadata Completeness",
        "rule":                 "Each reference must include all required fields for its type (e.g. journal articles require author, title, journal, year, volume; conference papers require author, title, booktitle, year).",
        "category":             "References",
        "skip_verifier":        False,
        "detector_confidence":  0.68,
    },
    "doi_url": {
        "check_id":             "doi_url",
        "check_name":           "DOI / URL",
        "rule":                 "References that have a DOI or URL must include it correctly formatted.",
        "category":             "References",
        "skip_verifier":        False,
        "detector_confidence":  0.70,
    },
    "sequential_ordering": {
        "check_id":             "sequential_ordering",
        "check_name":           "Sequential Ordering",
        "rule":                 "References must appear in sequential numerical order in the reference list.",
        "category":             "References",
        "skip_verifier":        False,
        "detector_confidence":  0.80,
    },
    "field_consistency": {
        "check_id":             "field_consistency",
        "check_name":           "Field Consistency",
        "rule":                 "References of the same type must include a consistent set of fields across all entries.",
        "category":             "References",
        "skip_verifier":        False,
        "detector_confidence":  0.65,
    },
}


def get_rule(check_id: str) -> Dict[str, Any]:
    """Return the rule dict for a given check_id, or a generic fallback."""
    return RULES.get(check_id, {
        "check_id":            check_id,
        "check_name":          check_id.replace("_", " ").title(),
        "rule":                "See check documentation.",
        "category":            "General",
        "skip_verifier":       False,
        "detector_confidence": 0.70,
    })
