"""Check that every rule and checklist item behind a known finding is still asked (order 13, C3). Ids only; read only.

    python scripts/c3_check_known_rules.py --ids <local file of ids> --run-db <trial copy's rag_intelligence.sqlite> [--run-id ID]

Prints `checked N, still asked M, dropped K` and the dropped ids; exits 1 when any is dropped, 2 when the file is not ids only.

A local, untracked file lists the rule ids (`R-...`) and checklist item ids (`S-...`) behind every caught problem and every
proven Pass of the finished runs. `missing` says which of them a plan no longer asks.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path

_ID = re.compile(r"^[RS]-[0-9A-Za-z-]{3,40}$")


def read_ids(path: str | Path) -> list[str]:
    """The ids of the file: one per line, blank lines and `#` comments skipped. Anything that is not an id (a sentence, a
    quote) raises ValueError, so the file can never carry text."""
    out: list[str] = []
    for raw in Path(path).expanduser().read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if not _ID.match(line):
            raise ValueError("the known-rules file holds a line that is not an id")
        out.append(line)
    return list(dict.fromkeys(out))


def is_asked(known_id: str, asked: Iterable[str]) -> bool:
    """A known id is asked when a plan key is that id or starts with it (a short id of eight characters names a full key)."""
    return any(k == known_id or k.startswith(known_id) for k in asked)


def missing(known: Iterable[str], asked: Iterable[str]) -> list[str]:
    """The known ids the plan does not ask, in order."""
    asked = list(asked)
    return [k for k in known if not is_asked(k, asked)]


def asked_in_run_db(db_path: str | Path, run_id: str | None = None) -> set[str]:
    """The rule keys asked and the checklist item ids of one stored run (default: the latest run that has any rule row)."""
    conn = sqlite3.connect(f"file:{Path(db_path).expanduser()}?mode=ro", uri=True)
    try:
        if run_id is None:
            row = conn.execute(
                "SELECT r.run_id FROM agent_review_run r WHERE EXISTS (SELECT 1 FROM agent_review_rule x WHERE x.run_id = r.run_id)"
                " ORDER BY r.started_at DESC LIMIT 1"
            ).fetchone()
            run_id = row[0] if row else ""
        keys = {
            r[0]
            for r in conn.execute(
                "SELECT rule_key FROM agent_review_rule WHERE run_id = ? AND asked = 1",
                (run_id,),
            )
        }
        keys |= {
            r[0]
            for r in conn.execute(
                "SELECT item_id FROM agent_review_line WHERE run_id = ? AND item_id LIKE 'S-%'",
                (run_id,),
            )
        }
        return keys
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ids", required=True)
    ap.add_argument("--run-db", required=True)
    ap.add_argument("--run-id")
    args = ap.parse_args(argv)
    try:
        known = read_ids(args.ids)
    except ValueError as exc:
        print(f"refused: {exc}")
        return 2
    lost = missing(known, asked_in_run_db(args.run_db, args.run_id))
    print(
        f"checked {len(known)}, still asked {len(known) - len(lost)}, dropped {len(lost)}"
    )
    for k in lost:
        print(f"dropped: {k}")
    return 1 if lost else 0


if __name__ == "__main__":
    raise SystemExit(main())
