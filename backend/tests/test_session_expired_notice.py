"""The switch that tells a reader their sign-in ran out reaches the page (order 4b).

It rides on the signed-in user, on both ways the page learns who that is. The
last test pins why the page also asks `/api/auth/me`: a read outside the gated
routes answers an expired sign-in with an empty 200, which no poll can see.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import access, auth, db
from app.config import settings
from app.main import app

PASSWORD = "correct-horse-battery-staple-a"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    monkeypatch.setattr(settings, "auth_secret", "x" * 48)
    db.reset_connection()
    db.init_db()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    auth.reset_limiter()
    access.set_user_resolver(auth.resolve_user_id)
    yield
    access.set_user_resolver(None)
    db.reset_connection()


def _user(email: str = "a@x.test") -> str:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    conn = db.connect()
    with conn:
        conn.execute(
            """INSERT INTO users (id, email, display_name, password_hash,
                                  is_active, created_at)
               VALUES (?, ?, ?, ?, 1, ?)""",
            ("user_a", email, "A", auth._hasher.hash(PASSWORD), now),
        )
    return "user_a"


@pytest.mark.parametrize("on", [True, False])
def test_me_carries_the_switch(monkeypatch, on):
    monkeypatch.setattr(settings, "session_expired_notice_enabled", on)
    token = auth.issue_token(_user())
    r = TestClient(app).get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    assert r.json()["user"]["session_expired_notice"] is on


@pytest.mark.parametrize("on", [True, False])
def test_login_carries_the_switch(monkeypatch, on):
    monkeypatch.setattr(settings, "session_expired_notice_enabled", on)
    _user()
    r = TestClient(app).post(
        "/api/auth/login", json={"email": "a@x.test", "password": PASSWORD}
    )
    assert r.status_code == 200
    assert r.json()["user"]["session_expired_notice"] is on


def test_the_switch_is_off_by_default():
    assert (
        type(settings).model_fields["session_expired_notice_enabled"].default is False
    )


def test_an_expired_sign_in_gets_an_empty_200_on_the_library_but_a_401_from_me():
    client = TestClient(app)
    expired = {"Authorization": "Bearer not-a-live-token"}
    assert client.get("/api/auth/me", headers=expired).status_code == 401
    library = client.get("/api/documents", headers=expired)
    assert library.status_code == 200
    assert library.json() == []
