"""Review of #1588: a hit is never fresh; a skipped step is listed as not checked; the cache
figures are the run's own; the cache folder is only inside `data_dir` and git-ignored."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import (
    absence,
    ai_call_ledger,
    ai_task_runner,
    applicability_reasoning,
    applicability_v2,
    claude_answer_cache,
    claude_spend,
    clause_review,
    comparison,
    crs_wording,
    db,
    field_naming,
    local_engine_bar,
    review_audit,
    review_audit_rows,
    review_jobs,
)
from app import reasoning_provider as rp
from app.ai import output_limits
from app.config import settings
from tests.test_p3_review_jobs import (  # noqa: F401 - fixtures
    _enqueue,
    temp_storage,
    world,
)

W = "worker-1588"
MODEL = "claude-sonnet-5-5"
SKIP_WORDS = "not checked: skipped in a Claude-lane run"


@pytest.fixture
def lane(monkeypatch):
    """The lane open; ledger and cache in this test's data folder (`temp_storage`)."""
    data = Path(settings.data_dir)
    monkeypatch.setattr(settings, "reasoning_provider", "per_task")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-invented")
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    monkeypatch.setattr(settings, "claude_spend_log", data / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", data / "claude_cache")
    monkeypatch.setattr(settings, "ai_answer_reuse_enabled", True)
    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    for name in (
        "STANDARDS_READER_ENABLED",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
        "ANTHROPIC_API_KEY",
        "STANDARDS_READER_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _send(reply: str):
    def send(url, *, headers, body, timeout):
        send.calls += 1
        return {
            "model": body["model"],
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": reply}],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

    send.calls = 0
    return send


def _row(rows, step):
    return next(r for r in rows if r["step"] == step)


# ---------------------------------------------------- MUST 1: a hit is never fresh


def test_a_hit_inside_asking_is_reused_not_fresh(lane):
    send = _send('{"a": 1}')
    provider = rp.ClaudeProvider(MODEL, transport=send)
    packet = rp.Packet(prompt="q", num_ctx=1, num_predict=50, step="s")
    with ai_call_ledger.open_ledger():
        for _ in range(2):
            with ai_call_ledger.asking("s", MODEL):
                provider.reason(packet)
        row = _row(ai_call_ledger.snapshot(), "s")
    assert send.calls == 1
    assert (row["fresh"], row["reused"], row["cache_hits"]) == (1, 1, 1)


def test_scope_reasoning_counts_a_hit_as_reused(lane):
    answer = json.dumps(
        {
            "decision": applicability_v2.APPLICABLE,
            "basis": "b",
            "quote": None,
            "page": None,
        }
    )
    send = _send(answer)
    provider = rp.ClaudeProvider(MODEL, transport=send)
    record = {"covers": [], "excludes": [], "limits": []}
    with ai_call_ledger.open_ledger():
        for _ in range(2):
            applicability_reasoning.decide_by_reasoning(
                record, "pump", provider, step="scope"
            )
        row = _row(ai_call_ledger.snapshot(), "scope")
    assert send.calls == 1
    assert (row["fresh"], row["reused"]) == (1, 1)


def test_field_naming_counts_a_hit_as_reused_for_each_item(lane):
    send = _send('{"names": []}')
    provider = rp.ClaudeProvider(MODEL, transport=send)
    lane.setattr(field_naming, "stored_names", lambda *a, **k: {})
    items = [("k1", "noise level"), ("k2", "flow rate")]
    with ai_call_ledger.open_ledger():
        for _ in range(2):
            field_naming.name_items(field_naming.LABEL, items, ["noise"], provider)
        row = _row(ai_call_ledger.snapshot(), field_naming.NAMING_STEP)
    assert send.calls == 1
    assert (row["fresh"], row["reused"]) == (2, 2)


def test_a_task_counts_a_hit_as_reused(lane):
    send = _send('{"a": 1}')
    provider = rp.ClaudeProvider(MODEL, transport=send)
    spec = ai_task_runner.TaskSpec(
        name="t1588", version="1", instruction="i", schema={"type": "object"}
    )
    with ai_call_ledger.open_ledger():
        for _ in range(2):
            ai_task_runner.run_task(
                spec, "some text", provider=provider, use_cache=False
            )
        row = _row(ai_call_ledger.snapshot(), "ai_task:t1588")
    assert send.calls == 1
    assert (row["fresh"], row["reused"]) == (1, 1)


def test_a_failed_ask_is_still_failed_and_a_fresh_one_still_fresh():
    with ai_call_ledger.open_ledger():
        with ai_call_ledger.asking("s", "m"):
            pass
        with pytest.raises(ValueError), ai_call_ledger.asking("s", "m"):
            raise ValueError
        row = _row(ai_call_ledger.snapshot(), "s")
    assert (row["fresh"], row["failed"], row["reused"]) == (1, 1, 0)
    assert "cache_hits" not in row


def test_the_ai_check_and_the_wording_count_their_hits_once_and_not_as_fresh():
    """Their own stored counts are calls attempted: a hit moves from fresh to reused,
    and the ledger's row for the same step is folded in, never added on top."""
    check = {"name": "ai_engineering_check", "calls": 2, "fresh": 2, "reused": 0}
    wording = {"name": "crs_wording", "calls": 3, "fresh": 3, "reused": 0}
    ledger = [
        {"step": "review_ai_check", "model": "m", "fresh": 0, "failed": 0, "reused": 1},
        {"step": "other", "model": "m", "fresh": 1, "failed": 0, "reused": 0},
    ]
    figures = {
        "claude_answer_cache": {
            "hits_by_step": {"review_ai_check": 1, "crs_wording": 3}
        }
    }
    left = review_audit_rows.fold_stored_hits([check, wording], ledger, figures)
    assert (check["fresh"], check["reused"]) == (1, 1) and "not sent" in check[
        "not_sent"
    ]
    assert (wording["fresh"], wording["reused"]) == (0, 3)
    assert [r["step"] for r in left] == ["other"]


def test_with_no_stored_answer_the_counts_stand():
    check = {
        "name": "ai_engineering_check",
        "calls": None,
        "fresh": None,
        "reused": None,
    }
    assert review_audit_rows.fold_stored_hits([check], None, {}) is None
    assert check["fresh"] is None and check["reused"] is None


# ---------------------------------------------------- MUST 2: a skip is listed as not checked


def _lines(outcome, **kw):
    return [
        p["line"]
        for p in absence.unchecked_parts(run_status="completed", outcome=outcome, **kw)
    ]


def test_each_skipped_step_is_listed_as_not_checked():
    steps = [
        clause_review.STEP,
        crs_wording.STEP,
        field_naming.NAMING_STEP,
        "scope-reasoning-decide",
        "requirement-matcher",
        "ai_task:anything",
        "local engine /api/generate",
    ]
    outcome = {
        local_engine_bar.OUTCOME_KEY: [
            {"step": s, "calls_not_made": 1, "note": local_engine_bar.NOTE}
            for s in steps
        ]
    }
    lines = _lines(outcome)
    assert len([ln for ln in lines if SKIP_WORDS in ln]) == len(steps)
    assert any(ln.startswith("AI clause review:") for ln in lines)
    assert any(ln.startswith("AI field naming:") for ln in lines)


def test_the_ai_check_skip_is_listed_once():
    from app import ai_engineering_check

    outcome = {
        local_engine_bar.OUTCOME_KEY: [
            {
                "step": ai_engineering_check.STEP,
                "calls_not_made": 1,
                "note": local_engine_bar.NOTE,
            }
        ]
    }
    status = absence.check_failed_status("AI engineering check", local_engine_bar.NOTE)
    lines = _lines(outcome, ai_status=status)
    assert len([ln for ln in lines if "Claude-lane" in ln]) == 1


def test_a_run_with_nothing_skipped_lists_nothing_new():
    assert not [ln for ln in _lines({}) if SKIP_WORDS in ln]


def test_a_skipped_clause_review_reaches_the_crs_list(world, lane):  # noqa: F811
    lane.setattr(settings, "clause_review_enabled", True)
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) == "done"
    row = (
        db.connect()
        .execute("SELECT outcome_json FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()
    )
    lines = _lines(json.loads(row["outcome_json"]))
    assert any(ln.startswith("AI clause review:") and SKIP_WORDS in ln for ln in lines)


def test_naming_skipped_is_stated_and_a_requirement_left_unpaired_never_passes(
    world,  # noqa: F811
    lane,
):
    """Naming only ADDS a pairing: with it skipped, containment decides, and a requirement
    nothing pairs stays a query, stated on the run. It never reads as a Pass."""
    lane.setattr(settings, "field_naming_enabled", True)
    lane.setattr(settings, "geometry_reader_enabled", True)
    with db.connect() as conn:
        conn.execute(
            "UPDATE submittal_facts SET field_name = 'flange rating', field_label = 'Flange rating',"
            " raw_value = '10', field_value = '10', unit = 'bar', raw_unit = 'bar'"
        )
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) == "done"
    rows = (
        db.connect()
        .execute(
            "SELECT compliance_status, requirement FROM review_findings WHERE review_run_id = ?",
            (run_id,),
        )
        .fetchall()
    )
    noise = [
        r["compliance_status"] for r in rows if "noise" in r["requirement"].lower()
    ]
    assert noise and comparison.COMPLIANT not in noise
    outcome = (
        db.connect()
        .execute("SELECT outcome_json FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()["outcome_json"]
    )
    lines = _lines(json.loads(outcome))
    assert any(ln.startswith("AI field naming:") and SKIP_WORDS in ln for ln in lines)


def test_naming_under_the_bar_says_it_refused_and_is_noted(lane):
    lane.setattr(field_naming, "build_dictionary", lambda *a: ["noise level"])
    lane.setattr(field_naming, "stored_names", lambda *a, **k: {})
    with local_engine_bar.bar():
        requirement = {
            "id": "r1",
            "requirement_type": "numeric_limit",
            "requirement_text": "Noise level shall not exceed 90 dB(A)",
            "field": "noise level",
        }
        fact = {"id": "f1", "field_label": "Noise level", "raw_value": "95"}
        result = field_naming.ensure_names([requirement], [fact])
        stated = {r["step"] for r in local_engine_bar.stated()}
    assert local_engine_bar.NOTE in str(result["refused"])
    assert field_naming.NAMING_STEP in stated


# ---------------------------------------------------- MUST 3: the figures are the run's


def _metered(send, step="s"):
    return output_limits.model_call_for(
        claude_spend.metered(send, step), output_limits.ROUTE_MATCH
    )


def test_the_cache_figures_cover_this_run_and_not_a_chat_beside_it(lane):
    send = _send('{"a": 1}')
    _metered(send, "chat")("a chat question")  # the same time window, not this run
    _metered(send, "chat")("a chat question")
    with claude_spend.for_run("run-1"):
        _metered(send)("q1")
        _metered(send)("q1")
    with claude_spend.for_run("run-2"):
        _metered(send)("q2")
    report = review_audit_rows.cache_figures({"id": "run-1"})["claude_answer_cache"]
    assert (report["hits"], report["misses"]) == (1, 1)
    assert report["hits_by_step"] == {"s": 1}
    assert "this review run" in report["boundary"]
    assert "this review run" in " ".join(
        review_audit_rows.cache_lines({"claude_answer_cache": report})
    )
    whole = claude_spend.cache_report()
    assert (whole["hits"], whole["misses"]) == (2, 3)
    assert "whole" in whole["boundary"]


def test_a_review_job_tags_its_own_ledger_lines(world, lane):  # noqa: F811
    seen = []
    lane.setattr(
        review_audit, "write", lambda *a, **k: seen.append(claude_spend.current_run())
    )
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) == "done"
    assert seen == [run_id] and claude_spend.current_run() is None


def test_the_audit_says_nothing_for_a_run_with_no_claude_call(lane):
    assert review_audit_rows.cache_figures({"id": "no-such-run"}) == {}


# ---------------------------------------------------- SHOULD: where the files may live


def test_a_folder_outside_the_data_folder_means_no_cache_and_says_so(
    lane, tmp_path_factory
):
    outside = tmp_path_factory.mktemp("outside")
    lane.setattr(settings, "claude_cache_dir", outside / "cache")
    send = _send('{"a": 1}')
    _metered(send)("q")
    _metered(send)("q")
    assert send.calls == 2 and not list(outside.rglob("*.json"))
    why = claude_answer_cache.refused_folder()
    assert why and "data folder" in why
    assert claude_spend.cache_report()["cache_off"] == why
    assert why in " ".join(
        review_audit_rows.cache_lines(
            {
                "claude_answer_cache": {
                    "hits": 0,
                    "misses": 2,
                    "saved_usd": 0,
                    "boundary": "b",
                    "cache_off": why,
                }
            }
        )
    )


def test_the_repo_root_is_refused_even_as_the_data_folder(lane):
    repo = Path(claude_answer_cache.__file__).resolve().parents[2]
    lane.setattr(settings, "data_dir", repo)
    lane.setattr(settings, "claude_cache_dir", repo)
    assert "repository" in claude_answer_cache.refused_folder()


def test_a_folder_git_does_not_ignore_is_refused(lane):
    repo = Path(claude_answer_cache.__file__).resolve().parents[2]
    lane.setattr(settings, "data_dir", repo / "docs")
    lane.setattr(settings, "claude_cache_dir", repo / "docs" / "claude_cache")
    claude_answer_cache._ignored_by_git.cache_clear()
    assert "git" in claude_answer_cache.refused_folder()
    send = _send('{"a": 1}')
    _metered(send)("q")
    assert not (repo / "docs" / "claude_cache").exists()


def test_a_git_ignored_folder_in_the_repo_is_allowed(lane):
    repo = Path(claude_answer_cache.__file__).resolve().parents[2]
    lane.setattr(settings, "data_dir", repo / "backend" / "data")
    lane.setattr(settings, "claude_cache_dir", None)
    claude_answer_cache._ignored_by_git.cache_clear()
    assert claude_answer_cache.refused_folder() is None


def test_the_default_folder_under_a_data_folder_outside_git_is_allowed(lane):
    lane.setattr(settings, "claude_cache_dir", None)
    assert claude_answer_cache.refused_folder() is None
    send = _send('{"a": 1}')
    _metered(send)("q")
    _metered(send)("q")
    assert send.calls == 1
