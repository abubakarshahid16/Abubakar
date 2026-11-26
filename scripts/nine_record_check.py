"""THE NINE-ROLE RECORD CHECK (SPEC section B, "Planner": the record a review run wrote is checked by code). READ-ONLY: the database is
opened read-only (`mode=ro&immutable=1`); nothing is written, no model is called, nothing leaves the machine. Prints ids, numbers and codes only.

    python scripts/nine_record_check.py --db <folder or rag_intelligence.sqlite> --run <run id>

Exit 0 when the record holds; exit 1 with one line per problem. A problem is any of:
  1. not exactly nine role rows (1 to 9);
  2. a call left "sent" (its end was never written: what happened to it is not known);
  3. a page in a read row that the document does not hold (the paper's or a book's stored pages and recognised pages);
  4. a document read by a Claude call that is not on the run's stored shown list (when the run has one; the paper is always
     allowed);
  5. calls of a step that differ from the run's own stored calls of that step (answered calls against the calls stored as ok);
  6. a role's stored counts that differ from its rows (calls, calls answered, paper pages sent, page pictures sent);
  7. with the money ledger (`--ledger`, or the data folder's claude_spend.jsonl): a ledger reservation of this run that no record
     call matches by its step AND the exact documents it sent. Everything the ledger saw leave must be in the record. A record
     call with no ledger line was answered from the stored answers (nothing sent): counted, not a problem. The ledger keeps the
     request BODY's digest, which is built with the key, so the record keeps its parts' digest and the two match by step and
     documents instead.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROLES, CALLS, READS = (
    "agent_review_role",
    "agent_review_role_call",
    "agent_review_role_read",
)
RUNS = "aim_runs"
SHOWN = "review_shown_lists"


def _tables(conn) -> set[str]:
    return {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _pages_of(conn, doc: str, tables: set[str]) -> set[int]:
    pages = (
        {
            int(r[0])
            for r in conn.execute(
                "SELECT page_no FROM pages WHERE document_id = ?", (doc,)
            )
        }
        if "pages" in tables
        else set()
    )
    if "page_ocr" in tables:
        pages |= {
            int(r[0])
            for r in conn.execute(
                "SELECT page_no FROM page_ocr WHERE document_id = ?", (doc,)
            )
        }
    return pages


def _shown(conn, run_id: str, tables: set[str]) -> set[str] | None:
    if SHOWN not in tables:
        return None
    row = conn.execute(
        f"SELECT documents_json FROM {SHOWN} WHERE run_id = ?", (run_id,)
    ).fetchone()
    if row is None:
        return None
    try:
        got = json.loads(row[0])
    except ValueError:
        return set()
    return {str(d) for d in got} if isinstance(got, list) else set()


def ledger_problems(
    conn, run_id: str, ledger_lines: list[dict]
) -> tuple[list[str], int]:
    """(problems, record calls the ledger has no line for): every reservation of this run must match one record call (not refused
    before sending) with the same step and the same set of documents."""
    calls = {c["call_id"]: c for c in (dict(r) for r in conn.execute(f"SELECT * FROM {CALLS} WHERE run_id = ?", (run_id,)))
             if c["engine"] == "claude" and c["state"] in ("answered", "failed")}  # fmt: skip
    docs: dict[str, set[str]] = {}
    for r in conn.execute(
        f"SELECT call_id, document_id FROM {READS} WHERE run_id = ?", (run_id,)
    ):
        docs.setdefault(r[0], set()).add(str(r[1]))
    pool = Counter((c["step"], frozenset(docs.get(i, set()))) for i, c in calls.items())
    problems = []
    for line in ledger_lines:
        if str(line.get("run") or "") != run_id or not line.get("reserved"):
            continue
        key = (
            str(line.get("step") or ""),
            frozenset(
                str(d.get("document_id")) for d in line.get("sent_documents") or []
            ),
        )
        if pool[key] > 0:
            pool[key] -= 1
        else:
            problems.append(
                f"ledger: a {key[0]} call sent {len(key[1])} document(s) that no record call of that step declares"
            )
    return problems, sum(pool.values())


def read_ledger(path: Path) -> list[dict]:
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if isinstance(line, dict):
            out.append(line)
    return out


def check(conn, run_id: str) -> list[str]:
    """Every problem of the run's record, one plain line each (ids, numbers and codes only); [] when it holds."""
    tables = _tables(conn)
    if not {ROLES, CALLS, READS} <= tables:
        return ["no role record in this database (the record was off for every run)"]
    problems: list[str] = []
    roles = {
        int(r["role_no"]): dict(r)
        for r in conn.execute(f"SELECT * FROM {ROLES} WHERE run_id = ?", (run_id,))
    }
    if sorted(roles) != list(range(1, 10)):
        problems.append(
            f"role rows: {len(roles)}, roles {sorted(roles)} (nine are owed, 1 to 9)"
        )
    calls = [
        dict(r)
        for r in conn.execute(f"SELECT * FROM {CALLS} WHERE run_id = ?", (run_id,))
    ]
    reads = [
        dict(r)
        for r in conn.execute(f"SELECT * FROM {READS} WHERE run_id = ?", (run_id,))
    ]
    for c in calls:
        if c["state"] == "sent":
            problems.append(
                f"call {c['call_id'][:8]} ({c['step']}) is still 'sent': its end was never written"
            )
    engine_of = {c["call_id"]: c["engine"] for c in calls}
    paper = None
    if RUNS in tables:
        row = conn.execute(
            f"SELECT paper_document_id, calls_json FROM {RUNS} WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        paper = str(row[0]) if row else None
        stored = json.loads(row[1]) if row and row[1] else None
    else:
        stored = None
    held_pages: dict[str, set[int]] = {}
    shown = _shown(conn, run_id, tables)
    for r in reads:
        doc = str(r["document_id"])
        pages = json.loads(r["pages_json"] or "[]")
        if pages:
            have = held_pages.setdefault(doc, _pages_of(conn, doc, tables))
            off = sorted(int(p) for p in pages if int(p) not in have)
            if off:
                problems.append(
                    f"call {r['call_id'][:8]}: {len(off)} page(s) of document {doc} that it does not hold (pages {off[:5]})"
                )
        if (
            shown is not None
            and engine_of.get(r["call_id"]) == "claude"
            and doc != paper
            and doc not in shown
        ):
            problems.append(
                f"call {r['call_id'][:8]}: document {doc} read by a Claude call is not on the run's shown list"
            )
    if isinstance(stored, list):
        ok_by_step = Counter(
            str(c.get("step"))
            for c in stored
            if isinstance(c, dict) and c.get("ok", True)
        )
        answered_by_step = Counter(c["step"] for c in calls if c["state"] == "answered")
        for step, n in sorted(answered_by_step.items()):
            if ok_by_step.get(step, 0) != n:
                problems.append(
                    f"step {step}: {n} answered call(s) in the record, {ok_by_step.get(step, 0)} in the run's stored calls"
                )
    for n, role in sorted(roles.items()):
        mine = [c for c in calls if int(c["role_no"]) == n]
        if int(role["calls"] or 0) != len(mine) and role["engine"] != "code":
            problems.append(
                f"role {n}: {role['calls']} call(s) stored, {len(mine)} call row(s)"
            )
        produced = json.loads(role["produced_json"] or "{}")
        own = [r for r in reads if int(r["role_no"]) == n]
        recount = {
            "calls_answered": sum(1 for c in mine if c["state"] == "answered"),
            "paper_pages_sent": len(
                {
                    p
                    for r in own
                    if r["document_kind"] == "paper"
                    for p in json.loads(r["pages_json"] or "[]")
                }
            ),
            "page_pictures_sent": sum(int(r["pictures"] or 0) for r in own),
        }
        for key, value in recount.items():
            if key in produced and int(produced[key]) != value:
                problems.append(
                    f"role {n}: count {key} is {produced[key]}, its rows give {value}"
                )
    return problems


def _open(path: str):
    p = Path(path)
    if p.is_dir():
        p = p / "rag_intelligence.sqlite"
    conn = sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--db",
        required=True,
        help="a data folder or its rag_intelligence.sqlite (opened read-only)",
    )
    ap.add_argument("--run", required=True, help="the general review run id")
    ap.add_argument(
        "--ledger",
        help="the money ledger (claude_spend.jsonl); default: the data folder's own, when present",
    )
    a = ap.parse_args(argv)
    conn = _open(a.db)
    folder = Path(a.db) if Path(a.db).is_dir() else Path(a.db).parent
    ledger = Path(a.ledger) if a.ledger else folder / "claude_spend.jsonl"
    if {ROLES, CALLS, READS} <= _tables(conn):
        for r in conn.execute(f"SELECT role_no, role, state, why, engine, calls, usd FROM {ROLES} WHERE run_id = ? ORDER BY role_no",
                              (a.run,)):  # fmt: skip
            reads = conn.execute(f"SELECT count(*), count(DISTINCT document_id) FROM {READS} WHERE run_id = ? AND role_no = ?",
                                 (a.run, r["role_no"])).fetchone()  # fmt: skip
            print(f"{r['role_no']} {r['role']:16} {r['state']:10} {(r['engine'] or '-')!s:6} calls {r['calls']:3}"
                  f" reads {reads[0]:4} documents {reads[1]:3} usd {r['usd'] if r['usd'] is not None else '-'}"
                  f"{'  (' + r['why'] + ')' if r['why'] else ''}")  # fmt: skip
    problems = check(conn, a.run)
    if ledger.is_file() and {CALLS, READS} <= _tables(conn):
        more, unmatched = ledger_problems(conn, a.run, read_ledger(ledger))
        problems += more
        print(
            f"ledger: {ledger.name}; record calls answered from the stored answers (no ledger line): {unmatched}"
        )
    for p in problems:
        print("PROBLEM:", p)
    print("RECORD OK" if not problems else f"RECORD NOT OK: {len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
