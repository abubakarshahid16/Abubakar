"""Coverage per document: how much of it search can actually see.

Coverage is the CEILING on everything downstream. If 4% of a document never
reaches the index, no retrieval improvement can answer from it - the passage is
not there to be found. It is the measurement OCR was built for, so it is
reported before and after recognition.

    python eval/coverage.py

DEFINITIONS, stated because a coverage number with an unstated definition is
worth nothing:

  covered    a page whose number falls inside the page range of at least one
             RETRIEVABLE chunk. Non-retrievable chunks are stored for
             inspection and never compete in search, so a page covered only by
             those is not covered.
  after      coverage as the index stands now, recognised text included.
  before     after, MINUS the pages that only OCR could have reached. A page
             counts as OCR-dependent only if it had no usable extractable text
             of its own AND recognition actually produced characters for it.

             THE FIRST VERSION OF THIS WAS WRONG AND HAND-CHECKING CAUGHT IT.
             It computed `before` by dropping every recognised CHUNK, which
             also drops coverage of pages that chunk merely spans. One NORSOK
             chunk covers pages 21-24: page 21 was already covered, page 22 has
             413 extracted characters of its own, page 23 is genuinely blank.
             Only page 24 was reached by OCR. The chunk-level definition
             reported +12.5% for that document; the true figure is +4.2%.
             Attributing coverage per PAGE, by that page's own text source, is
             the only version that survives being checked by hand.
  missing    covered=false. Reported WITH the exclusion rule that accounts for
             it, because "4% is missing" is a complaint and "4% is missing and
             here is the rule that dropped each page" is a measurement.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.db import connect, init_db  # noqa: E402


def covered_pages(conn, doc_id: str) -> set[int]:
    """Page numbers reachable through at least one retrievable chunk."""
    pages: set[int] = set()
    for r in conn.execute(
            """SELECT page_start, page_end FROM chunks
               WHERE document_id = ? AND retrievable = 1""", (doc_id,)):
        pages.update(range(r["page_start"], r["page_end"] + 1))
    return pages


def ocr_dependent_pages(conn, doc_id: str) -> set[int]:
    """Pages that ONLY recognition could have reached.

    Both conditions are required. A page that had extractable text never needed
    OCR even if a recognised chunk happens to span it, and a page recognition
    read nothing from is not a page recognition rescued.
    """
    return {r["page_no"] for r in conn.execute(
        """SELECT p.page_no FROM pages p
           JOIN page_ocr o ON o.document_id = p.document_id AND o.page_no = p.page_no
           WHERE p.document_id = ? AND p.needs_ocr = 1 AND o.char_count > 0""",
        (doc_id,))}


def missing_reasons(conn, doc_id: str, missing: set[int]) -> dict[str, int]:
    """Which rule accounts for each uncovered page."""
    if not missing:
        return {}
    rules: dict[str, int] = {}
    explained = set()
    # BOTH SCOPES. A page can be uncovered for two different reasons: the page
    # itself was excluded, or every chunk on it was. Querying only scope='page'
    # reported 21 pages as "dropped with no reason recorded" and very nearly
    # had a non-existent defect filed against the pipeline. Every one of them
    # turned out to carry a chunk-scope `content_quality_gate` row with a
    # quality flag saying exactly why. The invariant held; the query did not.
    rows = conn.execute(
        """SELECT page_start, page_end, rule FROM exclusions
           WHERE document_id = ? AND scope = 'page'""", (doc_id,)).fetchall()
    for r in rows:
        for p in range(r["page_start"], r["page_end"] + 1):
            if p in missing and p not in explained:
                rules[r["rule"]] = rules.get(r["rule"], 0) + 1
                explained.add(p)
    for r in conn.execute(
            """SELECT c.page_start, c.page_end, e.rule
               FROM exclusions e JOIN chunks c ON c.id = e.chunk_id
               WHERE e.document_id = ? AND e.scope = 'chunk'""", (doc_id,)):
        for p in range(r["page_start"], r["page_end"] + 1):
            if p in missing and p not in explained:
                rules[f"{r['rule']} (every chunk on the page)"] = (
                    rules.get(f"{r['rule']} (every chunk on the page)", 0) + 1)
                explained.add(p)
    unexplained = len(missing - explained)
    if unexplained:
        # THIS is the interesting case, and it should be empty: a page dropped
        # by something that did not record why violates the standing promise
        # that nothing is dropped silently.
        rules["(NO EXCLUSION RECORDED - investigate)"] = unexplained
    return rules


def main() -> int:
    init_db()
    conn = connect()
    docs = conn.execute(
        "SELECT id, filename, page_count, recognised_pages FROM documents"
        " ORDER BY page_count").fetchall()

    print(f"{'document':44} {'pages':>6} {'before':>8} {'after':>8} {'gain':>7} {'recog':>6}")
    print("-" * 84)
    totals = [0, 0, 0, 0]
    detail = []
    for d in docs:
        total = d["page_count"] or 0
        if not total:
            continue
        after = covered_pages(conn, d["id"])
        before = after - ocr_dependent_pages(conn, d["id"])
        pb, pa = 100 * len(before) / total, 100 * len(after) / total
        print(f"{d['filename'][:44]:44} {total:>6} {pb:>7.1f}% {pa:>7.1f}% "
              f"{pa - pb:>+6.1f}% {d['recognised_pages']:>6}")
        totals[0] += total
        totals[1] += len(before)
        totals[2] += len(after)
        totals[3] += d["recognised_pages"]
        detail.append((d["filename"], total, sorted(set(range(1, total + 1)) - after),
                       missing_reasons(conn, d["id"],
                                       set(range(1, total + 1)) - after)))
    print("-" * 84)
    tb = 100 * totals[1] / totals[0]
    ta = 100 * totals[2] / totals[0]
    print(f"{'ALL':44} {totals[0]:>6} {tb:>7.1f}% {ta:>7.1f}% {ta - tb:>+6.1f}% {totals[3]:>6}")

    print("\nWHAT IS STILL MISSING, and the rule that accounts for it")
    for filename, total, missing, rules in detail:
        if not missing:
            print(f"\n  {filename[:60]}: nothing missing")
            continue
        print(f"\n  {filename[:60]}: {len(missing)} of {total} pages "
              f"({100 * len(missing) / total:.1f}%)")
        for rule, n in sorted(rules.items(), key=lambda kv: -kv[1]):
            print(f"      {rule:34} {n}")
        if len(missing) <= 12:
            print(f"      pages: {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
