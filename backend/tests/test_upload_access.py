"""Security boundary for authenticated uploads (#79, #86)."""

import io

import pytest
from fastapi.testclient import TestClient

from app import access, db
from app.config import settings
from app.db import connect
from app.main import app

NOW = "2026-09-11T00:00:00Z"


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "test.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    db.reset_connection()
    db.init_db()
    with connect() as conn:
        for user_id in ("admin_user", "engineer"):
            conn.execute(
                "INSERT INTO users (id,email,display_name,password_hash,created_at) "
                "VALUES (?,?,?,?,?)",
                (user_id, f"{user_id}@test.local", user_id, "hash", NOW),
            )
        conn.execute(
            "INSERT INTO roles (id,name,description,created_at) VALUES (?,?,?,?)",
            ("role_admin", "admin", "Administrators", NOW),
        )
        conn.execute(
            "INSERT INTO roles (id,name,description,created_at) VALUES (?,?,?,?)",
            ("role_civil", "Civil", "Civil engineers", NOW),
        )
        conn.execute(
            "INSERT INTO user_roles (user_id,role_id,granted_at) VALUES (?,?,?)",
            ("admin_user", "role_admin", NOW),
        )
        conn.execute(
            "INSERT INTO user_roles (user_id,role_id,granted_at) VALUES (?,?,?)",
            ("engineer", "role_civil", NOW),
        )
    access.set_user_resolver(lambda request: request.headers.get("x-test-user"))
    yield
    access.set_user_resolver(None)
    db.reset_connection()


def _pdf(marker: bytes = b"x") -> bytes:
    return b"%PDF-1.4\n" + marker * 5000 + b"\n%%EOF\n"


def _upload(client: TestClient, user: str | None, data: bytes | None = None):
    headers = {"x-test-user": user} if user else {}
    return client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("spec.pdf", io.BytesIO(data or _pdf()), "application/pdf")},
    )


def test_anonymous_upload_is_rejected_before_writing_anything():
    response = _upload(TestClient(app), None)
    assert response.status_code == 401
    assert connect().execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"] == 0
    assert connect().execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"] == 0


def test_new_upload_is_admin_only_until_deliberately_granted():
    client = TestClient(app)
    response = _upload(client, "engineer")
    assert response.status_code == 200, response.text
    body = response.json()
    document_id = body["document"]["id"]
    assert body["awaiting_grant"] is True

    grants = connect().execute(
        "SELECT role_id FROM document_role_access WHERE document_id = ?",
        (document_id,),
    ).fetchall()
    assert [row["role_id"] for row in grants] == ["role_admin"]
    assert client.get("/api/documents", headers={"x-test-user": "engineer"}).json() == []
    admin_docs = client.get(
        "/api/documents", headers={"x-test-user": "admin_user"}
    ).json()
    assert [doc["id"] for doc in admin_docs] == [document_id]


def test_duplicate_cannot_widen_access_or_reveal_the_existing_document():
    client = TestClient(app)
    data = _pdf(b"z")
    original = _upload(client, "admin_user", data).json()["document"]
    response = _upload(client, "engineer", data)
    assert response.status_code == 200
    assert response.json() == {
        "document": None,
        "job_id": "",
        "duplicate_of": None,
        "awaiting_grant": True,
    }
    grants = connect().execute(
        "SELECT role_id FROM document_role_access WHERE document_id = ?",
        (original["id"],),
    ).fetchall()
    assert [row["role_id"] for row in grants] == ["role_admin"]


def test_required_auth_refuses_upload_when_admin_role_is_not_configured():
    with connect() as conn:
        conn.execute("DELETE FROM user_roles WHERE role_id = 'role_admin'")
        conn.execute("DELETE FROM roles WHERE id = 'role_admin'")
    response = _upload(TestClient(app), "engineer", _pdf(b"q"))
    assert response.status_code == 503
    assert connect().execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"] == 0
