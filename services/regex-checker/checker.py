"""
checker.py — Core analysis logic for the regex-checker service.

Key improvements in this version:
  - Section-aware: LanguageTool only runs on body text (not references/abstract).
  - _filter_prose() strips equations, figure captions, table cells, URLs,
    citation lines, and other non-prose content BEFORE sending to LT.
  - Aggressive LT rule ignore-list targeting scientific false-positives.
  - Issue cap: max 60 LT issues per document to prevent noise overload.
  - raw_ref_strings returned in response for reference-analyser pipeline.
"""
import re
import traceback
from typing import Dict, List, Optional, Tuple, Any

import fitz
import pymupdf4llm
from collections import Counter
from markdown_it import MarkdownIt
from mdit_plain.renderer import RendererPlain
import language_tool_python

from section_extractor import extract_sections

CONTEXT_LENGTH = 12   # chars of context around each LanguageTool error
MAX_LT_ISSUES  = 60   # cap to prevent noise overload on large papers


# ────────────────────────────────────────────────────────────────────────────
# Text helpers
# ────────────────────────────────────────────────────────────────────────────

def convert_markdown_to_plain_text(md: str) -> str:
    if not md:
        return ""
    try:
        parser = MarkdownIt(renderer_cls=RendererPlain)
        return parser.render(md)
    except Exception as e:
        print(f"Markdown→plain error: {e}")
        return md


def _clean(text: str) -> str:
    return re.sub(r'\s+', ' ', text.replace('\n', ' ')).strip()


# ────────────────────────────────────────────────────────────────────────────
# Non-prose line filter — removes content that causes LT false-positives
# ────────────────────────────────────────────────────────────────────────────

# Patterns for lines that are NOT prose and should be excluded from LT
_NON_PROSE_PATTERNS = [
    re.compile(r'https?://\S+'),                          # URLs
    re.compile(r'^\s*\[\d+\]'),                           # citation lines [1]
    re.compile(r'^\s*\d+\.\s+\S'),                        # numbered lists starting with digit.
    re.compile(r'[=\+\-\*\/]{3,}'),                       # math operators repeated
    re.compile(r'\\[a-zA-Z]+\{'),                         # LaTeX commands
    re.compile(r'\$.*?\$'),                               # inline math
    re.compile(r'[A-Z]{4,}\s*[=:]\s*\S'),                # ALL_CAPS definitions
    re.compile(r'^\s*Table\s+\d+', re.I),                 # table headers
    re.compile(r'^\s*Fig(?:ure)?\.?\s*\d+', re.I),       # figure captions
    re.compile(r'^\s*Algorithm\s+\d+', re.I),             # algorithm blocks
    re.compile(r'^\s*[\|\+\-]{3,}'),                      # table borders
    re.compile(r'<[a-z]+[^>]*>'),                         # HTML tags
    re.compile(r'^\s*\w+\s*\(?\s*\d{4}\s*\)?'),          # author (year) citation
    re.compile(r'^\s*et\s+al\.', re.I),                   # et al. lines
    re.compile(r'^\s*doi:\s*\S+', re.I),                  # DOI lines
    # lines that are mostly non-alphabetic (equations, code)
]

# Rules LT fires on constantly in academic text (false positives for scientific writing)
_LT_IGNORE_RULES = {
    # Spelling — scientific terms LT doesn't know
    "EN_SPLIT_WORDS_HYPHEN",
    "MORFOLOGIK_RULE_EN_US",
    "MORFOLOGIK_RULE_EN_GB",
    "SPELLING_RULE",
    # Punctuation style — APA/IEEE have different conventions
    "COMMA_BEFORE_AND",
    "COMMA_COMPOUND_SENTENCE",
    "COMMA_PARENTHESIS_WHITESPACE",
    "OXFORD_SPELLING_NOUNS",
    # Capitalization — acronyms, proper nouns in science
    "UPPERCASE_SENTENCE_START",
    "SENTENCE_WHITESPACE",
    # Whitespace noise
    "WHITESPACE_RULE",
    "DOUBLE_PUNCTUATION",
    # Grammar rules that misfire on technical writing
    "EN_QUOTES",
    "DASH_RULE",
    "UNIT_SPACE",
    "UNIT_ABBREVIATION",
    "METRIC_UNITS_EN_US",
    "UNPAIRED_BRACKETS",
    "TOO_LONG_SENTENCE",
    "LONG_SENTENCES",
    # Redundancy — too many false positives
    "REDUNDANCY",
    "SENT_START_CONJUNCTIVE_LINKING_ADVERB_COMMA",
    # Style rules — subjective
    "WIKIPEDIA",
    "EN_UNPAIRED_QUOTES",
    "CURRENCY",
    "APOS_ARE",
    # Math/formula fragments
    "MISSING_PERIOD_AFTER_ABBREVIATION",
    "ABBREVIATION",
    "TWO_IN_A_ROW",
    "ARROWS",
}

# Categories that are mostly noise for technical papers
_LT_IGNORE_CATEGORIES = {
    "STYLE",
    "TYPOGRAPHY",
    "REDUNDANCY",
    "MISC",
}


def _is_prose_line(line: str) -> bool:
    """Return True if this line looks like natural language prose worth checking."""
    line = line.strip()
    if len(line) < 20:
        return False  # too short to analyse

    # Check non-prose patterns
    for pat in _NON_PROSE_PATTERNS:
        if pat.search(line):
            return False

    # If more than 40% of characters are non-alphabetic → likely math/code
    alpha = sum(1 for c in line if c.isalpha())
    if len(line) > 0 and alpha / len(line) < 0.60:
        return False

    # Lines that are mostly UPPERCASE → headings / abbreviations
    if alpha > 0 and sum(1 for c in line if c.isupper()) / alpha > 0.55:
        return False

    return True


def _filter_to_prose(text: str) -> str:
    """
    Filter body text to keep only lines that look like prose sentences.
    This dramatically reduces LT false-positives from equations,
    figure captions, algorithm lines, etc.
    """
    lines = text.splitlines()
    kept = [ln for ln in lines if _is_prose_line(ln)]
    return "\n".join(kept)


# ────────────────────────────────────────────────────────────────────────────
# PDF text extraction — page-tracked
# ────────────────────────────────────────────────────────────────────────────

def extract_pdf_text_with_pages(path: str) -> Tuple[str, List[Tuple[int, int, int]], str]:
    """
    Extract full-document text using pymupdf4llm page_chunks=True.
    Returns (full_text, page_offsets, full_markdown).
    """
    try:
        chunks = pymupdf4llm.to_markdown(path, page_chunks=True)
    except Exception as e:
        print(f"pymupdf4llm page_chunks error: {e}. Falling back.")
        md    = pymupdf4llm.to_markdown(path)
        plain = _clean(convert_markdown_to_plain_text(md))
        return plain, [(0, len(plain), 1)], md

    all_parts:    List[str]   = []
    page_offsets: List[Tuple] = []
    md_parts:     List[str]   = []
    current = 0

    for chunk in (chunks or []):
        if not isinstance(chunk, dict):
            continue
        meta     = chunk.get("metadata", {})
        page_num = int(meta.get("page", 0)) + 1
        md_text  = chunk.get("text", "")
        md_parts.append(md_text)

        plain = _clean(convert_markdown_to_plain_text(md_text))
        if not plain:
            continue

        start = current
        end   = current + len(plain)
        page_offsets.append((start, end, page_num))
        all_parts.append(plain)
        current = end + 1

    full_text     = ' '.join(all_parts)
    full_markdown = '\n\n'.join(md_parts)
    return full_text, page_offsets, full_markdown


def _page_for_offset(offset: int, page_offsets: List[Tuple]) -> int:
    for start, end, pnum in page_offsets:
        if start <= offset < end:
            return pnum
    return 0


# ────────────────────────────────────────────────────────────────────────────
# Structural checks
# ────────────────────────────────────────────────────────────────────────────

def check_metadata(plain_text: str) -> dict:
    return {
        "author_email":    bool(re.search(r'\b[\w.-]+?@\w+?\.\w+?\b', plain_text)),
        "list_of_authors": bool(re.search(r'Authors?:', plain_text, re.IGNORECASE)),
        "keywords_list":   bool(re.search(r'Keywords?:', plain_text, re.IGNORECASE)),
        "word_count":      len(plain_text.split()) or "Missing",
    }


def check_disclosures(plain_text: str) -> dict:
    terms = [
        "conflict of interest statement",
        "ethics statement",
        "funding statement",
        "data access statement",
    ]
    results = {t: t.lower() in plain_text.lower() for t in terms}
    results["author contribution statement"] = (
        "author contribution statement" in plain_text.lower()
        or "author contributions statement" in plain_text.lower()
    )
    return results


def check_figures_and_tables(plain_text: str) -> dict:
    return {
        "figures_with_citations": bool(re.search(r'Figure \d+.*?citation', plain_text, re.IGNORECASE)),
        "figures_legends":        bool(re.search(r'Figure \d+.*?legend',   plain_text, re.IGNORECASE)),
        "tables_legends":         bool(re.search(r'Table \d+.*?legend',    plain_text, re.IGNORECASE)),
    }


def check_references_summary(plain_text: str, ref_count: int = 0) -> dict:
    abstract_candidate = plain_text[:2000]
    return {
        "old_references":        bool(re.search(r'\b19[0-9]{2}\b', plain_text)),
        "citations_in_abstract": (
            bool(re.search(r'\[\d+\]', abstract_candidate))
            or bool(re.search(r'\bcit(?:ation|ed)\b', abstract_candidate, re.IGNORECASE))
        ),
        "reference_count":       ref_count or len(re.findall(r'\[\d+(?:,\s*\d+)*\]', plain_text)),
        "self_citations":        bool(re.search(r'Self-citation', plain_text, re.IGNORECASE)),
    }


def check_structure(sections: Dict[str, dict]) -> dict:
    present = set(sections.keys())
    return {
        "imrad_structure":  all(k in present for k in ("introduction", "methods", "results", "discussion")),
        "abstract_present": "abstract"   in present,
        "conclusion_present": "conclusion" in present,
        "references_present": "references" in present,
        "abstract_structure": "structured abstract" in
                              (sections.get("abstract", {}).get("text", "").lower()),
        "detected_sections":  sorted(present),
    }


def check_figure_order(plain_text: str) -> dict:
    nums = [int(n) for n in re.findall(
        r'(?:Fig(?:ure)?\.?|Figure)\s*(\d+)', plain_text, re.IGNORECASE
    ) if n.isdigit()]
    if not nums:
        return {"sequential_order_of_unique_figures": True, "figure_count_unique": 0,
                "missing_figures_in_sequence_to_max": [], "figure_order_as_encountered": [],
                "duplicate_references_to_same_figure_number": [], "figures_mentioned_only_once": []}
    unique  = sorted(set(nums))
    is_seq  = all(unique[i] + 1 == unique[i+1] for i in range(len(unique)-1)) if len(unique) > 1 else True
    counts  = Counter(nums)
    return {
        "sequential_order_of_unique_figures":         is_seq,
        "figure_count_unique":                        len(unique),
        "missing_figures_in_sequence_to_max":         sorted(set(range(1, unique[-1]+1)) - set(unique)),
        "figure_order_as_encountered":                nums,
        "duplicate_references_to_same_figure_number": sorted(n for n, c in counts.items() if c > 1),
        "figures_mentioned_only_once":                sorted(n for n, c in counts.items() if c == 1),
    }


def check_reference_order(plain_text: str) -> dict:
    nums = [int(r) for r in re.findall(r'\[(\d+)\]', plain_text) if r.isdigit()]
    out_of_order = []
    cur_max = 0
    for i, r in enumerate(nums):
        if r < cur_max:
            out_of_order.append({"position": i+1, "value": r, "prev_max": cur_max})
        cur_max = max(cur_max, r)
    max_val = max(nums) if nums else 0
    missing = sorted(set(range(1, max_val+1)) - set(nums)) if max_val else []
    is_ord  = all(nums[i] <= nums[i+1] for i in range(len(nums)-1)) if len(nums) > 1 else True
    return {
        "max_reference_number_cited":               max_val,
        "out_of_order_citations_details":           out_of_order,
        "missing_references_up_to_max_cited":       missing,
        "is_citation_order_non_decreasing_in_text": is_ord,
    }


# ────────────────────────────────────────────────────────────────────────────
# Language + Regex checks (body-only, prose-filtered)
# ────────────────────────────────────────────────────────────────────────────

def check_language_issues_and_regex(
    body_text:    str,
    page_offsets: List[Tuple[int, int, int]],
) -> dict:
    """
    Run LanguageTool + regex checks on body prose text only.
    The text is pre-filtered to remove equations, captions, and non-prose lines.
    """
    if not body_text.strip():
        return {"total_issues": 0, "issues_list": [], "text_used_for_analysis": ""}

    # Filter to prose sentences only
    prose_text = _filter_to_prose(body_text)
    if not prose_text.strip():
        # Fallback: use raw body text if filter removes everything
        prose_text = body_text

    # Flatten to single line for LT (preserves offset tracking)
    flat_text = _clean(prose_text)

    tool = None
    processed: List[dict] = []

    try:
        try:
            tool = language_tool_python.LanguageTool('en-US')
        except (SystemError, Exception) as java_err:
            print(f"Local LT failed ({java_err}), trying public API")
            tool = language_tool_python.LanguageToolPublicAPI('en-US')

        raw_matches = tool.check(flat_text)

        for idx, m in enumerate(raw_matches):
            # Skip rules we know fire false-positives on academic text
            if m.rule_id in _LT_IGNORE_RULES:
                continue
            # Skip entire noisy categories
            if m.category in _LT_IGNORE_CATEGORIES:
                continue
            # Skip very short errors (1-2 chars) — mostly punctuation noise
            if m.error_length < 3:
                continue
            # Stop at cap
            if len(processed) >= MAX_LT_ISSUES:
                break

            ctx_start = max(0, m.offset - CONTEXT_LENGTH)
            ctx_end   = min(len(flat_text), m.offset + m.error_length + CONTEXT_LENGTH)
            ctx_str   = flat_text[ctx_start:ctx_end]

            # Map offset back to original body text page
            # (page_offsets are for the full doc, so approximate via ratio)
            page_num  = _page_for_offset(m.offset, page_offsets)

            processed.append({
                '_internal_id':            f"lt_{idx}",
                'ruleId':                  m.rule_id,
                'message':                 m.message,
                'context_text':            ctx_str,
                'offset_in_text':          m.offset,
                'error_length':            m.error_length,
                'replacements_suggestion': m.replacements[:3] if m.replacements else [],
                'category_name':           m.category,
                'page_num_from_offset':    page_num,
                'is_mapped_to_pdf':        False,
                'pdf_coordinates_list':    [],
                'mapped_page_number':      page_num,
            })

        # Regex check: missing space before citation bracket
        for reg_idx, m in enumerate(re.finditer(r'\b(\w+)\[(\d+)\]', flat_text)):
            if len(processed) >= MAX_LT_ISSUES:
                break
            word, num = m.group(1), m.group(2)
            page_num  = _page_for_offset(m.start(), page_offsets)
            processed.append({
                '_internal_id':            f"regex_{reg_idx}",
                'ruleId':                  "SPACE_BEFORE_BRACKET",
                'message':                 f"Missing space before '[{num}]' after '{word}'. Should be '{word} [{num}]'.",
                'context_text':            flat_text[m.start():m.end()],
                'offset_in_text':          m.start(),
                'error_length':            m.end() - m.start(),
                'replacements_suggestion': [f"{word} [{num}]"],
                'category_name':           "Formatting",
                'page_num_from_offset':    page_num,
                'is_mapped_to_pdf':        False,
                'pdf_coordinates_list':    [],
                'mapped_page_number':      page_num,
            })

        print(f"[checker] LT: {len(raw_matches)} raw -> {len(processed)} after filtering")


        return {
            "total_issues":           len(processed),
            "issues_list":            processed,
            "text_used_for_analysis": flat_text[:500],  # preview only
        }

    except Exception as e:
        print(f"Error in check_language_issues_and_regex: {e}")
        traceback.print_exc()
        return {"error": str(e), "total_issues": 0, "issues_list": [], "text_used_for_analysis": ""}
    finally:
        if tool:
            try:
                tool.close()
            except Exception:
                pass


# ────────────────────────────────────────────────────────────────────────────
# Coordinate mapping — per-page fitz text search
# ────────────────────────────────────────────────────────────────────────────

def map_issues_to_coordinates(
    issues:       List[dict],
    page_offsets: List[Tuple[int, int, int]],
    pdf_path:     str,
) -> None:
    """Mutates each issue dict in-place with PDF coordinates where found."""
    from collections import defaultdict

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        print(f"Could not open PDF for coordinate mapping: {e}")
        return

    try:
        by_page: Dict[int, List[dict]] = defaultdict(list)
        for issue in issues:
            if not issue['is_mapped_to_pdf']:
                pn = issue['mapped_page_number']
                if 1 <= pn <= doc.page_count:
                    by_page[pn].append(issue)

        for pn, page_issues in by_page.items():
            page = doc[pn - 1]
            by_ctx: Dict[str, List[dict]] = {}
            for iss in page_issues:
                ctx = iss['context_text'].strip()
                if ctx:
                    by_ctx.setdefault(ctx, []).append(iss)

            for ctx, ctx_issues in by_ctx.items():
                try:
                    rects = page.search_for(
                        ctx,
                        flags=fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE,
                    )
                    for i, rect in enumerate(rects):
                        if i >= len(ctx_issues):
                            break
                        iss = ctx_issues[i]
                        if not iss['is_mapped_to_pdf']:
                            iss['pdf_coordinates_list'] = [
                                {"x0": rect.x0, "y0": rect.y0, "x1": rect.x1, "y1": rect.y1}
                            ]
                            iss['is_mapped_to_pdf']   = True
                            iss['mapped_page_number'] = pn
                except Exception as search_err:
                    print(f"search_for error on page {pn}: {search_err}")
    finally:
        doc.close()


# ────────────────────────────────────────────────────────────────────────────
# Main entry point
# ────────────────────────────────────────────────────────────────────────────

def analyze_pdf(pdf_path: str) -> dict:
    """
    Full analysis pipeline for a single PDF file path.
    Returns { issues, raw_ref_strings, document_checks }
    """
    try:
        # ── Step 1: Section extraction ────────────────────────────────
        sections = extract_sections(pdf_path)
        print(f"[checker] Detected sections: {list(sections.keys())}")

        # Body text for LT (section extractor already excludes references)
        body_text = sections.get("body", {}).get("text", "")

        # Build page offsets for coordinate mapping
        _, page_offsets, _ = extract_pdf_text_with_pages(pdf_path)

        # Fallback: if section extractor found no body, use full doc
        if not body_text:
            print("[checker] No body section found — using full document text")
            body_text_parts = []
            for key, sec in sections.items():
                if key != "references":
                    body_text_parts.append(sec.get("text", ""))
            body_text = "\n".join(body_text_parts)
            if not body_text:
                # Last resort: use page_offsets text
                full_text, _, _ = extract_pdf_text_with_pages(pdf_path)
                body_text = full_text

        # ── Step 2: Language + regex checks (prose body only) ────────
        lr_report  = check_language_issues_and_regex(body_text, page_offsets)
        raw_issues = lr_report.get("issues_list", [])

        # ── Step 3: Map to PDF coordinates ───────────────────────────
        if raw_issues:
            map_issues_to_coordinates(raw_issues, page_offsets, pdf_path)

        # ── Step 4: Format language issues ────────────────────────────
        final_issues = []
        for iss in raw_issues:
            coords   = []
            page_num = iss['mapped_page_number']
            if iss['is_mapped_to_pdf'] and iss['pdf_coordinates_list']:
                c = iss['pdf_coordinates_list'][0]
                coords = [c['x0'], c['y0'], c['x1'], c['y1']]
            final_issues.append({
                "message":     iss['message'],
                "context":     iss['context_text'],
                "suggestions": iss['replacements_suggestion'],
                "category":    iss['category_name'],
                "rule_id":     iss['ruleId'],
                "offset":      iss['offset_in_text'],
                "length":      iss['error_length'],
                "coordinates": coords,
                "page":        page_num,
            })

        # Raw reference strings (for quality-check pipeline fallback)
        raw_ref_strings = sections.get("references", {}).get("raw_strings", [])
        ref_count       = len(raw_ref_strings)
        print(f"[checker] Raw ref strings from PDF text: {ref_count}")

        # Full text for structural checks
        full_plain = " ".join(
            sec.get("text", "") for sec in sections.values()
        )

        return {
            "issues":          final_issues,
            "raw_ref_strings": raw_ref_strings,
            "document_checks": {
                "metadata":                       check_metadata(full_plain),
                "disclosures":                    check_disclosures(full_plain),
                "figures_and_tables":             check_figures_and_tables(full_plain),
                "references_summary":             check_references_summary(full_plain, ref_count),
                "structure":                      check_structure(sections),
                "figure_order_analysis":          check_figure_order(full_plain),
                "reference_order_analysis":       check_reference_order(full_plain),
                "plain_language_summary_present": bool(re.search(r'plain language summary', full_plain, re.IGNORECASE)),
                "readability_issues_detected":    False,
                "detected_sections":              list(sections.keys()),
            },
        }

    except Exception as e:
        print(f"Overall analysis error: {e}")
        traceback.print_exc()
        return {"error": str(e)}
