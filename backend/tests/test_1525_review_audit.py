# ruff: noqa: F811
"""#1525: one machine-written AUDIT.md + AUDIT.json per review run, behind
REVIEW_AUDIT_REPORT_ENABLED (off by default). Invented documents only.

What must hold: off = nothing written; on = both files, whose counts equal the
review trace's counts for the same run (pages, decided, quotes, CRS rows);
a missing figure reads "not recorded" and is never 0; a failed AI step is
listed as failed with no verdict changed; a failure writing the audit never
breaks or changes the review.
"""

from __future__ import annotations

import json

import pytest

from app import (
    access,
    claude_models,
    claude_spend,
    review_audit,
    review_jobs,
    review_trace,
)
from app.config import settings
from app.db import connect
from tests.test_p3_review_jobs import (  # noqa: F401 - fixtures
    W,
    _enqueue,
    temp_storage,
    world,
)


@pytest.fixture
def audit_dir(tmp_path_factory, monkeypatch):
    out = tmp_path_factory.mktemp(
        "proof_out"
    )  # a sibling of the data folder, not inside it
    monkeypatch.setattr(settings, "review_audit_dir", str(out))
    return out.resolve()


def _scope(world):
    return access.AccessScope(user_id=None, allowed_document_ids=world["scope"])


def _review(world):
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) == "done"
    return run_id


def _files(audit_dir):
    return sorted(audit_dir.rglob("AUDIT.*")) if audit_dir.exists() else []


def _json(audit_dir):
    return json.loads(
        next(f for f in _files(audit_dir) if f.suffix == ".json").read_text()
    )


def test_the_switch_is_off_by_default_and_nothing_is_written(world, audit_dir):
    assert settings.review_audit_report_enabled is False
    _review(world)
    assert _files(audit_dir) == []


def test_a_review_with_the_switch_on_writes_both_files_in_the_dated_run_folder(
    world, audit_dir, monkeypatch
):
    monkeypatch.setattr(settings, "review_audit_report_enabled", True)
    run_id = _review(world)
    files = _files(audit_dir)
    assert [f.name for f in files] == ["AUDIT.json", "AUDIT.md"]
    assert files[0].parent.name.endswith(f"-{run_id}")
    assert files[0].parent.name[:4].isdigit()


def test_the_counts_equal_the_trace_counts_of_the_same_run(
    world, audit_dir, monkeypatch
):
    monkeypatch.setattr(settings, "review_audit_report_enabled", True)
    run_id = _review(world)
    audit = _json(audit_dir)
    steps = {s["step"]: s for s in review_trace.build(run_id, _scope(world))["steps"]}
    assert audit["run"]["id"] == run_id and audit["run"]["document_id"] == world["sub"]
    assert audit["rules"]["rows_total"] == len(audit["rules"]["rows"]) > 0
    decide = steps["DECIDE"]["counts"]
    assert audit["rules"]["verdict_counts"] == {
        review_audit.VERDICT.get(code, code): decide[label]
        for code, label in review_trace._DECISIONS
        if decide.get(label)
    }
    assert audit["crs"]["rows_exported"] == steps["CRS"]["counts"]["rows"]
    assert audit["standards"]["applied_count"] == steps["STANDARDS"]["counts"]["chosen"]
    assert (
        audit["standards"]["cited_not_in_library_count"]
        == steps["STANDARDS"]["counts"]["cited_not_held"]
    )
    assert "documents the requester may read" in audit["boundary"]


def test_markdown_and_json_carry_the_same_figures(world, audit_dir, monkeypatch):
    monkeypatch.setattr(settings, "review_audit_report_enabled", True)
    run_id = _review(world)
    md = next(f for f in _files(audit_dir) if f.suffix == ".md").read_text()
    audit = _json(audit_dir)
    assert f"rules compared: {audit['rules']['rows_total']}" in md
    for heading in (
        "## 1. Run",
        "## 2. Pages",
        "## 3. Standards",
        "## 4. Rules",
        "## 5. AI use",
        "## 6. Safety gates",
        "## 7. CRS",
        "## 8. Retractions and known gaps",
    ):
        assert heading in md
    assert run_id in md


def test_the_run_record_and_audit_name_the_models_that_answered(
    world, audit_dir, tmp_path, monkeypatch
):
    """Owner: the model ACTUALLY used, the response's `model`, in the run row and AUDIT.json."""
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    for step, model in (
        ("a-review-step", "claude-sonnet-5-5"),
        ("labels", "claude-haiku-5-5"),
        ("chat", "chat-is-not-this-run"),
    ):
        held = claude_spend.reserve(
            step, 0.01, model="what-was-asked-for", prompt_sha256="x"
        )
        claude_spend.settle(
            held,
            model=model,
            usage={"input_tokens": 1, "output_tokens": 1},
            finish_reason="stop",
        )
    assert review_jobs.run(job_id, W) == "done"
    row = (
        connect()
        .execute("SELECT model_name FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()
    )
    assert row["model_name"] == "claude-haiku-5-5, claude-sonnet-5-5"
    used = review_audit.build(run_id, _scope(world))["run"]["models_used"]
    assert "claude-haiku-5-5" in used and "claude-sonnet-5-5" in used
    assert "what-was-asked-for" not in used and "chat-is-not-this-run" not in used


def test_a_run_no_claude_call_answered_has_no_model_name(
    world, audit_dir, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    run_id = _review(world)
    row = (
        connect()
        .execute("SELECT model_name FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()
    )
    assert row["model_name"] is None


def test_the_matcher_section_names_the_model_not_the_word_claude(
    world, audit_dir, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    run_id = _review(world)
    with connect() as conn:
        conn.execute(
            "UPDATE review_runs SET outcome_json = ?, started_at = ? WHERE id = ?",
            (
                json.dumps({"ai_matcher": {"engine": "claude", "model": "claude"}}),
                "2000-01-01T00:00:00+00:00",
                run_id,
            ),
        )
    held = claude_spend.reserve("matcher", 0.01, model="asked", prompt_sha256="x")
    claude_spend.settle(
        held,
        model="claude-sonnet-5-5",
        usage={"input_tokens": 1, "output_tokens": 1},
        finish_reason="stop",
    )
    claude_models.record_run(run_id, match_step="matcher")
    row = (
        connect()
        .execute("SELECT outcome_json FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()
    )
    assert json.loads(row["outcome_json"])["ai_matcher"]["model"] == "claude-sonnet-5-5"


def test_an_unreadable_ledger_never_reads_as_a_local_only_run(
    world, audit_dir, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    run_id = _review(world)

    def unreadable(**_kw):
        raise OSError("no")

    monkeypatch.setattr(claude_spend, "models_used", unreadable)
    claude_models.record_run(run_id, match_step="matcher")
    row = (
        connect()
        .execute("SELECT model_name FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()
    )
    assert row["model_name"] == claude_models.LEDGER_UNREADABLE
    used = review_audit.build(run_id, _scope(world))["run"]["models_used"]
    assert claude_models.LEDGER_UNREADABLE in used


def test_a_cache_hit_names_the_model_on_the_run(world, audit_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    claude_spend.record(
        step="a-review-step",
        model="claude-sonnet-5-5",
        usage={},
        prompt_sha256="x",
        wall_time_s=0.0,
        finish_reason="cache_hit",
    )
    assert review_jobs.run(job_id, W) == "done"
    row = (
        connect()
        .execute("SELECT model_name FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()
    )
    assert row["model_name"] == "claude-sonnet-5-5"


def test_a_figure_that_was_not_recorded_reads_not_recorded_never_zero(world, audit_dir):
    run_id = _review(world)
    with connect() as conn:
        conn.execute("DELETE FROM page_ledger WHERE document_id = ?", (world["sub"],))
    audit = review_audit.build(run_id, _scope(world))
    assert audit["pages"]["total"] is None
    md = review_audit.render_markdown(audit)
    assert "pages in the document: not recorded" in md
    assert "pages in the document: 0" not in md


def test_a_failed_ai_step_is_listed_failed_and_the_verdicts_do_not_change(
    world, audit_dir
):
    run_id = _review(world)
    before = review_audit.build(run_id, _scope(world))
    failed = json.dumps(
        {
            "ran": False,
            "complete": False,
            "calls_made": 1,
            "reason": "timeout",
            "model": "invented-model",
        }
    )
    with connect() as conn:
        conn.execute(
            "UPDATE review_runs SET ai_check_status = ? WHERE id = ?", (failed, run_id)
        )
    after = review_audit.build(run_id, _scope(world))
    step = next(
        s for s in after["ai_use"]["steps"] if s["name"] == "ai_engineering_check"
    )
    assert step["state"] == "failed" and step["reason"] == "timeout"
    assert step["model"] == "invented-model" and step["calls"] == 1
    assert "no verdict is more confident" in step["effect_on_verdicts"]
    assert after["rules"]["verdict_counts"] == before["rules"]["verdict_counts"]
    assert after["rules"]["rows"] == before["rules"]["rows"]


def test_a_step_with_no_status_is_not_recorded_not_failed(world, audit_dir):
    run_id = _review(world)
    with connect() as conn:
        conn.execute(
            "UPDATE review_runs SET ai_check_status = NULL WHERE id = ?", (run_id,)
        )
    step = review_audit.build(run_id, _scope(world))["ai_use"]["steps"][0]
    assert step["state"] == "not recorded" and step["calls"] is None


def test_a_failure_writing_the_audit_never_breaks_the_review(
    world, audit_dir, monkeypatch
):
    monkeypatch.setattr(settings, "review_audit_report_enabled", True)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(review_audit, "render_markdown", boom)
    run_id = _review(world)  # review_jobs.run still returns "done"
    row = (
        connect()
        .execute("SELECT status FROM review_runs WHERE id = ?", (run_id,))
        .fetchone()
    )
    assert row["status"] == "completed"
    assert _files(audit_dir) == []


def test_the_audit_holds_no_page_text_beyond_stored_quotes(world, audit_dir):
    run_id = _review(world)
    audit = review_audit.build(run_id, _scope(world))
    md = review_audit.render_markdown(audit)
    assert "Pump shall comply with API 610" not in md
    assert "Equipment noise level shall not exceed" not in md
    # the stored quote IS shown: the probe sees a snippet when one is stored
    shown = [r["value_read"] for r in audit["rules"]["rows"] if r["value_read"]]
    assert shown and all(v in md for v in shown)
    audit["rules"]["rows"][0]["value_read"] = "Pump shall comply with API 610"
    assert "Pump shall comply with API 610" in review_audit.render_markdown(audit)


def test_a_draft_count_the_run_did_not_store_is_not_recorded_never_zero(
    world, audit_dir
):
    run_id = _review(world)
    audit = review_audit.build(run_id, _scope(world))
    assert audit["gates"]["recorded"]["draft_checklist_results"] is None
    md = review_audit.render_markdown(audit)
    assert "draft_checklist_results: not recorded" in md


def test_applied_count_is_what_is_listed_and_states_its_boundary(world, audit_dir):
    run_id = _review(world)
    sub_only = access.AccessScope(
        user_id=None, allowed_document_ids=frozenset({world["sub"]})
    )
    std = review_audit.build(run_id, sub_only)["standards"]
    assert std["applied_count"] == len(std["applied"]) == 0
    full = review_audit.build(run_id, _scope(world))
    assert full["standards"]["applied_count"] == len(full["standards"]["applied"])
    assert "of standards you may read" in review_audit.render_markdown(full)


def test_an_audit_dir_inside_the_repo_or_data_folder_falls_back(tmp_path, monkeypatch):
    default = review_audit.Path("~/project/mirror/proof").expanduser()
    inside_repo = review_audit.Path(review_audit.__file__).resolve().parents[2] / "x"
    monkeypatch.setattr(settings, "review_audit_dir", str(inside_repo))
    assert review_audit.audit_root() == default
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "review_audit_dir", str(tmp_path / "data" / "out"))
    assert review_audit.audit_root() == default
    monkeypatch.setattr(settings, "review_audit_dir", str(tmp_path / "elsewhere"))
    assert review_audit.audit_root() == (tmp_path / "elsewhere").resolve()


def test_the_audit_folder_is_kept_in_the_runs_stored_trace(
    world, audit_dir, monkeypatch
):
    monkeypatch.setattr(settings, "review_audit_report_enabled", True)
    run_id = _review(world)
    row = (
        connect()
        .execute(
            "SELECT trace FROM review_run_traces WHERE review_run_id = ?", (run_id,)
        )
        .fetchone()
    )
    assert json.loads(row["trace"])["audit_path"] == str(_files(audit_dir)[0].parent)
