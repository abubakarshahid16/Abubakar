import sqlite3, sys
doc = sys.argv[1]
c = sqlite3.connect("data/rag_intelligence.sqlite")
c.execute("DELETE FROM pages WHERE document_id=?", (doc,))
c.execute("UPDATE documents SET pages_done=0, needs_ocr_pages=0, page_count=NULL, status='queued' WHERE id=?", (doc,))
c.execute("UPDATE jobs SET state='running', stage='extract', pages_done=0, last_completed_batch=NULL, pages_total=NULL WHERE document_id=?", (doc,))
c.commit()
print(f"reset {doc}")
