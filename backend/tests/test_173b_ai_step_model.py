"""Order 173.2 (B): an AI step is never skipped silently.

Found on 216400C (s2, 20 Oct): `ai_task_model` defaulted to a tag the engine did
not hold, every scope step failed with a 404, nothing was held, and three false
verdicts reached the engineer. The step now falls back to the installed reader
model and says so; when it still cannot run, its clauses are held (see
`test_141_division_scope.py`). Invented tags only.
"""

from __future__ import annotations

import json
import logging

import pytest

from app import ai_applicability, ai_task_runner, model_transport
from app.config import settings
from app.reasoning_provider import Response
from tests.test_141_division_scope import (  # noqa: F401 - temp_storage is a fixture
    GENERAL,
    PAGES,
    STEEL,
    TITAN,
    FakeModel,
    temp_storage,
)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    ai_task_runner._tags_cache.clear()
    ai_task_runner._logged.clear()
    monkeypatch.setattr(settings, "ai_task_model", "tiny:2b")
    monkeypatch.setattr(settings, "answer_model", "reader:4b")
    yield
    ai_task_runner._tags_cache.clear()
    ai_task_runner._logged.clear()


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


def _ask(monkeypatch, names, caplog):
    ai_task_runner._tags_cache.clear()
    _engine(monkeypatch, names)
    with caplog.at_level(logging.WARNING, logger=ai_task_runner._log.name):
        ai_task_runner.model_status()


def test_the_log_line_comes_once_and_again_after_a_recovery(monkeypatch, caplog):
    def lines():
        return [r for r in caplog.records if "AI review steps" in r.getMessage()]

    _ask(monkeypatch, ["reader:4b"], caplog)
    _ask(monkeypatch, ["reader:4b"], caplog)
    assert len(lines()) == 1  # once per change, not once per call
    _ask(monkeypatch, ["tiny:2b"], caplog)  # the engine holds the tag again
    _ask(monkeypatch, ["reader:4b"], caplog)  # ... and loses it again
    assert len(lines()) == 2


_RAN: list[str] = []  # the tags the readers below were asked as


@pytest.fixture
def store(temp_storage):  # noqa: F811 - the fixture of test_141
    yield


class _Engine(FakeModel):
    """The provider the runner builds, with no weights: notes the tag it was given."""

    def __init__(self, model=None, *, timeout=None):
        super().__init__()
        self.requested_model = model

    def reason(self, packet):
        _RAN.append(self.requested_model)
        return super().reason(packet)


def test_the_division_gate_records_the_model_that_ran_not_the_missing_tag(
    store, monkeypatch
):
    # tiny:2b is configured but not installed; only reader:4b is
    _RAN.clear()
    monkeypatch.setattr(ai_task_runner, "OllamaProvider", _Engine)
    _engine(monkeypatch, ["reader:4b"])
    out = ai_applicability.division_gate(
        [dict(GENERAL), dict(TITAN)],
        classification={"equipment_type": "Pressure vessel"},
        facts=STEEL,
        standard_labels={"std": "XYZ code"},
        provider=None,
        pages_of=lambda sid: PAGES,
    )
    [item] = out["items"]
    assert set(_RAN) == {"reader:4b"}
    assert item["decided_by"] == "ai:reader:4b+code"
    assert "tiny:2b" not in item["decided_by"]
    note = out["summary"]["model_fallback"]
    assert "tiny:2b is not installed" in note and "reader:4b read the scopes" in note


def test_no_fallback_note_when_the_configured_model_ran(store, monkeypatch):
    _RAN.clear()
    monkeypatch.setattr(ai_task_runner, "OllamaProvider", _Engine)
    _engine(monkeypatch, ["tiny:2b", "reader:4b"])
    out = ai_applicability.division_gate(
        [dict(GENERAL), dict(TITAN)],
        classification={"equipment_type": "Pressure vessel"},
        facts=STEEL,
        standard_labels={"std": "XYZ code"},
        pages_of=lambda sid: PAGES,
    )
    assert set(_RAN) == {"tiny:2b"}
    assert out["items"][0]["decided_by"] == "ai:tiny:2b+code"
    assert "model_fallback" not in out["summary"]


class _NoteReader:
    """Answers the clause check: "no", resting on a note."""

    def __init__(self, model=None, *, timeout=None):
        self.requested_model = model

    def reason(self, packet):
        _RAN.append(self.requested_model)
        reply = {
            "applies": "no",
            "reason": "informative_note",
            "quote": "NOTE A vessel may be insulated.",
        }
        return Response(
            text=json.dumps(reply),
            provider="ollama",
            model_tag=self.requested_model,
            digest="d",
            finish_reason="stop",
            prompt_sha256=packet.sha256,
        )


def test_the_clause_gate_records_the_model_that_ran_too(store, monkeypatch):
    _RAN.clear()
    monkeypatch.setattr(ai_task_runner, "OllamaProvider", _NoteReader)
    _engine(monkeypatch, ["reader:4b"])
    clause = "NOTE A vessel may be insulated."
    out = ai_applicability.gate(
        [{"id": "n", "requirement_text": clause, "source_text": clause}],
        classification={"equipment_type": "Pressure vessel"},
        facts=STEEL,
    )
    [item] = out["items"]
    assert set(_RAN) == {"reader:4b"}
    assert item["decided_by"] == "ai:reader:4b+code"
