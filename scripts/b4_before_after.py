"""B4 acceptance: before/after extraction counts on the real datasheets, on COPIES only.

WHAT IT DOES, IN ORDER (the owner's B4 steps 2-5 and 8):

  1. BACKUP FIRST. `live_guard.verified_rollback_point` backs the live database
     up with the SQLite backup API, checks integrity, compares it with the live
     file and restores it into a scratch directory to prove it usable. Nothing
     else runs if that fails. The live file is only ever READ.
  2. Two disposable copies are made from that backup: one for BEFORE, one for
     AFTER. Neither path is live-shaped, so `db.connect()` opens them freely
     and nothing here can reach the live file.
  3. Each document is found by a filename fragment (passed with --doc;
     no default). A fragment matching none, or more than one document, stops the
     run - a guess at which document was meant is not a measurement.
  4. BEFORE: `--before-checkout` (a checkout of the code being replaced, e.g.
     `git worktree add ../b4-before origin/main`) re-extracts into its copy
     with ITS `scripts/reextract_on_copy.py`. AFTER: this checkout does the
     same into the other copy.
  5. Both copies are scored by THIS checkout's `scripts/fact_report.py`, so
     before and after are counted by the same rules: filled, blank,
     duplicate, garbled, numeric.

OUTPUT: counts per document and a table, on stdout and in `--out`. Document
ids and counts only - never a field name, a value or a filename. The copies
under `--scratch` DO contain document text: delete them when done, never
commit or paste them (CLAUDE.md rules 1 and 3).

    git worktree add ../b4-before origin/main
    mkdir C:\\b4-backups   (the backup tool never creates its folder)
    python scripts/b4_before_after.py --before-checkout ../b4-before \\
        --backup-dir C:\\b4-backups --scratch C:\\b4-scratch --out b4-result.json \\
        --doc <fragment 1> --doc <fragment 2> --doc <fragment 3>

Run with the backend STOPPED or running - the backup API is safe with the
server up. `GEOMETRY_READER_ENABLED` is read from the environment as usual;
leave it unset to measure the default path.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

METRICS = ("rows", "filled", "blank", "duplicate", "garbled", "numeric_filled")


def find_documents(db_path: Path, fragments: list[str]) -> dict[str, str]:
    """{fragment: document id}; exits when a fragment is missing or ambiguous."""
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    out, problems = {}, []
    for fragment in fragments:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM documents WHERE filename LIKE ? ORDER BY id",
            (f"%{fragment}%",))]
        if len(ids) != 1:
            problems.append(f"{fragment!r} matches {len(ids)} documents: {ids}")
        else:
            out[fragment] = ids[0]
    conn.close()
    if problems:
        raise SystemExit("stopping - each fragment must match exactly one document:\n  "
                         + "\n  ".join(problems))
    return out


def reextract(checkout: Path, source: Path, dest: Path, doc_ids: list[str]) -> dict:
    cmd = [sys.executable, str(checkout / "scripts" / "reextract_on_copy.py"),
           "--source", str(source), "--dest-dir", str(dest)]
    for doc in doc_ids:
        cmd += ["--doc", doc]
    done = subprocess.run(cmd, cwd=checkout, capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"re-extraction failed in {checkout}:\n{done.stderr[-2000:]}")
    return json.loads(done.stdout[done.stdout.index("{"):])


def score(db_path: Path, doc_id: str) -> dict:
    done = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "fact_report.py"),
         "--db", str(db_path), "--doc", doc_id],
        capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"fact_report failed:\n{done.stderr[-2000:]}")
    return json.loads(done.stdout.strip().splitlines()[-1])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live", type=Path,
                    default=REPO / "backend" / "data" / "rag_intelligence.sqlite")
    ap.add_argument("--before-checkout", required=True, type=Path)
    ap.add_argument("--scratch", required=True, type=Path)
    ap.add_argument("--backup-dir", type=Path, default=None)
    ap.add_argument("--doc", action="append", required=True,
                    help="filename fragment (repeatable, required); document names are never stored in the repo")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    from app import live_guard  # noqa: E402
    from reextract_on_copy import copy_database  # noqa: E402

    live = args.live.resolve()
    if not live.exists():
        raise SystemExit(f"live database not found: {live}")
    before_checkout = args.before_checkout.resolve()
    if not (before_checkout / "scripts" / "reextract_on_copy.py").exists():
        raise SystemExit(f"not a checkout with scripts/reextract_on_copy.py: {before_checkout}")

    # 1. BACKUP FIRST, proved restorable.
    proof = live_guard.verified_rollback_point(live, backup_dir=args.backup_dir)
    print("backup:", json.dumps({k: str(v) for k, v in proof.items()}, indent=2))

    # 2. Two disposable copies, from a consistent snapshot.
    snapshot = live_guard.diagnostic_copy(live)
    before_src = copy_database(snapshot, args.scratch / "before-src")
    after_src = copy_database(snapshot, args.scratch / "after-src")

    # 3. The documents, by fragment.
    docs = find_documents(snapshot, args.doc)
    ids = list(docs.values())

    # 4. Re-extract: old code, then new code, each into its own copy.
    before_run = reextract(before_checkout, before_src, args.scratch / "before", ids)
    after_run = reextract(REPO, after_src, args.scratch / "after", ids)

    # 5. Score both with the same rules.
    result = {"documents": {}, "backup": {k: str(v) for k, v in proof.items()},
              "live_unchanged": before_run.get("source_unchanged") and after_run.get("source_unchanged")}
    for fragment, doc_id in docs.items():
        b = score(Path(before_run["copy"]), doc_id)
        a = score(Path(after_run["copy"]), doc_id)
        result["documents"][fragment] = {
            "document_id": doc_id,
            "before": {m: b.get(m) for m in METRICS},
            "after": {m: a.get(m) for m in METRICS},
            "pages_unparsed_after": after_run["documents"][doc_id].get("pages_unparsed"),
        }

    print(f"\n{'document':<10} {'measure':<16} {'before':>8} {'after':>8} {'change':>8}")
    for fragment, row in result["documents"].items():
        for m in METRICS:
            b, a = row["before"][m], row["after"][m]
            change = (a - b) if isinstance(a, int) and isinstance(b, int) else ""
            print(f"{fragment:<10} {m:<16} {b!s:>8} {a!s:>8} {change!s:>8}")
    if args.out:
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("\nThe copies under", args.scratch, "contain document text - delete them when done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
