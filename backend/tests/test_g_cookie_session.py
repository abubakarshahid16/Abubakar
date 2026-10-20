"""Item G (owner order 164.2): the login lives in an HttpOnly cookie.

The page never holds the token; a reload (or a backend restart) keeps the user
signed in for the token's 8 hours. Every check the bearer path has (signature,
expiry, `is_active`, `token_epoch`) applies to the cookie too, and a cookie that
rides on a WRITE must also pass the CSRF layers: SameSite=Strict, the custom
header, and a matching Origin. A bearer header is not cookie-borne and is
unchanged. Invented users only.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import auth, db
from app.config import settings
from app.main import app
from tests.test_auth import PASSWORD_A, PASSWORD_B, make_user, temp_storage  # noqa: F401

HEADER = {"X-Requested-With": "rag-ui"}


@pytest.fixture
def admin_and_user():
    admin, _ = make_user("boss@example.test", PASSWORD_A, role="admin")
    other, _ = make_user("other@example.test", PASSWORD_B)
    with db.connect() as conn:
        conn.execute("UPDATE roles SET kind = 'capability' WHERE name = 'admin'")
    return admin, other


def _client(base="http://testserver"):
    return TestClient(app, base_url=base)


def _sign_in(client, email="boss@example.test", password=PASSWORD_A, **extra):
    return client.post(
        "/api/auth/login", json={"email": email, "password": password, **extra}
    )


def _flags(response) -> str:
    return response.headers.get("set-cookie", "").lower()


def test_a_cookie_login_sets_an_httponly_strict_cookie_and_puts_no_token_in_the_body(
    admin_and_user,
):
    r = _sign_in(_client(), session="cookie")
    assert r.status_code == 200
    assert (
        r.json()["token"] is None and r.json()["user"]["email"] == "boss@example.test"
    )
    flags = _flags(r)
    assert flags.startswith("rag_session=") and "httponly" in flags
    assert "samesite=strict" in flags and "path=/" in flags
    assert f"max-age={settings.auth_token_seconds}" in flags


def test_a_login_without_the_cookie_field_is_exactly_as_before(admin_and_user):
    r = _sign_in(_client())
    assert r.json()["token"] and "set-cookie" not in r.headers


def test_the_cookie_signs_the_user_in_for_a_read(admin_and_user):
    c = _client()
    _sign_in(c, session="cookie")
    assert c.get("/api/auth/me").json()["user"]["email"] == "boss@example.test"
    assert _client().get("/api/auth/me").status_code == 401  # no cookie, no header


def test_a_cookie_write_needs_the_custom_header(admin_and_user):
    _admin, other = admin_and_user
    c = _client()
    _sign_in(c, session="cookie")
    assert (
        c.post(f"/api/auth/revoke/{other}").status_code == 404
    )  # not signed in for a write
    assert c.post(f"/api/auth/revoke/{other}", headers=HEADER).status_code == 200


def test_a_cookie_write_from_another_origin_is_refused(admin_and_user):
    _admin, other = admin_and_user
    c = _client()
    _sign_in(c, session="cookie")
    evil = {**HEADER, "Origin": "http://evil.example"}
    assert c.post(f"/api/auth/revoke/{other}", headers=evil).status_code == 404
    same = {**HEADER, "Origin": "http://testserver"}
    assert c.post(f"/api/auth/revoke/{other}", headers=same).status_code == 200


def test_the_dev_origin_is_accepted(admin_and_user):
    _admin, other = admin_and_user
    c = _client()
    _sign_in(c, session="cookie")
    dev = {**HEADER, "Origin": "http://localhost:5173"}
    assert c.post(f"/api/auth/revoke/{other}", headers=dev).status_code == 200


def test_a_bearer_header_needs_neither_the_custom_header_nor_an_origin(admin_and_user):
    _admin, other = admin_and_user
    token = _sign_in(_client()).json()["token"]
    r = _client().post(
        f"/api/auth/revoke/{other}",
        headers={"Authorization": f"Bearer {token}", "Origin": "http://evil.example"},
    )
    assert r.status_code == 200


def test_the_bearer_header_wins_over_a_cookie(admin_and_user):
    _admin, _other = admin_and_user
    token = _sign_in(_client(), "other@example.test", PASSWORD_B).json()["token"]
    c = _client()
    _sign_in(c, session="cookie")  # the boss's cookie
    me = c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["user"]["email"] == "other@example.test"


def test_revoking_a_user_ends_their_cookie_session(admin_and_user):
    admin, other = admin_and_user
    c = _client()
    _sign_in(c, "other@example.test", PASSWORD_B, session="cookie")
    assert c.get("/api/auth/me").status_code == 200
    assert auth.revoke_user_tokens(other)
    assert c.get("/api/auth/me").status_code == 401


def test_deactivating_a_user_ends_their_cookie_session(admin_and_user):
    _admin, other = admin_and_user
    c = _client()
    _sign_in(c, "other@example.test", PASSWORD_B, session="cookie")
    with db.connect() as conn:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (other,))
    assert c.get("/api/auth/me").status_code == 401


def test_an_expired_cookie_is_refused(admin_and_user):
    admin, _other = admin_and_user
    c = _client()
    old = auth.issue_token(admin, now=1_000_000.0)  # long past its 8 hours
    c.cookies.set("rag_session", old)
    assert c.get("/api/auth/me").status_code == 401


def test_a_tampered_or_garbage_cookie_is_refused(admin_and_user):
    c = _client()
    _sign_in(c, session="cookie")
    good = c.cookies.get("rag_session")
    for bad in (good[:-3] + "AAA", "garbage", good.split(".")[0], ""):
        fresh = _client()
        fresh.cookies.set("rag_session", bad)
        assert fresh.get("/api/auth/me").status_code == 401, bad


def test_logout_clears_the_cookie_and_needs_no_session(admin_and_user):
    c = _client()
    _sign_in(c, session="cookie")
    r = c.post("/api/auth/logout")
    assert r.status_code == 200 and r.json() == {"signed_out": True}
    assert "max-age=0" in _flags(r) and "httponly" in _flags(r)
    assert c.get("/api/auth/me").status_code == 401
    assert (
        _client().post("/api/auth/logout").status_code == 200
    )  # nobody signed in: still fine


def test_the_secure_flag_follows_the_scheme_unless_forced(admin_and_user, monkeypatch):
    assert "secure" not in _flags(
        _sign_in(_client("http://testserver"), session="cookie")
    ).replace("samesite", "")
    https = _sign_in(_client("https://testserver"), session="cookie")
    assert "; secure" in _flags(https)
    monkeypatch.setattr(settings, "auth_cookie_secure", "true")
    assert "; secure" in _flags(
        _sign_in(_client("http://testserver"), session="cookie")
    )
    monkeypatch.setattr(settings, "auth_cookie_secure", "false")
    assert "; secure" not in _flags(
        _sign_in(_client("https://testserver"), session="cookie")
    )


def test_a_failed_login_sets_no_cookie(admin_and_user):
    r = _sign_in(_client(), password="wrong-password-wrong", session="cookie")
    assert r.status_code == 401 and "set-cookie" not in r.headers
