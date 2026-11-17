"""Order 14 LPV, V4: a datasheet run records its equipment type (or "type unsure: <reason>", never empty); the CRS names the local
model a rule check ran on when the run stored it; a discipline is never an equipment type; "decided by" says nobody decided yet
instead of "not recorded". Invented data only."""

from __future__ import annotations

import json
import sqlite3

from app import agent_review_kind as K
from app import crs_ai_header, crs_one, run_record, subject_scope
from tests.test_agent_general_review import job_world, start, world  # noqa: F401  (fixtures)


def _reading(kind="datasheet", equipment=None, unsure=None, known=True):
    return K.PaperReading(
        kind, known, "read by code", "title", False, equipment, None, None, (), unsure
    )


def test_a_datasheet_run_records_its_type_or_why_it_is_unsure_never_empty():
    assert _reading(equipment="pump").equipment_record == "pump"
    assert _reading(
        unsure="read as one type, the sheet states a code of another"
    ).equipment_record == (
        "type unsure: read as one type, the sheet states a code of another"
    )
    assert _reading().equipment_record == K.UNSURE_PREFIX + K.NO_TYPE_REASON
    assert (
        _reading(kind="test_record").equipment_record == "not a datasheet (test record)"
    )  # never empty, says why
    assert (
        _reading(known=False).equipment_record
        == K.UNSURE_PREFIX + K.KIND_UNKNOWN_REASON
    )
    assert (
        _reading().equipment_type is None
    )  # every rule decision still reads None when the type is unsure


def test_the_reason_is_the_readers_own_doubt_without_its_lead(monkeypatch):
    from app import classification, datasheets

    monkeypatch.setattr(datasheets, "list_facts", lambda *_a, **_k: [])
    monkeypatch.setattr(
        classification, "of_document", lambda _d: {"equipment_type": "Widget"}
    )
    monkeypatch.setattr(
        subject_scope,
        "read_equipment",
        lambda *_a: (
            set(),
            "unsure",
            {"reason": "equipment type unsure: read as a widget, but X"},
        ),
    )
    assert K.equipment_reading("d", frozenset()) == (
        None,
        "unsure",
        "read as a widget, but X",
    )
    monkeypatch.setattr(
        subject_scope, "read_equipment", lambda *_a: ({"pump"}, "title", None)
    )
    assert K.equipment_reading("d", frozenset()) == ("pump", "title", None)


def test_the_ai_run_row_stores_the_record(monkeypatch, tmp_path):
    from app import agent_review_jobs

    con = sqlite3.connect(tmp_path / "x.sqlite")
    con.execute(
        "CREATE TABLE agent_review_run (run_id TEXT PRIMARY KEY, submittal_document_id TEXT, paper_kind TEXT, kind_source TEXT,"
        " equipment_type TEXT, started_at TEXT)"
    )
    monkeypatch.setattr(agent_review_jobs, "connect", lambda: con)
    agent_review_jobs._write_run_start(
        "r1", "d", _reading(unsure="why"), "2026-01-01T00:00:00Z"
    )
    assert (
        con.execute("SELECT equipment_type FROM agent_review_run").fetchone()[0]
        == "type unsure: why"
    )


def test_the_rule_checks_equipment_record_from_its_outcome():
    assert (
        crs_one.rule_check_equipment(
            json.dumps({"applicability": {"submittal_equipment": ["pump"]}})
        )
        == "pump"
    )
    unsure = {
        "applicability": {
            "submittal_equipment": [],
            "equipment_unsure": "equipment type unsure: read as A, but B",
        }
    }
    assert (
        crs_one.rule_check_equipment(json.dumps(unsure))
        == "type unsure: read as A, but B"
    )
    assert (
        crs_one.rule_check_equipment(json.dumps({})) is None
        and crs_one.rule_check_equipment(None) is None
    )


def _engine_db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE review_engine_choice (run_id TEXT, plan_json TEXT)")
    con.execute(
        "INSERT INTO review_engine_choice VALUES ('rc', ?)",
        (json.dumps({"parts": [{"name": "rule_check", "engine": "local"}]}),),
    )
    con.execute(
        "CREATE TABLE model_call_metrics (review_run_id TEXT, model TEXT, day TEXT, calls INTEGER, errors INTEGER,"
        " seconds_total REAL, seconds_longest REAL, error_kinds TEXT, gold_score REAL, created_at TEXT)"
    )
    return con


def test_the_rule_checks_engine_names_the_local_model_it_stored():
    con = _engine_db()
    assert (
        crs_one._engine_of(con, "rc", "", "rule_check")
        == "Local (model name not recorded)"
    )  # an old run: said so
    con.execute(
        "INSERT INTO model_call_metrics VALUES ('rc', 'invented-local-7b', 'd', 3, 0, 1, 1, '{}', NULL, 'x')"
    )
    run = {
        "model_name": None,
        "outcome_json": json.dumps(
            {"ai_matcher": {"asked": 2, "model": "ollama:invented-local-7b"}}
        ),
    }
    names = run_record.models_used(con, "rc", run)
    assert names == {
        "claude": [],
        "local": ["invented-local-7b"],
        "unknown": [],
    }  # the name once, not "X, ollama:X"
    assert (
        crs_one._engine_of(con, "rc", "", "rule_check", names)
        == "Local (invented-local-7b)"
    )
    both = run_record.models_used(con, "rc", {**run, "model_name": "claude-invented-1"})
    assert both["claude"] == ["claude-invented-1"]
    marked = {
        **run,
        "model_name": "claude-invented-1",
        "ai_check_status": json.dumps(
            {"calls_made": 1, "model": "claude:claude-invented-1"}
        ),
    }
    assert run_record.models_used(con, "rc", marked)["claude"] == [
        "claude-invented-1"
    ]  # once, not "X, claude:X"
    assert crs_one._engine_of(con, "rc", "claude-invented-1", "rule_check", both) == (
        "Claude and Local (claude-invented-1, invented-local-7b)"
    )
    # no engine choice stored and a local name stored: the engine cell names it (never "not recorded" beside a models row)
    con.execute("DELETE FROM review_engine_choice")
    assert (
        crs_one._engine_of(con, "rc", "", "rule_check", names)
        == "Local (invented-local-7b)"
    )


def test_the_header_reads_the_runs_names_and_the_ai_record_first(monkeypatch):
    con = _engine_db()
    con.execute(
        "CREATE TABLE review_runs (id TEXT, model_name TEXT, outcome_json TEXT, completed_at TEXT, started_at TEXT)"
    )
    con.execute(
        "CREATE TABLE agent_review_run (run_id TEXT, models_json TEXT, finished_at TEXT, started_at TEXT, paper_kind TEXT,"
        " equipment_type TEXT, usd REAL, counts_json TEXT)"
    )
    outcome = {
        "applicability": {
            "submittal_equipment": [],
            "equipment_unsure": "equipment type unsure: read as A, but B",
        }
    }
    con.execute(
        "INSERT INTO review_runs VALUES ('rc', NULL, ?, 'd', 'd')",
        (json.dumps(outcome),),
    )
    con.execute(
        "INSERT INTO model_call_metrics VALUES ('rc', 'invented-local-7b', 'd', 3, 0, 1, 1, '{}', NULL, 'x')"
    )
    con.execute(
        "INSERT INTO agent_review_run VALUES ('ai', '[]', 'd', 'd', 'datasheet', 'pump', NULL, '{}')"
    )
    monkeypatch.setattr(crs_one, "connect", lambda: con)
    rc, ai = crs_one._run_facts({"rc_run": "rc", "ai_run": "ai"})
    assert rc["engine"] == "Local (invented-local-7b)" and rc["models"] == [
        "invented-local-7b"
    ]
    assert rc["equipment"] == "type unsure: read as A, but B"
    monkeypatch.setattr(crs_one.crs_ai_header, "document_header", lambda *_a: {})
    monkeypatch.setattr(crs_one, "connect", lambda: _FakeDocs(con))
    assert (
        crs_one._paper_facts("d", [rc, ai])["equipment"] == "pump"
    )  # the AI review's own record first
    assert (
        crs_one._paper_facts("d", [rc, {**ai, "equipment": None}])["equipment"]
        == rc["equipment"]
    )


class _FakeDocs:
    """The documents table the header reads, over the test connection."""

    def __init__(self, con):
        self.con = con

    def execute(self, sql, args=()):
        if "FROM documents" in sql:
            return self.con.execute("SELECT 'paper.pdf' AS filename")
        return self.con.execute(sql, args)


def _gates():
    import importlib.util
    import pathlib
    import sys

    path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "crs_gates.py"
    spec = importlib.util.spec_from_file_location("lpv_crs_gates", path)
    gates = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = (
        gates  # a dataclass module must be registered while it loads
    )
    spec.loader.exec_module(gates)
    return gates


def test_the_gates_report_keeps_the_papers_reason_out():
    """The report may be pasted into a PR: the run's recorded "type unsure: <reason derived from the paper>" reaches it as the
    words "type unsure" alone, through the report's own reading of the run (`paper_facts`)."""
    gates = _gates()
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(
        "CREATE TABLE review_runs (id TEXT, submittal_document_id TEXT);"
        "CREATE TABLE agent_review_run (run_id TEXT, paper_kind TEXT, equipment_type TEXT);"
        "CREATE TABLE agent_review_missing_book (run_id TEXT, name TEXT);"
    )
    con.execute("INSERT INTO review_runs VALUES ('r', 'd')")
    con.execute(
        "INSERT INTO agent_review_run VALUES ('r', 'datasheet', 'type unsure: read as A (page 4), but B')"
    )
    facts = gates.paper_facts(con, "r")
    assert facts["equipment"] == "type unsure" and "page 4" not in str(facts)
    assert gates.recorded_type("not a datasheet (procedure)") == "not a datasheet"
    assert gates.recorded_type("pump") == "pump" and gates.recorded_type(None) is None


def test_a_general_review_run_records_why_it_has_no_type(job_world):  # noqa: F811  (the fixture, imported above)
    from app import agent_review_jobs, db

    run_id, job_id = start()
    agent_review_jobs.run(job_id, "w")
    row = (
        db.connect()
        .execute(
            "SELECT equipment_type FROM agent_review_run WHERE run_id = ?", (run_id,)
        )
        .fetchone()
    )
    assert row[0] == "not a datasheet (procedure)"


def test_a_discipline_is_never_an_equipment_type():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(
        "CREATE TABLE document_classification (document_id TEXT, project TEXT, document_number TEXT, title TEXT, revision TEXT,"
        " effective_date TEXT, discipline TEXT, discipline_canonical TEXT, equipment_type TEXT)"
    )
    con.execute(
        "INSERT INTO document_classification (document_id, equipment_type) VALUES ('d', 'Widget pump')"
    )
    assert crs_ai_header.document_header(con, "d", "pump")["discipline"] == ""


def test_decided_by_says_nobody_decided_yet(monkeypatch):
    monkeypatch.setattr(crs_one.decisions_mod, "people", lambda _p: [])
    assert crs_one._people("d", {}) == crs_one.NO_DECISION_YET
    monkeypatch.setattr(crs_one.decisions_mod, "people", lambda _p: ["u1"])
    assert crs_one._people("d", {"u1": "Engineer A"}) == "Engineer A"
