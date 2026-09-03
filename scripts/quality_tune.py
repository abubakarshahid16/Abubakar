"""Tune the content-quality gate against known-good and known-bad chunks."""
import sqlite3
from collections import Counter

from app.chunker import content_quality

c = sqlite3.connect("file:data/nabaa.sqlite?mode=ro", uri=True)
c.row_factory = sqlite3.Row

GOOD = list(c.execute(
    """SELECT text, page_start FROM chunks
       WHERE document_id='doc_b02fb622b193' AND retrievable=1 AND kind='prose'
       AND page_start BETWEEN 22 AND 520"""))
BAD = list(c.execute(
    """SELECT text, page_start FROM chunks
       WHERE document_id='doc_0c5c007fcedd'
       AND (page_start = 570 OR page_start BETWEEN 583 AND 595)"""))

print(f"known-good (book1 prose, p22-520) : {len(GOOD)} chunks")
print(f"known-bad  (book2 p570, p583-595) : {len(BAD)} chunks")
print()

good_rejects = [g for g in GOOD if not content_quality(g["text"])["ok"]]
bad_rejects = [b for b in BAD if not content_quality(b["text"])["ok"]]

print(f"GOOD rejected (must be 0) : {len(good_rejects)}")
for g in good_rejects[:5]:
    q = content_quality(g["text"])
    print(f"    p{g['page_start']} reasons={q['reasons']}")
    print(f"      {g['text'][:110]!r}")
print(f"BAD  rejected             : {len(bad_rejects)} / {len(BAD)} "
      f"({100 * len(bad_rejects) / max(len(BAD), 1):.0f}%)")
print()

print("WHICH SIGNAL CATCHES WHAT (on the known-bad set)")
sig = Counter()
for b in BAD:
    for r in content_quality(b["text"])["reasons"]:
        sig[r.split("=")[0]] += 1
for name, n in sig.most_common():
    print(f"    {name:18} {n:>4}")
print()

print("SIGNAL RANGES")
for label, rows in (("GOOD", GOOD), ("BAD", BAD)):
    qs = [content_quality(r["text"]) for r in rows]
    qs = [q for q in qs if "alpha_ratio" in q]
    if not qs:
        continue
    def rng(k):
        vals = sorted(q[k] for q in qs)
        return f"min={vals[0]:<7} p50={vals[len(vals)//2]:<7} max={vals[-1]:<7}"
    print(f"  {label}")
    for k in ("alpha_ratio", "symbol_ratio", "wordish_ratio", "avg_word_len", "longest_run"):
        print(f"    {k:15} {rng(k)}")
print()

print("=" * 78)
print("10 REJECTED CHUNKS IN FULL - confirm these are genuinely garbage")
print("=" * 78)
for b in bad_rejects[:10]:
    q = content_quality(b["text"])
    print(f"\n--- book2 p{b['page_start']}  reasons={q['reasons']} ---")
    print(b["text"][:400])
