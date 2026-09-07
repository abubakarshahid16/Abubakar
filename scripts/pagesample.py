import sqlite3, sys
doc, mode = sys.argv[1], sys.argv[2]
c = sqlite3.connect("data/rag_intelligence.sqlite"); c.row_factory = sqlite3.Row
q = "SELECT page_no,batch_no,char_count,needs_ocr FROM pages WHERE document_id=? ORDER BY page_no DESC LIMIT 3"
for r in c.execute(q, (doc,)):
    print(f"  page {r['page_no']:>4}  batch {r['batch_no']:>3}  chars={r['char_count']:>5}  needs_ocr={r['needs_ocr']}")
