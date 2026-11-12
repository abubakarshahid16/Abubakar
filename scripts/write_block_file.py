#!/usr/bin/env python
"""Write `<data dir>/claude_blocked_hashes.json`: the hashes that may NEVER go to Claude (CLAUDE.md rule 3: the register).

    python scripts/write_block_file.py --data-dir <dir> --db <database> [--file <path>] [--sha256 <hex>] [--name <file name>]

NOT needed for `CLAUDE_AUTO_APPROVE_REVIEWS_ENABLED=true` any more (owner, 12 Nov 2026): the register is blocked by its file name
without any file. This script is how the owner MARKS files that must never go to Claude: by checksum (`--file`, `--sha256`, `--db`)
or by file name (`--name`, a name of at least 5 letters and digits; any file whose name contains it, in any case, spacing,
extension or with a copy/date suffix, is blocked). A block file that exists but cannot be read stops every Claude call that carries
a document (fail closed). Appends only: nothing already in the file is dropped.

Where the hash comes from, without printing a file name:
  * `--db`: every library document whose stored name looks like the register (`claude_approved.is_register_name`) gives its
    sha256 (the database is opened read-only);
  * `--file`: the sha256 of that file's bytes (the file is only read);
  * `--sha256`: a hash you already hold.
The output is counts only (how many hashes were found and how many are in the file now): never a name, a path or a hash.
Existing hashes in the file are kept (the file only ever grows here). Exit 1 when nothing to block is given.
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


def write(
    data_dir: str, found: set[str], names: set[str] | frozenset[str] = frozenset()
) -> tuple[int, int]:
    """Merge `found` (hashes) and `names` (file names to block) into the block file. Returns (hashes found,
    hashes in the file now). Raises ValueError for a hash that is not sha256 or a name too short to be a file name,
    and for a block file that exists but cannot be read (nothing is overwritten). Existing entries are never dropped."""
    if not all(_HEX.fullmatch(h) for h in found):
        raise ValueError("not a sha256")
    names = {n.strip() for n in names}
    if any(len(claude_approved.name_key(n)) < claude_approved.MIN_MARKED_KEY for n in names):
        raise ValueError("name too short")
    path = Path(data_dir) / claude_approved.BLOCK_FILE_NAME
    data: dict = {}
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("block file has the wrong shape")
    kept = {str(h).strip().lower() for h in data.get("blocked_sha256") or []}
    merged = sorted(kept | found)
    kept_names = [str(n) for n in data.get("blocked_names") or []]
    have = {claude_approved.name_key(n) for n in kept_names}
    for n in sorted(names):
        if claude_approved.name_key(n) not in have:
            kept_names.append(n)
            have.add(claude_approved.name_key(n))
    data["blocked_sha256"] = merged
    if kept_names:
        data["blocked_names"] = kept_names
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)
    return len(found), len(merged)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--db", default=None)
    ap.add_argument("--file", action="append", default=[])
    ap.add_argument("--sha256", action="append", default=[])
    ap.add_argument("--name", action="append", default=[])
    a = ap.parse_args(argv)
    found: set[str] = set()
    try:
        if a.db:
            found |= hashes_from_db(a.db)
        found |= {hash_of_file(f) for f in a.file}
        found |= {h.strip().lower() for h in a.sha256}
        names = {n for n in a.name if n.strip()}
        if not found and not names:
            print("REFUSED | nothing to block was given: the block file was not written")
            return 1
        n_found, n_file = write(a.data_dir, found, names)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"REFUSED | {type(exc).__name__}")
        return 1
    print(
        f"BLOCK FILE | hashes found {n_found} | hashes in the file now {n_file} | names given {len(names)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
