import sqlite3, sys
doc = sys.argv[1]
c = sqlite3.connect("data/rag_intelligence.sqlite"); c.row_factory = sqlite3.Row
d = c.execute("SELECT page_count,pages_done,needs_ocr_pages,status FROM documents WHERE id=?", (doc,)).fetchone()
j = c.execute("SELECT state,pages_total,pages_done,last_completed_batch FROM jobs WHERE document_id=? ORDER BY started_at DESC LIMIT 1", (doc,)).fetchone()
p = c.execute("SELECT COUNT(*) n, MIN(page_no) lo, MAX(page_no) hi, COUNT(DISTINCT page_no) uniq, MAX(batch_no) mb FROM pages WHERE document_id=?", (doc,)).fetchone()
print(f"documents : page_count={d['page_count']} pages_done={d['pages_done']} needs_ocr={d['needs_ocr_pages']} status={d['status']}")
print(f"jobs      : state={j['state']} pages_total={j['pages_total']} pages_done={j['pages_done']} last_completed_batch={j['last_completed_batch']}")
print(f"pages rows: count={p['n']} distinct={p['uniq']} min_page={p['lo']} max_page={p['hi']} max_batch={p['mb']}")
if p['n']:
    have = {r[0] for r in c.execute("SELECT page_no FROM pages WHERE document_id=?", (doc,))}
    missing = [x for x in range(1, p['hi']+1) if x not in have]
    print(f"gaps      : duplicates={p['n']-p['uniq']}  missing_below_max={len(missing)} {missing[:10]}")
