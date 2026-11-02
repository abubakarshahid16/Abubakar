"""#1471: a changed switch reads 'settings differ', the table says what it ran on,
and a Pass on a value any reading marks deferred is a wrong verdict (invented data)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import pytest
from tools import crs_bench

from app import datasheets, db, submittal_review
from app.config import settings
from app.datasheet_checks import LABEL

NOW = "2026-11-01T00:00:00Z"
REPO = Path(__file__).resolve().parents[2]
CHECK = "CHK-1"
WRONG = {
    "origin": "datasheet_check",
    "check": CHECK,
    "status": "COMPLIANT",
    "deferred": True,
}


@pytest.fixture(autouse=True)
def _storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "bench.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES ('sub','s.pdf','h',1,'s.pdf','ready',1,?)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,"
            "kind,text,token_count,content_hash,retrievable)"
            " VALUES ('sub-1','sub','s.pdf',1,1,1,NULL,'prose','x',1,'h',1)"
        )
    yield
    db.reset_connection()


def _fact(value, note=None):
    fact_id = datasheets.create_fact(
        submittal_document_id="sub",
        chunk_id="sub-1",
        field_label="Some field",
        raw_value=value,
        page=1,
    )
    fact_id = fact_id["id"] if isinstance(fact_id, dict) else fact_id
    with db.connect() as conn:
        conn.execute(
            "UPDATE submittal_facts SET value_note = ? WHERE id = ?", (note, fact_id)
        )
    return fact_id


def _run(fact_id, *, status="COMPLIANT", check=CHECK, wording="x"):
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
            " VALUES (?,'sub','completed',?,?)",
            (run, NOW, NOW),
        )
        conn.execute(
            "INSERT INTO review_findings (id,document_id,category,severity,requirement,finding,"
            "required_action,created_at,updated_at,review_run_id,compliance_status,origin,"
            "requirement_source_text,fact_id)"
            " VALUES (?,'sub','c','low','r',?,'a',?,?,?,?,'datasheet_check',?,?)",
            (
                str(uuid.uuid4()),
                wording,
                NOW,
                NOW,
                run,
                status,
                f"{LABEL} {check}: x",
                fact_id,
            ),
        )
    return run


def _wrong(run, *, replayed=True):
    case = {"kind": "datasheet", "wrong": [], "wrong_replay": [WRONG]}
    conn = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
    try:
        return crs_bench.score(conn, run, case, replayed=replayed)["wrong"]
    finally:
        conn.close()


def _both_readings():
    plain = _fact("5")
    _fact("5", "By Contractor")
    return plain


def test_a_pass_on_the_reading_without_the_note_is_wrong_when_another_reading_defers():
    assert _wrong(_run(_both_readings())) == 1


def test_a_pass_whose_wording_says_deferred_is_wrong():
    assert _wrong(_run(_fact("5"), wording="5 By Contractor (page 1)")) == 1


def test_a_pass_with_no_deferred_reading_is_not_wrong():
    assert _wrong(_run(_fact("5"))) == 0


def test_a_query_on_a_deferred_value_is_not_wrong():
    assert _wrong(_run(_both_readings(), status="NEEDS_ENGINEER_REVIEW")) == 0


def test_a_pass_on_another_check_is_not_wrong():
    assert _wrong(_run(_both_readings(), check="CHK-2")) == 0


def test_a_superseded_note_does_not_make_a_pass_wrong():
    plain = _fact("5")
    noted = _fact("5", "By Contractor")
    with db.connect() as conn:
        conn.execute(
            "UPDATE submittal_facts SET superseded_at = ? WHERE id = ?", (NOW, noted)
        )
    assert _wrong(_run(plain)) == 0


def test_the_stored_column_does_not_count_a_replay_only_matcher():
    # a saved run from before D2 keeps its Pass; only the current code is held to this
    assert _wrong(_run(_both_readings()), replayed=False) == 0


def _truth():
    return json.loads((REPO / "eval" / "bench" / "truth.json").read_text())


def _named():
    return [c for c in _truth()["cases"] if c.get("wrong_replay")]


def test_the_truth_names_the_check_by_id_and_meaning_only():
    cases = _named()
    assert len(cases) == 1
    checks = json.loads(
        (REPO / "backend/app/reference/datasheet_checks.json").read_text()
    )
    for matcher in cases[0]["wrong_replay"]:
        assert set(matcher) == {"origin", "check", "status", "deferred", "why"}
        assert matcher["status"] == "COMPLIANT" and matcher["deferred"] is True
        assert f'"{matcher["check"]}"' in json.dumps(checks)


def _baseline():
    return json.loads((REPO / "eval" / "bench" / "baseline.json").read_text())


def test_the_baseline_holds_the_d2_count_and_says_which_switch_it_was_made_on(
    monkeypatch,
):
    case_run = _named()[0]["run"]
    entry = next(b for b in _baseline() if b["case"]["run"] == case_run)
    assert entry["replay"]["checklist_decided"] == 21
    assert entry["case"]["baseline"]["checklist_decided"] == 21
    assert _named()[0]["baseline"]["checklist_decided"] == 21
    # the saved run's own rows did not change
    assert entry["stored"]["checklist_decided"] == 22
    assert all(
        b["config"].endswith("datasheet_one_value_enabled=True") for b in _baseline()
    )


def test_the_switch_changes_the_fingerprint(monkeypatch):
    monkeypatch.setattr(settings, "datasheet_one_value_enabled", True)
    on = crs_bench.fingerprint()
    monkeypatch.setattr(settings, "datasheet_one_value_enabled", False)
    off = crs_bench.fingerprint()
    assert on != off and "datasheet_one_value_enabled=False" in off


def _m(**over):
    return {
        "wrong": 0,
        "checklist_decided": 22,
        "findings": 1,
        "quotes_total": 0,
        "kind_ok": True,
        "kind": "datasheet",
        "run": "r",
        "document": "d",
        "model": None,
        **over,
    }


def test_a_changed_switch_reads_settings_differ_not_a_regression(monkeypatch):
    case = {"name": "t", "run": "r"}
    monkeypatch.setattr(settings, "datasheet_one_value_enabled", True)
    before = [
        {
            "case": case,
            "config": crs_bench.fingerprint(),
            "replay": _m(checklist_decided=21),
            "stored": _m(),
        }
    ]
    monkeypatch.setattr(settings, "datasheet_one_value_enabled", False)
    now = [
        {
            "case": case,
            "config": crs_bench.fingerprint(),
            "replay": _m(),
            "stored": _m(),
        }
    ]
    reasons = crs_bench.gate(now, before)
    assert len(reasons) == 1 and "settings differ" in reasons[0]


def test_a_wrong_verdict_stays_red_even_when_the_settings_differ():
    case = {"name": "t", "run": "r"}
    before = [{"case": case, "config": "a", "replay": _m(), "stored": _m()}]
    now = [{"case": case, "config": "b", "replay": _m(wrong=1), "stored": _m()}]
    reasons = crs_bench.gate(now, before)
    assert any("wrong verdict" in r for r in reasons)


def test_the_table_says_it_ran_on_loaded_settings_and_names_the_switch(monkeypatch):
    monkeypatch.setattr(settings, "datasheet_one_value_enabled", True)
    case = {"name": "t", "run": "r"}
    m = _m(
        untrue=0,
        irrelevant=0,
        checklist_total=1,
        rules_decided=0,
        rules_in_scope=0,
        fails=0,
        sent_away=0,
        quotes_verified=0,
        pages_read=None,
        pages_total=None,
        pass_on_deferred=0,
    )
    table = crs_bench.render_markdown(
        [{"case": case, "config": crs_bench.fingerprint(), "stored": m}], {}, title="T"
    )
    assert "Settings: as loaded" in table
    assert "datasheet_one_value_enabled=True" in table
