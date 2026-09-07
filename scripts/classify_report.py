"""Verification report for the front-matter / TOC classification fix."""
import re
import sqlite3
from collections import Counter

DB = "data/rag_intelligence.sqlite"
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
print("CHUNKS BY KIND  (retrievable = prose + table)")
print("=" * 78)
print(f"{'document':38} {'prose':>6} {'table':>6} {'toc':>5} {'front':>6} {'index':>6} {'refs':>5} {'RETR':>6}")
for doc, name in DOCS:
    counts = Counter()
    for r in c.execute("SELECT kind, COUNT(*) n FROM chunks WHERE document_id=? GROUP BY kind", (doc,)):
        counts[r["kind"]] = r["n"]
    retr = c.execute("SELECT COUNT(*) FROM chunks WHERE document_id=? AND retrievable=1", (doc,)).fetchone()[0]
    print(f"{name:38} {counts['prose']:>6} {counts['table']:>6} {counts['toc']:>5} "
          f"{counts['frontmatter']:>6} {counts['index']:>6} {counts['references']:>5} {retr:>6}")

print()
print("=" * 78)
print("PAGES EXCLUDED FROM SEARCH")
print("=" * 78)
for doc, name in DOCS[:2]:
    rows = list(c.execute(
        """SELECT kind, MIN(page_start) lo, MAX(page_end) hi, COUNT(*) n
           FROM chunks WHERE document_id=? AND retrievable=0 GROUP BY kind""", (doc,)))
    print(f"\n{name}")
    if not rows:
        print("   (none)")
    for r in rows:
        print(f"   {r['kind']:12} {r['n']:>3} chunks, pages {r['lo']}-{r['hi']}")

print()
print("=" * 78)
print("SECTION SANITY - every distinct section on a RETRIEVABLE chunk")
print("=" * 78)
# A plausible heading: a small dotted-or-integer section number then words, no digits in the title
PLAUSIBLE = re.compile(r"^\d{1,2}(\.\d{1,2}){0,3} [A-Z][^\d]*$")
bad = []
sections = [r["section"] for r in c.execute(
    "SELECT DISTINCT section FROM chunks WHERE retrievable=1 AND section IS NOT NULL")]
for s in sections:
    if not PLAUSIBLE.match(s):
        bad.append(s)
total_r = c.execute("SELECT COUNT(*) FROM chunks WHERE retrievable=1").fetchone()[0]
null_sec = c.execute("SELECT COUNT(*) FROM chunks WHERE retrievable=1 AND section IS NULL").fetchone()[0]
print(f"  distinct sections on retrievable chunks : {len(sections)}")
print(f"  implausible ones                        : {len(bad)}")
for s in bad[:10]:
    print(f"      BAD: {s!r}")
print(f"  retrievable chunks with section = NULL  : {null_sec} / {total_r} "
      f"({100*null_sec/max(total_r,1):.0f}%)  <- null is correct when uncertain")
print("\n  sample of accepted sections:")
for s in sorted(sections)[:8]:
    print(f"      {s!r}")
