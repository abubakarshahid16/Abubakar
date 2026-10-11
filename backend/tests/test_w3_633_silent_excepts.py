"""#633: a caught exception is never swallowed without a trace.

Nine places in backend/app used `except Exception: pass`. A failed audit write,
sweep, scope search or table re-read left no record at all, so a result that
depended on it looked as if the step had simply found nothing.
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from app import access, classification, db, ingest, progress, rule_eval, telemetry
from tools import scope_records
from app.config import settings

APP = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "w633s.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()
    db.init_db()
    yield


def _boom(*_a, **_k):
    raise RuntimeError("boom")


def test_no_broad_except_in_the_app_swallows_the_exception_without_a_trace():
    silent = []
    for path in sorted(APP.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.ExceptHandler)
                    and isinstance(node.type, ast.Name) and node.type.id == "Exception"
                    and all(isinstance(b, (ast.Pass, ast.Import, ast.ImportFrom)) or (
                        isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant))
                        for b in node.body)):
                silent.append(f"{path.relative_to(APP)}:{node.lineno}")
    assert silent == []


def test_a_failed_stage_timing_is_logged(monkeypatch, caplog):
    monkeypatch.setattr(telemetry, "connect", _boom)
    with caplog.at_level(logging.WARNING):
        telemetry.record("chunk", 3, 1.0)
    assert "stage timing" in caplog.text and "RuntimeError" in caplog.text


def test_a_failing_progress_listener_is_logged_and_does_not_fail_the_answer(caplog):
    progress.start("r1")
    progress.listen("r1", _boom)
    with caplog.at_level(logging.WARNING):
        progress.stage("r1", "reading")
    assert "progress listener failed" in caplog.text
    progress.clear()


def test_a_failed_scope_search_is_logged_and_the_other_sources_still_count(caplog):
    with caplog.at_level(logging.WARNING):
        out = scope_records.find_passages("doc-none", search_fn=_boom)
    assert out == []
    assert "scope search" in caplog.text and "RuntimeError" in caplog.text


def test_a_table_that_cannot_be_re_read_is_logged_and_the_clause_text_is_kept(monkeypatch, caplog):
    from app import tables
    conn = db.connect()
    with conn:
        conn.execute("INSERT INTO documents (id, filename, stored_path, sha256, size_bytes, uploaded_at) VALUES ('std1', 'x.pdf', 'x.pdf', 'h', 1, 'now')")
    monkeypatch.setattr(tables, "parse_page_tables", _boom)
    with caplog.at_level(logging.WARNING):
        texts = rule_eval._page_texts({"source_text": "clause", "standard_document_id": "std1", "page": 3})
    assert texts[0] == "clause"
    assert "could not be re-read" in caplog.text


def test_a_failed_audit_write_is_logged(monkeypatch, caplog):
    monkeypatch.setattr(classification, "connect", _boom)
    with caplog.at_level(logging.WARNING):
        classification._audit_equipment_type_change(
            "d1", old_value=None, evidence=type("E", (), {
                "equipment_type": "Pump", "method": "m", "confidence": "low",
                "classifier_version": "v"})(), classified_by="t")
    assert "audit event" in caplog.text


def test_a_failed_stall_diagnosis_is_logged(caplog):
    with caplog.at_level(logging.WARNING):
        ingest._stuck_reason(None, "d1", {}, "chunking")
    assert "stall diagnosis" in caplog.text
