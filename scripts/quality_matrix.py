"""Three-way confusion matrix for the content-quality gate."""
import sqlite3

from app.quality import assess

c = sqlite3.connect("file:data/rag_intelligence.sqlite?mode=ro", uri=True)
c.row_factory = sqlite3.Row

GOOD_PROSE = list(c.execute(
    """SELECT text, page_start, kind FROM chunks
       WHERE document_id='doc_b02fb622b193' AND kind='prose'
       AND page_start BETWEEN 22 AND 520"""))

GOOD_TABLES = list(c.execute(
    """SELECT text, page_start, kind FROM chunks
       WHERE document_id='doc_0c5c007fcedd' AND kind='table'"""))

BAD = list(c.execute(
    """SELECT text, page_start, kind FROM chunks
       WHERE document_id='doc_0c5c007fcedd'
       AND (page_start = 570 OR page_start BETWEEN 583 AND 595)"""))

sets = [
    ("GOOD PROSE  (book1 body)", GOOD_PROSE, True),
    ("GOOD TABLES (book2 kind=table)", GOOD_TABLES, True),
    ("BAD         (book2 p570/583-595)", BAD, False),
]

print("=" * 78)
print("THREE-WAY CONFUSION MATRIX")
print("=" * 78)
print(f"{'reference set':34} {'n':>5} {'accepted':>9} {'rejected':>9} {'verdict':>22}")
for label, rows, want_accept in sets:
    acc = sum(1 for r in rows if assess(r["text"], r["kind"])["ok"])
    rej = len(rows) - acc
    if want_accept:
        verdict = f"{rej} FALSE REJECTIONS" if rej else "0 false rejections OK"
    else:
        verdict = f"{acc} false acceptances" if acc else "all rejected OK"
    print(f"{label:34} {len(rows):>5} {acc:>9} {rej:>9} {verdict:>22}")

print()
print("=" * 78)
print("10 ACCEPTED TABLE CHUNKS - confirm these are genuinely useful")
print("=" * 78)
shown = 0
for r in GOOD_TABLES:
    a = assess(r["text"], r["kind"])
    if a["ok"] and shown < 10:
        shown += 1
        print(f"\n--- book2 p{r['page_start']} ACCEPTED clause={a['clause']} "
              f"evidence={a.get('table_evidence')} ---")
        print(r["text"][:300])

print()
print("=" * 78)
print("REJECTED TABLE CHUNKS (should be few / genuinely unrecoverable)")
print("=" * 78)
shown = 0
for r in GOOD_TABLES:
    a = assess(r["text"], r["kind"])
    if not a["ok"] and shown < 10:
        shown += 1
        print(f"\n--- book2 p{r['page_start']} REJECTED {a['reasons']} ---")
        print(r["text"][:300])
if shown == 0:
    print("\n  (none)")
