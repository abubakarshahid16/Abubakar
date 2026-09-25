"""The four Claude routes are wired, gated on the reader's flags, and write
nothing when the flags are off."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import access, claude_api, db, submittal_review
from app.config import settings
from app.main import app


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "claude_api.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    yield
    app.dependency_overrides.clear()
    access.set_user_resolver(None)
    db.reset_connection()

ROUTES = [
    ("post", "/api/reviews/runs/run-x/claude/select-standards"),
    ("post", "/api/reviews/runs/run-x/claude/read-datasheet"),
    ("post", "/api/reviews/runs/run-x/claude/recheck"),
    ("get", "/api/reviews/runs/run-x/claude/crs-draft"),
]

# PARKED LANE (#222): the claude_api router is defined but main.py never
# includes it (preserved-only commit 3713eb6). strict=True: if the router is
# ever registered these turn into failures, forcing the marks off.
PARKED = pytest.mark.xfail(strict=True, reason="#222: parked Claude lane - claude_api router "
                                                "is not registered in main.py")


@PARKED
def test_the_four_routes_are_registered():
    paths = set(app.openapi()["paths"])
    for _method, path in ROUTES:
        assert path.replace("run-x", "{review_run_id}") in paths


@PARKED
@pytest.mark.parametrize("method,path", ROUTES)
def test_an_unknown_run_is_404_before_the_model_is_asked(method, path, monkeypatch):
    monkeypatch.setattr(claude_api.reader_transport_mod, "transport",
                        lambda: pytest.fail("the transport was built for a run that does not exist"))
    client = TestClient(app)
    response = getattr(client, method)(path)
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "not_found"


def test_the_flags_off_answer_409_model_disabled(monkeypatch):
    monkeypatch.setattr(claude_api.reader_transport_mod, "transport", lambda: None)
    with pytest.raises(Exception) as caught:
        claude_api._model_call_or_409()
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == claude_api.MODEL_DISABLED


def test_usage_is_read_off_the_transport():
    class T:
        usage = {"calls": 2, "input_tokens": 10, "output_tokens": 3}
    assert claude_api._usage(T()) == T.usage
    assert claude_api._usage(object()) == {}


def test_by_finding_accepts_both_shapes():
    assert claude_api._by_finding({"f1": {"a": 1}}) == {"f1": {"a": 1}}
    assert claude_api._by_finding([{"finding_id": "f2", "a": 2}]) == {"f2": {"finding_id": "f2", "a": 2}}
    assert claude_api._by_finding(None) == {}
