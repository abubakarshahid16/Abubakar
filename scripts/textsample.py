import sqlite3, re
DB = r"d:\project\Rag_chatbot\backend\data\rag_intelligence.sqlite"
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); c.row_factory = sqlite3.Row

def sample(doc, label, min_page):
    rows = [r for r in c.execute(
        "SELECT page_no,text,char_count FROM pages WHERE document_id=? AND page_no>=? AND needs_ocr=0 ORDER BY page_no",
        (doc, min_page))]
    # A real body heading: a numbered section heading followed by prose, NOT a
    # contents page (contents pages end most lines with a page number).
    def is_toc(t):
        lines = [l for l in t.splitlines() if l.strip()]
        if not lines: return True
        return sum(1 for l in lines if re.search(r"\s\d{1,4}$", l.rstrip())) > len(lines) * 0.5
    def heading_score(row):
        t = row["text"]
        if is_toc(t): return -1
        m = re.search(r"(?m)^\s*\d+\.\d+\s+[A-Z][A-Za-z ,'-]{4,60}$", t)
        return len(t) if m else -1
    def table_score(row):
        t = row["text"]
        if is_toc(t): return -1
        s = 0
        if re.search(r"(?m)^\s*(Table|TABLE|Figure)\s+\d+", t): s += 5000
        lines = [l for l in t.splitlines() if l.strip()]
        s += sum(1 for l in lines if len(re.findall(r"\d+(?:\.\d+)?", l)) >= 3 and len(l.strip()) < 80) * 50
        return s

    for name, fn in (("HEADING", heading_score), ("TABLE / FIGURE", table_score)):
        best = max(rows, key=fn)
        if fn(best) <= 0:
            print(f"\n===== {label} — no clear {name} page found =====")
            continue
        body = best["text"].strip()
        print(f"\n===== {label} — {name} — page {best['page_no']} ({best['char_count']} chars) =====")
        print(body[:200])

sample("doc_b02fb622b193", "book1 professional practices", 40)
sample("doc_0c5c007fcedd", "book2 differential equations", 40)
