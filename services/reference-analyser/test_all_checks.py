"""
Full integration test — all 5 checks + classifier working together.
Simulates the exact enriched format our GROBID pipeline produces.
"""
from citation_classifier import classify
from reference_quality import detect_citation_style, _classify_entry_style, build_enriched_refs
from check_ordering import check_ordering
from check_doi import check_doi
from check_journal_casing import check_journal_casing
from check_completeness import check_completeness
from check_style_conformity import check_style_conformity

# --- Simulate 5 IEEE-style references (3 clean, 2 with issues) ---
raw_strings = [
    '[1] A. Smith and B. Jones, "Deep learning for IoT," IEEE Trans. Neural Netw., vol. 31, no. 4, pp. 1234-1245, Apr. 2020, doi: 10.1109/TNN.2020.1.',
    '[2] C. Lee et al., "Edge computing survey," Proc. IEEE Int. Conf. Cloud Comput., pp. 45-52, 2021.',
    '[4] D. Kumar, "Fog computing review," IEEE Access, 2020.',       # [4] instead of [3] — ordering issue
    '[4] E. Wang, "IoT security," IEEE Trans. Inf. Forensics Secur., vol. 15, pp. 100-110, 2020.',  # duplicate label
    '[5] F. Zhao, "5G networks," ieee transactions on communications, vol. 68, pp. 200-210, 2021.',  # wrong journal case
]

bibtex_entries = [
    {'ID':'r1','ENTRYTYPE':'article','author':'Smith, A and Jones, B','title':'Deep learning for IoT','journal':'IEEE Transactions on Neural Networks','year':'2020','volume':'31','pages':'1234-1245','doi':'10.1109/TNN.2020.1'},
    {'ID':'r2','ENTRYTYPE':'article','author':'Lee, C','title':'Edge computing survey','journal':'Proc. IEEE','year':'2021','volume':'','pages':'45-52','doi':''},
    {'ID':'r3','ENTRYTYPE':'article','author':'Kumar, D','title':'Fog computing review','journal':'IEEE Access','year':'2020','volume':'','pages':'','doi':''},  # missing volume+pages
    {'ID':'r4','ENTRYTYPE':'article','author':'Wang, E','title':'IoT security','journal':'IEEE Trans. Inf. Forensics Secur.','year':'2020','volume':'15','pages':'100-110','doi':''},
    {'ID':'r5','ENTRYTYPE':'article','author':'Zhao, F','title':'5G networks','journal':'ieee transactions on communications','year':'2021','volume':'68','pages':'200-210','doi':''},
]

# 1. Style detection
style = detect_citation_style(raw_strings)
print(f"Detected style: {style}")

# 2. Build enriched refs (no GROBID coords for this test)
enriched = build_enriched_refs(bibtex_entries, raw_strings, [], [])
print(f"Enriched refs: {len(enriched)}")

# 3. Run all 5 checks
print()
print("=== Check 1: Ordering ===")
res1 = check_ordering(enriched, style)
print(f"  type={res1.order_type}, checked={res1.checked}, issues={len(res1.issues)}")
for i in res1.issues:
    print(f"  [{i.ref_id}] {i.issue}: expected={i.expected} found={i.found}")

print()
print("=== Check 2: DOI ===")
res2 = check_doi(enriched)
print(f"  checked={res2.checked}, issues={len(res2.issues)}")
for i in res2.issues:
    print(f"  [{i.ref_id}] {i.issue_type}: {i.detail[:60]}")

print()
print("=== Check 3: Journal Casing ===")
res3 = check_journal_casing(enriched, style)
print(f"  checked={res3.checked}, issues={len(res3.issues)}")
for i in res3.issues:
    print(f"  [{i.ref_id}] {i.issue_type}: {i.journal[:50]}")
    if i.suggestion: print(f"    -> {i.suggestion}")

print()
print("=== Check 4: Completeness ===")
res4 = check_completeness(enriched, style)
print(f"  checked={res4.checked}, issues={len(res4.issues)}")
for i in res4.issues:
    if i.issue_type == "missing":
        print(f"  [{i.ref_id}][MISSING] {i.field_name}: {i.detail[:60]}")

print()
print("=== Check 5: Style Conformity ===")
res5 = check_style_conformity(enriched, style)
print(f"  dominant={res5.dominant_style}, checked={res5.checked}, skipped_low={res5.skipped_low}, issues={len(res5.issues)}")
for i in res5.issues:
    print(f"  [{i.ref_id}] found={i.entry_style} conf={i.entry_confidence}")

print()
print("=== SUMMARY ===")
total = len(res1.issues)+len(res2.issues)+len(res3.issues)+len(res4.issues)+len(res5.issues)
print(f"Total issues across all 5 checks: {total}")
print("All checks passed integration test!")
