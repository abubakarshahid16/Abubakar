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


#: #655: a handler of ANY exception type whose body is only `pass` (or a
#: docstring) is silent. These are the ones left on purpose, each with its
#: reason; anything else fails the test below.
SILENT_ALLOWED = {
    # control flow, not a failure: the plan-only pass stops by raising it
    ("datasheets.py", "_extract_facts_by_plan", "_PlanOnly"),
    # review path (order 3): left for the review-path owner, see #655
    ("rule_eval.py", "rule_for", "ValueError"),
    # not in #655's list; a lock file that vanished or cannot be read is
    # handled by the caller's next attempt
    ("heavy_lock.py", "try_acquire", "OSError"),
    ("heavy_lock.py", "waiters", "OSError"),
    ("heavy_lock.py", "acquire", "OSError"),
    ("heavy_lock.py", "release", "OSError"),
    ("docx_reader.py", "__init__", "ValueError"),
    ("claude_datasheet.py", "facts_before_the_cut", "(json.JSONDecodeError, TypeError)"),
}


def _silent_handlers() -> set[tuple[str, str, str]]:
    found = set()
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if (isinstance(node, ast.ExceptHandler) and node.type is not None
                        and all(isinstance(b, ast.Pass) or (
                            isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant))
                            for b in node.body)):
                    found.add((str(path.relative_to(APP)), func.name, ast.unparse(node.type)))
    return found


def test_no_new_silent_handler_of_any_exception_type():
    """#655: the broad-except guard above only saw `except Exception`. A
    narrower `except OSError: pass` is just as silent; each one now logs its
    error type, or is in `SILENT_ALLOWED` with the reason."""
    assert _silent_handlers() - SILENT_ALLOWED == set()


def test_a_cache_file_that_cannot_be_swept_is_logged(tmp_path, monkeypatch, caplog):
    from app import vectorcache
    monkeypatch.setattr(vectorcache, "cache_dir", lambda: tmp_path)
    (tmp_path / "old-layout.f32").write_bytes(b"x")

    def refuse(self, *a, **k):
        raise PermissionError("mapped by another process")
    monkeypatch.setattr(Path, "unlink", refuse)
    with caplog.at_level(logging.INFO, logger="app.vectorcache"):
        vectorcache._sweep("current")
    assert "kept a superseded file (PermissionError)" in caplog.text
    assert "mapped by another process" not in caplog.text, "only the error type is logged"


def test_a_reader_error_body_that_is_not_json_is_logged_and_the_status_kept(monkeypatch, caplog):
    import httpx

    from app import reader_transport

    class NotJson:
        status_code = 529
        content = b"<html>overloaded</html>"
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

        def json(self):
            raise ValueError("Expecting value")

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, content=None):
            return NotJson()

    monkeypatch.setenv("STANDARDS_READER_ENABLED", "1")
    monkeypatch.setenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "1")
    monkeypatch.setattr(httpx, "Client", Client)
    send = reader_transport.transport()
    with caplog.at_level(logging.DEBUG, logger="app.reader_transport"), \
            pytest.raises(httpx.HTTPStatusError, match="529"):
        send("https://api.anthropic.com/v1/messages", headers={}, body={"m": 1}, timeout=1.0)
    assert "was not JSON (ValueError)" in caplog.text
    assert "overloaded" not in caplog.text


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
