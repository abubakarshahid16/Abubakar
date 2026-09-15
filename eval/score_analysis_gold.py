"""Score the Analysis pipeline using the PRODUCT'S OWN retrieval code.

The first attempt hand-rolled the FTS SQL and scored 0/14 - a broken harness,
not a broken product, proved by a plain LIKE finding the same facts. This
version imports app.keyword and calls search() exactly as the API does, so a
failure here is the product's failure.

Run: python score2.py <sqlite> <backend-dir>
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

GOLD = Path(__file__).parent / "gold_analysis.json"


def main() -> int:
    db_path, backend = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])

    # Point the product's settings at the staged corpus BEFORE importing it.
    os.environ["DB_PATH"] = db_path
    sys.path.insert(0, backend)

    from app.config import settings  # noqa: E402
    settings.db_path = Path(db_path)
    from app import db as db_mod  # noqa: E402
    db_mod.reset_connection()
    from app import keyword  # noqa: E402

    gold = json.loads(GOLD.read_text())

    raw = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    raw.row_factory = sqlite3.Row
    docs = {r["filename"]: r["id"] for r in raw.execute("SELECT id, filename FROM documents")}
    all_ids = frozenset(docs.values())
    id_to_name = {v: k for k, v in docs.items()}

    def pages_of(chunk_id: str):
        r = raw.execute("SELECT page_start, page_end FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
        return (r["page_start"], r["page_end"]) if r else (None, None)

    print(f"corpus: {len(docs)} documents\n")

    # ---- LAYER 1: does the correct document+page come back? ------------
    print("=" * 78)
    print("LAYER 1 - RETRIEVAL (keyword side, product code, full corpus scope)")
    print("=" * 78)
    page_hits = doc_hits = 0
    for f in gold["facts"]:
        rows = keyword.search(f["question"], limit=20, allowed_document_ids=all_ids)
        got_doc = got_page = False
        rank = None
        for i, r in enumerate(rows, 1):
            if r["filename"] == f["doc"]:
                got_doc = True
                ps, pe = pages_of(r["chunk_id"])
                if ps is not None and ps <= f["page"] <= pe:
                    got_page, rank = True, i
                    break
        if got_page:
            page_hits += 1
        if got_doc:
            doc_hits += 1
        mark = f"PASS r{rank}" if got_page else ("DOC-ONLY" if got_doc else "MISS")
        top = f"{rows[0]['filename']}" if rows else "-"
        print(f"  [{mark:9}] {f['id']:26} want {f['doc']} p.{f['page']:<4} top1={top}")
    n = len(gold["facts"])
    print(f"\n  right page in top 20 : {page_hits}/{n} = {round(100*page_hits/n)}%")
    print(f"  right document at all: {doc_hits}/{n} = {round(100*doc_hits/n)}%")

    # ---- LAYER 2: scope discipline on named-document questions ---------
    print()
    print("=" * 78)
    print("LAYER 2 - SCOPE: does a named-document comparison stay on those docs?")
    print("=" * 78)
    for c in gold["comparisons"]:
        rows = keyword.search(c["question"], limit=24, allowed_document_ids=all_ids)
        seen: dict[str, int] = {}
        for r in rows:
            seen[r["filename"]] = seen.get(r["filename"], 0) + 1
        intruders = {k: v for k, v in seen.items() if k in c["forbidden_docs"]}
        others = {k: v for k, v in seen.items()
                  if k not in c["expected_docs"] and k not in c["forbidden_docs"]}
        missing = [d for d in c["expected_docs"] if d not in seen]
        print(f"\n  {c['id']}: {c['question']}")
        print(f"    retrieved : {dict(sorted(seen.items(), key=lambda kv: -kv[1]))}")
        verdict = []
        if intruders:
            verdict.append(f"FAIL off-topic textbooks: {intruders}")
        if missing:
            verdict.append(f"FAIL named doc absent: {missing}")
        if others:
            verdict.append(f"note other corpus docs: {others}")
        print("    " + ("\n    ".join(verdict) if verdict else "PASS scope clean"))

    # ---- LAYER 3: the false gap ----------------------------------------
    print()
    print("=" * 78)
    print("LAYER 3 - THE FALSE GAP (doc13 35% vs doc16 50%)")
    print("=" * 78)
    q = "compare design submittal percentages in doc13.pdf and doc16.pdf"
    rows = keyword.search(q, limit=24, allowed_document_ids=all_ids)
    sides = {}
    for r in rows:
        ps, pe = pages_of(r["chunk_id"])
        sides.setdefault(r["filename"], []).append(ps)
    print(f"  question: {q}")
    print(f"  doc13 pages retrieved: {sorted(set(sides.get('doc13.pdf', [])))[:8]}")
    print(f"  doc16 pages retrieved: {sorted(set(sides.get('doc16.pdf', [])))[:8]}")
    print(f"  doc16 p.18 (the 50% clause) retrieved: {18 in sides.get('doc16.pdf', [])}")
    print(f"  doc13 p.125 (the 35% clause) retrieved: {125 in sides.get('doc13.pdf', [])}")

    # both clauses exist - proved independently of retrieval
    for needle, where in (("50% design submission", "doc16.pdf p.18"),
                          ("Preliminary (35%)", "doc13.pdf p.125")):
        r = raw.execute(
            """SELECT filename, page_start FROM chunks
                WHERE text LIKE ? LIMIT 1""", (f"%{needle}%",)).fetchone()
        print(f"  clause exists in corpus: {needle!r} -> "
              f"{(r['filename'], r['page_start']) if r else 'ABSENT'} (expected {where})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
