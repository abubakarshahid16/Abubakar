#!/usr/bin/env python
"""Rehearsal check (live-update helper): can an AI review START on this copy? No model is loaded, nothing is sent, the live file is never touched.

    python scripts/check_review_can_start.py --db <copy>/rag_intelligence.sqlite --paper <document id>

WHY. On 15 Nov 2026 the live AI review that follows a Local-only rule check was refused in one second with 0 lines (a stored empty "shown"
list was read as "no rule book may be used"). This check runs the real start path and the AI job's real planning on a CLONE, in seconds.

IT DOES, on the clone only (it writes the rules file and the queue rows there):
  1. queues a Local-only start of the paper (`review_engine_start.start(..., "local", shown_document_ids=())`: it only queues) and asserts that the start
     stored NO shown list (a start that sends nothing has no list to restrict);
  2. marks that rule check done, runs the follow-up (`review_engine_start.follow_up`) and asserts an AI run was queued, barred from Claude;
  3. runs the AI job's planning (`agent_review_jobs._plan`) for it and asserts the plan is NOT a refusal and holds items (> 0);
  4. plans the same run as a CLAUDE run holding an empty list and asserts it sends nothing (no item cites a rule book) and is not a refusal.
The scope is the one the real job reads (`agent_review_jobs.reusable_scope_run`: the newest finished rule check with stored scope decisions); with none the check says CANNOT CHECK (exit 2). It prints which paper, run and counts it used.
Exit 0 when every check passed, 1 when any failed, 2 when it refused to run (a live-shaped path, a live checkout, a .env beside the code).
Prints ids and counts only, never a document text.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))


class Refused(Exception):
    pass


class CannotCheck(Refused):
    """The copy cannot be checked as it stands (not a failure of the AI review): exit 2."""


def _refuse_live(db_path: Path) -> None:
    from app import live_guard

    live = (Path.home() / "project" / "Abubakar").resolve()
    rp = db_path.resolve()
    if rp == live or live in rp.parents or live_guard.is_live_shaped(rp):
        raise Refused(
            "the database is the live one or live-shaped: make a clone with scripts/backup_db.py and give that"
        )
    if (BACKEND / ".env").exists():
        raise Refused(
            "a backend/.env sits beside this code and would be read by the settings: run from a worktree without one"
        )


def check(db_path: Path, paper: str) -> list[str]:
    """The problems found (empty = the AI review can start). Ids and counts only."""
    from app import agent_review_jobs as jobs
    from app import (
        agent_review_kind,
        claude_auto_approve,
        db,
        review_engine,
        review_engine_start,
        review_shown,
    )
    from app import agent_review_local as local_mod
    from app.config import settings

    db_path = Path(db_path)
    _refuse_live(db_path)
    settings.data_dir, settings.db_path = db_path.parent, db_path
    settings.claude_spend_log = (
        db_path.parent / "claude_spend.jsonl"
    )  # the clone's own ledger: never the live one
    settings.claude_cache_dir = db_path.parent / "claude_cache"
    settings.agent_review_enabled = settings.agent_review_local_engine_enabled = True
    settings.reasoning_provider, settings.standards_reader_enabled = "ollama", False
    settings.standards_reader_allow_public_egress, settings.anthropic_api_key = (
        False,
        "",
    )
    db.reset_connection()
    conn = db.connect()
    bad: list[str] = []
    scope = frozenset(r[0] for r in conn.execute("SELECT id FROM documents"))
    if paper not in scope:
        return [f"paper {paper} is not in the copy"]
    from app import agent_review_gate

    active = conn.execute(
        f"SELECT 1 FROM review_runs WHERE submittal_document_id = ? AND status IN ({','.join('?' * len(jobs.ACTIVE_RUN))}) LIMIT 1",
        (paper, *jobs.ACTIVE_RUN),
    ).fetchone()
    if active is not None:
        raise CannotCheck("copy has an active review of this paper")
    kind = agent_review_kind.decide(paper, scope)
    if not (kind.known and agent_review_gate.rules_kind_enabled(kind.kind)):
        raise CannotCheck("kind not enabled for the AI reviewer")
    # The scope the real job would read: the very function the job uses (a finished rule check of the paper, same code version,
    # with stored scope decisions). An AI run holds none, so a newer AI run never stands in for the rule check (update 10, 15 Nov).
    scope_run = jobs.reusable_scope_run(conn, paper)
    if scope_run is None:
        raise CannotCheck(
            "the copy holds no finished rule check of this paper with stored scope decisions for this code version"
            " (the real job would run the book selection with a model, which this check never does)"
        )
    decisions = conn.execute(
        "SELECT COUNT(*) FROM review_scope_decisions WHERE review_run_id = ?",
        (scope_run,),
    ).fetchone()[0]
    books = conn.execute(
        "SELECT COUNT(*) FROM review_applicable_standards WHERE review_run_id = ? AND included = 1",
        (scope_run,),
    ).fetchone()[0]
    print(
        f"paper {paper}: the plan reads the scope of rule-check run {scope_run} ({decisions} scope decisions, {books} selected books)"
    )
    who = conn.execute(
        "SELECT created_by FROM jobs WHERE document_id = ? AND created_by IS NOT NULL ORDER BY updated_at DESC LIMIT 1",
        (paper,),
    ).fetchone()
    user = (
        who["created_by"] if who else None
    )  # the person whose access the AI job reads (the newest requester of this paper)
    try:
        run_id, plan = review_engine_start.start(
            paper, scope, user, "local", shown_document_ids=()
        )
    except Exception as exc:  # noqa: BLE001 - reported as a problem, by type
        return [f"the Local-only start was refused: {type(exc).__name__}"]
    if plan.get("text_leaves"):
        bad.append("the Local-only plan says text leaves")
    if review_shown.shown_ids(conn, run_id) is not None:
        bad.append(
            "the Local-only start stored a shown list (an empty list reads as 'no book may be used')"
        )
    job = conn.execute(
        "SELECT id FROM jobs WHERE review_run_id = ?", (run_id,)
    ).fetchone()
    with conn:
        conn.execute("UPDATE jobs SET state = 'done' WHERE id = ?", (job["id"],))
        conn.execute(
            "UPDATE review_runs SET status = 'completed' WHERE id = ?", (run_id,)
        )
    ai_run = review_engine_start.follow_up(job["id"], "done")
    if not ai_run:
        note = (review_engine.stored(conn, run_id) or {}).get("followed_by")
        return [
            *bad,
            f"no AI run was queued after the rule check ({note or 'no note'})",
        ]
    stored = review_engine.stored(conn, ai_run) or {}
    if not stored.get("bar_claude"):
        bad.append("the AI run is not barred from Claude")
    claude_auto_approve.on_review_start = lambda *_a: None
    got = jobs._plan(conn, ai_run, paper, scope, kind, lambda: None)
    if str(got.get("stop") or "").startswith("refused"):
        bad.append(f"the AI review would be refused: {got['stop']}")
    rules = sum(1 for i in got["items"] if i.get("standard_document_id"))
    print(
        f"the Local-only AI plan holds {len(got['items'])} items ({rules} cite a rule book, {len(got['items']) - rules} do not)"
    )
    if not got["items"]:
        bad.append(
            f"the AI review plan holds no item (scope read from run {scope_run}: {decisions} decisions, {books} selected books)"
        )
    # the same run as a Claude run that holds an empty list: nothing is sent, and no false refusal
    with conn:
        review_shown.record_in(conn, ai_run, [], "rehearsal")
    local_mod.local_run = lambda _r: False
    sent = jobs._plan(conn, ai_run, paper, scope, kind, lambda: None)
    if str(sent.get("stop") or "").startswith("refused"):
        bad.append(f"a Claude plan with an empty list is refused: {sent['stop']}")
    if any(i.get("standard_document_id") for i in sent["items"]):
        bad.append(
            "a Claude plan with an empty list still holds items that cite a rule book"
        )
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--db",
        required=True,
        help="the CLONE's rag_intelligence.sqlite (never the live file)",
    )
    ap.add_argument("--paper", required=True, help="the document id of the paper")
    a = ap.parse_args(argv)
    try:
        problems = check(Path(a.db), a.paper)
    except CannotCheck as exc:
        print(f"CANNOT CHECK: {exc}")
        return 2
    except Refused as exc:
        print(f"REFUSED: {exc}")
        return 2
    for p in problems:
        print(f"FAIL: {p}")
    if not problems:
        print(
            "OK: a Local-only start queues, its AI review plans items and is not refused; a Claude plan with an empty list sends nothing"
        )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
