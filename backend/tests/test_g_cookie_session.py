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

from app import auth, auth_session, db
from app.config import settings
from app.main import app
from tests.test_auth import (  # noqa: F401
    PASSWORD_A,
    PASSWORD_B,
    make_user,
    temp_storage,
)

HEADER = {"X-Requested-With": "rag-ui"}


@pytest.fixture
def admin_and_user():
    admin, _ = make_user("boss@example.test", PASSWORD_A, role="admin")
    other, _ = make_user("other@example.test", PASSWORD_B)
    with db.connect() as conn:
        conn.execute("UPDATE roles SET kind = 'capability' WHERE name = 'admin'")
    return admin, other


@pytest.fixture
def network_hosts(monkeypatch):
    """The server answers only to configured host names (`trusted_host_gate`)."""
    monkeypatch.setattr(settings, "allowed_hosts", "files.example.test,192.168.1.20")


def _client(base="http://127.0.0.1:8000", *, header=True):
    """Like the app: every call carries the custom header, unless a test says
    it is another page (`header=False`: an <img>, a link, a form cannot set it)."""
    return TestClient(app, base_url=base, headers=HEADER if header else None)


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
    c = _client(header=False)
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
    same = {**HEADER, "Origin": "http://127.0.0.1:8000"}
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
    _admin, other = admin_and_user
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


def _cookie_value(response) -> str:
    return response.headers["set-cookie"].split("=", 1)[1].split(";", 1)[0]


def test_a_copy_of_the_cookie_is_refused_after_logout(admin_and_user):
    """cloud-3's S3: logout used to only clear the browser's copy; the token
    stayed good for its 8 hours. A replay, as a cookie or as a bearer, is 401."""
    c = _client()
    value = _cookie_value(_sign_in(c, session="cookie"))
    assert c.get("/api/auth/me").status_code == 200
    assert c.post("/api/auth/logout", headers=HEADER).status_code == 200
    replay = _client()
    replay.cookies.set("rag_session", value)
    assert replay.get("/api/auth/me").status_code == 401
    assert (
        _client()
        .get("/api/auth/me", headers={"Authorization": f"Bearer {value}"})
        .status_code
        == 401
    )


def test_logout_ends_only_that_token_not_the_users_other_sign_ins(admin_and_user):
    first, second = _client(), _client()
    _sign_in(first, session="cookie")
    script_token = _sign_in(_client()).json()["token"]
    other_cookie = _cookie_value(_sign_in(second, session="cookie"))
    first.post("/api/auth/logout", headers=HEADER)
    assert second.get("/api/auth/me").status_code == 200
    assert (
        _client()
        .get("/api/auth/me", headers={"Authorization": f"Bearer {script_token}"})
        .status_code
        == 200
    )
    assert other_cookie  # the second sign-in is a different token


def test_logout_with_a_bearer_token_ends_that_token(admin_and_user):
    token = _sign_in(_client()).json()["token"]
    bearer = {"Authorization": f"Bearer {token}"}
    c = _client()
    assert c.get("/api/auth/me", headers=bearer).status_code == 200
    assert c.post("/api/auth/logout", headers=bearer).status_code == 200
    assert c.get("/api/auth/me", headers=bearer).status_code == 401


def test_logout_of_nothing_or_of_garbage_records_nothing(admin_and_user):
    c = _client()
    c.post("/api/auth/logout")
    c.cookies.set("rag_session", "garbage.token")
    c.post("/api/auth/logout")
    c.post("/api/auth/logout", headers={"Authorization": "Bearer nonsense"})
    tables = {
        r["name"]
        for r in db.connect().execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert (
        "revoked_sessions" not in tables
        or not db.connect().execute("SELECT 1 FROM revoked_sessions").fetchone()
    )


def test_a_signed_out_record_is_dropped_once_the_token_would_have_expired(
    admin_and_user,
):
    user_id = db.connect().execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
    old = auth.issue_token(user_id, now=1_000_000.0)
    assert auth_session.sign_out(old, now=1_000_100.0) is True

    def count():
        row = db.connect().execute("SELECT COUNT(*) AS n FROM revoked_sessions")
        return row.fetchone()["n"]

    assert count() == 1
    later = auth.issue_token(
        user_id, now=1_000_000.0 + settings.auth_token_seconds + 50
    )
    assert (
        auth_session.sign_out(later, now=1_000_000.0 + settings.auth_token_seconds + 60)
        is True
    )
    assert count() == 1  # the old row went; only the new one is kept


def test_the_secure_flag_follows_where_the_request_came_from(
    admin_and_user, network_hosts, monkeypatch
):
    def plain(base):
        return _sign_in(_client(base), session="cookie")

    loopback = plain("http://localhost:8000")
    assert "rag_session=" in _flags(loopback) and "; secure" not in _flags(loopback)
    assert "; secure" in _flags(plain("https://files.example.test"))
    assert "; secure" in _flags(plain("https://127.0.0.1:8000"))
    monkeypatch.setattr(settings, "auth_cookie_secure", "true")
    assert "; secure" in _flags(plain("http://127.0.0.1:8000"))
    monkeypatch.setattr(settings, "auth_cookie_secure", "false")
    assert "; secure" not in _flags(plain("https://files.example.test"))


def test_plain_http_on_a_network_address_gets_no_cookie_and_the_bearer_token(
    admin_and_user, network_hosts
):
    r = _sign_in(_client("http://192.168.1.20:8000"), session="cookie")
    assert r.status_code == 200 and "set-cookie" not in r.headers
    assert r.json()["token"]


def test_a_forged_forwarded_proto_does_not_make_a_network_request_secure(
    admin_and_user, network_hosts
):
    c = _client("http://192.168.1.20:8000")
    r = c.post(
        "/api/auth/login",
        json={
            "email": "boss@example.test",
            "password": PASSWORD_A,
            "session": "cookie",
        },
        headers={"X-Forwarded-Proto": "https"},
    )
    assert "set-cookie" not in r.headers and r.json()["token"]


# `test_no_state_changing_route_is_a_get` (a heuristic over `app.routes`, which
# skipped the included routers) is replaced by `test_w7_get_routes_read_only.py`,
# the walk over every GET route; and since a cookie-borne GET now needs the custom
# header as well (tests above), a GET could not be driven by another page anyway.


def test_the_cookie_value_never_reaches_a_log_or_an_error(admin_and_user, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    c = _client()
    token = _sign_in(c, session="cookie").headers["set-cookie"].split("=", 1)[1]
    token = token.split(";", 1)[0]
    c.get("/api/auth/me")
    c.post("/api/auth/logout")
    bad = _client()
    bad.cookies.set("rag_session", token[:-3] + "AAA")
    r = bad.post("/api/auth/revoke/x", headers=HEADER)
    assert token not in r.text and "rag_session" not in r.text
    assert "rag_session=" not in caplog.text and token not in caplog.text


def test_a_failed_login_sets_no_cookie(admin_and_user):
    r = _sign_in(_client(), password="wrong-password-wrong", session="cookie")
    assert r.status_code == 401 and "set-cookie" not in r.headers


def test_a_forced_non_secure_cookie_is_said_at_startup(monkeypatch, caplog):
    import logging

    monkeypatch.setattr(settings, "auth_mode", "demo_required")
    for mode, expected in (("false", True), ("auto", False), ("true", False)):
        monkeypatch.setattr(settings, "auth_cookie_secure", mode)
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
            auth.announce_mode()
        assert ("AUTH_COOKIE_SECURE=false" in caplog.text) is expected, mode


def test_every_login_is_its_own_token_even_in_the_same_second(admin_and_user):
    """Without a per-login id two logins in one second were the identical
    token, and signing one out ended the other."""
    user_id = db.connect().execute("SELECT id FROM users LIMIT 1").fetchone()["id"]
    assert auth.issue_token(user_id, now=1_000_000.0) != auth.issue_token(
        user_id, now=1_000_000.0
    )


# ----------------------------------- every cookie-borne request needs the header
def test_a_cookie_read_without_the_header_is_not_signed_in(admin_and_user):
    """s2's blocking finding on #1242: an <img src> or a link on a page on another
    localhost port is the same SITE, so SameSite=Strict still sent the cookie on a
    GET - and `GET /api/answer?tier=generated` runs the model. A GET with only the
    cookie (no header) is now simply not signed in."""
    signed = _client()
    _sign_in(signed, session="cookie")
    value = signed.cookies.get("rag_session")
    other_page = _client(header=False)
    other_page.cookies.set("rag_session", value)
    for path in ("/api/auth/me", "/api/metrics", "/api/reviews"):
        assert other_page.get(path).status_code == 401, path
    # routes that answer an anonymous caller: the cookie changes nothing for it
    for path in ("/api/documents", "/api/answer?q=anything&tier=generated"):
        anon = _client(header=False).get(path)
        got = other_page.get(path)
        assert (got.status_code, got.json() if got.content else None) == (
            anon.status_code,
            anon.json() if anon.content else None,
        ), path
    assert signed.get("/api/auth/me").status_code == 200  # the app's own call


def test_a_cookie_read_from_another_origin_is_not_signed_in(admin_and_user):
    c = _client()
    _sign_in(c, session="cookie")
    r = c.get("/api/auth/me", headers={"Origin": "http://127.0.0.1:9999"})
    assert r.status_code == 401


def test_a_bearer_read_needs_neither_the_header_nor_an_origin(admin_and_user):
    token = _sign_in(_client(header=False)).json()["token"]
    r = _client(header=False).get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200


# ------------------------------------------------------- the fail-closed path
def test_a_database_fault_reading_the_sign_out_list_refuses_the_token(
    admin_and_user, monkeypatch
):
    """Only "no such table" means nobody ever signed out; any other fault must
    refuse (changing that to fail open passed every test before this one)."""
    import sqlite3

    c = _client()
    token = _sign_in(_client(header=False)).json()["token"]
    real = db.connect

    class Broken:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, *args):
            if "revoked_sessions" in sql:
                raise sqlite3.OperationalError("database is locked")
            return self._inner.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(auth_session, "connect", lambda: Broken(real()))
    assert auth_session.is_signed_out(token) is True
    r = c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
