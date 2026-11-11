#!/usr/bin/env python
"""Write `<data dir>/claude_blocked_hashes.json`: the hashes that may NEVER go to Claude (CLAUDE.md rule 3: the register).

    python scripts/write_block_file.py --data-dir <dir> --db <database> [--file <path>] [--sha256 <hex>]

Needed once, before `CLAUDE_AUTO_APPROVE_REVIEWS_ENABLED=true` (#1584): with the switch on, a block file that is missing or holds
no hash stops EVERY Claude call that carries a document (fail closed, `claude_approved.blocked_hashes`).

Where the hash comes from, without printing a file name:
  * `--db`: every library document whose stored name looks like the register (`claude_approved.is_register_name`) gives its
    sha256 (the database is opened read-only);
  * `--file`: the sha256 of that file's bytes (the file is only read);
  * `--sha256`: a hash you already hold.
The output is counts only (how many hashes were found and how many are in the file now): never a name, a path or a hash.
Existing hashes in the file are kept (the file only ever grows here). Exit 1 when no hash is found at all.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import claude_approved  # noqa: E402

_HEX = re.compile(r"[0-9a-f]{64}")


def hashes_from_db(db_path: str) -> set[str]:
    conn = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT filename, sha256 FROM documents").fetchall()
    finally:
        conn.close()
    return {
        str(sha).strip().lower()
        for name, sha in rows
        if sha and claude_approved.is_register_name(name)
    }


def hash_of_file(path: str) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write(data_dir: str, found: set[str]) -> tuple[int, int]:
    """Merge `found` into the block file. Returns (found, in the file now). Raises ValueError for a hash that is not sha256."""
    if not all(_HEX.fullmatch(h) for h in found):
        raise ValueError("not a sha256")
    path = Path(data_dir) / claude_approved.BLOCK_FILE_NAME
    kept: set[str] = set()
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        kept = {str(h).strip().lower() for h in data.get("blocked_sha256") or []}
    merged = sorted(kept | found)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"blocked_sha256": merged}, indent=1), encoding="utf-8")
    tmp.replace(path)
    return len(found), len(merged)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--db", default=None)
    ap.add_argument("--file", action="append", default=[])
    ap.add_argument("--sha256", action="append", default=[])
    a = ap.parse_args(argv)
    found: set[str] = set()
    try:
        if a.db:
            found |= hashes_from_db(a.db)
        found |= {hash_of_file(f) for f in a.file}
        found |= {h.strip().lower() for h in a.sha256}
        if not found:
            print("REFUSED | no hash found: the block file was not written")
            return 1
        n_found, n_file = write(a.data_dir, found)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"REFUSED | {type(exc).__name__}")
        return 1
    print(f"BLOCK FILE | hashes found {n_found} | hashes in the file now {n_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
