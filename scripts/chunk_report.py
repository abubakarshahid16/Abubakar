"""Chunking quality report for step 3."""
import sqlite3
import statistics as st
from collections import Counter

DB = r"d:\project\Rag_chatbot\backend\data\nabaa.sqlite"
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
c.row_factory = sqlite3.Row

DOCS = [
    ("doc_b02fb622b193", "book1-professionalpractices.pdf"),
    ("doc_0c5c007fcedd", "book2-Differential-Equations.pdf"),
    ("doc_b13461e0d8e6", "OS_Term_Project_SP2026.pdf"),
    ("doc_626f11d111dc", "Tabish_Arshad_RAG_Proposal.pdf"),
    ("doc_d509d026a2f7", "MuhammadZaid_Resume.pdf"),
]

print("=" * 78)
print("CHUNKS PER DOCUMENT")
print("=" * 78)
print(f"{'document':40} {'pages':>6} {'chunks':>7} {'per page':>9} {'tables':>7} {'spanning':>9}")
for doc, name in DOCS:
    d = c.execute("SELECT page_count FROM documents WHERE id=?", (doc,)).fetchone()
    r = c.execute(
        """SELECT COUNT(*) n,
                  SUM(kind='table') tbl,
                  SUM(page_end > page_start) span
           FROM chunks WHERE document_id=?""", (doc,)).fetchone()
    if not r["n"]:
        print(f"{name:40} {'-':>6} {'not chunked':>7}")
        continue
    pages = d["page_count"] or 0
    print(f"{name:40} {pages:>6} {r['n']:>7} {r['n']/pages if pages else 0:>9.2f} "
          f"{r['tbl']:>7} {r['span']:>9}")

print()
print("=" * 78)
print("CHUNKS-PER-PAGE DISTRIBUTION  (chunks whose page_start == that page)")
print("=" * 78)
for doc, name in DOCS[:2]:
    per_page = Counter()
    for r in c.execute("SELECT page_start FROM chunks WHERE document_id=?", (doc,)):
        per_page[r["page_start"]] += 1
    total_pages = c.execute("SELECT page_count FROM documents WHERE id=?", (doc,)).fetchone()["page_count"]
    for p in range(1, (total_pages or 0) + 1):
        per_page.setdefault(p, 0)
    vals = sorted(per_page.values())
    hist = Counter(vals)
    print(f"\n{name}")
    print(f"  min={vals[0]}  p25={vals[len(vals)//4]}  median={st.median(vals)}  "
          f"p75={vals[3*len(vals)//4]}  max={vals[-1]}  mean={st.mean(vals):.2f}")
    print("  pages with N chunks: ", end="")
    print("  ".join(f"{n}->{cnt}" for n, cnt in sorted(hist.items())[:10]))

print()
print("=" * 78)
print("TOKEN COUNTS  (real e5-small tokenizer)")
print("=" * 78)
print(f"{'document':40} {'min':>5} {'p25':>5} {'median':>7} {'p75':>5} {'max':>5} {'>480':>6} {'<25':>5}")
for doc, name in DOCS:
    toks = [r["token_count"] for r in
            c.execute("SELECT token_count FROM chunks WHERE document_id=? ORDER BY token_count", (doc,))]
    if not toks:
        continue
    over = sum(1 for t in toks if t > 480)
    tiny = sum(1 for t in toks if t < 25)
    print(f"{name:40} {toks[0]:>5} {toks[len(toks)//4]:>5} {int(st.median(toks)):>7} "
          f"{toks[3*len(toks)//4]:>5} {toks[-1]:>5} {over:>6} {tiny:>5}")

total_over = c.execute("SELECT COUNT(*) FROM chunks WHERE token_count > 480").fetchone()[0]
print(f"\n  CEILING CHECK: chunks exceeding 480 tokens across ALL documents = {total_over}")
print(f"  e5-small hard limit is 512; ceiling is 480, leaving headroom for the 'passage: ' prefix.")
