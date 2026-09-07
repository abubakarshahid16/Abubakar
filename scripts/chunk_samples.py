"""Header/footer evidence and full chunk samples for step 3 review."""
import sqlite3

from app.chunker import detect_running_lines

DB = "data/rag_intelligence.sqlite"
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
c.row_factory = sqlite3.Row

print("=" * 78)
print("RUNNING HEADERS / FOOTERS DETECTED AND STRIPPED")
print("=" * 78)
for doc, name in (("doc_b02fb622b193", "book1"), ("doc_0c5c007fcedd", "book2"),
                  ("doc_b13461e0d8e6", "OS_Term_Project")):
    pages = [(r["page_no"], r["text"]) for r in
             c.execute("SELECT page_no,text FROM pages WHERE document_id=? ORDER BY page_no", (doc,))]
    running = detect_running_lines(pages)
    print(f"\n{name}: {len(running)} distinct running lines detected")
    for line in sorted(running)[:12]:
        print(f"    {line!r}")

print()
print("=" * 78)
print("SAMPLE 1 - MID-PROSE CHUNK")
print("=" * 78)
r = c.execute("""SELECT * FROM chunks WHERE document_id='doc_b02fb622b193'
                 AND kind='prose' AND page_end=page_start
                 AND token_count BETWEEN 250 AND 320
                 AND section LIKE '%.%' ORDER BY ordinal LIMIT 1""").fetchone()
if r:
    print(f"id       : {r['id']}")
    print(f"file     : {r['filename']}")
    print(f"pages    : {r['page_start']}")
    print(f"section  : {r['section']}")
    print(f"tokens   : {r['token_count']}   hash: {r['content_hash'][:16]}")
    print("-" * 78)
    print(r["text"])

print()
print("=" * 78)
print("SAMPLE 2 - TABLE CHUNK (book2 p98 area)")
print("=" * 78)
r = c.execute("""SELECT * FROM chunks WHERE document_id='doc_0c5c007fcedd'
                 AND kind='table' AND page_start BETWEEN 95 AND 101
                 ORDER BY token_count DESC LIMIT 1""").fetchone()
if not r:
    r = c.execute("""SELECT * FROM chunks WHERE document_id='doc_0c5c007fcedd'
                     AND kind='table' ORDER BY token_count DESC LIMIT 1""").fetchone()
if r:
    print(f"id       : {r['id']}")
    print(f"pages    : {r['page_start']}-{r['page_end']}")
    print(f"section  : {r['section']}")
    print(f"tokens   : {r['token_count']}   kind: {r['kind']}")
    print("-" * 78)
    print(r["text"][:1400])

print()
print("=" * 78)
print("SAMPLE 3 - CHUNK SPANNING A PAGE BOUNDARY")
print("=" * 78)
r = c.execute("""SELECT * FROM chunks WHERE document_id='doc_b02fb622b193'
                 AND page_end > page_start AND token_count > 200
                 ORDER BY ordinal LIMIT 1""").fetchone()
if r:
    print(f"id       : {r['id']}")
    print(f"pages    : {r['page_start']}-{r['page_end']}   <-- page RANGE, not a single page")
    print(f"section  : {r['section']}")
    print(f"tokens   : {r['token_count']}")
    print("-" * 78)
    print(r["text"])
