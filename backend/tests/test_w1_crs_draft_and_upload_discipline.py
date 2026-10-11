"""W1: a Claude review route answers a run the caller may not read with the
same 404 as a missing one (#658), and an upload names at least one discipline,
so no document is left visible to nobody (#609).

The crs-draft route these tests were first written for (#441) was deleted with
`claude_crs_comments` (#736, F8c row 1): no screen called it. The 404 rule is
shared by every route through `claude_api._run_or_404`; it is tested here on
the recheck route.

An upload with an identity used to be granted to the admin capability only,
which left it visible to no discipline until an administrator noticed. It now
names its disciplines, defaulting to the uploader's own, and the API refuses
one with none before any byte is stored. No network: the Claude transport is
a fake.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app import access, claude_api, db, submittal_review
from app.config import settings
from app.db import connect
from app.main import app

NOW = "2026-10-08T00:00:00Z"
KEY = "sk-ant-test-NEVER-IN-A-LOG-0123456789"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "w1.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setenv("STANDARDS_READER_ENABLED", "true")
    monkeypatch.setenv("STANDARDS_READER_ALLOW_PUBLIC_EGRESS", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.delenv("STANDARDS_READER_MODEL", raising=False)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    with connect() as conn:
        for uid in ("admin_user", "engineer", "outsider"):
            conn.execute(
                "INSERT INTO users (id,email,display_name,password_hash,created_at)"
                " VALUES (?,?,?,?,?)", (uid, f"{uid}@test.local", uid, "hash", NOW))
        for rid, name, kind in (("role_admin", "admin", "capability"),
                                ("role_civil", "Civil", "discipline"),
                                ("role_mech", "Mechanical", "discipline")):
            conn.execute(
                "INSERT INTO roles (id,name,description,kind,created_at) VALUES (?,?,?,?,?)",
                (rid, name, name, kind, NOW))
        for uid, rid in (("admin_user", "role_admin"), ("engineer", "role_civil"),
                         ("outsider", "role_mech")):
            conn.execute("INSERT INTO user_roles (user_id,role_id,granted_at) VALUES (?,?,?)",
                         (uid, rid, NOW))
        # One submittal, readable by Civil only, and one review run on it.
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,uploaded_at)"
            " VALUES ('doc-1','sub.pdf','sha-1',1,'x',?)", (NOW,))
        conn.execute(
            "INSERT INTO document_role_access (document_id,role_id,permission,granted_at)"
            " VALUES ('doc-1','role_civil','read',?)", (NOW,))
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
            " VALUES ('run-1','doc-1','completed',?,?)", (NOW, NOW))
    access.set_user_resolver(lambda request: request.headers.get("x-test-user"))
    yield
    access.set_user_resolver(None)
    app.dependency_overrides.clear()
    db.reset_connection()


def _as(user: str | None) -> dict:
    return {"x-test-user": user} if user else {}


def _no_transport(monkeypatch):
    monkeypatch.setattr(claude_api.reader_transport_mod, "transport",
                        lambda: pytest.fail("the Claude transport was built"))


RECHECK = "/api/reviews/runs/{}/claude/recheck"


# ------------------------------------------------------- #658 the same 404

def _without_time(body):
    """The body with every `at` timestamp removed, at any depth."""
    if isinstance(body, dict):
        return {k: _without_time(v) for k, v in body.items() if k != "at"}
    if isinstance(body, list):
        return [_without_time(v) for v in body]
    return body


def test_the_time_filter_removes_only_the_timestamp():
    """Guards the filter itself: a difference in code or message must survive it,
    or the 404 comparison above would pass for two different refusals."""
    a = {"detail": {"code": "not_found", "message": "x", "at": "t1"}}
    assert _without_time(a) == _without_time({"detail": {"code": "not_found", "message": "x", "at": "t2"}})
    assert _without_time(a) != _without_time({"detail": {"code": "forbidden", "message": "x", "at": "t1"}})
    assert _without_time(a) != _without_time({"detail": {"code": "not_found", "message": "y", "at": "t1"}})


def test_a_run_the_caller_cannot_read_is_the_same_404_as_a_missing_one(monkeypatch):
    _no_transport(monkeypatch)
    client = TestClient(app)
    hidden = client.post(RECHECK.format("run-1"), headers=_as("outsider"))
    missing = client.post(RECHECK.format("run-none"), headers=_as("outsider"))
    assert hidden.status_code == 404, hidden.text
    # The 404 body carries `at`, the time to the second (errors.safe_error); two
    # requests either side of a second boundary differ in nothing else (#658).
    # Everything else - code, message, the detail - must still be identical.
    assert _without_time(hidden.json()) == _without_time(missing.json())


# ------------------------------------------------- #609 upload disciplines

def _pdf(marker: bytes) -> bytes:
    return b"%PDF-1.4\n" + marker * 5000 + b"\n%%EOF\n"


def _upload(user: str, disciplines: list[str] | None, marker: bytes = b"u"):
    data = {"disciplines": disciplines} if disciplines is not None else None
    return TestClient(app).post(
        "/api/documents", headers=_as(user), data=data,
        files={"file": ("spec.pdf", io.BytesIO(_pdf(marker)), "application/pdf")})


def _count(table: str) -> int:
    return connect().execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


@pytest.mark.parametrize("disciplines", [None, [], ["  "]])
def test_an_upload_with_no_discipline_is_refused_and_stores_nothing(disciplines):
    before = _count("documents")
    response = _upload("engineer", disciplines)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "invalid_parameter"
    assert "discipline" in response.json()["detail"]["message"]
    assert _count("documents") == before
    assert _count("jobs") == 0


def test_an_engineer_cannot_share_an_upload_with_a_discipline_they_are_not_in():
    before = _count("documents")
    response = _upload("engineer", ["Mechanical"])
    assert response.status_code == 422, response.text
    assert _count("documents") == before


def test_an_upload_is_granted_to_its_chosen_discipline_and_its_uploader_sees_it():
    response = _upload("engineer", ["Civil"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["awaiting_grant"] is False
    doc_id = body["document"]["id"]
    assert access.disciplines_for(doc_id) == ["Civil"]
    listed = TestClient(app).get("/api/documents", headers=_as("engineer")).json()
    assert doc_id in [d["id"] for d in listed]


def test_an_administrator_may_choose_any_discipline():
    response = _upload("admin_user", ["Mechanical"])
    assert response.status_code == 200, response.text
    assert access.disciplines_for(response.json()["document"]["id"]) == ["Mechanical"]


def test_the_upload_default_is_the_uploaders_own_disciplines():
    client = TestClient(app)
    engineer = client.get("/api/documents/upload-disciplines", headers=_as("engineer"))
    assert engineer.json() == {"required": True, "choices": ["Civil"], "default": ["Civil"]}
    admin = client.get("/api/documents/upload-disciplines", headers=_as("admin_user"))
    assert admin.json() == {"required": True, "choices": ["Civil", "Mechanical"], "default": []}
    assert client.get("/api/documents/upload-disciplines").status_code == 401
