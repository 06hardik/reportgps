import os
import sys
import json
import time

# Add services/extraction-pipeline to path so we can import orchestrator
sys.path.append('services/extraction-pipeline')
from orchestrator import extract_document

papers_dir = 'papers'
pdf_files = [f for f in os.listdir(papers_dir) if f.lower().endswith('.pdf')]
print("Found papers to extract:", pdf_files)

for pdf in pdf_files:
    pdf_path = os.path.join(papers_dir, pdf)
    print(f"\n======================================================================")
    print(f"PROCESSING PAPER: {pdf}")
    print(f"======================================================================")
    t_start = time.monotonic()
    
    res = extract_document(pdf_path)
    
    # Save the output json
    out_name = pdf.replace(' ', '_').replace('+', '_').replace('.pdf', '_out.json')
    out_path = os.path.join(papers_dir, out_name)
    with open(out_path, 'w') as f:
        json.dump(res, f, indent=2)
        
    duration = time.monotonic() - t_start
    print(f"FINISHED {pdf} in {duration:.1f}s. Saved output to {out_path}")
