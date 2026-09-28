"""Real-data sanity check for the geometry-reader OCR-awareness fix
(fix/geometry-needs-ocr-guard, commit 5088b99): does it behave sanely on the
owner's actual submittals and standards, not just the synthetic unit tests.

WHY THIS EXISTS. The unit tests (test_geometry_reader.py, test_geometry_
wiring.py) prove the fix's LOGIC is correct on tiny synthetic pages. They
cannot prove it behaves reasonably at the scale and variety of the owner's
real documents - a page-selection bug, an exception on a real PDF's table
shape, or a needs_ocr flag rate the fix silently drops nearly everything for
would only show up here.

READ-ONLY, SAFE ON THE LIVE SYSTEM (CLAUDE.md rules 2 and 3, and the live-DB
rule in CLAUDE.md's tooling traps): uses `live_guard.diagnostic_copy()` for
every database read - a WAL-safe copy, never the live file - and opens PDFs
with plain `pymupdf.open()`, read-only. Writes nothing, queues nothing,
changes no document, and does not require the server to be running or
stopped.

WHAT IT NEVER PRINTS. No field label, value, unit, or any other document
text - only: document ids (opaque hashes, already how this project logs
them elsewhere), page numbers, document_role, and integer counts. Same
convention as scripts/prove_vision_reader_layouts.py and
scripts/backfill_requirement_extraction.py.

Usage (run from the backend/ directory, server may be running or stopped -
this never touches the live file):

    python ../scripts/verify_geometry_ocr_guard_on_real_docs.py
    python ../scripts/verify_geometry_ocr_guard_on_real_docs.py --limit 15
    python ../scripts/verify_geometry_ocr_guard_on_real_docs.py --pages-per-doc 20
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=10,
                    help="max documents to sample per role (submittal / standard)")
    ap.add_argument("--pages-per-doc", type=int, default=12,
                    help="max pages to read per document (keeps this quick)")
    args = ap.parse_args(argv)

    import pymupdf

    from app import geometry_reader as gr
    from app import live_guard
    from app.config import settings
    from app.db import connect as _connect_module  # noqa: F401 - module, not called live

    db_path = settings.db_path
    if not Path(db_path).is_file():
        print(f"STOP - no database found at {db_path}. Run this from the machine "
              "that holds the real documents, not a fresh clone.")
        return 1

    copy_path = live_guard.diagnostic_copy(db_path)
    print(f"Working from a read-only diagnostic copy: {copy_path} (live file untouched)")

    import sqlite3
    conn = sqlite3.connect(f"file:{copy_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    totals = {"docs": 0, "pages": 0, "exceptions": 0,
              "table_rows_kept": 0, "form_pairs_kept": 0,
              "rows_needs_ocr_flagged": 0, "docs_by_role": {}}

    for role in ("CONTRACTOR_SUBMITTAL", "COMPANY_STANDARD"):
        docs = conn.execute(
            "SELECT d.id, d.stored_path, d.page_count FROM documents d"
            " JOIN document_classification c ON c.document_id = d.id"
            " WHERE c.document_role = ? AND d.status = 'ready' AND d.stored_path IS NOT NULL"
            " ORDER BY d.id LIMIT ?", (role, args.limit)).fetchall()
        totals["docs_by_role"][role] = len(docs)
        print(f"\n=== {role}: {len(docs)} document(s) sampled ===")
        for doc in docs:
            doc_id, stored_path, page_count = doc["id"], doc["stored_path"], doc["page_count"] or 0
            if not Path(stored_path).is_file():
                print(f"  {doc_id[:12]}...  SKIP - stored file not present on this machine")
                continue
            ocr_pages = {r["page_no"] for r in conn.execute(
                "SELECT page_no FROM pages WHERE document_id = ? AND needs_ocr = 1",
                (doc_id,)).fetchall()}
            totals["docs"] += 1
            kept_this_doc = 0
            flagged_this_doc = 0
            try:
                with pymupdf.open(stored_path) as pdf:
                    n = min(page_count or pdf.page_count, pdf.page_count, args.pages_per_doc)
                    for page_no in range(1, n + 1):
                        totals["pages"] += 1
                        try:
                            rows = gr.read_page_rows(pdf[page_no - 1])
                        except Exception as exc:  # noqa: BLE001 - report, never crash the scan
                            totals["exceptions"] += 1
                            print(f"  {doc_id[:12]}... page {page_no}: EXCEPTION "
                                 f"{type(exc).__name__}: {exc}")
                            continue
                        table_rows = sum(1 for r in rows if r["source"] == "table")
                        form_rows = sum(1 for r in rows if r["source"] == "form")
                        totals["table_rows_kept"] += table_rows
                        totals["form_pairs_kept"] += form_rows
                        kept_this_doc += len(rows)
                        if page_no in ocr_pages and rows:
                            flagged_this_doc += len(rows)
                            totals["rows_needs_ocr_flagged"] += len(rows)
            except Exception as exc:  # noqa: BLE001 - one bad file must not kill the scan
                totals["exceptions"] += 1
                print(f"  {doc_id[:12]}...  EXCEPTION opening file: {type(exc).__name__}: {exc}")
                continue
            print(f"  {doc_id[:12]}...  {n if 'n' in dir() else '?'} pages read, "
                 f"{kept_this_doc} geometry rows kept "
                 f"({flagged_this_doc} on needs_ocr pages), "
                 f"{len(ocr_pages)} needs_ocr page(s) in this document")

    conn.close()
    try:
        copy_path.unlink()
        copy_path.parent.rmdir()
    except OSError:
        pass

    print("\n" + "=" * 60)
    print("SUMMARY (structural counts only - no document text)")
    for role, n in totals["docs_by_role"].items():
        print(f"  {role}: {n} document(s) sampled")
    print(f"  Documents actually read: {totals['docs']}")
    print(f"  Pages read: {totals['pages']}")
    print(f"  Table rows kept: {totals['table_rows_kept']}")
    print(f"  Form pairs kept: {totals['form_pairs_kept']}")
    print(f"  Of those, on a needs_ocr page (now flagged for engineer review): "
         f"{totals['rows_needs_ocr_flagged']}")
    print(f"  Exceptions: {totals['exceptions']}")
    if totals["exceptions"]:
        print("\nEXCEPTIONS ABOVE ARE THE THING TO LOOK AT FIRST - the fix must not "
             "crash on any real page shape. Zero is what a clean run looks like.")
    return 1 if totals["exceptions"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
