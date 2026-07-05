# ReportGPS — Extraction Pipeline Architecture (v3.0)

## Overview

The extraction pipeline is a **lean, 3-step PDF analysis service** that runs in **< 1 second per paper** (down from 50–175s in v2).

No LLM. No ML models. No heavy table grids. Every extraction is traceable to a PDF primitive (text, font size, bold flag, image block).

---

## Architecture

```
PDF Input
   │
   ▼ Step 1: PyMuPDF Full-Document Pass (~0.3–0.7s)
   │   • page_texts[], full_text
   │   • per-span: font_size, is_bold, bbox
   │   • image blocks per page: {x0,y0,x1,y1}
   │
   ▼ Step 2: Heuristic Structural Analysis (~0.03–0.1s)
   │   structural_analyzer.py
   │   a) Heading detection via font-size + bold flags
   │   b) Manuscript metadata (title, abstract, keywords, authors) from page-1 heuristics
   │   c) Figure discovery: regex for "Fig. N:" captions + PyMuPDF image bboxes
   │   d) Table discovery: regex for "Table N:" captions
   │   e) Equation discovery: regex for "(N)" at line-end
   │
   ▼ Step 3: Regex Extraction (~0.05–0.15s)
       a) regex_extractor.py → references + in-text citations
       b) typography_checker.py → en-dash, number-unit, percent/degree, latin abbreviations
```

---

## Modules

| File | Role | Status |
|---|---|---|
| `orchestrator.py` | Pipeline entry point (3 steps) | Active |
| `pymupdf_extractor.py` | PyMuPDF text + font + image extraction | Active |
| `structural_analyzer.py` | Heading/metadata/figure/table/equation detection | Active |
| `regex_extractor.py` | References + in-text citations | Active |
| `typography_checker.py` | Typography violation checks | Active |
| `app.py` | FastAPI wrapper (port 8004) | Active |
| `_archive/nuextract_client.py` | LLM client (archived — too slow) | Archived |

### Deleted Modules
- `merger.py` — only reconciled LLM page outputs
- `nuextract_schema.py` — LLM prompt schema
- `camelot_extractor.py` — full table grid extraction (not needed)
- `coordinate_mapper.py` — absorbed into structural_analyzer
- `document_extractor.py` — superseded by structural_analyzer
- `docling_extractor.py` — ML table extractor (can re-add if needed)

---

## Output JSON Schema

```json
{
  "manuscript": {
    "title": "...",
    "abstract_text": "...",
    "abstract_word_count": 243,
    "keywords": ["kw1", "kw2"],
    "keywords_section_present": true,
    "authors": ["Author A", "Author B"],
    "publishing_statements": {
      "conflict_of_interest": null,
      "ethics_statement": null,
      "funding_statement": null,
      "data_access_statement": null,
      "author_contribution_statement": null
    }
  },

  "sections": [
    {
      "heading_text": "Introduction",
      "heading_number": "1",
      "heading_level": 2,
      "page_number": 2,
      "bbox": {"page": 2, "x0": 54.0, "y0": 130.0, "x1": 200.0, "y1": 145.0},
      "coordinate_found": true
    }
  ],

  "figures": [
    {
      "number": 1,
      "caption_text": "Classification of metaheuristic algorithms",
      "caption_page": 3,
      "caption_ends_period": false,
      "image_bbox": {"page": 3, "x0": 52.6, "y0": 57.8, "x1": 542.7, "y1": 288.5},
      "first_mention_page": 2,
      "coordinate_found": true
    }
  ],

  "tables": [
    {
      "number": 1,
      "caption_text": "Standard benchmark test functions",
      "caption_page": 9,
      "caption_ends_period": false,
      "caption_bbox": null,
      "first_mention_page": 8,
      "coordinate_found": false
    }
  ],

  "equations": [
    {
      "number": 1,
      "number_format": "(1)",
      "raw_text": "fk = µk mg cos θ",
      "page_number": 7
    }
  ],

  "references": [
    {
      "raw_string": "1. Smith A (2020) Title. Journal 10(2):100–120",
      "number": 1,
      "year": 2020,
      "doi": null,
      "url": null,
      "bbox": {"page": 18, "x0": 306.1, "y0": 210.7, "x1": 546.4, "y1": 233.5},
      "coordinate_found": true
    }
  ],

  "in_text_citations": [
    {
      "marker": "[1]",
      "style": "numeric-bracket",
      "context_snippet": "...as shown in [1] the algorithm...",
      "page_number": 3
    }
  ],

  "typography": {
    "en_dash_violations":        [{"found": "1-5", "correct": "1–5", "snippet": "...pages 1-5 of...", "detail": "..."}],
    "number_unit_violations":    [{"found": "10ms", "correct": "10 ms", "snippet": "...", "detail": "..."}],
    "percent_degree_violations": [],
    "latin_abbrev_violations":   []
  },

  "estimated_word_count": 11260,
  "total_pages_processed": 19,
  "extraction_errors": [],
  "pipeline_timings": {
    "pymupdf_s": 0.67,
    "structural_s": 0.05,
    "regex_s": 0.08,
    "typography_s": 0.07,
    "total_s": 0.87
  }
}
```

---

## Performance Benchmarks (5 papers, 16–34 pages each)

| Paper | Pages | Time | Secs | Figs | Tbls | Eqs | Refs |
|---|---|---|---|---|---|---|---|
| Fog Computing+WOA | 18 | 0.55s | 13 | 10 | 12 | 42 | 43 |
| GG-GSA | 16 | 0.98s | 73 | 6 | 15 | 23 | 46 |
| GOA_paper | 18 | 1.17s | 30 | 13 | 16 | 0 | 65 |
| Giza | 19 | 0.81s | 19 | 9 | 9 | 9 | 61 |
| WOA+MFO image | 34 | 0.82s | 20 | 15 | 10 | 22 | 63 |
| **Average** | **21** | **0.87s** | | | | | |

**Previous pipeline (NuExtract): 50–175s per paper.**

---

## Structural Analyzer: Heading Detection

Font-size heuristics for heading detection:
- **Size heading**: `font_size >= body_font_size * 1.15`
- **Bold heading**: `is_bold AND font_size >= body_font_size AND len(text) <= 80 AND not sentence-like`
- **All-caps heading**: `ALL_CAPS AND len <= 50 AND font_size >= body_font_size * 0.9`
- **Excluded**: y0 < 55pt (header) or y1 > page_height-55pt (footer), figure/table caption patterns, journal titles

Body font size estimation uses **length-weighted mode** across all spans > 7pt, so footnote sizes don't skew the estimate.

---

## Regex Extractor: Reference Styles Supported

- **Numbered bracket**: `[1] Smith, A. ...`
- **Dot number**: `1. Smith, A. ...`
- **APA author-year**: `Smith, A. (2020). Title. Journal...`

Detection uses a layout-aware extraction that handles two-column PDFs, page headers/footers, and multi-line references.

---

## API

```
POST http://localhost:8004/extract
  Content-Type: multipart/form-data
  file: <PDF binary>

GET  http://localhost:8004/health
GET  http://localhost:8004/health/llm   (always returns unreachable now — LLM archived)
```

Response: JSON document as described above.
Typical response time: **< 2 seconds** for most papers.
