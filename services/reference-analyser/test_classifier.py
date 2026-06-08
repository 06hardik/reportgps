from citation_classifier import classify

_NORM = {"Harvard": "HARVARD", "Vancouver": "VANCOUVER"}

tests = [
    ("[1] A. Smith, B. Jones, Deep learning, IEEE Trans. Neural Netw., vol. 31, pp. 1234-1245, 2020.", "IEEE"),
    ("Smith, J. A., & Jones, B. (2020). Deep learning. J. AI Res., 45(3), 112-134. https://doi.org/10.1234/x", "APA"),
    ("Smith, John. Deep Learning. J. Comput. Sci., vol. 12, no. 3, 2020, pp. 45-67.", "MLA"),
    ("Smith, AB (2020) Deep learning. J. AI Res., 45(3): 112-134.", "HARVARD"),
    ("1. Smith AB, Jones BC. Deep learning. N Engl J Med. 2020;383(5):456-63.", "VANCOUVER"),
]

ok = 0
for text, expected in tests:
    r = classify(text)
    norm = _NORM.get(r.predicted_style, r.predicted_style)
    status = "OK" if norm == expected else "FAIL"
    if status == "OK":
        ok += 1
    print(f"[{status}] expected={expected:<10} got={norm:<10} conf={r.confidence}")

print(f"\nClassifier score: {ok}/{len(tests)}")

# Also test list-level detection
from reference_quality import detect_citation_style
raw_list = [
    "[1] A. Smith. Deep learning. IEEE Trans., 2020.",
    "[2] B. Jones. Edge computing. Proc. IEEE, 2019.",
    "[3] C. Lee. IoT survey. Trans. Comput., 2021.",
]
detected = detect_citation_style(raw_list)
print(f"List-level style detected: {detected}  (expected IEEE)")
