"""Order 173.2 (B): an AI step is never skipped silently.

Found on 216400C (s2, 20 Oct): `ai_task_model` defaulted to a tag the engine did
not hold, every scope step failed with a 404, nothing was held, and three false
verdicts reached the engineer. The step now falls back to the installed reader
model and says so; when it still cannot run, its clauses are held (see
`test_141_division_scope.py`). Invented tags only.
"""

from __future__ import annotations

import pytest

from app import ai_task_runner, model_transport
from app.config import settings


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    ai_task_runner._tags_cache.clear()
    monkeypatch.setattr(settings, "ai_task_model", "tiny:2b")
    monkeypatch.setattr(settings, "answer_model", "reader:4b")
    yield
    ai_task_runner._tags_cache.clear()


def _engine(monkeypatch, names):
    def fake_get(path, *, timeout, required=True):
        assert path == "/api/tags"
        if names is None:
            raise ConnectionError("down")
        return {"models": [{"name": n} for n in names]}

    monkeypatch.setattr(model_transport, "get_json", fake_get)


def test_the_configured_tag_is_used_when_the_engine_holds_it(monkeypatch):
    _engine(monkeypatch, ["tiny:2b", "reader:4b"])
    status = ai_task_runner.model_status()
    assert status["used"] == "tiny:2b" and status["fallback"] is False
    assert ai_task_runner.make_provider().requested_model == "tiny:2b"


def test_a_tag_the_engine_does_not_hold_falls_back_to_the_installed_reader(monkeypatch):
    _engine(monkeypatch, ["reader:4b", "big:9b"])
    status = ai_task_runner.model_status()
    assert status["used"] == "reader:4b" and status["fallback"] is True
    assert "tiny:2b is not installed" in status["reason"]
    assert ai_task_runner.make_provider().requested_model == "reader:4b"
    assert ai_task_runner.model_in_use() == "reader:4b"


def test_neither_tag_installed_keeps_the_configured_tag_and_says_why(monkeypatch):
    _engine(monkeypatch, ["other:1b"])
    status = ai_task_runner.model_status()
    assert status["used"] == "tiny:2b" and status["fallback"] is False
    assert "neither tiny:2b nor reader:4b is installed" in status["reason"]


def test_an_engine_that_cannot_be_asked_changes_nothing(monkeypatch):
    _engine(monkeypatch, None)
    status = ai_task_runner.model_status()
    assert status["used"] == "tiny:2b" and status["engine_asked"] is False


def test_an_explicit_model_is_never_replaced(monkeypatch):
    _engine(monkeypatch, ["reader:4b"])
    assert ai_task_runner.make_provider("chosen:7b").requested_model == "chosen:7b"


def test_a_fallback_is_a_warning_on_the_metrics_surface(monkeypatch, tmp_path):
    from app import db, fts_index, metrics

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "m.sqlite")
    db.reset_connection()
    db.init_db()
    fts_index.ensure_schema()
    try:
        _engine(monkeypatch, ["reader:4b"])
        warned = metrics.snapshot({"busy": False}, None, True)["warnings"]
        found = [w for w in warned if w["code"] == "ai_steps_model"]
        assert len(found) == 1 and found[0]["severity"] == "warning"
        assert "tiny:2b is not installed" in found[0]["message"]
        assert "reader:4b instead" in found[0]["message"]
        ai_task_runner._tags_cache.clear()
        _engine(monkeypatch, ["tiny:2b"])
        warned = metrics.snapshot({"busy": False}, None, True)["warnings"]
        assert not [w for w in warned if w["code"] == "ai_steps_model"]
        ai_task_runner._tags_cache.clear()
        _engine(monkeypatch, ["other:1b"])
        [none] = ai_task_runner.warnings()
        assert "held for the engineer" in none["message"]
    finally:
        db.reset_connection()
