"""Extraction CLI.

    python -m app.worker --all
    python -m app.worker <doc_id>
    python -m app.worker <doc_id> --memlog mem.csv

Kill it at any point with Ctrl+C or taskkill; rerunning resumes from the
last committed batch.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import psutil

from . import live_guard
from .db import connect, init_db
from .extract import extract_document


def tree_rss_mb() -> float:
    """RSS of this process plus its extraction workers."""
    me = psutil.Process(os.getpid())
    total = me.memory_info().rss
    for c in me.children(recursive=True):
        try:
            total += c.memory_info().rss
        except psutil.Error:
            pass
    return total / (1024 * 1024)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("doc_id", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--memlog")
    args = ap.parse_args()

    # A live database only after a verified backup and a restore drill.
    live_guard.clear_if_live(f"app.worker extract {'--all' if args.all else args.doc_id}")
    init_db()
    conn = connect()

    if args.all:
        ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM documents WHERE status IN ('queued','extracting') ORDER BY size_bytes"
            )
        ]
    elif args.doc_id:
        ids = [args.doc_id]
    else:
        ap.error("give a doc_id or --all")
        return 2

    memf = open(args.memlog, "w", encoding="utf-8") if args.memlog else None
    if memf:
        memf.write("elapsed_s,pages_done,rss_mb\n")
    t0 = time.perf_counter()
    peak = tree_rss_mb()

    for doc_id in ids:
        def progress(done: int, total: int) -> None:
            nonlocal peak
            rss = tree_rss_mb()
            peak = max(peak, rss)
            if memf:
                memf.write(f"{time.perf_counter()-t0:.2f},{done},{rss:.1f}\n")
                memf.flush()
            print(f"  {done}/{total} pages   rss={rss:.0f} MB", flush=True)

        r = extract_document(doc_id, progress=progress)
        r["peak_rss_mb"] = round(peak, 1)
        if r.get("error"):
            print(f"[FAILED] {r['filename'][:40]:40} {r['error']}", flush=True)
            continue
        print(
            f"[done] {r['filename'][:40]:40} "
            f"pages={r['pages_extracted']}/{r['pages_total']} "
            f"needs_ocr={r['needs_ocr']} "
            f"{r['seconds']}s  {r['pages_per_sec']} pages/s  "
            f"peak_rss={r['peak_rss_mb']}MB  resumed_from_batch={r['resumed_from_batch']}",
            flush=True,
        )

    if memf:
        memf.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
