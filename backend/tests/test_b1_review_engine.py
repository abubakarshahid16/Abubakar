# ruff: noqa: F811, C408
"""ONE Review button: Automatic, Claude, Local only (owner decision, 12 Nov 2026, #1584 comment 6820183348).

Synthetic documents only. The resolver is pure; the bar, the approvals, the header and the routes are checked end to end with a fake
Claude transport that records every call.
"""

from __future__ import annotations

import itertools
import json

import pytest
from fastapi.testclient import TestClient

from app import (
    agent_claude,
    agent_review_gate,
    classification,
    claude_approved,
    claude_auto_approve,
    claude_spend,
    contract_yes,
    crs_ai_header,
    crs_layout,
    db,
    local_engine_bar,
    model_transport,
    reader_transport,
    review_engine,
    review_engine_start,
    review_jobs,
)
from app import reasoning_provider as rp
from app.config import settings
from app.main import app
from tests.test_p3_review_jobs import (  # noqa: F401 - fixtures
    _enqueue,
    temp_storage,
    world,
)

E = review_engine
F = review_engine.Facts
W = "worker-b1"


def open_facts(**kw) -> F:
    """Every door open for a datasheet; a test closes one."""
    base = dict(
        kind="datasheet", agent_enabled=True, provider="per_task", agent_engine_claude=True,
        step_engine_claude=True, lane_open=True, blocked=False, paper_approved=True, is_contract=False,
        contract_yes=False, scored_allowed=True, kind_scored=True, caps_ok=True, books_ok=True,
    )  # fmt: skip
    base.update(kw)
    return F(**base)


# --------------------------------------------------------------------------------------------- the resolver table


def test_automatic_uses_claude_when_every_door_is_open():
    plan = E.decide("automatic", open_facts())
    assert plan.part(E.AI_REVIEW).engine == E.ON_CLAUDE
    assert plan.part(E.RULE_CHECK).engine == E.ON_CLAUDE and plan.text_leaves


def test_local_only_runs_the_rule_check_and_says_the_ai_review_needs_claude():
    plan = E.decide("local", open_facts())
    assert plan.part(E.RULE_CHECK).engine == E.ON_LOCAL
    ai = plan.part(E.AI_REVIEW)
    assert ai.engine == E.NOT_RUN
    assert (
        ai.why
        == "The AI review needs Claude and will not run; the rule check runs on this computer"
    )
    assert not plan.text_leaves and plan.refused is None


@pytest.mark.parametrize(
    "closed, words, rule_check",
    [
        (dict(agent_enabled=False), "switched off", E.ON_CLAUDE),
        (dict(kind=None), "not known", E.ON_CLAUDE),
        (
            dict(kind="drawing", kind_scored=True),
            "does not take a drawing",
            E.ON_CLAUDE,
        ),
        (dict(provider="ollama"), "not switched on", E.ON_LOCAL),
        (dict(agent_engine_claude=False), "not switched on", E.ON_CLAUDE),
        (dict(lane_open=False), "connection to Claude is closed", E.ON_LOCAL),
        (dict(blocked=True), "blocked", E.ON_LOCAL),
        (dict(paper_approved=False), "not approved", E.ON_LOCAL),
        (dict(books_ok=False), "rule books", E.ON_CLAUDE),
        (dict(scored_allowed=False, kind_scored=False), "not been scored", E.ON_LOCAL),
        (dict(caps_ok=False), "cap", E.ON_LOCAL),
    ],
)
def test_automatic_falls_back_to_local_with_one_plain_sentence(
    closed, words, rule_check
):
    plan = E.decide("automatic", open_facts(**closed))
    assert plan.refused is None
    ai = plan.part(E.AI_REVIEW)
    assert ai.engine == E.NOT_RUN and words in ai.why
    # the rule check follows its OWN switches: it stays on Claude where only an AI-review door is shut
    assert plan.part(E.RULE_CHECK).engine == rule_check and plan.part(E.RULE_CHECK).why


def test_claude_is_refused_never_silently_local():
    plan = E.decide("claude", open_facts(lane_open=False))
    assert plan.refused and "Claude cannot be used" in plan.refused
    assert plan.runs == []  # nothing runs, on any engine


def test_claude_with_the_ai_review_closed_but_rule_check_steps_open_runs_and_says_so():
    plan = E.decide("claude", open_facts(kind="drawing", kind_scored=True))
    assert plan.refused is None
    assert plan.part(E.RULE_CHECK).engine == E.ON_CLAUDE
    assert plan.part(E.AI_REVIEW).engine == E.NOT_RUN and plan.part(E.AI_REVIEW).why


def test_a_contract_needs_the_owners_yes_on_claude_and_nothing_on_local():
    f = open_facts(kind="contract", is_contract=True, contract_yes=False)
    local = E.decide("local", f)
    assert local.refused is None and local.part(E.RULE_CHECK).engine == E.ON_LOCAL
    refused = E.decide("claude", f)
    assert refused.refused and E.NEEDS_YES in refused.refused and refused.needs_yes
    auto = E.decide("automatic", f)
    assert auto.part(E.AI_REVIEW).why == E.NEEDS_YES and not auto.text_leaves
    yes = E.decide(
        "claude", open_facts(kind="contract", is_contract=True, contract_yes=True)
    )
    assert yes.refused is None and yes.text_leaves


def test_a_contract_says_its_checklists_are_empty():
    plan = E.decide("automatic", open_facts(kind="contract", is_contract=True))
    assert {w["part"] for w in plan.wont_run} == {
        "contract checklist",
        "calculation checklist",
    }
    assert all("empty" in w["why"] for w in plan.wont_run)
    assert E.decide("automatic", open_facts()).wont_run == []


def test_an_unscored_kind_is_not_offered_unless_the_setting_says_so():
    f = open_facts(kind="procedure", kind_scored=False, scored_allowed=False)
    plan = E.decide("automatic", f)
    assert plan.unscored and plan.part(E.AI_REVIEW).engine == E.NOT_RUN
    assert agent_review_gate.UNSCORED_WORDS in plan.part(E.AI_REVIEW).why
    on = E.decide(
        "automatic",
        open_facts(kind="procedure", kind_scored=False, scored_allowed=True),
    )
    assert on.unscored and on.part(E.AI_REVIEW).engine == E.ON_CLAUDE


def test_a_bad_choice_is_refused():
    with pytest.raises(ValueError):
        E.decide("both", open_facts())


def test_every_choice_by_every_kind_table():
    """The resolver table of the PR: rows are choices, columns are kinds, all doors open."""
    got = {}
    for choice in E.CHOICES:
        for kind in (
            "datasheet",
            "procedure",
            "contract",
            "drawing",
            "test_record",
            "other",
            None,
        ):
            scored = kind in agent_review_gate.SCORED_KINDS
            plan = E.decide(
                choice,
                open_facts(
                    kind=kind, is_contract=kind == "contract", contract_yes=kind == "contract",
                    kind_scored=scored, scored_allowed=scored,
                ),
            )  # fmt: skip
            got[(choice, kind)] = (
                plan.refused is not None,
                plan.part(E.RULE_CHECK).engine,
                plan.part(E.AI_REVIEW).engine,
            )
    assert got[("automatic", "datasheet")] == (False, E.ON_CLAUDE, E.ON_CLAUDE)
    assert got[("local", "datasheet")] == (False, E.ON_LOCAL, E.NOT_RUN)
    for kind in ("procedure", "contract", "drawing", "test_record", "other", None):
        assert got[("local", kind)] == (False, E.ON_LOCAL, E.NOT_RUN)
        assert got[("automatic", kind)] == (
            False,
            E.ON_LOCAL,
            E.NOT_RUN,
        )  # unscored: nothing goes out
        assert (
            got[("claude", kind)][0] is True
        )  # Claude asked for, nothing may go: refused


# --------------------------------------------------------------------------------------------- the brute force

KINDS = ("datasheet", "procedure", "contract", "drawing", "other", None)
BOOLS = (False, True)


def _all_facts():
    for kind, provider, agent, steps, lane, blocked, approved, yes, scored_ok, caps, books, enabled in itertools.product(
        KINDS, ("ollama", "claude", "per_task", "weird"), BOOLS, BOOLS, BOOLS, BOOLS, BOOLS, BOOLS, BOOLS, BOOLS, BOOLS, BOOLS
    ):  # fmt: skip
        yield F(
            kind=kind, kind_scored=kind in agent_review_gate.SCORED_KINDS, agent_enabled=enabled, provider=provider,
            agent_engine_claude=agent, step_engine_claude=steps, lane_open=lane, blocked=blocked, paper_approved=approved,
            is_contract=kind == "contract", contract_yes=yes, scored_allowed=scored_ok, caps_ok=caps, books_ok=books,
        )  # fmt: skip


def _allowed_to_leave(f: F) -> bool:
    """The rules of CLAUDE.md rule 1 and the owner's decision, written again from the outside."""
    if not (f.provider == "claude" or f.provider == "per_task"):
        return False
    if not (
        f.lane_open
        and not f.blocked
        and f.paper_approved
        and f.scored_allowed
        and f.caps_ok
    ):
        return False
    if f.is_contract and not f.contract_yes:
        return False
    return True


def test_brute_force_no_combination_sends_text_out_when_the_answer_says_it_would_not():
    seen = 0
    for f in _all_facts():
        for choice in E.CHOICES:
            plan = E.decide(choice, f)
            seen += 1
            if choice == E.LOCAL:
                assert not plan.text_leaves and all(
                    p.engine != E.ON_CLAUDE for p in plan.parts
                )
            if (
                plan.text_leaves
            ):  # an answer that says text leaves must be one the rules allow
                assert _allowed_to_leave(f), (choice, f)
                assert choice != E.LOCAL
            for p in plan.parts:  # a part is on Claude only through the lane its own installed switch opens
                if p.engine == E.ON_CLAUDE and p.name == E.AI_REVIEW:
                    assert f.provider == "claude" or (
                        f.provider == "per_task" and f.agent_engine_claude
                    )
                    assert f.agent_enabled and f.kind in (
                        "datasheet",
                        "procedure",
                        "contract",
                    )
                if p.engine == E.ON_CLAUDE and p.name == E.RULE_CHECK:
                    assert f.provider == "claude" or (
                        f.provider == "per_task" and f.step_engine_claude
                    )
            if choice == E.AUTOMATIC:
                assert (
                    plan.refused is None
                )  # Automatic never refuses: it falls back, with a reason
                assert all(p.why for p in plan.parts)
            if choice == E.CLAUDE:
                assert (
                    plan.refused is not None or plan.text_leaves
                )  # never a silent local run
            if plan.refused:
                assert plan.runs == []
            if f.is_contract and not f.contract_yes:
                assert (
                    not plan.text_leaves
                )  # a contract never goes without the owner's yes
    assert seen == len(KINDS) * 4 * 2**10 * 3


# --------------------------------------------------------------------------------------------- the bar (enforcement)


@pytest.fixture
def lane(tmp_path, monkeypatch):
    """The Claude lane open and the list not enforced: only the run's plan can keep text in."""
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-invented")
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", settings.data_dir / tmp_path.name)
    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    monkeypatch.setattr(settings, "datasheet_ai_reader", "claude")
    monkeypatch.setattr(settings, "agent_review_engine", "claude")
    monkeypatch.setattr(settings, "review_ai_check_enabled", True)
    monkeypatch.setattr(settings, "crs_ai_wording_enabled", True)
    monkeypatch.setattr(settings, "crs_ai_wording_engine", "claude")
    monkeypatch.setattr(settings, "clause_review_enabled", True)
    for name in (
        "STANDARDS_READER_ENABLED",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_the_bar_closes_every_door_the_lane_has(lane):
    assert rp.claude_unavailable_for_task("claude")[0] is None  # open before
    assert agent_claude.gate_open({"REASONING_PROVIDER": "claude"}) is True
    with E.barring():
        assert rp.claude_unavailable_for_task("claude")[0] == rp.UNAVAILABLE_RUN_LOCAL
        assert rp.claude_unavailable()[0] is not None
        assert rp.claude_lane_open() is False
        assert agent_claude.gate_open({"REASONING_PROVIDER": "claude"}) is False
        assert agent_claude.gate_open() is False
        assert claude_approved.refusal()[0] == E.BARRED_CODE
        assert (
            local_engine_bar.is_claude_lane_run(False) is False
        )  # no Claude lane: no bar on the local engine either
        with claude_approved.carrying(()):
            with pytest.raises(claude_spend.DocumentNotApproved) as caught:
                claude_spend.reserve("t", 0.01, model="claude-sonnet-5")
        assert caught.value.code == E.BARRED_CODE
    assert (
        rp.claude_unavailable_for_task("claude")[0] is None
    )  # the bar is per run: gone after


def _fake_claude():
    def send(url, *, headers, body, timeout):
        send.calls.append(body["model"])
        return {
            "model": body["model"], "stop_reason": "end_turn",
            "content": [{"type": "text", "text": '{"comment": "Noise level exceeds the limit."}'}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }  # fmt: skip

    send.calls = []
    return send


@pytest.fixture
def no_local_engine(monkeypatch):
    """A local engine that is simply not there: a step that falls back to it fails fast instead of loading a model."""

    def gone(*a, **k):
        raise model_transport.LocalEngineNotLoaded("test: no local engine")

    for name in ("post_json", "post_json_retrying", "stream_json", "get_json"):
        monkeypatch.setattr(model_transport, name, gone)


def _run_started(world, choice):
    run_id, plan = review_engine_start.start(
        world["sub"], world["scope"], "adm", choice
    )
    review_jobs.claim_next(W)
    job = (
        db.connect()
        .execute("SELECT id FROM jobs WHERE review_run_id = ?", (run_id,))
        .fetchone()["id"]
    )
    return run_id, plan, review_jobs.run(job, W)


def test_local_only_reaches_reader_transport_zero_times_with_the_lane_wide_open(
    world, lane, no_local_engine
):
    fake = _fake_claude()
    lane.setattr(reader_transport, "transport", lambda: fake)
    lane.setattr(
        reader_transport,
        "stream",
        lambda *a, **k: pytest.fail("a call reached reader_transport"),
    )
    run_id, plan, state = _run_started(world, "local")
    assert state == "done"
    assert fake.calls == [], "Local only sent something to Claude"
    assert plan["text_leaves"] is False and plan["choice"] == "local"
    assert [
        r["step"]
        for r in claude_spend.entries()
        if r.get("run") == run_id and not r.get("refused")
    ] == []


def test_a_plan_on_claude_is_not_barred_and_does_call_claude(
    world, lane, no_local_engine
):
    """The bar follows the plan, never more: with the approvals met the same run does reach Claude (the test above is not vacuous)."""
    fake = _fake_claude()
    lane.setattr(reader_transport, "transport", lambda: fake)
    run_id, plan, state = _run_started(world, "automatic")
    assert plan["parts"][0]["engine"] == "claude", plan["parts"][0]
    assert state == "done"
    assert fake.calls, (
        "a plan that said Claude never reached Claude: the Local-only test above proves nothing"
    )
    stored = review_engine.stored(db.connect(), run_id)
    assert stored["bar_claude"] == 0


def test_automatic_with_an_unapproved_paper_is_kept_local_and_barred(
    world, lane, no_local_engine
):
    lane.setattr(settings, "claude_approved_list_enforced", True)
    lane.setattr(settings, "claude_auto_approve_reviews_enabled", False)
    fake = _fake_claude()
    lane.setattr(reader_transport, "transport", lambda: fake)
    run_id, plan, state = _run_started(world, "automatic")
    assert plan["text_leaves"] is False and "not approved" in plan["parts"][0]["why"]
    assert state == "done" and fake.calls == []
    assert review_engine.stored(db.connect(), run_id)["bar_claude"] == 1


def test_the_old_start_has_no_stored_choice_and_is_not_barred(world, lane):
    _run_id, job_id = _enqueue(world)
    assert review_engine.bar_for_job(db.connect(), job_id) is False


# --------------------------------------------------------------------------------------------- the routes


def _rows(table):
    try:
        return db.connect().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except Exception:  # noqa: BLE001
        return None


def test_the_pre_start_route_has_no_side_effect_and_makes_no_call(
    world, lane, monkeypatch
):
    monkeypatch.setattr(reader_transport, "transport", lambda: pytest.fail("a call"))
    monkeypatch.setattr(
        model_transport,
        "post_json_retrying",
        lambda *a, **k: pytest.fail("a local call"),
    )
    before = {
        t: _rows(t)
        for t in ("review_runs", "jobs", "audit_events", "review_engine_choice")
    }
    ledger = claude_spend.entries()
    client = TestClient(app)
    for choice in ("automatic", "claude", "local"):
        r = client.get(
            "/api/reviews/plan",
            params={"submittal_document_id": world["sub"], "engine": choice},
            headers=world["admin"],
        )
        assert r.status_code == 200, r.text
        got = r.json()
        assert got["choice"] == choice and got["sentence"] and "exact" in got["cost"]
        if choice == "local":
            assert got["text_leaves"] is False and got["cost"]["at_most_usd"] is None
            assert "needs Claude and will not run" in got["sentence"]
    after = {t: _rows(t) for t in before}
    assert after == before and claude_spend.entries() == ledger


def test_the_plan_names_documents_cost_and_what_will_not_run(world, lane):
    lane.setattr(settings, "claude_approved_list_enforced", False)
    got = (
        TestClient(app)
        .get(
            "/api/reviews/plan",
            params={"submittal_document_id": world["sub"], "engine": "automatic"},
            headers=world["admin"],
        )
        .json()
    )
    assert got["text_leaves"] is True and got["documents"]["paper"] is True
    assert got["cost"]["at_most_usd"] == float(settings.claude_budget_usd_per_run)
    assert got["cost"]["exact"] is False and got["cost"]["last_review_usd"] is None
    ai = next(p for p in got["parts"] if p["name"] == "ai_review")
    assert (
        ai["engine"] == "not_run" and ai["why"]
    )  # the paper's kind is not known: said, not hidden


def test_the_plan_of_a_paper_the_caller_cannot_read_is_a_404(world, lane):
    r = TestClient(app).get(
        "/api/reviews/plan",
        params={"submittal_document_id": "nope", "engine": "local"},
        headers=world["admin"],
    )
    assert r.status_code == 404


def test_start_refuses_claude_with_a_plain_sentence_and_queues_nothing(
    world, monkeypatch
):
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    before = _rows("review_runs")
    r = TestClient(app).post(
        "/api/reviews/start",
        json={"submittal_document_id": world["sub"], "engine": "claude"},
        headers=world["admin"],
    )
    assert r.status_code == 409
    assert (
        "Claude cannot be used" in json.dumps(r.json())
        and _rows("review_runs") == before
    )


def test_start_local_queues_the_rule_check_and_stores_the_choice(world, monkeypatch):
    monkeypatch.setattr(settings, "reasoning_provider", "ollama")
    r = TestClient(app).post(
        "/api/reviews/start",
        json={"submittal_document_id": world["sub"], "engine": "local"},
        headers=world["admin"],
    )
    assert r.status_code == 200, r.text
    stored = review_engine.stored(db.connect(), r.json()["review_run_id"])
    assert (
        stored["choice"] == "local"
        and stored["bar_claude"] == 1
        and stored["then_ai"] == 0
    )


def test_start_needs_an_admin(world, monkeypatch):
    r = TestClient(app).post(
        "/api/reviews/start",
        json={"submittal_document_id": world["sub"], "engine": "local"},
    )
    assert r.status_code in (401, 404)


def test_the_ai_review_follows_the_rule_check_and_is_checked_again(
    world, lane, monkeypatch
):
    run_id, _job = _enqueue(world)
    plan = {"choice": "automatic", "project_document_ids": [], "fresh": False}
    review_engine.record(
        db.connect(),
        run_id,
        plan,
        "adm",
        then_ai=True,
        bar_claude=False,
        now="2026-11-12T00:00:00Z",
    )
    job_id = (
        db.connect()
        .execute("SELECT id FROM jobs WHERE review_run_id = ?", (run_id,))
        .fetchone()["id"]
    )
    ai_plan = {"choice": "automatic", "refused": None, "kind": "datasheet",
               "parts": [{"name": "rule_check", "engine": "local", "why": "x"},
                         {"name": "ai_review", "engine": "claude", "why": "y"}]}  # fmt: skip
    queued = []
    monkeypatch.setattr(review_engine, "plan_for", lambda *a, **k: ai_plan)
    monkeypatch.setattr(review_engine_start.agent_review_gate, "enabled", lambda: True)
    monkeypatch.setattr(
        review_engine_start.agent_review_jobs,
        "enqueue",
        lambda doc, **k: queued.append((doc, k)) or ("ai-run", "ai-job"),
    )
    assert (
        review_engine_start.follow_up(job_id, "running") is None and not queued
    )  # only after a finished rule check
    assert review_engine_start.follow_up(job_id, "done") == "ai-run"
    assert queued[0][0] == world["sub"] and queued[0][1]["requested_by"] == "adm"
    assert review_engine.stored(db.connect(), run_id)["followed_by"] == "ai-run"
    assert review_engine_start.follow_up(job_id, "done") is None  # once only
    # a plan that no longer holds starts nothing and says why
    run2 = "run-2"
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET status='complete' WHERE id = ?", (run_id,))
    run_b, job_b = _enqueue(world)
    review_engine.record(
        db.connect(),
        run_b,
        plan,
        "adm",
        then_ai=True,
        bar_claude=False,
        now="2026-11-12T00:00:00Z",
    )
    ai_plan["parts"][1] = {
        "name": "ai_review",
        "engine": "not_run",
        "why": "the spending cap leaves no room today",
    }
    queued.clear()
    assert review_engine_start.follow_up(job_b, "done") is None and not queued
    assert "spending cap" in review_engine.stored(db.connect(), run_b)["followed_by"]
    assert run2


# --------------------------------------------------------------------------------------------- the approvals


def _doc(doc_id, sha, role=None, filename=None):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES (?,?,?,1,?,'ready',1,?)",
            (
                doc_id,
                filename or f"{doc_id}.pdf",
                sha,
                f"{doc_id}.pdf",
                "2026-11-12T00:00:00Z",
            ),
        )
    if role:
        classification.set_role(doc_id, role)
    return doc_id


@pytest.fixture
def approvals(world, monkeypatch):
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    monkeypatch.setattr(settings, "claude_auto_approve_reviews_enabled", True)
    monkeypatch.setattr(settings, "claude_spend_log", settings.data_dir / "spend.jsonl")
    return world


def _approved(sha) -> bool:
    return sha in claude_approved.approved_hashes()


def test_a_specification_for_review_is_approved_for_claude(approvals):
    spec = _doc("spec_1", "11" * 32, "SPECIFICATION")
    run_id, _ = review_jobs.enqueue(
        spec, allowed_document_ids=frozenset({spec}), requested_by=None
    )
    assert _approved("11" * 32), "a specification uploaded for review was not approved"
    claude_auto_approve.on_upload(spec)
    assert claude_approved.SPECIFICATION_ROLE in claude_approved.REVIEW_ROLES and run_id


def test_a_specification_role_is_a_real_role_and_a_standard_is_not_a_review_paper(
    approvals,
):
    assert classification.ROLES.count("SPECIFICATION") == 1
    std = _doc("std_1", "22" * 32, "COMPANY_STANDARD")
    review_jobs.enqueue(std, allowed_document_ids=frozenset({std}), requested_by=None)
    assert not _approved("22" * 32)


def test_a_contract_paper_is_not_approved_by_the_automatic_route(
    approvals, monkeypatch
):
    monkeypatch.setattr(
        claude_auto_approve, "is_contract_paper", lambda d: d == "contract_1"
    )
    con = _doc("contract_1", "33" * 32, "CONTRACTOR_SUBMITTAL")
    review_jobs.enqueue(con, allowed_document_ids=frozenset({con}), requested_by=None)
    assert not _approved("33" * 32)
    assert E.decide("claude", open_facts(kind="contract", is_contract=True)).needs_yes


def test_the_contract_kind_is_read_from_the_papers_own_decided_kind(approvals):
    con = _doc("c_kind", "34" * 32, "CONTRACTOR_SUBMITTAL")
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET document_role='CONTRACT_DOCUMENT' WHERE document_id=?",
            (con,),
        )
    assert claude_auto_approve.is_contract_paper(con) is True
    other = _doc("not_contract", "35" * 32, "CONTRACTOR_SUBMITTAL")
    assert claude_auto_approve.is_contract_paper(other) is False


def test_the_yes_is_recorded_per_file_with_who_when_and_the_document_and_can_be_withdrawn(
    approvals,
):
    con = _doc("contract_2", "44" * 32, "CONTRACT_DOCUMENT")
    assert contract_yes.has_yes(con) is False and not _approved("44" * 32)
    row = contract_yes.grant(con, "owner@example.test")
    assert (
        row["approved_by"] == "owner@example.test"
        and row["document_id"] == con
        and row["approved_on"]
    )
    assert contract_yes.has_yes(con) and _approved("44" * 32)
    assert contract_yes.record_of(con)["approved_by"] == "owner@example.test"
    audit = [
        r["action"] for r in db.connect().execute("SELECT action FROM audit_events")
    ]
    assert contract_yes.AUDIT_GRANTED in audit
    # the gate honours it
    with claude_approved.carrying([con]):
        assert claude_approved.refusal() is None
    assert contract_yes.withdraw(con, "owner@example.test") is True
    assert not contract_yes.has_yes(con) and not _approved("44" * 32)
    assert contract_yes.AUDIT_WITHDRAWN in [
        r["action"] for r in db.connect().execute("SELECT action FROM audit_events")
    ]
    assert contract_yes.record_of(con)["status"] == "withdrawn"
    with claude_approved.carrying([con]):
        assert claude_approved.refusal()[0] == claude_approved.NOT_APPROVED


def test_a_changed_file_asks_again(approvals):
    old = _doc("contract_3", "55" * 32, "CONTRACT_DOCUMENT")
    contract_yes.grant(old, "owner")
    new = _doc("contract_3b", "56" * 32, "CONTRACT_DOCUMENT", filename="contract_3.pdf")
    assert contract_yes.has_yes(old) and not contract_yes.has_yes(new)


def test_a_block_wins_over_a_yes(approvals):
    con = _doc("contract_4", "66" * 32, "CONTRACT_DOCUMENT")
    claude_approved.block_file_path().write_text(
        json.dumps({"blocked_sha256": ["66" * 32]})
    )
    with pytest.raises(contract_yes.YesRefused):
        contract_yes.grant(con, "owner")
    named = _doc(
        "reg",
        "67" * 32,
        "CONTRACT_DOCUMENT",
        filename=f"{claude_approved.REGISTER_NAME_KEY} (1).pdf",
    )
    with pytest.raises(contract_yes.YesRefused):
        contract_yes.grant(named, "owner")


def test_the_yes_routes_are_admin_only_and_scoped(world, monkeypatch):
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    client = TestClient(app)
    assert client.post(
        "/api/reviews/contract-yes", json={"document_id": world["sub"]}
    ).status_code in (401, 404)
    ok = client.post(
        "/api/reviews/contract-yes",
        json={"document_id": world["sub"]},
        headers=world["admin"],
    )
    assert ok.status_code == 200 and ok.json()["document_id"] == world["sub"]
    plan = client.get(
        "/api/reviews/plan",
        params={"submittal_document_id": world["sub"], "engine": "local"},
        headers=world["admin"],
    ).json()
    assert plan["contract_yes"]["approved_by"]
    gone = client.delete(
        f"/api/reviews/contract-yes/{world['sub']}", headers=world["admin"]
    )
    assert gone.json() == {"withdrawn": True}


# --------------------------------------------------------------------------------------------- scored kinds


def test_only_the_datasheet_is_scored_and_it_is_the_kind_table_of_k1():
    assert agent_review_gate.SCORED_KINDS == ("datasheet",)
    for kind in ("procedure", "contract", "drawing", "test_record", "other", None):
        assert not agent_review_gate.kind_scored(kind)
    assert (
        not settings.review_unscored_kinds_for_claude_enabled
    )  # the default: not offered


def _confirm_kind(world, kind):
    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO document_kinds (document_id, kind, state, routed_at) VALUES (?, ?, 'confirmed', 'x')",
            (world["sub"], kind),
        )


def test_a_procedure_is_not_offered_for_claude_on_a_live_install_and_carries_the_draft_note(
    world, lane
):
    _confirm_kind(world, "procedure")
    lane.setattr(settings, "agent_review_enabled", True)
    got = review_engine.plan_for(
        db.connect(), world["sub"], world["scope"], "automatic"
    )
    ai = next(p for p in got["parts"] if p["name"] == "ai_review")
    assert ai["engine"] == "not_run" and agent_review_gate.UNSCORED_WORDS in ai["why"]
    assert got["unscored"] and got["unscored_note"] == agent_review_gate.UNSCORED_WORDS
    assert got["text_leaves"] is False
    assert review_engine.plan_for(db.connect(), world["sub"], world["scope"], "claude")[
        "refused"
    ]
    lane.setattr(settings, "review_unscored_kinds_for_claude_enabled", True)
    on = review_engine.plan_for(db.connect(), world["sub"], world["scope"], "automatic")
    assert (
        next(p for p in on["parts"] if p["name"] == "ai_review")["engine"] == "claude"
    )
    assert on["unscored"]  # offered, and still a draft


# --------------------------------------------------------------------------------------------- the header


def test_engine_rows_are_one_home_and_name_the_engine_not_a_model():
    rows = crs_layout.engine_rows(
        {"reviewed_by": "AI reviewer on Claude", "draft_note": "A draft."}
    )
    assert rows == [("Reviewed by:", "AI reviewer on Claude"), ("Note:", "A draft.")]
    assert (
        crs_layout.engine_rows({"reviewed_by": ""}) == []
        and crs_layout.engine_rows(None) == []
    )


def test_the_ai_header_names_the_engine_on_both_copies():
    from app import crs_ai_workbook

    meta = {
        "header": {
            "project": "P",
            "reviewed_by": "AI reviewer on Claude",
            "draft_note": "",
        },
        "paper": "x.pdf",
    }
    for copy in ("internal", "contractor"):
        view = crs_ai_workbook.layout_view([], meta, copy)
        assert ("Reviewed by:", "AI reviewer on Claude") in [
            tuple(p) for p in view["header"]
        ]
        assert "claude-" not in json.dumps(view["header"]) and "run" not in json.dumps(
            view["header"]
        ).lower().replace("review", "")


def test_the_normal_sheet_names_the_engine_in_its_title_and_keeps_its_row_geometry():
    from app import crs_normal

    def view(copy):
        return {
            "crs_copy": copy, "rows": [], "columns": [], "run_status_note": "", "title": "Company",
            "header": [], "incomplete_notice": "", "recommended_code": "", "rulebook_v2_note": "",
            "applicable_standards": [],
        }  # fmt: skip

    for copy in ("internal", "contractor"):
        meta = {
            "header": {
                "reviewed_by": "rule check on the local model",
                "draft_note": "A draft.",
            }
        }
        got = crs_normal.layout_view(crs_normal.decorate(view(copy), meta), meta)
        assert (
            "Reviewed by: rule check on the local model" in got["title"]
            and "Note: A draft." in got["title"]
        )
        assert got["gap"] == (1 if copy == "internal" else 0)
        bare = crs_normal.layout_view(
            crs_normal.decorate(view(copy), {"header": {}}), {"header": {}}
        )
        assert bare["title"] == "Company" and len(got["header"]) == len(
            bare["header"]
        )  # no row added


def test_reviewed_by_reads_what_the_run_did(world, lane):
    assert crs_ai_header.reviewed_by("r", ai=False) == "rule check on the local model"
    assert crs_ai_header.reviewed_by("r", ai=True, usd=0.5) == "AI reviewer on Claude"
    assert "no model was asked" in crs_ai_header.reviewed_by("r", ai=True, usd=None)
    claude_spend.record(
        step="crs_wording",
        model="claude-sonnet-5",
        usage={"input_tokens": 1, "output_tokens": 1},
        prompt_sha256="x",
        wall_time_s=0.1,
        finish_reason="end_turn",
    )  # not under a run: not counted
    with claude_spend.for_run("r"):
        claude_spend.record(
            step="crs_wording",
            model="claude-sonnet-5",
            usage={"input_tokens": 1, "output_tokens": 1},
            prompt_sha256="x",
            wall_time_s=0.1,
            finish_reason="end_turn",
        )
    mixed = crs_ai_header.reviewed_by("r", ai=False)
    assert (
        mixed.startswith("rule check on the local model, with Claude for:")
        and "wording" in mixed
    )
    assert "claude-sonnet" not in mixed


def test_an_unscored_kind_carries_the_draft_sentence_in_the_header(world):
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO document_kinds (document_id, kind, state, routed_at) VALUES (?, 'drawing', 'confirmed', 'x')",
            (world["sub"],),
        )
    assert (
        crs_ai_header.draft_note(conn, world["sub"])
        == agent_review_gate.UNSCORED_WORDS + "."
    )
    with conn:
        conn.execute(
            "UPDATE document_kinds SET kind = 'datasheet' WHERE document_id = ?",
            (world["sub"],),
        )
    assert crs_ai_header.draft_note(conn, world["sub"]) == ""


# --------------------------------------------------------------------------------------------- the trial script


def test_the_trial_takes_an_engine_and_local_checks_the_ledger_and_that_no_ai_review_ran(
    world, tmp_path, monkeypatch
):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import trial_on_copy as t

    assert (
        t.TrialConfig(data_dir=tmp_path, document="d").engine is None
    )  # the old start stays the default
    monkeypatch.setattr(t, "wait_for", lambda *a, **k: "completed")
    import sqlite3

    def own_connection(
        _db,
    ):  # the script closes what it opens: give it its own, not the app's
        conn = sqlite3.connect(settings.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(t, "ro", own_connection)

    cfg = t.TrialConfig(data_dir=tmp_path, document=world["sub"], engine="local")
    follow, checks = t.engine_follow(
        None, cfg, "run-1", tmp_path / "x.sqlite", tmp_path, 0
    )
    names = {c.name: c.ok for c in checks}
    assert (
        follow is None
        and names["rule check completed"]
        and names["no Claude call (ledger unchanged)"]
    )
    assert names["no AI review ran (Local only)"]
    (tmp_path / "claude_spend.jsonl").write_text(
        "{}\n"
    )  # a line appeared: the check must fail
    _f, bad = t.engine_follow(None, cfg, "run-1", tmp_path / "x.sqlite", tmp_path, 0)
    assert not {c.name: c.ok for c in bad}["no Claude call (ledger unchanged)"]


def test_the_trial_does_not_wait_for_an_ai_review_the_plan_did_not_start(
    world, tmp_path, monkeypatch
):
    import sqlite3
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import trial_on_copy as t

    run_id, _job = _enqueue(world)
    review_engine.record(
        db.connect(),
        run_id,
        {"choice": "automatic"},
        "adm",
        then_ai=False,
        bar_claude=True,
        now="2026-11-12T00:00:00Z",
    )

    def own(_db):
        conn = sqlite3.connect(settings.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(t, "wait_for", lambda *a, **k: "completed")
    monkeypatch.setattr(t, "ro", own)
    cfg = t.TrialConfig(
        data_dir=tmp_path, document=world["sub"], engine="automatic", timeout=5.0
    )
    follow, checks = t.engine_follow(None, cfg, run_id, tmp_path / "x", tmp_path, 0)
    assert follow is None and all(c.ok for c in checks)
    assert any("runs no AI review" in c.name for c in checks)


# ------------------------------------------------------------------------------- review R47: the blocking three


def _job_of(run_id):
    return (
        db.connect()
        .execute("SELECT id FROM jobs WHERE review_run_id = ?", (run_id,))
        .fetchone()["id"]
    )


def test_the_choice_exists_the_moment_the_job_does_a_worker_can_never_run_it_unbarred(
    world, lane, monkeypatch
):
    """A worker that claims the job between its creation and the old second step found no choice and ran unbarred. The hook
    that `enqueue` calls right after the commit is exactly that gap: the bar must already be readable there."""
    seen = []

    def worker_in_the_gap(run_id):
        job_id = _job_of(run_id)
        seen.append(review_engine.bar_state(db.connect(), job_id))

    monkeypatch.setattr(
        review_jobs.claude_auto_approve, "on_review_start", worker_in_the_gap
    )
    run_id, _plan = review_engine_start.start(
        world["sub"], world["scope"], "adm", "local"
    )
    assert seen == [(True, None)], seen
    assert _job_of(run_id).startswith(review_engine.JOB_MARK)


def test_a_job_with_a_choice_row_and_one_without_are_told_apart(world, lane):
    run_id, _plan = review_engine_start.start(
        world["sub"], world["scope"], "adm", "local"
    )
    marked = _job_of(run_id)
    with db.connect() as conn:
        conn.execute(f"DELETE FROM {review_engine.TABLE} WHERE run_id = ?", (run_id,))
        conn.execute(
            "UPDATE review_runs SET status = 'complete' WHERE id = ?", (run_id,)
        )
    # a job of the new route that lost its choice: kept on this computer, and it says so
    assert review_engine.bar_state(db.connect(), marked) == (
        True,
        review_engine.MISSING_WORDS,
    )
    # a job of the older routes: no mark, no row: as before
    _old_run, old_job = _enqueue(world)
    assert not old_job.startswith(review_engine.JOB_MARK)
    assert review_engine.bar_state(db.connect(), old_job) == (False, None)


def test_an_unreadable_choice_fails_closed_and_the_run_says_why(
    world, lane, no_local_engine, monkeypatch
):
    import sqlite3

    fake = _fake_claude()
    lane.setattr(reader_transport, "transport", lambda: fake)
    run_id, _plan = review_engine_start.start(
        world["sub"], world["scope"], "adm", "automatic"
    )
    job_id = _job_of(run_id)
    real = review_engine.stored

    def locked(conn, rid):
        if rid == run_id:
            raise sqlite3.OperationalError("database is locked")
        return real(conn, rid)

    monkeypatch.setattr(review_engine, "stored", locked)
    assert review_engine.bar_state(db.connect(), job_id) == (
        True,
        review_engine.UNREADABLE_WORDS,
    )
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) == "done"
    assert fake.calls == [], "an unreadable choice let the run reach Claude"
    outcome = json.loads(
        db.connect()
        .execute("SELECT outcome_json FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()[0]
    )
    assert outcome["engine_choice_note"] == review_engine.UNREADABLE_WORDS


def test_a_missing_job_row_is_barred_too(world, lane):
    assert review_engine.bar_state(db.connect(), "no-such-job") == (
        True,
        review_engine.UNREADABLE_WORDS,
    )


# --------------------------------------------------------------------------------------------- review R47: the rest


def test_the_cost_says_the_true_bound_per_part_and_in_total(world, lane, monkeypatch):
    monkeypatch.setattr(
        review_engine, "read_facts", lambda *a, **k: (open_facts(), None)
    )
    got = review_engine.plan_for(
        db.connect(), world["sub"], world["scope"], "automatic"
    )
    per = float(settings.claude_budget_usd_per_run)
    assert got["cost"]["at_most_usd"] == 2 * per and got["cost"][
        "by_part_at_most_usd"
    ] == {"rule_check": per, "ai_review": per}
    assert (
        "rule check: at most USD 15; AI review: at most USD 15; together at most USD 30"
        in got["cost"]["basis"]
    )
    assert got["cost"]["exact"] is False
    one = review_engine.plan_for(db.connect(), world["sub"], world["scope"], "local")
    assert one["cost"]["at_most_usd"] is None and one["cost"]["basis"] is None


def test_the_header_engine_is_a_saved_fact_of_the_run_not_the_ledger_of_the_day(
    world, lane
):
    run_id, _job = _enqueue(world)
    with claude_spend.for_run(run_id):
        claude_spend.record(step="crs_wording", model="claude-sonnet-5", usage={"input_tokens": 1, "output_tokens": 1},
                            prompt_sha256="x", wall_time_s=0.1, finish_reason="end_turn")  # fmt: skip
    review_engine.save_ran(run_id)
    first = crs_ai_header.reviewed_by(run_id, ai=False)
    with claude_spend.for_run(
        run_id
    ):  # a later ledger line (a re-run under the same id, a rotated file) changes nothing
        claude_spend.record(step="review_ai_check", model="claude-sonnet-5", usage={"input_tokens": 1, "output_tokens": 1},
                            prompt_sha256="y", wall_time_s=0.1, finish_reason="end_turn")  # fmt: skip
    assert crs_ai_header.reviewed_by(run_id, ai=False) == first and "wording" in first
    assert "AI check" not in first and "review ai check" not in first.lower()
    # a run with no saved fact (an older one) still falls back to the ledger
    with claude_spend.for_run("legacy"):
        claude_spend.record(step="crs_wording", model="claude-sonnet-5", usage={"input_tokens": 1, "output_tokens": 1},
                            prompt_sha256="z", wall_time_s=0.1, finish_reason="end_turn")  # fmt: skip
    assert "with Claude for" in crs_ai_header.reviewed_by("legacy", ai=False)


def test_who_approved_a_contract_is_shown_only_to_an_admin(world, lane):
    from tests.test_p3_review_jobs import _user

    contract_yes.grant(world["sub"], "owner@example.test")
    bob = _user("bob", [world["sub"], world["std"]])
    client = TestClient(app)
    ask = dict(params={"submittal_document_id": world["sub"], "engine": "local"})
    as_admin = client.get("/api/reviews/plan", headers=world["admin"], **ask).json()[
        "contract_yes"
    ]
    as_bob = client.get("/api/reviews/plan", headers=bob, **ask).json()["contract_yes"]
    assert as_admin["approved_by"] == "owner@example.test"
    assert as_bob == {"document_id": world["sub"], "status": "approved"}


def test_local_only_also_keeps_the_public_web_check_from_running(
    world, lane, monkeypatch
):
    from app import market_transport

    monkeypatch.setattr(settings, "review_web_standards_enabled", True)
    monkeypatch.setattr(
        market_transport, "transport", lambda: pytest.fail("a market call was made")
    )
    run_id, _job = _enqueue(world)
    with review_engine.barring():
        review_jobs._web_check(run_id, world["scope"], ["INVENTED 1"])
    status = (
        db.connect()
        .execute("SELECT web_check_status FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()[0]
    )
    assert "kept on this computer" in status
    note = review_engine.plan_for(db.connect(), world["sub"], world["scope"], "local")[
        "notes"
    ]
    assert any("web check" in n and "will not run" in n for n in note)


def test_a_contract_by_role_alone_needs_the_yes_whatever_its_kind(world, lane):
    lane.setattr(settings, "agent_review_enabled", True)
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET document_role = 'CONTRACT_DOCUMENT' WHERE document_id = ?",
            (world["sub"],),
        )
    got = review_engine.plan_for(db.connect(), world["sub"], world["scope"], "claude")
    assert (
        got["refused"]
        and review_engine.NEEDS_YES in got["refused"]
        and got["needs_yes"]
    )
    local = review_engine.plan_for(db.connect(), world["sub"], world["scope"], "local")
    assert local["refused"] is None


def test_a_recorded_yes_on_an_unscored_contract_is_said_not_to_offer_it(world, lane):
    _confirm_kind(world, "contract")
    contract_yes.grant(world["sub"], "owner")
    got = review_engine.plan_for(
        db.connect(), world["sub"], world["scope"], "automatic"
    )
    assert any("recorded yes does not offer a contract" in n for n in got["notes"])
    assert (
        got["text_leaves"] is False
    )  # scored kinds only: the contract path waits for a score or the setting
