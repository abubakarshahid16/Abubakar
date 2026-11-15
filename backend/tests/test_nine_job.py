# ruff: noqa: RUF059
"""B5: the nine-role job's order, failures, resume and the one branch. Fake roles and a fake record (no model, no network)."""

from __future__ import annotations

import sys
import types

import pytest

from app import agent_review_dispatch, db, nine_job
from app.config import settings
from tests.test_b1_review_points import world_with_both
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    monkeypatch.setattr(settings, "review_page_v2_enabled", True)


class FakeRecord:
    def __init__(self):
        self.rows: dict[tuple[str, int], dict] = {}
        self.began: list = []

    def ensure_schema(self):
        pass

    def begin_run(self, run_id):
        self.began.append(run_id)
        for n in range(1, 10):
            self.rows.setdefault(
                (run_id, n), {"state": "not_run", "why": "not reached"}
            )

    def role_state(self, run_id, n):
        return (
            self.rows.get((run_id, n), {}).get("state")
            if self.rows.get((run_id, n), {}).get("done")
            else None
        )

    def role_started(self, run_id, n):
        pass

    def role_finished(self, run_id, n, **kw):
        self.rows[(run_id, n)] = {**kw, "done": True}


def ctx_args(items=("a", "b")):
    asked = []
    plan = {"items": [{"item_id": i} for i in items]}
    return (
        "run1",
        "doc1",
        object(),
        plan,
        {},
        lambda *a: asked.append([i["item_id"] for i in a[3]["items"]]),
    ), asked


def fakes(calls, over=None):
    def make(n):
        def run(ctx):
            calls.append(n)
            return nine_job.RoleResult("ran", engine="code", produced={"n": n})

        return run

    return {**{n: make(n) for n in range(1, 10)}, **(over or {})}


def test_nine_rows_at_the_start_all_not_reached_and_the_roles_run_in_order():
    rec, calls = FakeRecord(), []
    args, asked = ctx_args()
    nine_job.run_roles(*args, record=rec, roles=fakes(calls))
    assert rec.began == ["run1"] and calls == list(range(1, 10))
    assert sorted(n for (_r, n) in rec.rows) == list(range(1, 10)) and all(
        r["state"] == "ran" for r in rec.rows.values()
    )


def test_a_failing_role_is_recorded_by_type_and_the_run_goes_on():
    rec, calls = FakeRecord(), []

    def boom(ctx):
        raise ValueError("secret text that must not be stored")

    args, _ = ctx_args()
    nine_job.run_roles(*args, record=rec, roles=fakes(calls, {2: boom}))
    row = rec.rows[("run1", 2)]
    assert (
        row["state"] == "not_run"
        and row["why"] == "failed (ValueError)"
        and "secret" not in str(row)
    )
    assert calls == [1, 3, 4, 5, 6, 7, 8, 9]


def test_when_the_reviewer_fails_the_checklist_asks_every_item():
    rec = FakeRecord()
    args, asked = ctx_args(("a", "b", "c"))

    def reviewer(ctx):
        ctx.store["findings"] = [types.SimpleNamespace(origin="reviewer")]
        raise RuntimeError("down")

    roles = {
        n: (lambda ctx: nine_job.RoleResult("ran", engine="code"))
        for n in (1, 2, 3, 6, 7, 8, 9)
    }
    nine_job.run_roles(
        *args, record=rec, roles={**roles, 4: reviewer, 5: nine_job.checklist_role}
    )
    assert (
        asked == [["a", "b", "c"]]
        and rec.rows[("run1", 4)]["why"] == "failed (RuntimeError)"
    )
    assert args[3]["items"] and len(args[3]["items"]) == 3  # the plan is restored


def test_a_reviewer_that_found_nothing_means_the_checklist_asks_everything():
    rec = FakeRecord()
    args, asked = ctx_args(("a", "b"))
    roles = {
        n: (lambda ctx: nine_job.RoleResult("ran", engine="code"))
        for n in (1, 2, 3, 4, 6, 7, 8, 9)
    }
    nine_job.run_roles(*args, record=rec, roles={**roles, 5: nine_job.checklist_role})
    assert asked == [["a", "b"]]


def test_resume_does_not_run_or_pay_a_role_that_ran_again():
    rec, calls = FakeRecord(), []
    args, _ = ctx_args()
    nine_job.run_roles(*args, record=rec, roles=fakes(calls))
    assert calls == list(range(1, 10))
    nine_job.run_roles(*args, record=rec, roles=fakes(calls))
    assert calls == list(range(1, 10))  # nothing ran a second time
    rec.rows[("run1", 4)] = {"state": "not_run", "why": "failed (X)", "done": True}
    nine_job.run_roles(*args, record=rec, roles=fakes(calls))
    assert calls[9:] == [4]  # only the role that did not run is tried again


def test_a_role_that_did_not_fully_run_always_carries_a_reason():
    rec = FakeRecord()
    args, _ = ctx_args()
    roles = fakes([], {3: lambda ctx: nine_job.RoleResult("ran_partly")})
    nine_job.run_roles(*args, record=rec, roles=roles)
    assert rec.rows[("run1", 3)]["why"] == "no reason recorded"


def test_a_cancellation_is_never_swallowed():
    class Stop(Exception):
        pass

    def stop(ctx):
        raise Stop

    args, _ = ctx_args()
    with pytest.raises(Stop):
        nine_job.run_roles(
            *args, record=FakeRecord(), roles=fakes([], {4: stop}), reraise=(Stop,)
        )


def test_the_writer_role_reuses_the_one_sheet_and_the_completeness_check():
    doc, rc, ai, client = world_with_both()
    ctx = nine_job.RoleContext(ai, doc, None, {}, {}, lambda *a: None)
    got = nine_job.writer_role(ctx)
    assert (
        got.state == "ran_partly"
        and got.produced["points"] == got.produced["database_lines"] == 4
    )
    assert "worded by code" in got.why
    stored = (
        db.connect()
        .execute("SELECT ok FROM crs_completeness WHERE run_id = ?", (ai,))
        .fetchone()
    )
    assert stored["ok"] == 1


def test_code_role_counts_lines_by_class_only():
    doc, rc, ai, client = world_with_both()
    got = nine_job.code_role(
        nine_job.RoleContext(ai, doc, None, {}, {}, lambda *a: None)
    )
    assert (
        got.engine == "code"
        and got.produced["lines"] == 3
        and sum(got.produced["by_class"].values()) == 3
    )


# ------------------------------------------------------------------------------------------------ the one branch


def test_switch_off_asks_exactly_as_today_and_never_imports_the_nine_job(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_nine_roles_enabled", False)
    monkeypatch.delitem(sys.modules, "app.nine_job", raising=False)
    got = []
    plan = {"items": [{"item_id": "a"}]}
    agent_review_dispatch.run("r", "d", "k", plan, {"h": 1}, lambda *a: got.append(a))
    assert (
        got == [("r", "d", "k", plan, {"h": 1})] and "app.nine_job" not in sys.modules
    )
    got.clear()
    agent_review_dispatch.run(
        "r", "d", "k", {"items": []}, {}, lambda *a: got.append(a)
    )
    assert got == []  # no items: today's code did not ask either
    tables = {
        r[0]
        for r in db.connect().execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'agent_review_role%'"
        )
    }
    assert tables == set()


def test_switch_on_hands_the_job_to_the_nine_roles(monkeypatch):
    monkeypatch.setattr(settings, "agent_review_nine_roles_enabled", True)
    seen = []
    monkeypatch.setattr(nine_job, "run_roles", lambda *a, **k: seen.append((a, k)))
    agent_review_dispatch.run(
        "r", "d", "k", {"items": []}, {}, lambda *a: None, reraise=(KeyError,)
    )
    assert seen and seen[0][1] == {"reraise": (KeyError,)}


def test_execute_with_the_switch_off_calls_the_old_ask_with_the_same_arguments(
    monkeypatch,
):
    """The hook in `_execute`: switch off, the review asks exactly as before and no nine-role table is made."""
    from app import agent_review_jobs as jobs

    monkeypatch.setattr(settings, "agent_review_nine_roles_enabled", False)
    seen = []
    monkeypatch.setattr(jobs, "_write_missing", lambda *a: None)
    monkeypatch.setattr(jobs.calculator_run, "step_job", lambda *a: None)
    monkeypatch.setattr(jobs, "_tier_lookup", lambda k: None)
    monkeypatch.setattr(jobs, "_ask", lambda *a: seen.append(a))
    monkeypatch.setattr(jobs.rule_choice, "store_group_lines", lambda *a, **k: [])
    monkeypatch.setattr(jobs, "_finish", lambda *a: {"done": True})
    plan = {"items": [{"item_id": "a"}], "block": {}}
    assert jobs._execute("r1", "d1", "kind", plan, "t0") == {"done": True}
    assert (
        len(seen) == 1
        and seen[0][:4] == ("r1", "d1", "kind", plan)
        and seen[0][4] == {}
    )
    assert (
        not db.connect()
        .execute("SELECT name FROM sqlite_master WHERE name LIKE 'agent_review_role%'")
        .fetchall()
    )


# ------------------------------------------------------------------------------------------------ R69: failure, cancellation, resume


def test_the_checklist_restores_the_whole_plan_even_when_the_batch_path_raises():
    items = [{"item_id": "R-1"}, {"item_id": "R-2"}]
    plan = {"items": list(items)}

    def boom(*a):
        raise RuntimeError("transient")

    ctx = nine_job.RoleContext("run1", "doc1", object(), plan, {}, boom)
    with pytest.raises(RuntimeError):
        nine_job.checklist_role(ctx)
    assert plan["items"] == items  # `_finish` and the CRS read the whole list


def test_an_error_in_todays_path_roles_is_raised_as_today_and_only_the_new_roles_are_recorded_failed():
    for n in (5, 6, 7, 8):
        rec = FakeRecord()
        args, _ = ctx_args()

        def boom(ctx):
            raise TimeoutError("transient")

        with pytest.raises(TimeoutError):
            nine_job.run_roles(
                *args, record=rec, roles=fakes([], {n: boom}), should_stop=lambda: False
            )
        assert (
            rec.rows.get(("run1", n), {}).get("state") != "ran"
        )  # not recorded as finished: the retry runs it again
    for n in (1, 2, 3, 4, 9):
        rec = FakeRecord()
        args, _ = ctx_args()

        def boom(ctx):
            raise TimeoutError("transient")

        nine_job.run_roles(
            *args, record=rec, roles=fakes([], {n: boom}), should_stop=lambda: False
        )
        assert rec.rows[("run1", n)]["why"] == "failed (TimeoutError)"


def test_a_cancellation_stops_the_job_before_the_next_role_and_before_a_paid_call():
    class Stop(Exception):
        pass

    calls, flag = [], {"stop": False}

    def role_two(ctx):
        calls.append(2)
        flag["stop"] = True  # the engineer cancels while role 2 runs
        return nine_job.RoleResult("ran", engine="code")

    def make(n):
        return lambda ctx: calls.append(n) or nine_job.RoleResult("ran", engine="code")

    roles = {n: make(n) for n in range(1, 10)} | {2: role_two}
    args, _ = ctx_args()
    with pytest.raises(Stop):
        nine_job.run_roles(
            *args,
            record=FakeRecord(),
            roles=roles,
            reraise=(Stop,),
            should_stop=lambda: flag["stop"],
        )
    assert calls == [1, 2]  # role 3 was never started
    ctx = nine_job.RoleContext(
        "r",
        "d",
        None,
        {},
        {},
        lambda *a: None,
        should_stop=lambda: True,
        cancel_exc=Stop,
    )
    with pytest.raises(Stop):
        nine_job._guarded_ask(ctx)(
            "r", 4, [], ("t", {})
        )  # no paid call is made after a cancel


def test_a_restart_that_skips_a_role_that_ran_hands_over_what_it_made(monkeypatch):
    """Role 3 ran and handed over its chosen chapters; after a crash between roles 3 and 4 the restart skips role 3 and role 4 still gets them."""
    from tests.test_b1_review_points import world_with_both

    doc, rc, ai, client = world_with_both()
    ctx = nine_job.RoleContext(ai, doc, None, {}, {}, lambda *a: None)
    nine_job._handover_save(ai, "chosen", [["doc_book", "5.1"]])
    nine_job._handover_save(
        ai,
        "context_blocks",
        [
            {
                "name": "ctx_a",
                "sources": [doc],
                "kinds": None,
                "items": [["standard", "x"]],
            }
        ],
    )
    rec = FakeRecord()
    rec.rows[(ai, 2)] = {"state": "ran", "done": True}
    rec.rows[(ai, 3)] = {"state": "ran", "done": True}
    nine_job._execute_role(2, ctx, lambda c: 1 / 0, rec, ())
    nine_job._execute_role(
        3, ctx, lambda c: 1 / 0, rec, ()
    )  # skipped: the role function is never called
    assert (
        ctx.store["chosen"] == [("doc_book", "5.1")]
        and ctx.store["context_blocks"][0].name == "ctx_a"
    )
