"""Clean-run extraction benchmark. Resets each document, then measures."""
import os, subprocess, sqlite3, sys, time, csv

BACKEND = r"d:\project\Rag_chatbot\backend"
PY = r"d:\project\Rag_chatbot\.venv\Scripts\python.exe"
DB = os.path.join(BACKEND, "data", "rag_intelligence.sqlite")
DOCS = [("doc_b02fb622b193", "book1-professionalpractices.pdf"),
        ("doc_0c5c007fcedd", "book2-Differential-Equations.pdf")]

print(f"{'document':38} {'pages':>6} {'ocr':>4} {'secs':>7} {'pages/s':>9} {'peakRSS':>9}")
print("-" * 78)
for doc, name in DOCS:
    subprocess.run([PY, r"..\scripts\resetdoc.py", doc], cwd=BACKEND, capture_output=True)
    memlog = os.path.join(os.environ["TEMP"], f"mem_{doc}.csv")
    t0 = time.perf_counter()
    r = subprocess.run([PY, "-m", "app.worker", doc, "--memlog", memlog],
                       cwd=BACKEND, capture_output=True, text=True)
    wall = time.perf_counter() - t0
    line = [l for l in r.stdout.splitlines() if "[done]" in l]
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); c.row_factory = sqlite3.Row
    d = c.execute("SELECT page_count,pages_done,needs_ocr_pages FROM documents WHERE id=?", (doc,)).fetchone()
    import re
    m = re.search(r"([\d.]+)s\s+([\d.]+) pages/s\s+peak_rss=([\d.]+)MB", line[0]) if line else None
    secs, pps, rss = (m.group(1), m.group(2), m.group(3)) if m else ("?", "?", "?")
    print(f"{name:38} {d['pages_done']:>6} {d['needs_ocr_pages']:>4} {secs:>7} {pps:>9} {rss:>7}MB")
    print(f"{'  (incl. process startup)':38} {'':>6} {'':>4} {wall:>7.2f} {d['pages_done']/wall:>9.1f}")

    # memory shape
    rows = list(csv.DictReader(open(memlog, encoding="utf-8")))
    if rows:
        print(f"  RAM shape over {len(rows)} batches: ", end="")
        step = max(1, len(rows) // 6)
        pts = [f"{r['pages_done']}p={float(r['rss_mb']):.0f}MB" for r in rows[::step]][:6]
        pts.append(f"{rows[-1]['pages_done']}p={float(rows[-1]['rss_mb']):.0f}MB")
        print("  ".join(pts))
        vals = [float(r["rss_mb"]) for r in rows]
        print(f"  RAM min={min(vals):.0f}MB max={max(vals):.0f}MB drift={max(vals)-min(vals):.0f}MB "
              f"first_half_avg={sum(vals[:len(vals)//2])/max(1,len(vals)//2):.0f}MB "
              f"second_half_avg={sum(vals[len(vals)//2:])/max(1,len(vals)-len(vals)//2):.0f}MB")
    print()
