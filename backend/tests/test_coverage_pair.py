"""Plan change 6 part B: ONE meaning of "checked", one function, for the bench, the
board call and the CRS. The headline is a pair: risk (wrong among decided) and
coverage (decided of applicable). Synthetic runs, built in code; no model call."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tools import crs_bench

from app import (
    access,
    clause_coverage,
    comparison,
    coverage_pair,
    coverage_values,
    db,
    main,
    review_trace,
    submittal_review,
)
from app.config import settings

NOW = "2026-11-02T00:00:00Z"
REPO = Path(__file__).resolve().parents[2]
SPLIT = {
    "checked": 3,
    "applies_not_checked": 5,
    "does_not_apply": 40,
    "not_used": 7,
    "total": 55,
    "repeats_ignored": 2,
    "applies_not_checked_reasons": [
        {"reason": "no field on the sheet", "count": 3},
        {"reason": "its text could not be read reliably", "count": 2},
    ],
    "does_not_apply_reasons": [],
    "unchecked_share": 0.625,
}


@pytest.fixture(autouse=True)
def _storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "pair.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _doc(doc_id, role, **meta):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf", NOW),
        )
        cols = ["document_id", "suggested_by", "document_role", *meta]
        conn.execute(
            f"INSERT INTO document_classification ({','.join(cols)})"
            f" VALUES ({','.join('?' * len(cols))})",
            [doc_id, "test", role, *meta.values()],
        )
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,"
            "kind,text,token_count,content_hash,retrievable) VALUES (?,?,?,1,1,1,NULL,'prose',"
            "'x',1,?,1)",
            (f"{doc_id}-1", doc_id, f"{doc_id}.pdf", f"h-{doc_id}"),
        )


def _rule(rule_id, text):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO standard_requirements (id,standard_document_id,chunk_id,requirement_text,"
            "source_text,extraction_method,created_at,updated_at)"
            " VALUES (?,'std','std-1',?,?,'extracted',?,?)",
            (rule_id, text, text, NOW, NOW),
        )


def _finding(
    run, status, *, rid=None, origin=None, finding="x", requirement="r", tick=0
):
    fid = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_findings (id,document_id,category,severity,requirement,finding,"
            "required_action,created_at,updated_at,review_run_id,compliance_status,origin,"
            "requirement_source_text,requirement_id,show_for_engineer_tick)"
            " VALUES (?,'sub','c','low',?,?,'a',?,?,?,?,?,?,?,?)",
            (
                fid,
                requirement,
                finding,
                NOW,
                NOW,
                run,
                status,
                origin,
                requirement,
                rid,
                tick,
            ),
        )
    return fid


def _run(split=SPLIT, **outcome):
    run = str(uuid.uuid4())
    body = {"requirement_split": split, **outcome} if split else outcome
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at,"
            "outcome_json) VALUES (?,'sub','completed',?,?,?)",
            (run, NOW, NOW, json.dumps(body)),
        )
    return run


@pytest.fixture
def run():
    """Three rules reached the comparison: one Pass, one Fail, one Pass on a value
    the sheet defers (D2); plus a repeat of the Pass, a checklist Pass, a chat row."""
    _doc("std", "COMPANY_STANDARD", document_number="STD-1")
    _doc("sub", "CONTRACTOR_SUBMITTAL", equipment_type="Centrifugal Pump")
    for rid, text in (
        ("r-pass", "The design pressure shall be at least 12 barg."),
        ("r-pass-repeat", "The design pressure shall be at least 12 barg."),
        ("r-fail", "The flange rating shall be class 300."),
        ("r-d2", "The set pressure shall be stated."),
        ("r-sent", "The material certificate shall be given."),
    ):
        _rule(rid, text)
    r = _run()
    _finding(r, "COMPLIANT", rid="r-pass")
    _finding(r, "COMPLIANT", rid="r-pass-repeat")  # same standard + text: one rule
    _finding(r, "NON_COMPLIANT", rid="r-fail")
    _finding(r, "COMPLIANT", rid="r-d2", finding="340 psig By Contractor")
    _finding(r, "NOT_IN_DOCUMENT_SCOPE", rid="r-sent")
    _finding(r, "COMPLIANT", origin="datasheet_check", requirement="c1")
    _finding(r, "NEEDS_ENGINEER_REVIEW", origin="datasheet_check", requirement="c2")
    _finding(
        r, "COMPLIANT", origin="chat", rid="r-pass"
    )  # an engineer row, never a decision
    return r


def _conn():
    return db.connect()


def _pair(run_id, **kw):
    return coverage_pair.for_run(_conn(), run_id, **kw)


# ------------------------------------------------------------ the definition


def test_applicable_is_what_the_run_states_and_decided_is_pass_or_fail(run):
    p = _pair(run)
    assert p["applicable"] == 8  # checked 3 + applies but not checked 5: nothing else
    assert (p["pass"], p["fail"], p["unknown"]) == (1, 1, 6)
    assert p["decided"] == 2
    assert p["coverage"] == {"decided": 2, "applicable": 8}
    assert "2 of 8" in p["line"]


def test_the_boundary_is_printed_with_what_it_leaves_out(run):
    p = _pair(run)
    assert p["left_out"] == {
        "does_not_apply": 40,
        "covered_by_checklist": 7,
        "stored_repeats": 2,
    }
    for word in ("40", "7", "this run's document"):
        assert word in p["boundary"]


def test_a_pass_on_a_deferred_value_is_not_decided(run):
    p = _pair(run)
    assert p["deferred_passes"] == 1
    _finding(run, "COMPLIANT", rid="r-sent", finding="value TBA")
    assert _pair(run)["decided"] == 2  # a second D2 Pass adds nothing


def test_a_pass_whose_other_reading_defers_the_value_is_not_decided(run):
    """D2, whichever reading the row kept (`value_is_deferred`, the bench's own)."""
    with db.connect() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(submittal_facts)")}
    assert {"id", "value_note", "field_name", "superseded_at"} <= cols
    finding = {"compliance_status": "COMPLIANT", "finding": "x", "fact_id": None}
    assert coverage_pair.value_is_deferred(_conn(), finding) is False
    assert coverage_pair.value_is_deferred(
        _conn(), {**finding, "finding": "12 by contractor"}
    )


def test_risk_is_not_measured_without_a_truth_set_never_zero(run):
    p = _pair(run)
    assert p["risk"] == {"measured": False, "wrong": None, "decided": 2}
    assert coverage_pair.NOT_MEASURED in p["line"]
    assert "0 wrong" not in p["line"]


def test_risk_with_a_truth_set_counts_wrong_among_decided_with_the_denominator(run):
    case = {"wrong": [{"status": "NON_COMPLIANT"}]}
    p = _pair(run, case=case)
    assert p["risk"] == {"measured": True, "wrong": 1, "decided": 2}
    assert "1 wrong of 2 decided" in p["line"]
    named_but_clean = {"wrong": [{"requirement_id": "no-such-rule"}]}
    assert _pair(run, case=named_but_clean)["risk"] == {
        "measured": True,
        "wrong": 0,
        "decided": 2,
    }


def test_a_truth_case_naming_no_wrong_row_is_not_measured_not_zero_wrong(run):
    """All five truth cases hold `wrong: []` today: nothing is known wrong to look for."""
    for case in ({"wrong": []}, {"wrong": [], "untrue": []}, {"kind": "datasheet"}):
        p = _pair(run, case=case)
        assert p["risk"] == {"measured": False, "wrong": None, "decided": 2}
        assert "0 wrong" not in p["line"]
        assert p["checklist"]["wrong"] is None


def test_replayed_counts_wrong_replay_and_a_saved_run_does_not(run):
    case = {"wrong": [], "wrong_replay": [{"status": "NON_COMPLIANT"}]}
    assert _pair(run, case=case, replayed=True)["risk"]["wrong"] == 1
    assert _pair(run, case=case, replayed=False)["risk"]["measured"] is False
    both = {
        "wrong": [{"requirement_id": "no-such-rule"}],
        "wrong_replay": [{"status": "NON_COMPLIANT"}],
    }
    assert _pair(run, case=both, replayed=True)["risk"]["wrong"] == 1
    assert _pair(run, case=both, replayed=False)["risk"]["wrong"] == 0


def test_a_wrong_checklist_verdict_is_printed_beside_zero_wrong_rules(run):
    case = {"wrong": [{"origin": "datasheet_check", "status": "COMPLIANT"}]}
    p = _pair(run, case=case)
    assert p["risk"]["wrong"] == 0 and p["checklist"]["wrong"] == 1
    assert "Wrong checklist verdicts: 1 of 1 decided" in p["line"]
    assert "Wrong checklist verdicts: 1 of 1 decided" in p["checklist_line"]
    m = crs_bench.score(_conn(), run, {"kind": "datasheet", **case})
    result = [{"case": {"name": "x", "run": run}, "config": "c", "stored": m}]
    text = crs_bench.render_markdown(result, {"counting_rule": []}, title="t")
    assert f"| {crs_bench.PAIR_CHECKLIST} | 1/2 (1 wrong) |" in text


def test_a_truth_hit_on_a_deferred_pass_is_not_a_wrong_decision(run):
    p = _pair(run, case={"wrong": [{"status": "COMPLIANT", "requirement_id": "r-d2"}]})
    assert p["risk"]["wrong"] == 0  # the headline's hard stop still counts it


def test_a_run_with_no_statement_has_no_coverage_null_is_nothing_never_zero(run):
    r = _run(split=None)
    p = _pair(r)
    assert p["applicable"] is None and p["unknown"] is None
    assert p["coverage"] == {"decided": 0, "applicable": None}
    assert coverage_pair.coverage_text(p) == ""
    assert " 0 of 0" not in p["line"] and "of None" not in p["line"]


def test_a_run_stored_before_the_split_uses_its_stored_counts(run):
    r = _run(
        split=None, unchecked_counts={"not_compared": 4, "not_applied": 1, "checked": 2}
    )
    assert _pair(r)["applicable"] == 6


def test_decided_above_the_stated_boundary_prints_no_coverage(run):
    r = _run(split={**SPLIT, "checked": 0, "applies_not_checked": 0})
    _finding(r, "COMPLIANT", rid="r-pass")
    p = _pair(r)
    assert p["decided"] == 1 and p["unknown"] is None
    assert coverage_pair.coverage_text(p) == ""
    assert "more than" in p["line"]


def test_the_gate_reason_table_prints_no_decided_above_applicable(run):
    r = _run(split={**SPLIT, "checked": 0, "applies_not_checked": 0})
    _finding(r, "COMPLIANT", rid="r-pass")
    rows = _pair(r)["by_gate_reason"]
    assert rows[0] == {
        "reason": coverage_pair.REACHED,
        "applicable": 0,
        "decided": None,
        "wrong": None,
    }
    m = crs_bench.score(_conn(), r, {"kind": "datasheet"})
    result = [{"case": {"name": "x", "run": r}, "config": "c", "stored": m}]
    text = crs_bench.render_markdown(result, {"counting_rule": []}, title="t")
    assert f"{coverage_pair.REACHED}: 0" in text
    assert f"{coverage_pair.REACHED}: 1/0" not in text


def test_stored_checked_is_never_taken_as_decided(run):
    """A run stored `checked` for rows sent to another document: not a decision."""
    r = _run(split={**SPLIT, "checked": 292, "applies_not_checked": 84})
    _finding(r, "NOT_IN_DOCUMENT_SCOPE", rid="r-sent")
    p = _pair(r)
    assert (p["decided"], p["applicable"]) == (0, 376)


def test_conditional_stays_unknown_three_outcomes_only(run):
    r = _run()
    _finding(r, "CONDITIONAL", rid="r-pass")
    p = _pair(r)
    assert (p["pass"], p["fail"], p["unknown"]) == (0, 0, 8)


def test_a_rule_with_a_pass_and_a_fail_is_one_fail(run):
    r = _run()
    _finding(r, "COMPLIANT", rid="r-pass")
    _finding(r, "NON_COMPLIANT", rid="r-pass-repeat")
    p = _pair(r)
    assert (p["pass"], p["fail"], p["decided"]) == (0, 1, 1)


def test_engineer_rows_and_no_rule_links_are_not_decisions(run):
    r = _run()
    _finding(r, "COMPLIANT", rid="spec_kit:x")
    _finding(r, "COMPLIANT", rid="r-pass", origin="clause_review")
    _finding(r, "COMPLIANT", rid="r-pass", tick=1)
    assert _pair(r)["decided"] == 0


# ------------------------------------------------------------ checklist apart


def test_checklist_is_stated_apart_and_never_added(run):
    p = _pair(run)
    assert p["checklist"] == {
        "decided": 1,
        "rows": 2,
        "pass": 1,
        "fail": 0,
        "wrong": None,
    }
    assert p["decided"] == 2 and p["applicable"] == 8
    assert "1 of 2" in p["checklist_line"]
    assert "stated apart" in p["checklist_line"]


def test_checklist_lane_agrees_with_the_source_row_of_pr_1566(run):
    m = crs_bench.score(_conn(), run, {"kind": "datasheet"})
    row = m["sources"][crs_bench.SRC_CHECKLIST]
    assert (m["pair"]["checklist"]["decided"], m["pair"]["checklist"]["rows"]) == (
        row["decided"],
        row["rows"],
    )


# ------------------------------------------------------------ the breakdowns


def test_per_gate_reason_adds_up_to_the_applicable_rules(run):
    rows = _pair(run)["by_gate_reason"]
    assert sum(r["applicable"] for r in rows) == 8
    assert sum(r["decided"] for r in rows) == 2
    assert rows[0]["reason"] == coverage_pair.REACHED and rows[0]["applicable"] == 3
    assert {
        "reason": "no field on the sheet",
        "applicable": 3,
        "decided": 0,
        "wrong": None,
    } in rows


def test_a_reason_the_run_did_not_record_is_said_not_lost(run):
    r = _run(split={**SPLIT, "applies_not_checked_reasons": []})
    rows = _pair(r)["by_gate_reason"]
    assert sum(x["applicable"] for x in rows) == 8
    assert "no reason recorded" in {x["reason"] for x in rows}


def test_per_equipment_type_never_blends_a_truth_set_with_none(run):
    measured = _pair(run, case={"wrong": [{"requirement_id": "no-such-rule"}]})
    plain = _pair(run)
    other = {**plain, "equipment_type": None, "applicable": None, "decided": 0}
    rows = coverage_pair.by_equipment_type([measured, plain, other])
    pump = rows["Centrifugal Pump"]
    assert (pump["runs"], pump["decided"], pump["applicable"]) == (2, 4, 16)
    assert pump["risk"] == {"measured_runs": 1, "wrong": 0, "decided": 2}
    blank = rows[coverage_pair.NO_TYPE]
    assert blank["applicable"] is None  # no run stated it: nothing, not 0
    assert blank["risk"] == {"measured_runs": 0, "wrong": None, "decided": None}


# ------------------------------------------------------------ one function, three homes


def _board(db_path, run_id, *extra):
    out = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "board_pair.py"),
            "--db",
            str(db_path),
            "--run",
            run_id,
            "--json",
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _client():
    main.app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="t", allowed_document_ids=frozenset({"std", "sub"})
    )
    return TestClient(main.app)


def _crs_notes(run_id):
    scope = access.AccessScope(
        user_id="t", allowed_document_ids=frozenset({"std", "sub"})
    )
    return main._crs_content(run_id, scope, "internal")[1]["review_notes"]


def test_bench_board_and_crs_print_the_same_pair(run, monkeypatch):
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    bench = crs_bench.score(_conn(), run, {"kind": "datasheet"})["pair"]
    board = _board(settings.db_path, run)[0]
    notes = {n["note"]: n["detail"] for n in _crs_notes(run)}
    assert board == bench
    assert bench["line"] in notes[coverage_pair.NOTE]
    assert bench["checklist_line"] in notes[coverage_pair.NOTE_CHECKLIST]
    assert bench["boundary"] in notes[coverage_pair.NOTE]


def test_bench_table_prints_the_pair_below_the_headline_always(run):
    m = crs_bench.score(_conn(), run, {"kind": "datasheet"})
    result = [{"case": {"name": "x", "run": run}, "config": "c", "stored": m}]
    assert settings.one_checked_definition_enabled is False
    text = crs_bench.render_markdown(result, {"counting_rule": []}, title="t")
    last_headline = text.index("| CRS lines |")
    coverage = text.index(f"| {crs_bench.PAIR_COVERAGE} | 2/8 |")
    risk = text.index(f"| {crs_bench.PAIR_RISK} | {coverage_pair.NOT_MEASURED} |")
    assert last_headline < coverage and last_headline < risk
    assert f"| {crs_bench.PAIR_CHECKLIST} | 1/2 |" in text
    assert "Centrifugal Pump" in text.split(crs_bench.PAIR_BY_TYPE)[1]


def test_bench_with_a_truth_case_measures_risk_and_the_gate_ignores_the_pair(run):
    case = {"kind": "datasheet", "wrong": [{"requirement_id": "no-such-rule"}]}
    m = crs_bench.score(_conn(), run, case)
    assert m["pair"]["risk"] == {"measured": True, "wrong": 0, "decided": 2}
    result = {"case": {"name": "x", "run": run, "kind": "datasheet"}, "stored": m}
    worse = json.loads(json.dumps(result))
    worse["stored"]["pair"]["coverage"]["decided"] = 99
    assert (
        crs_bench.gate([result], [worse]) == []
    )  # the gate stays until the owner moves it


def test_a_saved_result_without_the_pair_prints_blank(run):
    m = crs_bench.score(_conn(), run, {"kind": "datasheet"})
    del m["pair"]
    result = [{"case": {"name": "x", "run": run}, "config": "c", "stored": m}]
    text = crs_bench.render_markdown(result, {"counting_rule": []}, title="t")
    assert f"| {crs_bench.PAIR_COVERAGE} |  |" in text


def test_the_bench_prints_no_free_text_gate_reason(run):
    r = _run(
        split={
            **SPLIT,
            "applies_not_checked_reasons": [
                {
                    "reason": "the sentence applies only to words from the standard",
                    "count": 5,
                }
            ],
        }
    )
    m = crs_bench.score(_conn(), r, {"kind": "datasheet"})
    result = [{"case": {"name": "x", "run": r}, "config": "c", "stored": m}]
    text = crs_bench.render_markdown(result, {"counting_rule": []}, title="t")
    assert "words from the standard" not in text
    assert crs_bench.OTHER_REASONS in text


def test_a_saved_bench_result_holds_no_free_text_reason_and_no_document_id(run):
    """`scripts/crs_bench.py --save` writes run_bench's results as they are, and git
    tracks a saved baseline in a public repo. The pair's numbers survive."""
    secret = "the sentence applies only to words from the standard"
    r = _run(
        split={**SPLIT, "applies_not_checked_reasons": [{"reason": secret, "count": 5}]}
    )
    truth = {"cases": [{"name": "x", "run": r, "kind": "datasheet", "wrong": []}]}
    results = crs_bench.run_bench(settings.db_path, truth, do_replay=False)
    saved = json.loads(json.dumps(results, default=str))
    pair = saved[0]["stored"]["pair"]
    assert "words from the standard" not in json.dumps(pair)
    assert "document" not in pair
    assert (
        sum(x["applicable"] for x in pair["by_gate_reason"]) == pair["applicable"] == 8
    )
    raw = coverage_pair.for_run(_conn(), r)
    assert any(
        x["reason"] == secret for x in raw["by_gate_reason"]
    )  # a local screen keeps it


def test_the_board_call_holds_no_free_text_reason(run):
    r = _run(
        split={
            **SPLIT,
            "applies_not_checked_reasons": [
                {"reason": "words from the standard", "count": 5}
            ],
        }
    )
    pair = _board(settings.db_path, r)[0]
    assert "words from the standard" not in json.dumps(pair)
    assert "document" not in pair


STORED_CLAUSE = {
    "applicable": 9,
    "line": "0 of 9 stored line",
    "counts": {"checked": 0},
    "adds_up": True,
}


def _trace_body(run_id):
    client = _client()
    try:
        response = client.get(f"/api/reviews/runs/{run_id}/trace")
    finally:
        main.app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    return response.json()


def _coverage_step(body):
    return next(s for s in body["steps"] if s["step"] == "COVERAGE")


def _stored_run():
    """The real path: the trace is stored when the review ends, whatever the switch
    says later, with the old clause coverage line inside it."""
    r = _run(clause_coverage=STORED_CLAUSE)
    scope = access.AccessScope(
        user_id="t", allowed_document_ids=frozenset({"std", "sub"})
    )
    assert review_trace.store(r, scope) is not None
    return r


def test_switch_on_the_steps_route_says_the_pair_not_the_stored_line(run, monkeypatch):
    """The Steps page shows this route beside the pair."""
    r = _stored_run()
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    body = _trace_body(r)
    assert body["source"].startswith("stored")
    step = _coverage_step(body)
    assert step["summary"].startswith(coverage_pair.for_run(_conn(), r)["line"])
    assert "no checklist coverage recorded" in step["summary"]
    assert "0 of 9" not in json.dumps(body)
    assert not any(k.startswith("clause_") for k in step["counts"])
    assert step["counts"]["applicable"] == 8


def test_switch_on_a_trace_built_now_says_the_pair(run, monkeypatch):
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    r = _run(clause_coverage=STORED_CLAUSE)
    body = _trace_body(r)
    assert body["source"].startswith("built now")
    assert "0 of 9" not in json.dumps(body["steps"])


def test_switch_off_the_steps_route_keeps_the_stored_line(run):
    r = _stored_run()
    step = _coverage_step(_trace_body(r))
    assert step["summary"].startswith("0 of 9")
    assert step["counts"]["clause_applicable"] == 9


def _meta(run_id):
    scope = access.AccessScope(
        user_id="t", allowed_document_ids=frozenset({"std", "sub"})
    )
    return main._crs_content(run_id, scope, "internal")[1]


def test_the_crs_notice_has_one_meaning_of_checked_with_the_switch_on(run, monkeypatch):
    counts = {"not_compared": 5, "not_applied": 40, "checked": 3}
    r = _run(unchecked_counts=counts)
    _finding(r, "NOT_IN_DOCUMENT_SCOPE", rid="r-sent")
    assert "3 checked" in _meta(r)["incomplete_notice"]
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    meta = _meta(r)
    assert "3 checked" not in meta["incomplete_notice"]
    assert "0 decided, 8 apply but were not decided" in meta["incomplete_notice"]
    assert not any("3 checked" in p for p in meta["unchecked_parts"])
    assert not any("3 checked" in (n.get("detail") or "") for n in meta["review_notes"])
    assert not any("Apply but not checked" in p for p in meta["unchecked_parts"])
    assert not any(
        "Apply but not checked" in (n.get("detail") or "") for n in meta["review_notes"]
    )
    assert any("Stopped before a decision (5)" in p for p in meta["unchecked_parts"])


def test_the_board_call_refuses_the_live_database(tmp_path):
    (tmp_path / "backend" / "data").mkdir(parents=True)
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    sqlite3.connect(live).close()
    out = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "board_pair.py"),
            "--db",
            str(live),
            "--run",
            "x",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert out.returncode == 2


# ------------------------------------------------------------ the switch


def test_switch_off_leaves_the_crs_notes_as_they_were(run):
    r = _run(
        clause_coverage={
            "applicable": 9,
            "line": "0 of 9 applicable requirement(s) checked",
        }
    )
    notes = _crs_notes(r)
    names = {n["note"] for n in notes}
    assert clause_coverage.NOTE in names
    assert coverage_pair.NOTE not in names and coverage_pair.NOTE_CHECKLIST not in names
    assert coverage_pair.for_screen(_conn(), r) is None


def test_switch_on_replaces_the_second_denominator_on_the_crs(run, monkeypatch):
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    r = _run(
        clause_coverage={
            "applicable": 9,
            "line": "0 of 9 applicable requirement(s) checked",
        }
    )
    notes = _crs_notes(r)
    names = [n["note"] for n in notes]
    assert clause_coverage.NOTE not in names
    assert names.count(coverage_pair.NOTE) == 1
    assert not any("0 of 9" in (n.get("detail") or "") for n in notes)
    row = next(n for n in notes if n["note"] == coverage_pair.NOTE)
    assert row["count"] == 8  # the stated denominator, never the row count


def test_switch_on_the_screen_route_and_run_detail_carry_the_same_line(
    run, monkeypatch
):
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    want = coverage_pair.for_run(_conn(), run)
    assert coverage_pair.for_screen(_conn(), run) == want
    shown = coverage_pair.screen_coverage(
        {"line": "0 of 9", "applicable": 9}, _conn(), run
    )
    assert shown["line"] == want["line"] and shown["applicable"] == 9
    monkeypatch.setattr(settings, "one_checked_definition_enabled", False)
    off = coverage_pair.screen_coverage({"line": "0 of 9"}, _conn(), run)
    assert off == {"line": "0 of 9"}


def test_the_three_screen_routes_print_the_one_line(run, monkeypatch):
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    client = _client()
    try:
        want = coverage_pair.for_run(_conn(), run)["line"]
        assert client.get(f"/api/reviews/runs/{run}/coverage").json()["line"] == want
        assert (
            client.get(f"/api/reviews/runs/{run}").json()["coverage_pair"]["line"]
            == want
        )
        how = client.get(f"/api/reviews/runs/{run}/summary").json()["how_reviewed"]
        assert how["coverage_pair"]["line"] == want
    finally:
        main.app.dependency_overrides.clear()


def test_switch_off_the_screen_routes_carry_no_pair(run):
    client = _client()
    try:
        assert client.get(f"/api/reviews/runs/{run}").json()["coverage_pair"] is None
        how = client.get(f"/api/reviews/runs/{run}/summary").json()["how_reviewed"]
        assert how["coverage_pair"] is None
        line = client.get(f"/api/reviews/runs/{run}/coverage").json().get("line")
        assert not (line or "").startswith("Standard rules decided")
    finally:
        main.app.dependency_overrides.clear()


def test_a_failing_truth_file_is_not_measured(run, monkeypatch, tmp_path):
    monkeypatch.setattr(coverage_pair, "TRUTH", tmp_path / "absent.json")
    assert _pair(run)["risk"]["measured"] is False
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(coverage_pair, "TRUTH", tmp_path / "broken.json")
    assert _pair(run)["risk"]["measured"] is False


def test_the_truth_file_is_read_by_run_for_every_home(run, monkeypatch, tmp_path):
    truth = tmp_path / "truth.json"
    truth.write_text(
        json.dumps({"cases": [{"run": run, "wrong": [{"status": "NON_COMPLIANT"}]}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(coverage_pair, "TRUTH", truth)
    assert _pair(run)["risk"] == {"measured": True, "wrong": 1, "decided": 2}


def test_kit_cards_and_tick_rows_are_outside_the_checklist_lane(run):
    from app import kit_core

    words = next(k.words for k in kit_core._kits() if k.words)
    r = _run()
    _finding(
        r,
        "NEEDS_ENGINEER_REVIEW",
        origin="datasheet_check",
        requirement=f"{words} card",
    )
    _finding(r, "COMPLIANT", origin="datasheet_check", requirement="c1", tick=1)
    _finding(r, "COMPLIANT", origin="datasheet_check", requirement="c2")
    m = crs_bench.score(_conn(), r, {"kind": "datasheet"})
    assert (m["pair"]["checklist"]["decided"], m["pair"]["checklist"]["rows"]) == (1, 1)
    row = m["sources"][crs_bench.SRC_CHECKLIST]
    assert (row["decided"], row["rows"]) == (1, 1)


# ------------------------------------------------------------ re-review of PR 1590


def test_a_wrong_deferred_checklist_pass_agrees_with_the_headline(run):
    """A known-wrong row that is only a Pass on a deferred value: the headline's hard
    stop counts it, so the pair may not say "0 wrong" and nothing else."""
    r = _run()
    _finding(r, "COMPLIANT", rid="r-pass")
    _finding(r, "NON_COMPLIANT", rid="r-fail")
    _finding(
        r, "COMPLIANT", origin="datasheet_check", requirement="c1", finding="x TBA"
    )
    case = {
        "kind": "datasheet",
        "wrong": [{"origin": "datasheet_check", "deferred": True}],
    }
    m = crs_bench.score(_conn(), r, case)
    assert m["wrong"] == 1
    pair = m["pair"]
    assert pair["wrong_verdicts"] == {"all": 1, "outside": 1}
    # D2 stays undecided: the row is said, not added to the decisions
    assert pair["risk"] == {"measured": True, "wrong": 0, "decided": 2}
    assert pair["checklist"]["decided"] == 0
    assert "Risk: 1 wrong in all; standard rules 0 wrong of 2 decided." in pair["line"]
    assert "Wrong verdicts not counted as decided: 1" in pair["line"]
    result = [{"case": {"name": "x", "run": r}, "config": "c", "stored": m}]
    text = crs_bench.render_markdown(result, {"counting_rule": []}, title="t")
    assert f"| {crs_bench.PAIR_RISK} | 0/2 (1 wrong in all) |" in text
    assert "1 wrong in all" in text.split(crs_bench.PAIR_BY_TYPE)[1]


def test_the_headline_and_the_pair_count_the_same_wrong_rows_stored_and_replayed(run):
    r = _run()
    _finding(
        r, "COMPLIANT", origin="datasheet_check", requirement="c1", finding="x TBA"
    )
    _finding(r, "NON_COMPLIANT", rid="r-fail")
    _finding(r, "COMPLIANT", origin="chat", rid="r-pass")  # on no lane
    case = {
        "kind": "datasheet",
        "wrong": [{"status": "NON_COMPLIANT"}],
        "wrong_replay": [
            {"origin": "datasheet_check", "deferred": True},
            {"origin": "chat"},
        ],
    }
    for replayed, want in ((False, 1), (True, 3)):
        m = crs_bench.score(_conn(), r, case, replayed=replayed)
        assert m["wrong"] == want == m["pair"]["wrong_verdicts"]["all"]
    assert m["pair"]["wrong_verdicts"]["outside"] == 2


def test_no_truth_case_has_no_wrong_verdict_count(run):
    p = _pair(run)
    assert p["wrong_verdicts"] == {"all": None, "outside": None}
    assert "wrong in all" not in p["line"]


def _approval_outcome():
    """The sentence the approval rule really writes, from the danger-zone module."""
    result = comparison.recommend_code(
        [{"compliance_status": "COMPLIANT", "severity": "low"}],
        {"completeness": 1.0, "sufficient": True},
        unchecked_counts={"not_compared": 5, "not_applied": 1, "checked": 3},
    )
    assert coverage_pair.REASON_OLD in result["reason"]
    return result


def test_the_approval_reason_reads_one_meaning_and_the_code_does_not_change(
    run, monkeypatch
):
    result = _approval_outcome()
    r = _run(
        recommended_code=result["code"],
        reason=result["reason"],
        details=result.get("details"),
        unchecked_counts={"not_compared": 5, "not_applied": 1, "checked": 3},
    )
    client = _client()
    try:
        off = client.get(f"/api/reviews/runs/{r}").json()
        assert coverage_pair.REASON_OLD in off["recommended_reason"]
        assert coverage_pair.REASON_OLD in _meta(r)["recommended_code_reason"]
        monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
        on = client.get(f"/api/reviews/runs/{r}").json()
        listed = client.get("/api/reviews/runs").json()["runs"]
    finally:
        main.app.dependency_overrides.clear()
    assert on["recommended_code"] == off["recommended_code"] == result["code"]
    row = next(x for x in listed if x["review_run_id"] == r)
    said = (
        on["recommended_reason"],
        on["recommended_details"],
        row["recommended_reason"],
    )
    assert not any(coverage_pair.REASON_OLD in (text or "") for text in said)
    assert coverage_pair.REASON_NEW in on["recommended_reason"]
    meta = _meta(r)
    assert meta["recommended_code"] == result["code"]
    assert coverage_pair.REASON_NEW in meta["recommended_code_reason"]
    assert coverage_pair.REASON_OLD not in json.dumps(meta)


def _code_step(body):
    return next(s for s in body["steps"] if s["step"] == "CODE")["summary"]


def test_the_code_step_of_the_trace_route_reads_one_meaning(run, monkeypatch):
    result = _approval_outcome()
    r = _run(recommended_code=result["code"], reason=result["reason"])
    built = _trace_body(r)  # no stored trace yet: built now
    assert built["source"].startswith("built now")
    assert coverage_pair.REASON_OLD in _code_step(built)
    scope = access.AccessScope(
        user_id="t", allowed_document_ids=frozenset({"std", "sub"})
    )
    assert review_trace.store(r, scope) is not None
    stored = _trace_body(r)
    assert stored["source"].startswith("stored")
    assert coverage_pair.REASON_OLD in _code_step(stored)
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    on = _trace_body(r)
    assert on["source"].startswith("stored")
    assert coverage_pair.REASON_OLD not in json.dumps(on)
    assert coverage_pair.REASON_NEW in _code_step(on)
    assert _code_step(on).startswith(f"{result['code']} | rule: ")
    fresh = _run(recommended_code=result["code"], reason=result["reason"])
    now = _trace_body(fresh)
    assert now["source"].startswith("built now")
    assert coverage_pair.REASON_OLD not in json.dumps(now)


def test_an_engineers_typed_reason_is_never_reworded(run, monkeypatch):
    typed = f"I read it: 5 of 8 {coverage_pair.REASON_OLD}, and I accept that."
    result = _approval_outcome()
    r = _run(recommended_code=result["code"], reason=result["reason"])
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_runs SET engineer_final_code = ?, override_reason = ?"
            " WHERE id = ?",
            (result["code"], typed, r),
        )
    assert _meta(r)["recommended_code_reason"] == typed
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    assert _meta(r)["recommended_code_reason"] == typed


def test_the_debug_console_and_its_file_read_one_meaning(run, monkeypatch):
    """`review_trace.emit` builds its own trace: it is a home of its own."""
    result = _approval_outcome()
    r = _run(
        recommended_code=result["code"],
        reason=result["reason"],
        clause_coverage=STORED_CLAUSE,
    )
    scope = access.AccessScope(
        user_id="t", allowed_document_ids=frozenset({"std", "sub"})
    )
    log_file = review_trace.debug_dir() / f"review-{r}.log"
    monkeypatch.setattr(settings, "review_debug", True)

    off = "\n".join(review_trace.emit(r, scope))
    assert coverage_pair.REASON_OLD in off and "0 of 9" in off
    assert coverage_pair.REASON_OLD in log_file.read_text(encoding="utf-8")

    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    on = "\n".join(review_trace.emit(r, scope))
    assert coverage_pair.REASON_OLD not in on and "0 of 9" not in on
    assert coverage_pair.REASON_NEW in on
    assert coverage_pair.for_run(_conn(), r)["line"] in on
    written = log_file.read_text(encoding="utf-8")
    assert coverage_pair.REASON_OLD not in written and "0 of 9" not in written


def test_the_stored_reason_itself_is_not_rewritten(run, monkeypatch):
    result = _approval_outcome()
    r = _run(recommended_code=result["code"], reason=result["reason"])
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    _meta(r)
    stored = (
        _conn()
        .execute("SELECT outcome_json FROM review_runs WHERE id = ?", (r,))
        .fetchone()[0]
    )
    assert coverage_pair.REASON_OLD in stored


def test_the_rules_step_of_a_stored_trace_says_one_meaning(run, monkeypatch):
    r = _stored_run()
    words = "not checked or not applying:"
    step = next(s for s in _trace_body(r)["steps"] if s["step"] == "RULES")
    assert words in step["summary"]
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    step = next(s for s in _trace_body(r)["steps"] if s["step"] == "RULES")
    assert words not in step["summary"]
    assert "stopped before a decision or not applying:" in step["summary"]


def test_a_saved_file_has_no_equipment_type_and_the_table_still_does(run, tmp_path):
    truth = {"cases": [{"name": "x", "run": run, "kind": "datasheet", "wrong": []}]}
    results = crs_bench.run_bench(settings.db_path, truth, do_replay=False)
    text = crs_bench.render_markdown(results, truth, title="t")
    assert "Centrifugal Pump" in text.split(crs_bench.PAIR_BY_TYPE)[1]
    out = tmp_path / "saved.json"
    crs_bench.save_results(out, results)
    saved = out.read_text(encoding="utf-8")
    assert "equipment_type" not in saved and "Centrifugal Pump" not in saved
    assert json.loads(saved)[0]["stored"]["pair"]["applicable"] == 8
    assert results[0]["stored"]["pair"]["equipment_type"] == "Centrifugal Pump"
    assert crs_bench.gate(results, json.loads(saved)) == []


def test_the_bench_script_saves_through_the_one_function():
    source = (REPO / "scripts" / "crs_bench.py").read_text(encoding="utf-8")
    assert "crs_bench.save_results(Path(args.save), results)" in source
    assert "write_text(json.dumps(results" not in source


# ------------------------------------------- the footer's one count of values read


def _values_outcome(answered=0, required=4, **more):
    """A run whose gate rests on rule rows with no field tied, while the checklist read
    values: what `comparison.plain_reason` and `_insufficient_reason` really store."""
    completeness = {
        "basis": comparison.BASIS_REQUIRED_FIELDS,
        "fields_required": required,
        "fields_answered": answered,
        "fields_read": 30,
    }
    details = comparison._insufficient_reason(completeness)
    return {
        "recommended_code": "Manual Review Required",
        "reason": comparison.plain_reason(
            "Manual Review Required", details, completeness, None, []
        ),
        "details": details,
        "completeness": completeness,
        **more,
    }


LISTED = {
    **SPLIT,
    "checklist": {"type": "Invented Valve", "items": 11, "standards": 1},
    "checklist_coverage": {"fields": 9, "read": 6, "on_sheet_not_read": 2},
}
SAID = (
    "Read from this datasheet: 6 of the 9 fields the Invented Valve checklist asks"
    " for, each field once (a field read may still defer its value). Of the 8"
    " standard rules that apply, 2 looked for a field on this sheet and a field was"
    " tied to 1 of them. The checklist and the rules are counted apart."
)


def _values_run(split=LISTED, **stored):
    """Two rules looked for a field: one stored twice under two ids (tied on the repeat
    only), one with no field. Left out: a rule that does not apply, one sent to another
    document, an engineer's chat row. Stored counts (`stored`) say 4 ids, as they would."""
    _rule("r-na", "The jacket shall be stated.")
    r = _run(split=split, **stored)
    _finding(r, "NEEDS_ENGINEER_REVIEW", rid="r-pass")
    tied = _finding(r, "NEEDS_ENGINEER_REVIEW", rid="r-pass-repeat")
    _finding(r, "NEEDS_ENGINEER_REVIEW", rid="r-fail")
    na = _finding(r, "NOT_APPLICABLE", rid="r-na")
    _finding(r, "NOT_IN_DOCUMENT_SCOPE", rid="r-sent")
    chat = _finding(r, "NEEDS_ENGINEER_REVIEW", rid="r-d2", origin="chat")
    with db.connect() as conn:
        for fid in (tied, na, chat):
            conn.execute(
                "UPDATE review_findings SET fact_id = 'fact-1' WHERE id = ?", (fid,)
            )
    return r


def _stored(r):
    row = (
        _conn()
        .execute("SELECT outcome_json FROM review_runs WHERE id = ?", (r,))
        .fetchone()
    )
    return json.loads(row[0])


@pytest.mark.parametrize("required", [1, 4, 1200])
def test_the_found_sentences_are_what_the_comparison_stores(required):
    outcome = _values_outcome(0, required)
    count = {"answered": 0, "required": required}
    plain = coverage_values.FOUND_OLD_PLAIN.format(
        s="" if required == 1 else "s", **count
    )
    assert plain in outcome["reason"]
    assert coverage_values.FOUND_OLD_TECHNICAL.format(**count) in outcome["details"]


def test_the_rule_lane_counts_once_per_rule_on_both_sides(run):
    """Not per stored id: a repeat counts once, tied if any of its rows is, and a rule
    that does not apply is not in the count. The same flaw as A-1590 otherwise."""
    r = _values_run(**_values_outcome())
    rules = coverage_values.values_count(_conn(), r, _stored(r))["rules"]
    assert rules == {"tied": 1, "rows": 2, "applicable": 8}


def test_the_footer_prints_one_count_with_its_boundary_in_every_home(run, monkeypatch):
    stored = _values_outcome()
    r = _values_run(**stored)
    old = coverage_values.FOUND_OLD_PLAIN.format(answered=0, required=4, s="s")
    tech = coverage_values.FOUND_OLD_TECHNICAL.format(answered=0, required=4)
    assert old in stored["reason"]
    client = _client()
    try:
        off = client.get(f"/api/reviews/runs/{r}").json()
        monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
        on = client.get(f"/api/reviews/runs/{r}").json()
        listed = client.get("/api/reviews/runs").json()["runs"]
    finally:
        main.app.dependency_overrides.clear()
    row = next(x for x in listed if x["review_run_id"] == r)
    assert off["recommended_reason"] == stored["reason"]
    assert off["recommended_details"] == stored["details"]
    assert coverage_values.values_sentence(_conn(), r, _stored(r)) == SAID
    meta = _meta(r)
    for home in (
        on["recommended_reason"],
        row["recommended_reason"],
        meta["recommended_code_reason"],
    ):
        assert SAID in home
        assert old not in home
    assert SAID.rstrip(".") in on["recommended_details"]
    assert tech not in on["recommended_details"]
    # words only: the code and the stored outcome stay as the gate wrote them
    assert on["recommended_code"] == off["recommended_code"]
    assert meta["recommended_code"] == stored["recommended_code"]
    assert _stored(r)["reason"] == stored["reason"]


def test_the_trace_code_step_says_the_one_count_with_the_switch_on(run, monkeypatch):
    stored = _values_outcome()
    r = _values_run(**stored)
    old = coverage_values.FOUND_OLD_PLAIN.format(answered=0, required=4, s="s")
    assert old in _code_step(_trace_body(r))
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    body = _code_step(_trace_body(r))
    assert old not in body
    assert "6 of the 9 fields" in body


def test_switch_off_leaves_the_found_sentence_word_for_word(run):
    stored = _values_outcome()
    r = _values_run(**stored)
    assert _meta(r)["recommended_code_reason"] == stored["reason"]
    assert coverage_pair.reason_words(stored["reason"], stored, r) == stored["reason"]


def test_an_engineers_typed_reason_keeps_the_found_words(run, monkeypatch):
    stored = _values_outcome()
    typed = "I read it: " + stored["reason"]
    r = _values_run(**stored)
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_runs SET engineer_final_code='Code 2', override_reason=?"
            " WHERE id=?",
            (typed, r),
        )
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    assert _meta(r)["recommended_code_reason"] == typed


def test_the_rule_lane_uses_the_pairs_denominator(run):
    r = _values_run(**_values_outcome())
    assert (
        coverage_values.values_count(_conn(), r, _stored(r))["rules"]["applicable"]
        == _pair(r)["applicable"]
    )


def test_a_run_with_no_checklist_says_the_rules_alone(run):
    r = _values_run(split=SPLIT, **_values_outcome())
    assert coverage_values.values_count(_conn(), r, _stored(r))["checklist"] is None
    said = coverage_values.values_sentence(_conn(), r, _stored(r))
    assert "tied to 1 of them" in said
    assert "checklist" not in said


def test_a_rule_count_above_the_stated_boundary_prints_no_boundary(run):
    small = {**SPLIT, "checked": 0, "applies_not_checked": 1}
    r = _values_run(split=small, **_values_outcome())
    assert (
        coverage_values.values_count(_conn(), r, _stored(r))["rules"]["applicable"]
        is None
    )
    assert coverage_values.values_sentence(_conn(), r, _stored(r)).startswith(
        "Of the standard rules, 2 "
    )


def test_no_rule_that_looked_says_so_never_tied_to_0_of_0(run):
    r = _run(split=SPLIT, **_values_outcome())
    assert coverage_values.values_sentence(_conn(), r, _stored(r)) == (
        "Of the 8 standard rules that apply, none looked for a field on this sheet."
    )


@pytest.mark.parametrize(
    "completeness",
    [
        {},
        {"basis": "nominal", "fields_required": 4},
        {"basis": comparison.BASIS_REQUIRED_FIELDS, "fields_required": 0},
    ],
)
def test_no_rows_counted_leaves_the_stored_words(run, completeness, monkeypatch):
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    outcome = {"requirement_split": LISTED, "completeness": completeness}
    r = _run(split=LISTED, completeness=completeness)
    assert coverage_values.values_count(_conn(), r, outcome) is None
    assert coverage_values.values_sentence(_conn(), r, outcome) is None
    assert coverage_pair.reason_words("as stored", outcome, r) == "as stored"


def test_without_a_run_id_the_stored_words_stand(monkeypatch):
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    stored = {"requirement_split": LISTED, **_values_outcome()}
    assert coverage_pair.reason_words(stored["reason"], stored) == stored["reason"]
