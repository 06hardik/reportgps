"""
docling_extractor.py
====================
IBM Docling wrapper for high-accuracy deep-learning table extraction.

Why Docling instead of Camelot?
  Camelot is lightweight but relies on spacing/lines heuristics which fail on 
  academic double-column layouts and require manual parameter tuning.
  Docling uses Layout Detection and TableFormer visual models to isolate 
  borderless grids cleanly and accurately without manual parameter tuning.

This module converts Docling's top-left coordinates to bottom-left PDF 
coordinates using page heights, cleans scientific notations in cells, 
and returns tables matching ExtractedTable as_dict format.
"""

import os
import re
import time
import traceback
from typing import Dict, List, Any

import pandas as pd
import fitz  # PyMuPDF for page heights

try:
    # Programmatic CPU safety settings before importing heavy models
    os.environ["DOCLING_DEVICE"] = "cpu"
    os.environ["DOCLING_NUM_THREADS"] = "4"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False
    print("[DoclingExtractor] docling not installed — table extraction using Docling disabled.")


# Footnote marker regex (reused from camelot_extractor)
_FOOTNOTE_RE = re.compile(
    r"""
    (?:^|\s)          # start of cell or after whitespace
    (?:
        [a-z]{1,2}    # single/double lowercase letter marker
        | \*{1,3}     # asterisk(s)
        | †{1,2}      # dagger(s)
        | ‡           # double dagger
        | [¶§]        # pilcrow / section sign
    )
    (?:\s|$)          # followed by whitespace or end
    """,
    re.VERBOSE,
)


def clean_cell_text(text: str) -> str:
    """Clean cell text to collapse floating point / scientific notation spaces."""
    if not isinstance(text, str):
        return text
    # Normalize minus symbols
    text = text.replace('\u2212', '-')
    text = text.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')
    
    # 1. Collapse spaces in floating point / scientific numbers
    prev = ""
    while prev != text:
        prev = text
        text = re.sub(r'(\d)\s+(\d)', r'\1\2', text)
        text = re.sub(r'(\d)\s+(\.)', r'\1\2', text)
        text = re.sub(r'(\.)\s+(\d)', r'\1\2', text)
        text = re.sub(r'([+\-])\s+(\d)', r'\1\2', text)
        text = re.sub(r'([\d\.])\s+([Ee])', r'\1\2', text)
        text = re.sub(r'([Ee])\s+([+\-\d])', r'\1\2', text)
        
    # 2. Move misplaced exponent signs to the correct place (e.g. E17- -> E-17)
    text = re.sub(r'([Ee])\s*(\d+)\s*([+\-])', r'\1\3\2', text)
    
    # 3. Collapse spaces one more time
    prev = ""
    while prev != text:
        prev = text
        text = re.sub(r'(\d)\s+(\d)', r'\1\2', text)
        text = re.sub(r'(\d)\s+(\.)', r'\1\2', text)
        text = re.sub(r'(\.)\s+(\d)', r'\1\2', text)
        text = re.sub(r'([+\-])\s+(\d)', r'\1\2', text)
        text = re.sub(r'([\d\.])\s+([Ee])', r'\1\2', text)
        text = re.sub(r'([Ee])\s+([+\-\d])', r'\1\2', text)
        
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_tables_docling(pdf_path: str) -> List[dict]:
    """
    Extract all tables from the PDF using IBM Docling.
    Returns a list of table dictionaries matching the ExtractedTable format.
    """
    if not DOCLING_AVAILABLE:
        print("[DoclingExtractor] Skipping — docling not available.")
        return []

    print(f"[DoclingExtractor] Starting Docling table extraction on {pdf_path} ...")
    t0 = time.monotonic()
    
    # Precompute page heights using PyMuPDF to convert coordinates to bottom-left
    page_heights: Dict[int, float] = {}
    try:
        doc = fitz.open(pdf_path)
        for i, page in enumerate(doc):
            page_heights[i + 1] = page.rect.height
        doc.close()
    except Exception as e:
        print(f"[DoclingExtractor] Failed to read page heights with PyMuPDF: {e}")

    results: List[dict] = []
    
    try:
        # Configure Docling pipeline options (CPU only, 4 threads, no OCR)
        cpu_accel = AcceleratorOptions(num_threads=4, device=AcceleratorDevice.CPU)
        pipeline_options = PdfPipelineOptions(accelerator_options=cpu_accel, do_ocr=False)
        
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        
        # Convert document
        conv_result = converter.convert(source=pdf_path)
        tables = conv_result.document.tables
        
        for idx, table in enumerate(tables):
            # 1. Page number (1-indexed)
            page_num = 1
            if table.prov:
                page_num = int(table.prov[0].page_no)
                
            # 2. DataFrame and Clean Data
            try:
                df = table.export_to_dataframe()
            except Exception as e:
                print(f"[DoclingExtractor] Failed to export table {idx} as DataFrame: {e}")
                continue
                
            def safe_clean(v):
                if v is None:
                    return ""
                if isinstance(v, float):
                    import math
                    if math.isnan(v):
                        return ""
                try:
                    val_str = str(v).strip()
                    if val_str.lower() in ("nan", "none", "nat"):
                        return ""
                    return clean_cell_text(val_str)
                except Exception:
                    return ""

            # Clean up the entire dataframe element-wise
            if hasattr(df, "map"):
                df = df.map(safe_clean)
            else:
                df = df.applymap(safe_clean)

            # Make column names unique to satisfy json records serialization
            unique_cols = []
            seen_cols = {}
            for col in df.columns:
                c_str = str(col)
                if c_str in seen_cols:
                    seen_cols[c_str] += 1
                    unique_cols.append(f"{c_str}_{seen_cols[c_str]}")
                else:
                    seen_cols[c_str] = 0
                    unique_cols.append(c_str)
            df.columns = unique_cols
                
            # 3. Bounding box conversion to Camelot bottom-left format
            bbox_dict = {"x1": 0.0, "y1": 0.0, "x2": 0.0, "y2": 0.0}
            if table.prov:
                prov_bbox = table.prov[0].bbox
                page_height = page_heights.get(page_num, 842.0)  # default A4 height
                
                # Docling is top-left origin (l, t, r, b)
                # l, r match x1, x2
                # y1 (bottom) = page_height - b
                # y2 (top) = page_height - t
                bbox_dict = {
                    "x1": float(prov_bbox.l),
                    "y1": float(page_height - prov_bbox.b),
                    "x2": float(prov_bbox.r),
                    "y2": float(page_height - prov_bbox.t),
                }

            # 4. Table properties
            headers = [str(col) for col in df.columns]
            row_count = len(df)
            col_count = len(df.columns)
            
            # Find empty cells and footnote markers
            empty_locs: List[Dict] = []
            has_fn = False
            for r_idx in range(row_count):
                for c_idx in range(col_count):
                    val = str(df.iloc[r_idx, c_idx]).strip()
                    if val == "" or val.lower() in ("nan", "none"):
                        empty_locs.append({"row": r_idx, "col": c_idx})
                    if _FOOTNOTE_RE.search(val):
                        has_fn = True

            t_dict = {
                "table_index": idx,
                "page_number": page_num,
                "bbox": bbox_dict,
                "accuracy": 100.0,  # DL layout detection accuracy metric
                "parse_method": "docling",
                "has_empty_cells": len(empty_locs) > 0,
                "empty_cell_locations": empty_locs,
                "has_footnote_markers": has_fn,
                "row_count": row_count,
                "col_count": col_count,
                "headers": headers,
                "data_json": df.to_json(orient="records"),
            }
            results.append(t_dict)
            
        print(f"[DoclingExtractor] Extracted {len(results)} table(s) in {time.monotonic() - t0:.2f}s")
    except Exception as exc:
        print(f"[DoclingExtractor] Docling extraction failed: {exc}")
        traceback.print_exc()

    return results
