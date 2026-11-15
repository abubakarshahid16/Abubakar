"""The role record route: behind the switch, scope-checked, a document the caller may not read counted and never named."""

# ruff: noqa: F811
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import db, nine_record
from app.api import nine_roles
from app.main import app
from app.nine_contract import ReadEntry
from tests.test_p3_review_jobs import temp_storage, world  # noqa: F401 - fixtures

SECRET_TITLE = "unreadable-secret-name.pdf"


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(nine_roles, "switch_on", lambda: True)


def _record(world):
    run_id = "run-nine"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at) VALUES (?,?, 'running', 't', 't')",
            (run_id, world["sub"]),
        )
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES ('hidden',?,?,1,'h.pdf','ready',1,'t')",
            (SECRET_TITLE, "h" * 64),
        )
    nine_record.start_run(run_id)
    reads = [
        ReadEntry(
            4, "c1", world["sub"], "paper", (1,), None, None, None, 10, "a" * 64, 0
        ),
        ReadEntry(4, "c1", "hidden", "rule_book", (4,), "4", 1, 1, 20, "b" * 64, 0),
    ]
    nine_record.call_sent(
        run_id,
        4,
        "c1",
        step="nine_reviewer",
        engine="claude",
        model="m",
        request_sha256="d" * 64,
        reads=reads,
    )
    nine_record.call_end(run_id, "c1", "answered", usd=0.12)
    nine_record.role_end(run_id, 4, "ran", produced={"findings": 3})
    return run_id


def test_the_route_is_off_while_the_switch_is_off(world):
    run_id = _record(world)
    r = TestClient(app).get(f"/api/reviews/runs/{run_id}/roles", headers=world["admin"])
    assert r.status_code == 404 and "feature_off" in r.text


def test_the_record_is_shown_with_the_unreadable_document_counted_and_never_named(
    world, on
):
    run_id = _record(world)
    r = TestClient(app).get(f"/api/reviews/runs/{run_id}/roles", headers=world["admin"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert (
        len(body["roles"]) == 9
        and body["roles"][3]["state"] == "ran"
        and body["roles"][3]["usd"] == 0.12
    )
    role = body["roles"][3]
    assert [x["title"] for x in role["reads"]] == ["sub_pump.pdf"] and role[
        "not_readable"
    ] == 1
    assert (
        SECRET_TITLE not in r.text and "hidden" not in r.text
    )  # counted, never named, not even by id
    assert (
        body["roles"][0]["state"] == "not_run"
        and "Roles run: 1 of 9" in body["roles_line"]
    )
    assert body["boundary"] == "documents you may read"


def test_a_run_the_caller_may_not_read_and_a_run_with_no_role_rows_are_404(world, on):
    client = TestClient(app)
    assert (
        client.get("/api/reviews/runs/nope/roles", headers=world["admin"]).status_code
        == 404
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at) VALUES ('old', ?, 'completed','t','t')",
            (world["sub"],),
        )
    r = client.get("/api/reviews/runs/old/roles", headers=world["admin"])
    assert r.status_code == 404 and "no role record" in json.dumps(r.json())
