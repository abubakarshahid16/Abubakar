# ruff: noqa: F811
"""#1525, what the first audit PRs left "not recorded": the gates, the limit, comparator
and approval of a rule row, the standards' split and editions, the clause review's
figures, the CRS copies' paths, the bench's own counts, and an audit for a review that
did not finish. Behind REVIEW_AUDIT_REPORT_ENABLED. Invented documents only.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import uuid
from pathlib import Path

import pytest
from tools import crs_bench

from app import (
    access,
    comparison,
    datasheet_checks,
    job_queue,
    review_audit,
    review_audit_detail,
    review_jobs,
    run_measures,
)
from app.clause_review import STATUS_KEY
from app.config import settings
from app.db import connect
from tests.test_1525_review_audit import _review, _scope, audit_dir  # noqa: F401
from tests.test_p3_review_jobs import (  # noqa: F401 - fixtures
    W,
    _enqueue,
    temp_storage,
    world,
)

NOW = "2026-11-02T10:00:00+00:00"


def _finding(world, run_id, **cols) -> str:
    row = {
        "id": str(uuid.uuid4()),
        "document_id": world["sub"],
        "review_run_id": run_id,
        "category": "technical_query",
        "severity": "minor",
        "requirement": "an invented requirement",
        "finding": "an invented finding",
        "required_action": "None.",
        "created_at": NOW,
        "updated_at": NOW,
        **cols,
    }
    names = ", ".join(row)
    marks = ", ".join(f":{k}" for k in row)
    with connect() as conn:
        conn.execute(f"INSERT INTO review_findings ({names}) VALUES ({marks})", row)
    return row["id"]


def _outcome(run_id, **changes) -> None:
    conn = connect()
    raw = conn.execute(
        "SELECT outcome_json FROM review_runs WHERE id = ?", (run_id,)
    ).fetchone()[0]
    outcome = {**json.loads(raw or "{}"), **changes}
    with conn:
        conn.execute(
            "UPDATE review_runs SET outcome_json = ? WHERE id = ?",
            (json.dumps(outcome), run_id),
        )


def _build(world, run_id, timings=None):
    return review_audit.build(run_id, _scope(world), timings)


def _row(audit, finding_id):
    return next(r for r in audit["rules"]["rows"] if r["finding_id"] == finding_id)


def _gate(audit, name):
    return next(g for g in audit["gates"]["gates"] if g["gate"] == name)


# ------------------------------------------------------------ the bench's counts


def test_the_audit_counts_equal_the_bench_score_of_the_same_run(world, monkeypatch):
    run_id = _review(world)
    _finding(
        world,
        run_id,
        origin="datasheet_check",
        compliance_status="COMPLIANT",
        requirement_source_text=f"{datasheet_checks.LABEL} X-01: an invented item",
        contractor_evidence_text="not on any page",
        contractor_page=1,
    )
    _finding(
        world,
        run_id,
        origin="datasheet_check",
        compliance_status="NON_COMPLIANT",
        requirement_source_text=f"{datasheet_checks.LABEL} X-02: an invented item",
    )
    case = {
        "run": run_id,
        "kind": "datasheet",
        "wrong": [{"check": "X-02"}],
        "untrue": [{"check": "X-01"}],
    }
    monkeypatch.setattr(review_audit_detail, "truth_case", lambda _run: case)
    audit = _build(world, run_id)
    bench = crs_bench.score(connect(), run_id, case)
    counts = audit["rules"]["bench_counts"]
    for key in (
        "wrong",
        "untrue",
        "checklist_decided",
        "checklist_total",
        "rules_decided",
        "rules_in_scope",
        "quotes_verified",
        "quotes_unverified",
        "quotes_total",
        "pages_read",
        "pages_total",
        "pass_on_deferred",
    ):
        assert counts[key] == bench[key], key
    assert bench["wrong"] == 1 and bench["untrue"] == 1
    assert bench["checklist_decided"] == 2 and bench["quotes_unverified"] >= 1
    assert _gate(audit, "wrong")["count"] == 1
    assert _gate(audit, "untrue")["count"] == 1
    md = review_audit.render_markdown(audit)
    assert f"checklist decided: 2 of {bench['checklist_total']}" in md
    assert (
        f"quotes verified: {bench['quotes_verified']} of {bench['quotes_total']}" in md
    )


def test_the_bench_takes_its_counts_from_the_one_function_the_audit_reads(
    world, monkeypatch
):
    run_id = _review(world)
    monkeypatch.setattr(
        run_measures,
        "headline",
        lambda *a, **k: {"wrong": 77},
    )
    assert crs_bench.score(connect(), run_id, {"kind": "x"})["wrong"] == 77


def test_a_run_not_on_the_truth_file_says_not_recorded_never_0(world):
    run_id = _review(world)
    audit = _build(world, run_id)
    assert _gate(audit, "wrong")["count"] is None
    assert _gate(audit, "untrue")["count"] is None
    assert "wrong" in audit["gates"]["not_recorded_on_the_run"]
    assert audit["rules"]["bench_counts"]["wrong"] is None
    assert "- wrong: not recorded" in review_audit.render_markdown(audit)


def test_a_named_bench_run_is_found_on_the_real_truth_file():
    truth = json.loads(review_audit_detail.TRUTH.read_text())
    named = truth["cases"][0]
    assert review_audit_detail.truth_case(named["run"])["name"] == named["name"]
    assert review_audit_detail.truth_case("not a run") is None


# ------------------------------------------------------------------ section 3


def test_cited_not_in_library_is_split_design_material_purchasing(world):
    run_id = _review(world)
    _outcome(
        run_id,
        missing_references=["ISO 1000", "ASTM A1", {"identifier": "01-SAMSS-1"}],
    )
    std = _build(world, run_id)["standards"]
    assert std["cited_not_in_library_count"] == 3
    assert std["cited_not_in_library_split"] == {
        "design": 1,
        "material": 1,
        "purchasing": 1,
    }


def test_a_run_that_stored_no_list_says_not_recorded_never_0(world):
    run_id = _review(world)
    with connect() as conn:
        conn.execute(
            "UPDATE review_runs SET outcome_json = '{}' WHERE id = ?", (run_id,)
        )
    audit = _build(world, run_id)
    std = audit["standards"]
    assert std["cited_not_in_library_count"] is None
    assert std["cited_not_in_library_split"] is None
    assert "cited, not in library: not recorded" in review_audit.render_markdown(audit)


def test_a_standard_edition_comes_from_its_file_name_or_reads_not_recorded(world):
    run_id = _review(world)
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO review_applicable_standards"
            " (review_run_id, standard_document_id, included, selection_method,"
            " created_at) VALUES (?, ?, 1, 'governing', ?)",
            (run_id, world["std"], NOW),
        )
    audit = _build(world, run_id)
    assert [a["edition"] for a in audit["standards"]["applied"]] == [None]
    assert audit["standards"]["editions_printed"] == 0
    with connect() as conn:
        conn.execute(
            "UPDATE documents SET filename = 'ISO 1000 (2019).pdf' WHERE id = ?",
            (world["std"],),
        )
    audit = _build(world, run_id)
    assert [a["edition"] for a in audit["standards"]["applied"]] == ["2019"]
    md = review_audit.render_markdown(audit)
    assert "(governing; edition 2019)" in md
    assert "editions: 1 of 1 applied standards print a year" in md


# ------------------------------------------------------------------ section 4


def _rule(world, **cols) -> str:
    rule_id = str(uuid.uuid4())
    row = {
        "id": rule_id,
        "standard_document_id": world["std"],
        "requirement_text": "an invented rule",
        "created_at": NOW,
        "updated_at": NOW,
        **cols,
    }
    names = ", ".join(row)
    marks = ", ".join(f":{k}" for k in row)
    with connect() as conn:
        conn.execute(
            f"INSERT INTO standard_requirements ({names}) VALUES ({marks})", row
        )
    return rule_id


def test_a_rule_row_prints_the_stored_limit_comparator_and_approval(world):
    run_id = _review(world)
    rule = _rule(world, operator="<=", raw_value="90", raw_unit="dB(A)")
    confirmed = _rule(world, operator=">=", value=5.0, unit="mm", confirmed_by="adm")
    plain = _finding(world, run_id, requirement_id=rule, compliance_status="COMPLIANT")
    signed = _finding(world, run_id, requirement_id=confirmed)
    audit = _build(world, run_id)
    row = _row(audit, plain)
    assert (row["limit"], row["comparator"]) == ("90 dB(A)", "<=")
    assert row["kit_card_approval"] == "not confirmed"
    row = _row(audit, signed)
    assert (row["limit"], row["comparator"]) == ("5.0 mm", ">=")
    assert row["kit_card_approval"] == "engineer confirmed"
    md = review_audit.render_markdown(audit)
    assert "| limit | comparator |" in md
    assert "| 90 dB(A) | <= |" in md


def test_a_limit_from_a_standard_the_requester_may_not_read_is_not_printed(world):
    run_id = _review(world)
    rule = _rule(world, operator="<=", raw_value="90", raw_unit="dB(A)")
    finding = _finding(world, run_id, requirement_id=rule)
    scope = access.AccessScope(
        user_id=None, allowed_document_ids=frozenset({world["sub"]})
    )
    row = _row(review_audit.build(run_id, scope), finding)
    assert row["limit"] is None and row["comparator"] is None


@pytest.mark.parametrize(
    ("rule", "limit", "comparator"),
    [
        ({"kind": "required", "field": "a"}, "a value stated", "required"),
        ({"kind": "allowed", "field": "a", "values": ["x", "y"]}, "x, y", "one of"),
        ({"kind": "compare", "left": "a", "op": "<=", "right": "b"}, "b", "<="),
        (
            {"kind": "constant", "field": "a", "op": "<=", "value": 21, "unit": "%"},
            "21 %",
            "<=",
        ),
        (
            {
                "kind": "percent_of",
                "left": "a",
                "op": "<=",
                "percent": 10,
                "right": "b",
            },
            "10% of b",
            "<=",
        ),
        (
            {
                "kind": "above_by",
                "left": "a",
                "right": "b",
                "percent": 10,
                "at_least": 100,
                "unit": "kPa",
            },
            "b: 10%, at least 100 kPa",
            "above by",
        ),
        ({"kind": "calc", "formula": "f", "field": "a"}, "f", "calculated"),
    ],
)
def test_a_checklist_rule_of_every_kind_states_its_limit(rule, limit, comparator):
    assert review_audit_detail.checklist_limit(rule) == (limit, comparator)


def test_a_checklist_row_is_found_by_its_id_and_says_whether_it_is_a_draft(
    world, monkeypatch
):
    run_id = _review(world)
    item = {"id": "X-09", "rule": {"kind": "compare", "op": "<=", "right": "b"}}
    monkeypatch.setattr(
        datasheet_checks,
        "load_rules",
        lambda *a: {"checklists": {"pump": {"items": [item]}}},
    )
    label = datasheet_checks.LABEL
    signed = _finding(
        world,
        run_id,
        origin="datasheet_check",
        requirement_source_text=f"{label} X-09: an invented item",
    )
    draft = _finding(
        world,
        run_id,
        origin="datasheet_check",
        requirement_source_text=(
            f"{label} X-09: {datasheet_checks.DRAFT_MARK} an invented item"
        ),
    )
    gone = _finding(
        world,
        run_id,
        origin="datasheet_check",
        requirement_source_text=f"{label} X-10: an invented item",
    )
    audit = _build(world, run_id)
    row = _row(audit, signed)
    assert row["kit_card_id"] == "X-09"
    assert (row["limit"], row["comparator"]) == ("b", "<=")
    assert row["kit_card_approval"] == "signed-off checklist"
    assert _row(audit, draft)["kit_card_approval"] == "draft, not signed off"
    assert _row(audit, gone)["limit"] is None
    assert _row(audit, gone)["comparator"] is None


def test_a_row_with_neither_rule_nor_checklist_says_not_recorded(world):
    run_id = _review(world)
    finding = _finding(world, run_id, origin="spec_kit")
    row = _row(_build(world, run_id), finding)
    assert row["limit"] is None and row["kit_card_approval"] is None


@pytest.mark.parametrize(
    ("cols", "basis"),
    [
        ({"match_method": "rule"}, "code"),
        ({"match_method": comparison.METHOD_MODEL_CHOICE}, "AI-suggested"),
        ({"match_method": comparison.METHOD_FIELD_NAME}, "AI-suggested"),
        ({"match_method": comparison.METHOD_ASKED}, "AI-suggested"),
        ({"origin": "ai_engineering_check"}, "AI-suggested"),
        ({"origin": "clause_review"}, "AI-suggested"),
        ({"origin": "web_standard_check"}, "AI-suggested"),
        ({"origin": "chat"}, "engineer"),
        ({"origin": "datasheet_check"}, "code"),
    ],
)
def test_a_row_paired_by_a_model_is_never_labelled_code_proven(world, cols, basis):
    run_id = _review(world)
    finding = _finding(world, run_id, **cols)
    assert _row(_build(world, run_id), finding)["basis"] == basis


def test_rules_in_scope_are_counted_by_standard_without_the_ones_sent_away(world):
    run_id = _review(world)
    before = _build(world, run_id)["rules"]["in_scope_by_standard"]
    _finding(
        world,
        run_id,
        standard_document_id=world["std"],
        compliance_status="MISSING_INFORMATION",
    )
    _finding(
        world,
        run_id,
        standard_document_id=world["std"],
        compliance_status="NOT_IN_DOCUMENT_SCOPE",
    )
    after = _build(world, run_id)["rules"]["in_scope_by_standard"]
    key = f"{world['std']}.pdf"
    assert after[key] == before.get(key, 0) + 1


# ------------------------------------------------------------------ section 5


def _ai_status(run_id, status) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE review_runs SET ai_check_status = ? WHERE id = ?",
            (json.dumps(status), run_id),
        )


def _clause_status(**changes) -> dict:
    return {
        STATUS_KEY: {
            "ran": True,
            "model": "local-model",
            "requirements": 10,
            "calls": 8,
            "cache_hits": 0,
            "verified": 3,
            "no_evidence": 2,
            "unverified": 1,
            "unreadable": 2,
            "failed": [],
            "not_reviewed": [],
            "stopped": None,
            "elapsed_seconds": 12.5,
            **changes,
        }
    }


def _clause_step(audit):
    return next(s for s in audit["ai_use"]["steps"] if s["name"] == "clause_review")


def test_the_clause_review_states_what_it_read_of_the_total(world):
    run_id = _review(world)
    _ai_status(run_id, _clause_status())
    audit = _build(world, run_id)
    step = _clause_step(audit)
    assert step["state"] == "completed"
    assert step["clauses_read_of_total"] == "8 of 10"
    assert step["quotes_verified_of_total"] == "3 of 4"
    assert step["unverified_quotes_dropped"] == 1
    assert step["seconds"] == 12.5
    assert "clauses read of total 8 of 10" in review_audit.render_markdown(audit)


def test_a_clause_review_with_failed_clauses_is_listed_failed_with_its_effect(world):
    run_id = _review(world)
    before = _build(world, run_id)["rules"]["verdict_counts"]
    _ai_status(run_id, _clause_status(failed=["8.1"]))
    audit = _build(world, run_id)
    step = _clause_step(audit)
    assert step["state"] == "failed"
    assert step["effect_on_verdicts"] == review_audit_detail.FAILED_NO_WORSE
    assert audit["rules"]["verdict_counts"] == before


def test_a_clause_review_that_stopped_says_so(world):
    run_id = _review(world)
    _ai_status(run_id, _clause_status(stopped="out of time", not_reviewed=["9"]))
    assert _clause_step(_build(world, run_id))["state"] == "stopped"


def test_an_old_clause_status_without_the_counts_says_not_recorded(world):
    run_id = _review(world)
    _ai_status(run_id, {STATUS_KEY: {"ran": True, "calls": 2}})
    step = _clause_step(_build(world, run_id))
    assert step["clauses_read_of_total"] == review_audit.NOT_RECORDED
    assert step["unverified_quotes_dropped"] is None


def test_the_matcher_and_the_phase_times_are_stated_outside_the_totals(world):
    run_id = _review(world)
    _outcome(
        run_id,
        model_calls=4,
        ai_matcher={"enabled": True, "model": "m", "sent": 9, "asked": 5, "used": 2},
    )
    audit = _build(world, run_id, {"read": {"seconds": 1.5}})
    ai = audit["ai_use"]
    assert ai["matcher"]["asked"] == 5 and ai["matcher"]["model_calls"] == 4
    assert ai["phase_seconds"]["read"] == 1.5
    assert ai["totals"]["fresh"] == audit["run"]["ai_calls_made"]
    md = review_audit.render_markdown(audit)
    assert "matcher (not in the totals): 5 asked of 9 sent; 2 used" in md
    assert "read 1.5 s" in md


def test_the_phase_times_of_a_re_export_come_from_the_stored_trace(world):
    run_id = _review(world)  # the job stored the trace with its timings
    phases = _build(world, run_id)["ai_use"]["phase_seconds"]
    assert phases and set(phases) >= {"read", "compare"}


def test_no_phase_times_says_not_recorded(world):
    run_id = _review(world)
    with connect() as conn:
        conn.execute("DELETE FROM review_run_traces WHERE review_run_id = ?", (run_id,))
    audit = _build(world, run_id)
    assert audit["ai_use"]["phase_seconds"] is None
    assert "time per phase: not recorded" in review_audit.render_markdown(audit)


def test_refused_calls_come_from_the_spend_record_or_read_not_recorded(
    world, monkeypatch
):
    run_id = _review(world)
    audit = _build(world, run_id)
    assert audit["run"]["ai_calls_refused"] is None
    assert "refused calls: not recorded" in review_audit.render_markdown(audit)
    monkeypatch.setattr(
        review_audit.review_audit_rows,
        "run_figures",
        lambda _run: {
            "claude_spend": {
                "refused": 3,
                "usd": 0,
                "asked": 3,
                "calls_charged": 0,
                "batch_calls": 0,
                "usd_estimated": 0,
                "stored_answers": 0,
                "steps": [],
                "held_calls": 0,
                "unreadable_lines": 0,
                "boundary": "this run",
            }
        },
    )
    monkeypatch.setattr(
        review_audit_detail.claude_spend_report, "OUTCOME_KEY", "claude_spend"
    )
    assert _build(world, run_id)["run"]["ai_calls_refused"] == 3


# ------------------------------------------------------------------ section 6


def test_the_certificate_guard_counts_clauses_that_name_their_own_document(world):
    run_id = _review(world)
    before = _gate(_build(world, run_id), "certificate guard")["count"]
    _finding(world, run_id, reason_code=comparison.REQUIRES_OTHER_DOCUMENT)
    _finding(
        world,
        run_id,
        ai_rationale=f"{comparison.REQUIRES_OTHER_DOCUMENT}: an old row",
    )
    _finding(world, run_id, reason_code=comparison.NO_FIELD_MATCHED)
    audit = _build(world, run_id)
    gate = _gate(audit, "certificate guard")
    assert gate["count"] == before + 2
    assert gate["of"] == audit["rules"]["rows_total"]
    assert "#163" in gate["rule_id"]


def test_pass_on_deferred_is_a_gate_with_the_rules_count_and_its_rule_id(world):
    run_id = _review(world)
    audit = _build(world, run_id)
    gate = _gate(audit, "pass_on_deferred")
    assert gate["count"] == audit["rules"]["pass_on_deferred"]
    assert gate["rule_id"] == "owner decision D2"
    assert f"pass_on_deferred: {gate['count']}" in review_audit.render_markdown(audit)


def test_the_nothing_read_guard_counts_only_what_the_job_itself_saw(world, monkeypatch):
    run_id = _review(world)
    # a re-export cannot know the switch the run ran with
    assert _gate(_build(world, run_id), "nothing-read guard")["count"] is None
    monkeypatch.setattr(settings, "nothing_read_fails_enabled", True)
    assert _gate(_build(world, run_id), "nothing-read guard")["count"] is None
    from app import ai_call_ledger

    with ai_call_ledger.open_ledger():
        gate = _gate(_build(world, run_id), "nothing-read guard")
        assert (gate["count"], gate["of"]) == (0, 1)
    monkeypatch.setattr(settings, "nothing_read_fails_enabled", False)
    with ai_call_ledger.open_ledger():
        assert _gate(_build(world, run_id), "nothing-read guard")["count"] is None


def test_the_nothing_read_guard_firing_is_seen_on_any_later_export(world):
    run_id = _review(world)
    _outcome(run_id, error="nothing read: the document could not be read")
    gate = _gate(_build(world, run_id), "nothing-read guard")
    assert (gate["count"], gate["of"]) == (1, 1)
    assert "#1495" in gate["rule_id"]


# ------------------------------------------------------------------ section 7


def _issue(run_id, path, at) -> None:
    from app import crs_issue

    crs_issue.ensure_schema()
    with connect() as conn:
        conn.execute(
            "INSERT INTO crs_issued_copies (id, review_run_id, filename, sha256,"
            " size_bytes, path, issued_by, issued_at) VALUES (?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), run_id, "f.xlsx", "s", 1, path, "adm", at),
        )


def test_the_client_copy_path_is_the_newest_issued_copy_or_not_issued(world):
    run_id = _review(world)
    crs = _build(world, run_id)["crs"]
    assert crs["client_copy_path"] == "not issued"
    assert (
        crs["internal_copy_path"]
        == f"no stored file: GET /api/reviews/runs/{run_id}/crs"
    )
    _issue(run_id, "/copies/old.xlsx", "2026-11-01T00:00:00+00:00")
    _issue(run_id, "/copies/new.xlsx", "2026-11-02T00:00:00+00:00")
    audit = _build(world, run_id)
    assert audit["crs"]["client_copy_path"] == "/copies/new.xlsx"
    assert "client copy: /copies/new.xlsx" in review_audit.render_markdown(audit)


# ---------------------------------------------- a review that did not finish


def _fail_the_compare(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("invented failure")

    monkeypatch.setattr(comparison, "run_comparison", boom)


def _run_again(job_id, monkeypatch) -> None:
    """The next failure is the job's last."""
    monkeypatch.setattr(settings, "job_max_retries", 0)
    with connect() as conn:
        conn.execute(
            "UPDATE jobs SET state = 'running', claimed_by = ? WHERE id = ?",
            (W, job_id),
        )


def _audit_files(root) -> list[Path]:
    return sorted(root.rglob("AUDIT.*"))


def test_a_review_that_failed_for_good_gets_its_audit_and_says_failed(
    world, audit_dir, monkeypatch
):
    monkeypatch.setattr(settings, "review_audit_report_enabled", True)
    _fail_the_compare(monkeypatch)
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) == job_queue.RETRYING
    assert _audit_files(audit_dir) == []  # a retry is not the end of the run
    _run_again(job_id, monkeypatch)
    assert review_jobs.run(job_id, W) == job_queue.POISONED
    md = next(f for f in _audit_files(audit_dir) if f.suffix == ".md").read_text()
    assert f"# Review audit {run_id}" in md
    assert "- status: failed" in md
    stored = connect().execute(
        "SELECT outcome_json FROM review_runs WHERE id = ?", (run_id,)
    )
    assert json.loads(stored.fetchone()[0])["audit_path"] == str(
        _audit_files(audit_dir)[0].parent
    )


def test_a_cancelled_review_gets_its_audit(world, audit_dir, monkeypatch):
    monkeypatch.setattr(settings, "review_audit_report_enabled", True)
    _run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    monkeypatch.setattr(
        review_jobs.nothing_read,
        "read_phase",
        lambda *a: (_ for _ in ()).throw(review_jobs._Cancelled()),
    )
    assert review_jobs.run(job_id, W) == "cancelled"
    md = next(f for f in _audit_files(audit_dir) if f.suffix == ".md").read_text()
    assert "- status: cancelled" in md


def test_with_the_switch_off_a_failed_review_writes_nothing(
    world, audit_dir, monkeypatch
):
    _fail_the_compare(monkeypatch)
    monkeypatch.setattr(
        review_audit, "write", lambda *a, **k: pytest.fail("the switch is off")
    )
    _run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    _run_again(job_id, monkeypatch)
    assert review_jobs.run(job_id, W) == job_queue.POISONED
    assert _audit_files(audit_dir) == []


def test_a_failure_writing_the_end_audit_never_changes_the_job_state(
    world, monkeypatch
):
    monkeypatch.setattr(settings, "review_audit_report_enabled", True)
    monkeypatch.setattr(
        review_jobs,
        "_scope_of",
        lambda _u: (_ for _ in ()).throw(RuntimeError("no scope")),
    )
    _run_id, job_id = _enqueue(world)
    assert review_jobs._audit_ended(job_id) is None


# ----------------------------------------------------------- the re-export tool


def _export_tool():
    path = Path(__file__).resolve().parents[2] / "scripts" / "review_audit_export.py"
    spec = importlib.util.spec_from_file_location("review_audit_export", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_export_tool_writes_from_a_copy_and_leaves_the_switch_as_it_was(
    world, audit_dir, tmp_path, capsys
):
    run_id = _review(world)
    connect().execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    copy = tmp_path / "copy.sqlite"
    shutil.copy2(settings.db_path, copy)
    live = settings.db_path
    assert _export_tool().main(["--db", str(copy), "--run", run_id]) == 0
    assert settings.review_audit_report_enabled is False
    assert settings.db_path == live
    assert [f.name for f in _audit_files(audit_dir)] == ["AUDIT.json", "AUDIT.md"]
    out = capsys.readouterr().out
    assert run_id in out and "not written" not in out


def test_the_export_tool_says_when_a_run_was_not_written(world, tmp_path, capsys):
    _review(world)
    connect().execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    copy = tmp_path / "copy.sqlite"
    shutil.copy2(settings.db_path, copy)
    assert _export_tool().main(["--db", str(copy), "--run", "no-such-run"]) == 1
    assert "not written" in capsys.readouterr().out


def test_the_export_tool_refuses_the_live_database(tmp_path, capsys):
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    live.write_bytes(b"")
    assert _export_tool().main(["--db", str(live), "--run", "x"]) == 2
    assert "refused" in capsys.readouterr().out


def test_the_export_tool_refuses_a_missing_file(tmp_path, capsys):
    gone = tmp_path / "gone.sqlite"
    assert _export_tool().main(["--db", str(gone), "--run", "x"]) == 2
    assert "refused" in capsys.readouterr().out
