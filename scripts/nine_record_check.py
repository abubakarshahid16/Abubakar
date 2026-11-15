#!/usr/bin/env python3
"""Check the role record of a nine-role review against the rest of the database and the spend ledger (planner tool; read only).

    python scripts/nine_record_check.py --copy <folder> --run <run id> [--ledger <spend.jsonl>]

`<folder>` holds the database copy (`rag_intelligence.sqlite`). It is opened READ-ONLY with `immutable=1`: nothing is written, nothing is
created. Prints the nine rows and, per role, what it read (ids, kinds, pages, sizes: never a title or any text). Exit 1 when:

  1. there are not nine role rows;
  2. a role that "ran" and made a model call has no read row (a role that ran and read nothing must say so in `produced`: `read_nothing`);
  3. a read page lies outside its document's pages;
  4. a Claude read names a document that is not on the run's stored list (`review_shown_lists`), when a list was stored;
  5. a Claude call that was answered has not exactly one ledger line with the same digest and step, or a ledger line of a nine-role step
     of this run has no call row with its digest (so each Claude call of the record matches one ledger line);
  6. a produced count differs from the rows it counts: role 1 `facts` against `agent_review_fact`, role 8 `lines` against `agent_review_line`.

No model is called and no document text is read. Importable: `check(conn, run_id, ledger)` returns the list of problems.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

NINE_STEPS = (
    "nine_reader",
    "nine_context",
    "nine_librarian",
    "nine_reviewer",
    "agent_review",
    "nine_second",
    "nine_writer",
)
CODE_ROLES = (7, 8)


def connect_read_only(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _has(conn, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def _count(conn, table: str, run_id: str, column: str = "run_id") -> int | None:
    if not _has(conn, table):
        return None
    return conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {column} = ?", (run_id,)
    ).fetchone()[0]


def check(
    conn: sqlite3.Connection, run_id: str, ledger: list[dict] | None = None
) -> list[str]:
    problems: list[str] = []
    if not _has(conn, "agent_review_role"):
        return ["no role tables: this run has no role record"]
    roles = conn.execute(
        "SELECT * FROM agent_review_role WHERE run_id = ? ORDER BY role_no", (run_id,)
    ).fetchall()
    if [r["role_no"] for r in roles] != list(range(1, 10)):
        problems.append(f"not nine role rows ({len(roles)} found)")
    reads = (
        conn.execute(
            "SELECT * FROM agent_review_role_read WHERE run_id = ?", (run_id,)
        ).fetchall()
        if _has(conn, "agent_review_role_read")
        else []
    )
    calls = (
        conn.execute(
            "SELECT * FROM agent_review_role_call WHERE run_id = ?", (run_id,)
        ).fetchall()
        if _has(conn, "agent_review_role_call")
        else []
    )

    for r in roles:  # 2
        mine = [x for x in reads if x["role_no"] == r["role_no"]]
        made = [
            c for c in calls if c["role_no"] == r["role_no"] and c["state"] != "refused"
        ]
        produced = json.loads(r["produced_json"] or "{}")
        if (
            r["state"] == "ran"
            and r["role_no"] not in CODE_ROLES
            and made
            and not mine
            and "read_nothing" not in produced
        ):
            problems.append(
                f"role {r['role_no']} ran and made a call but has no read row and no read_nothing reason"
            )

    pages = {}  # 3
    for x in reads:
        if x["document_id"] not in pages:
            row = (
                conn.execute(
                    "SELECT page_count FROM documents WHERE id = ?", (x["document_id"],)
                ).fetchone()
                if _has(conn, "documents")
                else None
            )
            pages[x["document_id"]] = row["page_count"] if row else None
        total = pages[x["document_id"]]
        for p in json.loads(x["pages_json"] or "[]"):
            if total is not None and not 1 <= int(p) <= int(total):
                problems.append(
                    f"role {x['role_no']} read page {p} outside document {x['document_id']} ({total} pages)"
                )

    shown = None  # 4
    if _has(conn, "review_shown_lists"):
        row = conn.execute(
            "SELECT documents_json FROM review_shown_lists WHERE run_id = ?", (run_id,)
        ).fetchone()
        shown = None if row is None else set(json.loads(row["documents_json"] or "[]"))
    claude_calls = {c["call_id"] for c in calls if c["engine"] == "claude"}
    if shown is not None:
        for x in reads:
            if x["call_id"] in claude_calls and x["document_id"] not in shown:
                problems.append(
                    f"role {x['role_no']} sent document {x['document_id']} to Claude: it is not on the run's stored list"
                )

    if ledger is not None:  # 5
        mine = [
            e
            for e in ledger
            if e.get("run") == run_id
            and e.get("step") in NINE_STEPS
            and not e.get("refused")
        ]
        for c in calls:
            if c["engine"] == "claude" and c["state"] == "answered":
                found = [
                    e
                    for e in mine
                    if e.get("prompt_sha256") == c["request_sha256"]
                    and e.get("step") == c["step"]
                ]
                if len(found) != 1:
                    problems.append(
                        f"call {c['call_id']} (role {c['role_no']}) matches {len(found)} ledger line(s), not one"
                    )
        digests = {c["request_sha256"] for c in calls if c["engine"] == "claude"}
        for e in mine:
            if (
                e.get("step") != "agent_review"
                and e.get("prompt_sha256") not in digests
            ):
                problems.append(
                    f"a ledger line of step {e.get('step')} has no call row with its digest"
                )

    for role_no, key, table in (
        (1, "facts", "agent_review_fact"),
        (8, "lines", "agent_review_line"),
    ):  # 6
        row = next((r for r in roles if r["role_no"] == role_no), None)
        produced = json.loads(row["produced_json"] or "{}") if row is not None else {}
        counted = _count(conn, table, run_id)
        if key in produced and counted is not None and int(produced[key]) != counted:
            problems.append(
                f"role {role_no} produced {key}={produced[key]} but {table} holds {counted} row(s) of this run"
            )
    return problems


def report(conn: sqlite3.Connection, run_id: str) -> str:
    out = [f"run {run_id}: the nine roles"]
    for r in conn.execute(
        "SELECT * FROM agent_review_role WHERE run_id = ? ORDER BY role_no", (run_id,)
    ):
        reads = (
            conn.execute(
                "SELECT document_id, document_kind, pages_json, chapter_id, part_no, part_of, chars, pictures FROM agent_review_role_read"
                " WHERE run_id = ? AND role_no = ? ORDER BY call_id, seq",
                (run_id, r["role_no"]),
            ).fetchall()
            if _has(conn, "agent_review_role_read")
            else []
        )
        usd = "not known" if r["usd"] is None else f"{r['usd']:.4f}"
        out.append(
            f"  {r['role_no']} {r['role']}: {r['state']}{'' if r['state'] == 'ran' else ' (' + str(r['why']) + ')'}; engine {r['engine']}; calls {r['calls']}; USD {usd}; reads {len(reads)}"
        )
        for x in reads:
            pages = json.loads(x["pages_json"] or "[]")
            out.append(
                f"      {x['document_kind']} {x['document_id']} pages {pages[:1]}..{pages[-1:]} chapter {x['chapter_id']} part {x['part_no']}/{x['part_of']} chars {x['chars']} pictures {x['pictures']}"
            )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--copy", required=True, type=Path)
    ap.add_argument("--run", required=True)
    ap.add_argument("--ledger", type=Path)
    a = ap.parse_args(argv)
    db = a.copy / "rag_intelligence.sqlite"
    if not db.is_file():
        print(f"no database in {a.copy}", file=sys.stderr)
        return 2
    conn = connect_read_only(db)
    ledger_path = a.ledger or (a.copy / "claude_spend.jsonl")
    ledger = None
    if ledger_path.is_file():
        ledger = [
            json.loads(line)
            for line in ledger_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    if _has(conn, "agent_review_role"):
        print(report(conn, a.run))
    problems = check(conn, a.run, ledger)
    for p in problems:
        print("FAIL:", p)
    print(
        "OK: the record is consistent"
        if not problems
        else f"{len(problems)} problem(s)"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
