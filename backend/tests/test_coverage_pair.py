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

from app import access, clause_coverage, coverage_pair, db, main, submittal_review
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
    assert _pair(run, case={"wrong": []})["risk"] == {
        "measured": True,
        "wrong": 0,
        "decided": 2,
    }


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
    measured = _pair(run, case={"wrong": []})
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
    m = crs_bench.score(_conn(), run, {"kind": "datasheet", "wrong": []})
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


def test_switch_defaults_off():
    assert (
        type(settings).model_fields["one_checked_definition_enabled"].default is False
    )


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
