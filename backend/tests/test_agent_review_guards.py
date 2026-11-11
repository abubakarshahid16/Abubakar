"""The guards that lived only in the experiment's runner (review R10, section 5), each with a test that fails without it.

Invented paper, rule book and model; the item builder, kind reader and classic selection are replaced as in the job tests."""

from __future__ import annotations

import json

import pytest

from app import (
    agent_claude,
    agent_review_gate,
    agent_review_jobs,
    agent_review_kind,
    db,
    nothing_read,
)
from app import agent_review_items as items_mod
from app import agent_review_request as request_mod
from app import agent_review_run as run_mod
from app import agent_review_verdict as V
from tests import agent_review_support as s
from tests.test_agent_review_job import lines_of, reading, run_job, start


@pytest.fixture
def w(tmp_path, monkeypatch):
    s.setup_world(tmp_path, monkeypatch)
    fake = s.FakeModel()
    state = {"fake": fake, "kind": reading(), "build_kwargs": None}
    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (state["fake"], s.ENV))
    monkeypatch.setattr(agent_review_kind, "decide", lambda *_a, **_k: state["kind"])
    monkeypatch.setattr(
        agent_review_jobs, "_scope_run_id", lambda _c, _s, run_id, *_a: run_id
    )
    monkeypatch.setattr(nothing_read, "read_phase", lambda *_a: None)
    state["doc"], state["cache"] = s.item_doc()

    def build(_conn, _paper, _kind, *, cache=None, **kw):
        state["build_kwargs"] = kw
        cache.update(state["cache"])
        return state["doc"]

    monkeypatch.setattr(items_mod, "build_items", build)
    with db.connect() as conn:
        s.label_rows(conn, [i["item_id"] for i in state["doc"]["items"]])
    return state


def run_review():
    run_id, job_id = start()
    run_job(job_id)
    return run_id


def run_row(run_id):
    return dict(
        db.connect()
        .execute("SELECT * FROM agent_review_run WHERE run_id = ?", (run_id,))
        .fetchone()
    )


def test_1_an_absent_answer_is_a_query_never_a_fail_and_buys_no_second_opinion(w):
    w["fake"].answers["R-mark"] = {
        **s.ANSWERS["R-mark"],
        "reason_code": "absent",
        "paper_quote": "",
        "pages_searched": [1],
    }
    lines = lines_of(run_review())
    assert (
        lines["R-mark"]["word"] == "AI thinks: not met"
    )  # the AI's opinion, shown as one, with the reason
    assert lines["R-mark"]["verdict_class"] == "AI opinion, engineer to confirm"
    assert "code cannot prove an absence" in lines["R-mark"]["reason"]
    assert (
        w["fake"].kinds.count("second") == 1
    )  # the Pass of R-coat only: an absent claim is never sent for a second opinion


def test_1_a_reason_code_that_does_not_fit_the_verdict_forces_a_query(w):
    w["fake"].answers["R-coat"] = {
        **s.ANSWERS["R-coat"],
        "reason_code": "not_met",
    }  # a Pass that says not_met
    line = lines_of(run_review())["R-coat"]
    assert (
        line["word"] != "Pass"
        and json.loads(line["line_json"])["reason_code"] == "verdict_and_reason_differ"
    )


def test_2_the_second_opinion_must_come_from_another_family_as_the_api_names_it(w):
    w["fake"] = s.FakeModel(
        second_model=s.FakeModel.LEAD
    )  # the "second" model names itself as the lead
    lines = lines_of(run_review())
    assert (
        lines["R-coat"]["word"] == "AI thinks: met"
        and lines["R-mark"]["word"] == "AI thinks: not met"
    )


def test_2_the_context_check_by_the_lead_family_holds_the_fail(w):
    w["fake"] = s.FakeModel(second_model=s.FakeModel.LEAD)
    line = json.loads(lines_of(run_review())["R-mark"]["line_json"])
    assert line["verdict"] != "Fail"


def test_4_a_conditional_rule_is_held_before_the_context_check_is_ever_bought(
    w, monkeypatch
):
    quote = "The marking shall be in red when the unit is installed outdoors."
    monkeypatch.setitem(s.RULES, "R-mark", (quote, "4.3", None, None, None, None))
    w["fake"].answers["R-mark"] = {**s.ANSWERS["R-mark"], "clause_quote": quote}
    w["doc"], w["cache"] = s.item_doc()
    run_id = run_review()
    line = json.loads(lines_of(run_id)["R-mark"]["line_json"])
    assert line["verdict"] != "Fail" and line["conditional_hold"] is True
    assert w["fake"].kinds.count("context") == 0


def test_4_a_proven_fail_is_checked_once_against_the_rule_book_page(w):
    run_review()
    assert (
        w["fake"].kinds.count("context") == 1
    )  # only the one Fail; a Pass is never sent to the context check


def test_5_the_deferral_guard_reads_every_page_of_the_paper_not_only_the_pages_sent(w):
    text = "Coating layers: By Contractor\nNotes invented"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages(document_id, page_no, text, char_count, batch_no) VALUES (?,2,?,?,0)",
            (s.PAPER, text, len(text)),
        )
    line = json.loads(
        lines_of(run_review())["R-coat"]["line_json"]
    )  # item page hint is page 1 only
    assert (
        line["verdict"] == "Query"
        and line["reason_code"] == "value_deferred"
        and line["deferred_page"] == 2
    )


def test_6_a_budget_stop_during_the_context_check_halts_the_run_and_writes_a_partial_run(
    w, monkeypatch
):
    real = run_mod.Runner.call

    def call(self, model, parts, max_tokens):
        if model == request_mod.FINAL_MODEL:
            raise agent_claude.AgentBudgetStop("usd_cap_reached")
        return real(self, model, parts, max_tokens)

    monkeypatch.setattr(run_mod.Runner, "call", call)
    run_id = run_review()
    row = run_row(run_id)
    assert row["partial"] == 1 and row["stop_reason"].startswith("usd_cap_reached")
    assert (
        json.loads(lines_of(run_id)["R-mark"]["line_json"])["verdict"] != "Fail"
    )  # held, never proven without the check


def test_7_the_run_is_refused_before_any_call_when_the_paper_has_no_stored_page(w):
    with db.connect() as conn:
        conn.execute("DELETE FROM pages WHERE document_id = ?", (s.PAPER,))
    run_id = run_review()
    assert run_row(run_id)["stop_reason"].startswith(
        "refused: the paper has no stored page text"
    )
    assert w["fake"].lead_asked == []


def test_7_the_run_is_refused_when_the_paper_kind_differs_from_the_kind_the_filter_used(
    w,
):
    w["doc"]["rule_labels"]["paper_kind"] = "procedure"
    run_id = run_review()
    assert (
        "differs from the kind" in run_row(run_id)["stop_reason"]
        and w["fake"].lead_asked == []
    )


def test_7_the_run_is_refused_when_an_item_list_fails_its_checks(w):
    w["doc"]["counts"] = {"skill": 0, "rule": 99}
    run_id = run_review()
    assert (
        "failed its checks" in run_row(run_id)["stop_reason"]
        and w["fake"].lead_asked == []
    )


def test_7_the_run_is_refused_when_a_rule_book_has_no_stored_pages(w):
    with db.connect() as conn:
        conn.execute("DELETE FROM pages WHERE document_id = ?", (s.STD,))
    run_id = run_review()
    assert (
        "no stored pages" in run_row(run_id)["stop_reason"]
        and w["fake"].lead_asked == []
    )


def test_7_the_run_is_refused_when_the_lead_and_the_second_model_are_one_family(
    w, monkeypatch
):
    monkeypatch.setattr(agent_claude, "SECOND_MODEL", agent_claude.LEAD_MODEL)
    run_id = run_review()
    assert (
        "same family" in run_row(run_id)["stop_reason"] and w["fake"].lead_asked == []
    )


def test_7_the_switch_turned_off_while_the_job_waits_sends_nothing_and_requeues_it(
    w, monkeypatch
):
    _run_id, job_id = start()
    monkeypatch.setattr(agent_review_gate.settings, "agent_review_enabled", False)
    assert run_job(job_id) == "queued"
    assert w["fake"].lead_asked == []
    assert (
        db.connect()
        .execute("SELECT state FROM jobs WHERE id = ?", (job_id,))
        .fetchone()["state"]
        == "queued"
    )


def test_9_the_papers_equipment_type_goes_to_the_rule_choice(w):
    w["kind"] = agent_review_kind.PaperReading(
        "datasheet",
        True,
        "read by code",
        "title",
        False,
        "invented_type",
        "classification",
    )
    run_review()
    assert w["build_kwargs"]["equipment_type"] == "invented_type"
    assert w["build_kwargs"]["equipment_filter"] == "type"


def test_the_silent_paper_rule_is_the_cores_at_the_exit_for_any_kind_but_a_datasheet():
    from app import agent_review_wording as W

    line = {
        "item_id": "R-1",
        "source": "rule",
        "verdict": "Query",
        "ai_verdict": "Fail",
        "reason_code": "sheet_silent",
        "reason_code_ai": "sheet_silent",
        "rule_label": {"tier": "AI approved"},
    }
    item = {"item_id": "R-1", "source": "rule", "rule_label": {"tier": "AI approved"}}
    look = lambda _i: "AI approved"  # noqa: E731
    for kind in ("procedure", "contract", None):
        assert (
            W.final_cap_all([line], {"R-1": item}, look, None, kind)[0]["verdict_label"]
            == "Query for the engineer"
        )
    assert (
        W.final_cap_all([line], {"R-1": item}, look, None, "datasheet")[0][
            "verdict_label"
        ]
        == "AI thinks: not met"
    )
    assert not hasattr(run_mod, "silence_guard") and not hasattr(
        request_mod, "silence_guard"
    )  # no local copy


def test_10_calls_allowed_is_asked_of_the_current_tier_before_every_extra_call(w):
    # one rule's label is withdrawn AFTER the item list was built (it still carries "AI approved"): no call is bought for it
    with db.connect() as conn:
        conn.execute("DROP TRIGGER IF EXISTS rule_label_no_delete")
        conn.execute("DELETE FROM rule_label WHERE rule_ref = 'req-R-mark'")
    run_review()
    assert (
        w["fake"].kinds.count("context") == 0 and w["fake"].kinds.count("second") == 1
    )  # coat only (frame is by code)
    assert V.RULE_NOT_APPROVED == "not_approved"


def test_the_claude_lane_gate_reads_the_settings_when_the_process_env_lacks_the_flags(
    monkeypatch,
):
    from app.config import settings

    for name in (
        "REASONING_PROVIDER",
        "STANDARDS_READER_ENABLED",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    assert (
        agent_claude.gate_open() is True
    )  # the app does not copy .env into os.environ
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    assert agent_claude.gate_open() is False
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setenv(
        "REASONING_PROVIDER", "ollama"
    )  # the environment wins when it says anything
    assert agent_claude.gate_open() is False
    assert (
        agent_claude.gate_open({"REASONING_PROVIDER": "claude"}) is True
    )  # an injected env is obeyed exactly
