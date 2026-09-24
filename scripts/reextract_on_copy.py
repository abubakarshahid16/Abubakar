"""Re-extract datasheet facts into a DISPOSABLE COPY of a database, never the original.

WHY THIS EXISTS (issue #179). `scripts/eval_extraction.py` scores whatever is
in `submittal_facts`. To score the CURRENT extractor on a real document, the
facts have to be re-read with the current code - and `extract_facts(replace=
True)` deletes and rewrites rows, which must never happen to the live database
without the owner's decision. Until now every such run was a one-off script
in a scratchpad. This is the committed, reproducible version.

WHAT IT DOES, IN ORDER:

  1. Copies `<source>`, `<source>-wal` and `<source>-shm` TOGETHER into
     `--dest-dir` (SQLite WAL mode: copying the main file alone loses the
     documents still in the WAL - CLAUDE.md, "Tooling traps").
  2. Refuses if the destination IS the source, or if the source's size or
     mtime changed while it ran - the proof the original was not written.
  3. Points `settings.db_path` at the COPY and, per document, first counts
     read-only what `orphan_guard` would report: unconfirmed facts the
     re-extraction deletes, and review findings that cite them.
  4. Re-extracts with `replace=True, acknowledge_orphaned_findings=True` -
     acknowledged ONLY because the database is a disposable copy.

Output: a JSON summary on stdout (and to `--summary` if given). It carries
document ids and counts only, never document text.

    python scripts/reextract_on_copy.py --source backend/data/rag_intelligence.sqlite \\
        --dest-dir <scratch> --doc doc_a --doc doc_b
    python scripts/eval_extraction.py --doc doc_a --gold gold/X.csv \\
        --db <scratch>/rag_intelligence.sqlite --out-dir .cowork/eval
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

SUFFIXES = ("", "-wal", "-shm")


def _stat(path: Path) -> dict:
    out = {}
    for suffix in SUFFIXES:
        p = Path(f"{path}{suffix}")
        if p.exists():
            st = p.stat()
            out[suffix or "main"] = (st.st_size, st.st_mtime_ns)
    return out


def copy_database(source: Path, dest_dir: Path) -> Path:
    source = source.resolve()
    if not source.exists():
        raise SystemExit(f"source database not found: {source}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = (dest_dir / source.name).resolve()
    if dest == source:
        raise SystemExit("refusing: the destination is the source database itself")
    for suffix in SUFFIXES:
        src = Path(f"{source}{suffix}")
        dst = Path(f"{dest}{suffix}")
        if dst.exists():
            dst.unlink()
        if src.exists():
            shutil.copy2(src, dst)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", required=True, type=Path,
                    help="the database to copy FROM (read, never written)")
    ap.add_argument("--dest-dir", required=True, type=Path,
                    help="scratch directory the copy is written into")
    ap.add_argument("--doc", required=True, action="append",
                    help="document id to re-extract (repeatable)")
    ap.add_argument("--summary", type=Path, default=None,
                    help="also write the JSON summary here")
    args = ap.parse_args()

    before = _stat(args.source.resolve())
    copy = copy_database(args.source, args.dest_dir)

    from app import datasheets, db, orphan_guard  # noqa: E402
    from app.config import settings  # noqa: E402

    settings.db_path = copy
    db.reset_connection()
    conn = db.connect()
    summary: dict = {"copy": str(copy), "documents": {}}
    for doc_id in args.doc:
        exists = conn.execute("SELECT 1 FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if exists is None:
            summary["documents"][doc_id] = {"error": "document not found in the copy"}
            continue
        where = "submittal_document_id = ? AND confirmed_by IS NULL"
        facts_before = conn.execute(
            "SELECT COUNT(*) FROM submittal_facts WHERE submittal_document_id = ?",
            (doc_id,)).fetchone()[0]
        unconfirmed = conn.execute(
            f"SELECT COUNT(*) FROM submittal_facts WHERE {where}", (doc_id,)).fetchone()[0]
        # What orphan_guard.check_facts would record and refuse on - counted
        # with its own query, before anything is deleted.
        orphaned = orphan_guard.findings_orphaned_by_facts(where, (doc_id,))
        result = datasheets.extract_facts(
            doc_id, allowed_document_ids=frozenset([doc_id]), replace=True,
            acknowledge_orphaned_findings=True)
        facts_after = conn.execute(
            "SELECT COUNT(*) FROM submittal_facts WHERE submittal_document_id = ?",
            (doc_id,)).fetchone()[0]
        summary["documents"][doc_id] = {
            "facts_before": facts_before,
            "unconfirmed_facts_deleted": unconfirmed,
            "confirmed_facts_kept": facts_before - unconfirmed,
            "review_findings_orphaned": orphaned,
            "facts_after": facts_after,
            "blanks_after": result.get("blanks"),
            "pages_read": result.get("pages_read"),
            "pages_unparsed": result.get("pages_unparsed"),
        }
    db.reset_connection()

    after = _stat(args.source.resolve())
    summary["source_unchanged"] = before == after
    text = json.dumps(summary, indent=2)
    print(text)
    if args.summary is not None:
        args.summary.write_text(text, encoding="utf-8")
    if before != after:
        print("SOURCE DATABASE CHANGED DURING THE RUN", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
