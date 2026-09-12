"""Prove the three analysis accuracy fixes (a288653) survive the map-reduce merge.

eval/score_analysis_gold.py cannot do this: it imports app.keyword and calls
search() directly, so it measures the RAW retrieval layer BEFORE the
analysis-layer scoping, cap and percentage recall are applied. That harness
documents the original defect; it does not exercise the fix.

This calls analysis.gather() - the function the API route calls - over the real
staged corpus, and checks the three properties named in the brief.

Run: python verify_accuracy.py <sqlite> <backend-dir>
"""
from __future__ import annotations

import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path


def main() -> int:
    db_path = str(Path(sys.argv[1]).resolve())
    backend = str(Path(sys.argv[2]).resolve())
    os.environ["DB_PATH"] = db_path
    sys.path.insert(0, backend)

    from app.config import settings
    settings.db_path = Path(db_path)
    from app import db as db_mod
    db_mod.reset_connection()
    from app import access, analysis

    scope = access.unrestricted_scope()
    raw = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    raw.row_factory = sqlite3.Row
    docs = {r["filename"]: r["id"] for r in raw.execute(
        "SELECT id, filename FROM documents")}
    id_to_name = {v: k for k, v in docs.items()}
    print(f"corpus: {len(docs)} documents")

    failures = []

    # ---------------------------------------------------------------- 1. SCOPE
    print("\n" + "=" * 78)
    print("1. NAMED-DOCUMENT SCOPE: nothing from unnamed textbooks")
    print("=" * 78)
    textbook_markers = ("book", "Differential-Equations", "Chemical", "civil-Design")
    scope_questions = [
        "compare design requirements in doc13.pdf, doc15.pdf and doc16.pdf",
        "compare design submittal percentages in doc13.pdf and doc16.pdf",
        "compare structural model requirements in doc16.pdf and doc15.pdf",
    ]
    for q in scope_questions:
        evidence, _ = analysis.gather(q, scope, limit=24)
        names = Counter(id_to_name.get(e["document_id"], e["document_id"])
                        for e in evidence)
        intruders = {n: c for n, c in names.items()
                     if any(m.lower() in n.lower() for m in textbook_markers)}
        print(f"\n  {q}")
        print(f"    retrieved: {dict(names)}")
        if intruders:
            print(f"    FAIL unnamed documents present: {intruders}")
            failures.append(f"scope leak on {q!r}: {intruders}")
        else:
            print("    PASS scope clean")

    # ------------------------------------------------------------------ 2. CAP
    print("\n" + "=" * 78)
    print("2. PER-DOCUMENT CAP: no document exceeds the cap in the evidence")
    print("=" * 78)
    for limit in (8, 24):
        cap = analysis.per_document_cap(limit)
        for q in scope_questions:
            evidence, _ = analysis.gather(q, scope, limit=limit)
            names = Counter(id_to_name.get(e["document_id"], e["document_id"])
                            for e in evidence)
            worst, count = (names.most_common(1) or [("-", 0)])[0]
            status = "PASS" if count <= cap else "FAIL"
            print(f"  limit={limit:2d} cap={cap} worst={count} ({worst}) "
                  f"total={len(evidence)}  {status}")
            if count > cap:
                failures.append(
                    f"cap exceeded at limit={limit}: {worst} supplied {count} > {cap}")

    # ----------------------------------------------------- 3. THE FALSE GAP
    print("\n" + "=" * 78)
    print("3. THE FALSE GAP: both percentage clauses in the evidence")
    print("=" * 78)
    q = "compare design submittal percentages in doc13.pdf and doc16.pdf"
    for limit in (8, 24):
        evidence, _ = analysis.gather(q, scope, limit=limit)
        blob = " ".join(str(e.get("exact_span", "")) for e in evidence)
        pages = {}
        for e in evidence:
            pages.setdefault(e["filename"], []).append(e["page_start"])
        has35 = "35%" in blob
        has50 = "50% design submission" in blob
        d13_125 = 125 in pages.get("doc13.pdf", [])
        d16_18 = 18 in pages.get("doc16.pdf", [])
        print(f"\n  limit={limit}")
        print(f"    pages: { {k: sorted(v) for k, v in pages.items()} }")
        print(f"    doc13 p.125 (the 35% clause) retrieved: {d13_125}")
        print(f"    doc16 p.18  (the 50% clause) retrieved: {d16_18}")
        print(f"    '35%' in evidence text                : {has35}")
        print(f"    '50% design submission' in evidence   : {has50}")
        if d13_125 and d16_18:
            print("    PASS both percentage clauses are in the evidence")
        else:
            print("    FAIL the false gap would be reported again")
            failures.append(
                f"false gap at limit={limit}: doc13p125={d13_125} doc16p18={d16_18}")

    print("\n" + "=" * 78)
    if failures:
        print(f"REGRESSED - {len(failures)} failure(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL THREE ACCURACY PROPERTIES HOLD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
