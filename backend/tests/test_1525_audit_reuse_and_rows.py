# ruff: noqa: F811
"""#1525 order 4d: the audit's two gaps. Invented rows and answers only.

1. A stored AI answer reused is counted apart from a fresh call, per step, with
   the model: never a reused answer as a fresh call.
2. "Audit rows N; exported rows M; removed K: ..." for each copy of the CRS: the
   numbers sum, and M is what the workbook really prints.
"""

from __future__ import annotations

import io
import json

import pytest
from openpyxl import load_workbook

from app import (
    access,
    ai_call_ledger,
    ai_task_runner,
    applicability,
    applicability_reasoning,
    clause_review,
    crs_export,
    field_naming,
    review_audit,
    review_audit_rows,
)
from app.config import settings
from app.reasoning_provider import ProviderRefused, Response
from tests.test_1525_review_audit import (  # noqa: F401
    _files,
    _json,
    _review,
    _scope,
    audit_dir,
)
from tests.test_p3_review_jobs import temp_storage, world  # noqa: F401

SCHEMA = {
    "type": "object",
    "required": ["kind"],
    "properties": {"kind": {"type": "string"}},
}


class Fake:
    def __init__(self, *replies, model="invented-model"):
        self.requested_model = model
        self.replies = list(replies)
        self.asked = 0

    def reason(self, packet):
        self.asked += 1
        return Response(
            text=self.replies.pop(0),
            provider="ollama",
            model_tag=self.requested_model,
            digest="d",
            finish_reason="stop",
            prompt_sha256=packet.sha256,
        )


def _counts(ledger) -> dict:
    return {(r["step"], r["model"]): (r["fresh"], r["reused"]) for r in ledger}


# ---------------------------------------------------------- 1: the ledger


def test_with_no_ledger_open_a_note_is_nothing_and_no_ledger_exists():
    ai_call_ledger.fresh("step", "m")
    ai_call_ledger.reused("step", "m")
    assert ai_call_ledger.snapshot() is None


def test_reuse_or_ask_counts_the_stored_answer_apart_from_the_fresh_call(
    temp_storage, monkeypatch
):
    monkeypatch.setattr(ai_task_runner, "model_identity", lambda m: f"{m}@d|ollama/1")
    monkeypatch.setattr(settings, "ai_answer_reuse_enabled", True)
    asked = []

    def ask():
        asked.append(1)
        return '{"kind": "rule"}'

    with ai_call_ledger.open_ledger():
        for _ in range(3):
            ai_task_runner.reuse_or_ask("reader", "v1", "invented", None, "p", ask)
        got = _counts(ai_call_ledger.snapshot())
    assert len(asked) == 1
    assert got == {("reader", "invented"): (1, 2)}


def test_reuse_or_ask_with_reuse_off_or_no_identity_is_a_fresh_call(
    temp_storage, monkeypatch
):
    monkeypatch.setattr(ai_task_runner, "model_identity", lambda m: None)
    with ai_call_ledger.open_ledger():
        ai_task_runner.reuse_or_ask("reader", "v1", "invented", None, "p", lambda: "x")
        monkeypatch.setattr(settings, "ai_answer_reuse_enabled", False)
        ai_task_runner.reuse_or_ask("reader", "v1", "invented", None, "p", lambda: "x")
        got = _counts(ai_call_ledger.snapshot())
    assert got == {("reader", "invented"): (2, 0)}


def test_run_task_counts_each_attempt_fresh_and_a_cache_hit_reused(
    temp_storage, monkeypatch
):
    monkeypatch.setattr(settings, "ai_answer_reuse_enabled", True)
    spec = ai_task_runner.TaskSpec(
        name="t_invented", version="v1", instruction="Say the kind.", schema=SCHEMA
    )
    ai_task_runner.register(spec)
    provider = Fake("not json", '{"kind": "rule"}')  # one retry: two real calls
    with ai_call_ledger.open_ledger():
        first = ai_task_runner.run_task(spec, "a sentence", provider=provider)
        second = ai_task_runner.run_task(spec, "a sentence", provider=provider)
        got = _counts(ai_call_ledger.snapshot())
    assert first.state == "ok" and second.cached is True
    assert provider.asked == 2
    assert got == {("ai_task:t_invented", "invented-model"): (2, 1)}


def test_a_stored_scope_decision_is_reused_and_its_model_is_not_claimed(
    world, monkeypatch
):
    """The scope cache does not store which model answered: its reused row says
    so (None, "not recorded") rather than naming today's model."""
    decision = {
        "decision": "UNKNOWN",
        "basis": "invented",
        "quote": None,
        "page": None,
        "term": "pump",
    }
    monkeypatch.setattr(
        applicability_reasoning,
        "decide_with_confirmation_by_reasoning",
        lambda *a, **k: dict(decision),
    )
    with ai_call_ledger.open_ledger():
        for _ in range(2):
            applicability._cached_scope_decision(
                world["std"], "pump", {"standard": "x"}, Fake(), "scope-step"
            )
        got = _counts(ai_call_ledger.snapshot())
    assert got == {("scope-step", None): (0, 1)}


def test_a_scope_reasoning_call_is_fresh(monkeypatch):
    monkeypatch.setattr(applicability_reasoning, "packet", lambda *a, **k: _Pkt())
    monkeypatch.setattr(applicability_reasoning, "_usable", lambda r: None)
    with ai_call_ledger.open_ledger():
        applicability_reasoning.decide_by_reasoning(
            {"standard": "x"}, "pump", Fake("{}"), step="scope-step"
        )
        got = _counts(ai_call_ledger.snapshot())
    assert got == {("scope-step", "invented-model"): (1, 0)}


class _Pkt:
    sha256 = "s"


class Refuses(Fake):
    def reason(self, packet):
        self.asked += 1
        raise ProviderRefused("invented")


def test_a_refused_call_is_not_counted_fresh_on_any_counted_step(
    temp_storage, monkeypatch
):
    monkeypatch.setattr(ai_task_runner, "model_identity", lambda m: f"{m}@d|ollama/1")
    monkeypatch.setattr(settings, "ai_answer_reuse_enabled", True)
    monkeypatch.setattr(applicability_reasoning, "packet", lambda *a, **k: _Pkt())
    spec = ai_task_runner.TaskSpec(
        name="t_refused", version="v1", instruction="Say the kind.", schema=SCHEMA
    )
    ai_task_runner.register(spec)

    def refused():
        raise ProviderRefused("invented")

    with ai_call_ledger.open_ledger():
        for reuse_on in (True, False):
            monkeypatch.setattr(settings, "ai_answer_reuse_enabled", reuse_on)
            with pytest.raises(ProviderRefused):
                ai_task_runner.reuse_or_ask("reader", "v1", "m", None, "p", refused)
        monkeypatch.setattr(settings, "ai_answer_reuse_enabled", True)
        monkeypatch.setattr(ai_task_runner, "model_identity", lambda m: None)
        with pytest.raises(ProviderRefused):
            ai_task_runner.reuse_or_ask("reader", "v1", "m", None, "p", refused)
        assert (
            ai_task_runner.run_task(spec, "a sentence", provider=Refuses()).state
            != "ok"
        )
        with pytest.raises(ProviderRefused):
            applicability_reasoning.decide_by_reasoning(
                {"standard": "x"}, "pump", Refuses(), step="scope-step"
            )
        with pytest.raises(ProviderRefused):
            field_naming.name_items(
                field_naming.REQUIREMENT, [("r1", "A sentence")], ["Flow"], Refuses()
            )
        rows = ai_call_ledger.snapshot()
    assert {r["step"]: (r["fresh"], r["failed"]) for r in rows} == {
        "reader": (0, 3),
        "ai_task:t_refused": (0, 1),
        "scope-step": (0, 1),
        field_naming.NAMING_STEP: (0, 1),
    }


def test_a_timeout_is_counted_as_failed_not_lost_and_not_fresh(
    temp_storage, monkeypatch
):
    monkeypatch.setattr(ai_task_runner, "model_identity", lambda m: f"{m}@d|ollama/1")
    monkeypatch.setattr(settings, "ai_answer_reuse_enabled", True)

    def late():
        raise TimeoutError("invented")

    with ai_call_ledger.open_ledger():
        with pytest.raises(TimeoutError):
            ai_task_runner.reuse_or_ask("reader", "v1", "m", None, "p", late)
        rows = ai_call_ledger.snapshot()
    assert rows == [
        {"step": "reader", "model": "m", "fresh": 0, "reused": 0, "failed": 1}
    ]


def test_the_report_prints_failed_calls_on_their_own(world, audit_dir, monkeypatch):
    monkeypatch.setattr(settings, "review_audit_report_enabled", True)

    def invented_step(run_id, scope):
        ai_call_ledger.fresh("invented-step", "invented-model")
        with pytest.raises(TimeoutError):
            with ai_call_ledger.asking("invented-step", "invented-model"):
                raise TimeoutError("invented")

    monkeypatch.setattr(clause_review, "for_review", invented_step)
    _review(world)
    audit = _json(audit_dir)
    row = next(s for s in audit["ai_use"]["steps"] if s["name"] == "invented-step")
    assert (row["fresh"], row["failed"]) == (1, 1)
    assert audit["ai_use"]["totals"]["failed"] == 1
    assert audit["run"]["ai_calls_failed"] == 1
    md = next(f for f in _files(audit_dir) if f.suffix == ".md").read_text()
    assert "fresh calls 1; failed calls 1; reused answers 0" in md
    assert "failed calls: 1" in md.split("## 2. Pages")[0]
    assert "refused or failed call is not fresh" in review_audit.AI_BOUNDARY


def test_the_run_line_prints_the_boundary_and_names_the_steps_left_out(
    world, audit_dir, monkeypatch
):
    monkeypatch.setattr(settings, "review_audit_report_enabled", True)
    _review(world)
    md = next(f for f in _files(audit_dir) if f.suffix == ".md").read_text()
    run_part = md.split("## 2. Pages")[0]
    line = run_part.split("- AI calls made (fresh):")[1]
    assert review_audit.AI_BOUNDARY in line
    for step in ("rule_eval", "statement_roles", "field_vocabulary"):
        assert step in review_audit.AI_BOUNDARY


def test_stored_field_names_are_reused_per_item_and_new_ones_fresh(temp_storage):
    items = [("r1", "The set pressure is 10 barg"), ("r2", "The flow is 5 m3/h")]
    reply = json.dumps(
        [
            {"i": 0, "field_name": None, "quote": None},
            {"i": 1, "field_name": None, "quote": None},
        ]
    )
    provider = Fake(reply)
    with ai_call_ledger.open_ledger():
        field_naming.name_items(field_naming.REQUIREMENT, items, ["Flow"], provider)
        field_naming.name_items(field_naming.REQUIREMENT, items, ["Flow"], provider)
        got = _counts(ai_call_ledger.snapshot())
    assert provider.asked == 1
    assert got == {
        (field_naming.NAMING_STEP, "invented-model"): (2, 0),
        (field_naming.NAMING_STEP, None): (0, 2),
    }


# ----------------------------------------------- 1: what the report says


def _run(status: dict) -> dict:
    return {"id": "r", "ai_check_status": json.dumps(status)}


def test_the_clause_review_cache_is_reused_not_called_in_the_report():
    run = _run(
        {
            "ran": True,
            "calls_made": 4,
            "model": "check-model",
            clause_review.STATUS_KEY: {
                "ran": True,
                "calls": 2,
                "cache_hits": 5,
                "model": "clause-model",
            },
        }
    )
    ai = review_audit._ai_section(run, {}, ledger=[])
    steps = {s["name"]: s for s in ai["steps"]}
    assert steps["clause_review"]["fresh"] == 2
    assert steps["clause_review"]["reused"] == 5
    assert steps["clause_review"]["model"] == "clause-model"
    assert steps["ai_engineering_check"]["fresh"] == 4
    assert steps["ai_engineering_check"]["reused"] == 0  # this step keeps no answers
    assert ai["totals"]["fresh"] == 6 and ai["totals"]["reused"] == 5


def test_a_clause_review_status_from_before_the_count_is_not_recorded_not_zero():
    run = _run({"ran": True, clause_review.STATUS_KEY: {"ran": True}})
    step = next(
        s
        for s in review_audit._ai_section(run, {}, ledger=[])["steps"]
        if s["name"] == "clause_review"
    )
    assert step["fresh"] is None and step["reused"] is None


def test_the_ledger_rows_join_the_report_and_no_ledger_is_not_recorded():
    ledger = [{"step": "reader", "model": "m", "fresh": 1, "reused": 3, "failed": 0}]
    ai = review_audit._ai_section(
        _run({"ran": True, "calls_made": 1}), {}, ledger=ledger
    )
    row = next(s for s in ai["steps"] if s["name"] == "reader")
    assert (row["fresh"], row["reused"], row["model"]) == (1, 3, "m")
    assert ai["totals"]["fresh"] == 2 and ai["totals"]["reused"] == 3

    alone = review_audit._ai_section(_run({"ran": True}), {}, ledger=None)
    unknown = alone["steps"][-1]
    assert unknown["state"] == review_audit.NOT_RECORDED
    assert unknown["fresh"] is None and unknown["reused"] is None


def test_the_wording_step_is_listed_only_when_it_was_on():
    run = _run({"ran": True})
    on = {"enabled": True, "tried": 3, "model": "ollama:w"}
    steps = review_audit._ai_section(run, {}, ledger=[], wording=on)["steps"]
    row = next(s for s in steps if s["name"] == "crs_wording")
    assert (row["fresh"], row["reused"], row["model"]) == (3, 0, "ollama:w")
    off = {"enabled": False, "tried": 0, "model": None}
    steps = review_audit._ai_section(run, {}, ledger=[], wording=off)["steps"]
    assert all(s["name"] != "crs_wording" for s in steps)


def test_a_review_job_opens_the_ledger_and_the_report_carries_it(
    world, audit_dir, monkeypatch
):
    monkeypatch.setattr(settings, "review_audit_report_enabled", True)

    def invented_step(run_id, scope):
        ai_call_ledger.fresh("invented-step", "invented-model")
        ai_call_ledger.reused("invented-step", "invented-model", 2)

    monkeypatch.setattr(clause_review, "for_review", invented_step)
    _review(world)
    audit = _json(audit_dir)
    row = next(s for s in audit["ai_use"]["steps"] if s["name"] == "invented-step")
    assert (row["fresh"], row["reused"]) == (1, 2)
    assert audit["run"]["ai_calls_made"] == audit["ai_use"]["totals"]["fresh"]
    assert audit["run"]["ai_answers_reused"] == audit["ai_use"]["totals"]["reused"] == 2
    assert "invented-model" in audit["run"]["models_used"]
    md = next(f for f in _files(audit_dir) if f.suffix == ".md").read_text()
    assert (
        "invented-step" in md
        and "fresh calls 1; failed calls 0; reused answers 2" in md
    )
    assert ai_call_ledger.snapshot() is None  # closed with the job


def test_with_the_switch_off_the_job_opens_no_ledger(world, audit_dir, monkeypatch):
    seen = []
    monkeypatch.setattr(
        clause_review,
        "for_review",
        lambda run_id, scope: seen.append(ai_call_ledger.snapshot()),
    )
    _review(world)
    assert seen == [None]
    assert _files(audit_dir) == []


# ---------------------------------------------------------- 2: the rows


def _row(n, section="p.1", clause="C-1", comment=None, **extra):
    return {
        "finding_id": f"f{n}",
        "document_name": "invented.pdf",
        "page_section": section,
        "standard_reference": clause,
        "comment": f"comment {n}" if comment is None else comment,
        "comment_by": "machine",
        "row_kind": "datasheet_check",
        **extra,
    }


#: Six rows: 2 and 3 repeat row 1's key (merged), one has no comment (dropped);
#: one more with its own key; an engineer's tick, never merged.
ROWS = [
    _row(1),
    _row(2),
    _row(3),
    _row(4, clause="C-2", comment=""),
    _row(5, clause="C-3"),
    _row(6, clause="C-4", row_kind="safety_tick", engineer_confirmed=True),
]


def _sheet_rows(rows, meta) -> int:
    """The data rows the real workbook prints."""
    wb = load_workbook(io.BytesIO(crs_export.build_crs(rows, meta)))
    ws = wb.worksheets[0]
    return sum(
        1
        for r in range(crs_export.COLUMN_HEADER_ROW + 1, ws.max_row + 1)
        if ws.cell(r, 4).value
    )


def _meta(copy, on):
    return {"copy": copy, "review_run_id": "r", "export_quality": on}


def test_the_internal_copy_reconciles_and_equals_the_workbook():
    meta = _meta("internal", True)
    got = review_audit_rows.crs_reconciliation(ROWS, meta)
    assert got["audit_rows"] == 6
    assert got["exported_rows"] == 3 == _sheet_rows(ROWS, meta)
    assert got["removed"] == {"duplicates_merged": 2, "empty_dropped": 1}
    assert got["removed_total"] == 3
    assert got["adds_up"] is True
    assert (
        got["line"]
        == "audit rows 6; exported rows 3; removed 3: duplicates merged 2, empty dropped 1"
    )


def test_with_the_quality_switch_off_nothing_is_removed():
    got = review_audit_rows.crs_reconciliation(ROWS, _meta("internal", False))
    assert got["audit_rows"] == got["exported_rows"] == 6
    assert got["removed_total"] == 0 and got["adds_up"] is True


def test_the_issue_copy_names_every_row_it_holds_back():
    rows = [
        _row(1, engineer_confirmed=True),
        _row(2, engineer_confirmed=True),  # the same key: merged
        _row(3, clause="C-2"),  # no engineer: a draft
        _row(4, clause="C-3", row_kind="safety_tick", engineer_confirmed=True),
        _row(5, clause="C-4", row_kind="safety_tick"),  # unconfirmed: counted once
        _row(6, clause="C-5", comment="", engineer_confirmed=True),  # no text
    ]
    meta = _meta("issue", True)
    got = review_audit_rows.crs_reconciliation(rows, meta)
    assert got["removed"] == {
        "duplicates_merged": 1,
        "empty_dropped": 0,
        "not_engineer_confirmed": 2,
        "safety_ticks": 1,
        "withheld_no_text": 1,
    }
    assert got["exported_rows"] == 1 == _sheet_rows(rows, meta)
    assert got["adds_up"] is True


def test_rows_that_do_not_sum_say_so_never_a_quiet_fudge(monkeypatch):
    real = crs_export.build_crs_view

    def loses_a_row(rows, meta):
        view = real(rows, meta)
        view["rows"] = view["rows"][:-1]
        return view

    monkeypatch.setattr(crs_export, "build_crs_view", loses_a_row)
    got = review_audit_rows.crs_reconciliation(ROWS, _meta("internal", True))
    assert got["adds_up"] is False
    assert "DOES NOT ADD UP" in got["line"]


def test_the_report_gives_both_copies_with_their_boundary(
    world, audit_dir, monkeypatch
):
    from app import main

    run_id = _review(world)
    monkeypatch.setattr(settings, "crs_export_quality_enabled", True)
    monkeypatch.setattr(
        main,
        "_crs_content",
        lambda rid, scope, copy="internal": (
            [dict(r) for r in ROWS],
            {"copy": copy, "review_run_id": rid},
            "invented.pdf",
            "2026-11-02",
        ),
    )
    audit = review_audit.build(run_id, _scope(world))
    crs = audit["crs"]
    assert crs["rows_composed"] == 6
    assert crs["rows_exported"] == 3
    assert crs["rows_dropped"] == {"duplicates_merged": 2, "empty_dropped": 1}
    assert crs["reconciliation"]["internal"]["adds_up"] is True
    assert crs["reconciliation"]["issue"]["adds_up"] is True
    assert "before" in crs["rows_boundary"] and "findings" in crs["rows_boundary"]
    md = review_audit.render_markdown(audit)
    assert (
        "internal copy: audit rows 6; exported rows 3; removed 3: duplicates merged 2, "
        "empty dropped 1" in md
    )
    assert "issue copy: audit rows 6" in md
    assert crs["rows_boundary"] in md
    assert "rows dropped (empty, duplicate): not recorded" not in md


def test_a_crs_that_cannot_be_composed_is_not_recorded_never_zero(
    world, audit_dir, monkeypatch
):
    from app import main

    run_id = _review(world)

    def boom(*a, **k):
        raise RuntimeError("invented")

    monkeypatch.setattr(main, "_crs_content", boom)
    crs = review_audit.build(run_id, _scope(world))["crs"]
    assert crs["rows_exported"] is None and crs["rows_composed"] is None
    assert crs["reconciliation"] == {"internal": None, "issue": None}
    assert crs["failed"] is True


def test_the_reconciliation_reads_under_the_callers_scope(
    world, audit_dir, monkeypatch
):
    from app import main

    run_id = _review(world)
    seen = []
    real = main._crs_content

    def spy(rid, scope, copy="internal"):
        seen.append((copy, scope.allowed_document_ids))
        return real(rid, scope, copy)

    monkeypatch.setattr(main, "_crs_content", spy)
    scope = access.AccessScope(user_id=None, allowed_document_ids=world["scope"])
    review_audit.build(run_id, scope)
    assert {c for c, _ in seen} >= {"internal", "issue"}
    assert all(ids == world["scope"] for _, ids in seen)


@pytest.mark.parametrize("copy", ["internal", "issue"])
def test_a_real_run_reconciles_on_both_copies(world, audit_dir, monkeypatch, copy):
    run_id = _review(world)
    monkeypatch.setattr(settings, "crs_export_quality_enabled", True)
    part = review_audit.build(run_id, _scope(world))["crs"]["reconciliation"][copy]
    assert part["adds_up"] is True
    assert part["audit_rows"] == part["exported_rows"] + part["removed_total"]
