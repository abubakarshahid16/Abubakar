# ruff: noqa: F811
"""scripts/check_review_can_start.py: the rehearsal check that would have caught the live fault of 15 Nov 2026 (the AI review of a Local-only
start refused at the start). Clone only; no model; no request; exit 1 on failure, 2 when it refuses to run."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app import (
    agent_review_jobs,
    agent_review_kind,
    claude_auto_approve,
    claude_spend,
    db,
    reader_transport,
    review_shown,
)
from app import agent_review_local as local_mod
from app.config import settings
from tests import agent_review_support as s
from tests.test_p3_review_jobs import _enqueue, temp_storage, world  # noqa: F401 - fixtures

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_review_can_start.py"


def _script():
    spec = importlib.util.spec_from_file_location("check_review_can_start", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _copy_world(world, monkeypatch, *, items_ok=True):
    """A copy with a completed classic review of the paper; the item builder is replaced (it reads rule books the invented world lacks)."""
    from app import scope_ledger

    scope_ledger.ensure_schema()
    run_id, _j = _enqueue(world)
    with db.connect() as c:
        c.execute("UPDATE review_runs SET status = 'completed' WHERE id = ?", (run_id,))
        c.execute(  # the rule check's stored scope: the plan reads it the way the real job does
            "INSERT INTO review_scope_decisions(review_run_id, requirement_id, state, reason_code, reason, decided_by, created_at)"
            " VALUES (?, 'r1', 'applies', 'x', 'x', 't', '2026-11-15')",
            (run_id,),
        )
        s.add_document(
            c, s.STD, "std.pdf", s.STD_PAGE
        )  # the rule book the items cite, with its pages
        c.execute("DELETE FROM pages WHERE document_id = ?", (world["sub"],))
        c.execute(
            "INSERT INTO pages(document_id, page_no, text, char_count, batch_no) VALUES (?,1,?,?,0)",
            (world["sub"], s.PAPER_PAGE, len(s.PAPER_PAGE)),
        )
    kind = agent_review_kind.PaperReading(
        "datasheet", True, "r", "t", False, None, None
    )
    monkeypatch.setattr(agent_review_kind, "decide", lambda *_a, **_k: kind)
    doc, cache = s.item_doc()
    doc["items"] = doc["items"] if items_ok else []
    doc["counts"] = {"skill": 0, "rule": len(doc["items"])}

    def build(_c, _p, _k, *_a, cache=None, shown=None, **_kw):
        cache.update({k: dict(v) for k, v in _cache.items()})
        out = json.loads(json.dumps(doc))
        if shown is not None:
            out["items"] = [
                i for i in out["items"] if i["standard_document_id"] in shown
            ]
            out["counts"] = {"skill": 0, "rule": len(out["items"])}
        return out

    _cache = cache
    monkeypatch.setattr(agent_review_jobs.items_mod, "build_items_for_run", build)
    monkeypatch.setattr(agent_review_jobs, "_write_rules", lambda *_a: None)
    # the script replaces these module attributes; the monkeypatch restores them at the end of the test
    monkeypatch.setattr(
        agent_review_jobs, "_scope_run_id", agent_review_jobs._scope_run_id
    )
    monkeypatch.setattr(
        claude_auto_approve, "on_review_start", claude_auto_approve.on_review_start
    )
    monkeypatch.setattr(local_mod, "local_run", local_mod.local_run)
    monkeypatch.setattr(
        reader_transport,
        "transport",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("a request was made")),
    )
    return Path(settings.db_path)


def test_the_check_passes_on_a_copy_where_the_local_start_plans_items_and_nothing_is_sent(
    world, monkeypatch, capsys
):
    path = _copy_world(world, monkeypatch)
    mod = _script()
    assert mod.check(path, world["sub"]) == []
    assert (
        mod.main(["--db", str(path), "--paper", "no_such_doc"]) == 1
    )  # a paper the copy does not hold is a failure, not a crash
    assert claude_spend.entries() == []


def test_the_check_fails_when_the_ai_review_plan_holds_no_item(world, monkeypatch):
    path = _copy_world(world, monkeypatch, items_ok=False)
    problems = _script().check(path, world["sub"])
    assert any("plan holds no item" in p for p in problems)


def test_the_check_fails_on_the_live_fault_a_start_that_stores_an_empty_list_for_a_local_run(
    world, monkeypatch
):
    path = _copy_world(world, monkeypatch)
    from app import review_engine_start

    old_start = review_engine_start.start

    def buggy_start(
        *a, **k
    ):  # the round-13 start: it wrote the empty list for a run that sends nothing
        run_id, plan = old_start(*a, **k)
        with db.connect() as c:
            review_shown.record_in(c, run_id, [], "t")
        return run_id, plan

    monkeypatch.setattr(review_engine_start, "start", buggy_start)
    problems = _script().check(path, world["sub"])
    assert any("stored a shown list" in p for p in problems)


def test_the_check_refuses_a_live_path_with_exit_2_and_touches_nothing(
    tmp_path, capsys
):
    mod = _script()
    live = (
        Path.home()
        / "project"
        / "Abubakar"
        / "backend"
        / "data"
        / "rag_intelligence.sqlite"
    )
    assert mod.main(["--db", str(live), "--paper", "doc_x"]) == 2
    assert "REFUSED" in capsys.readouterr().out
    shaped = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    assert mod.main(["--db", str(shaped), "--paper", "doc_x"]) in (
        1,
        2,
    )  # never reads a file that does not exist as a copy


def test_a_copy_with_an_active_review_of_the_paper_cannot_be_checked_exit_2_not_a_failure(
    world, monkeypatch, capsys
):
    path = _copy_world(world, monkeypatch)
    with db.connect() as c:
        c.execute("DELETE FROM jobs")
    _enqueue(world)  # a queued review of the paper on the copy
    code = _script().main(["--db", str(path), "--paper", world["sub"]])
    out = capsys.readouterr().out
    assert (
        code == 2
        and "copy has an active review of this paper" in out
        and "FAIL" not in out
    )


def test_a_paper_of_a_kind_the_ai_reviewer_is_not_enabled_for_cannot_be_checked_exit_2_not_a_false_no_item_failure(
    world, monkeypatch, capsys
):
    path = _copy_world(world, monkeypatch)
    drawing = agent_review_kind.PaperReading(
        "drawing", True, "r", "t", False, None, None
    )
    monkeypatch.setattr(agent_review_kind, "decide", lambda *_a, **_k: drawing)
    code = _script().main(["--db", str(path), "--paper", world["sub"]])
    out = capsys.readouterr().out
    assert (
        code == 2
        and "kind not enabled for the AI reviewer" in out
        and "plan holds no item" not in out
        and "FAIL" not in out
    )


def test_a_newer_ai_run_holding_no_scope_does_not_stand_in_for_the_rule_check_update_10_stop(
    world, monkeypatch, capsys
):
    """15 Nov 2026: the paper's newest completed run was an AI run (no scope decisions); the check planned from it and failed 'no item'."""
    path = _copy_world(world, monkeypatch)
    with db.connect() as c:
        rule_check = c.execute("SELECT id FROM review_runs").fetchone()["id"]
        c.execute(
            "INSERT INTO review_runs(id, submittal_document_id, status, started_at, created_at, updated_at)"
            " SELECT 'ai_newer', submittal_document_id, 'completed', '2099-01-01T00:00:00Z', '2099-01-01T00:00:00Z', '2099-01-01T00:00:00Z' FROM review_runs WHERE id = ?",
            (rule_check,),
        )
    assert _script().main(["--db", str(path), "--paper", world["sub"]]) == 0
    out = capsys.readouterr().out
    assert f"rule-check run {rule_check}" in out and "ai_newer" not in out


def test_a_copy_with_no_rule_check_holding_a_scope_cannot_be_checked_exit_2(
    world, monkeypatch, capsys
):
    path = _copy_world(world, monkeypatch)
    with db.connect() as c:
        c.execute("DELETE FROM review_scope_decisions")
    code = _script().main(["--db", str(path), "--paper", world["sub"]])
    out = capsys.readouterr().out
    assert code == 2 and "no finished rule check" in out and "FAIL" not in out


def test_several_finished_rule_checks_with_scope_decisions_the_newest_wins(
    world, monkeypatch
):
    from app import scope_ledger

    _copy_world(
        world, monkeypatch
    )  # one finished rule check with a scope decision already
    scope_ledger.ensure_schema()
    ids = []
    for _ in range(2):
        with db.connect() as c:
            c.execute("UPDATE jobs SET state = 'done'")
            c.execute("UPDATE review_runs SET status = 'completed'")
        run_id, _j = _enqueue(world)
        ids.append(run_id)
    with db.connect() as c:
        c.execute("UPDATE review_runs SET status = 'completed'")
        allr = [r["id"] for r in c.execute("SELECT id FROM review_runs")]
        for n, rid in enumerate(
            allr
        ):  # created_at rises with n; every run holds a scope decision
            c.execute(
                "UPDATE review_runs SET created_at = ? WHERE id = ?",
                (f"2026-11-1{n}T00:00:00Z", rid),
            )
            c.execute(
                "INSERT OR IGNORE INTO review_scope_decisions(review_run_id, requirement_id, state, reason_code, reason, decided_by, created_at)"
                " VALUES (?, 'r1', 'applies', 'x', 'x', 't', '2026-11-15')",
                (rid,),
            )
        c.execute("UPDATE jobs SET state = 'done'")
        assert len(allr) >= 3
        c.commit()
        got = agent_review_jobs.reusable_scope_run(c, world["sub"])
    assert got == allr[-1]
