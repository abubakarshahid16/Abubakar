"""Authentication: who a request is, and what it may never talk itself into.

Every test here is negative. The positive case - a correct password returns a
token - is one assertion; the rest of the file is about what a caller can claim
and what the server refuses to believe.

The one to read first is
`test_the_scope_never_comes_from_the_request`. `auth.resolve_user_id` returns
`str | None` and nothing wider, so the client picks WHICH row is looked up and
never WHAT the lookup returns. That test tries four ways to state an identity
alongside a valid token and requires all four to be ignored. It is what catches
a resolver that has grown a fallback.
"""

from __future__ import annotations

import statistics
import time

import pytest
from fastapi.testclient import TestClient

from app import access, auth, db
from app.config import settings
from app.main import app

PASSWORD_A = "correct-horse-battery-staple-a"
PASSWORD_B = "correct-horse-battery-staple-b"


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


def make_user(email, password, *, active=True, role="engineer"):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = db.connect()
    user_id = f"user_{email.split('@')[0]}"
    role_id = f"role_{role}"
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO roles (id, name, description, created_at) "
            "VALUES (?, ?, '', ?)", (role_id, role, now))
        conn.execute(
            """INSERT INTO users (id, email, display_name, password_hash,
                                  is_active, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, email, email.split("@")[0], auth._hasher.hash(password),
             1 if active else 0, now))
        conn.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id, granted_at) "
            "VALUES (?, ?, ?)", (user_id, role_id, now))
    return user_id, role_id


def grant_document(role_id, doc_id):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = db.connect()
    with conn:
        conn.execute(
            """INSERT INTO documents (id, filename, sha256, size_bytes,
                   stored_path, page_count, status, needs_ocr_pages,
                   recognised_pages, uploaded_at)
               VALUES (?, ?, ?, 1, '', 1, 'ready', 0, 0, ?)""",
            (doc_id, f"{doc_id}.pdf", doc_id.ljust(64, "0"), now))
        conn.execute(
            "INSERT INTO document_role_access (document_id, role_id, granted_at)"
            " VALUES (?, ?, ?)", (doc_id, role_id, now))


def _shape(response):
    """A refusal reduced to what a caller can see, for comparing two of them."""
    body = response.json()
    detail = body.get("detail", body)
    return (response.status_code, detail.get("code"), detail.get("message"))


# ------------------------------------------------------------- credentials


def test_a_correct_password_returns_a_token_and_the_user():
    make_user("a@x.test", PASSWORD_A)
    client = TestClient(app)
    r = client.post("/api/auth/login",
                    json={"email": "a@x.test", "password": PASSWORD_A})
    assert r.status_code == 200
    body = r.json()
    assert body["token"]
    assert body["user"]["email"] == "a@x.test"
    assert body["user"]["roles"] == ["engineer"]


def test_the_two_ways_to_get_a_password_wrong_are_indistinguishable():
    """A wrong password and a missing account must be one answer.

    Two different messages, or two different codes, is a user enumeration
    oracle: an attacker learns which addresses exist by reading the refusal.
    """
    make_user("a@x.test", PASSWORD_A)
    client = TestClient(app)
    wrong = client.post("/api/auth/login",
                        json={"email": "a@x.test", "password": "not-it-at-all"})
    missing = client.post("/api/auth/login",
                          json={"email": "nobody@x.test", "password": "not-it-at-all"})
    assert wrong.status_code == 401
    assert _shape(wrong) == _shape(missing)


def test_a_deactivated_user_fails_with_the_same_shape():
    """Being deactivated is not a fact an anonymous caller may learn."""
    make_user("a@x.test", PASSWORD_A)
    make_user("off@x.test", PASSWORD_A, active=False)
    client = TestClient(app)
    deactivated = client.post("/api/auth/login",
                              json={"email": "off@x.test", "password": PASSWORD_A})
    missing = client.post("/api/auth/login",
                          json={"email": "nobody@x.test", "password": PASSWORD_A})
    assert _shape(deactivated) == _shape(missing)


def test_the_hash_is_argon2id_and_salted_per_user():
    make_user("a@x.test", PASSWORD_A)
    make_user("b@x.test", PASSWORD_A)  # THE SAME password
    rows = db.connect().execute(
        "SELECT email, password_hash FROM users ORDER BY email").fetchall()
    hashes = [r["password_hash"] for r in rows]
    assert all(h.startswith("$argon2id$") for h in hashes)
    assert hashes[0] != hashes[1], (
        "two users with the same password share a hash - there is no per-user "
        "salt, so one cracked password is every account with it"
    )


def test_no_response_ever_carries_a_hash_or_the_active_flag():
    make_user("a@x.test", PASSWORD_A)
    client = TestClient(app)
    token = client.post("/api/auth/login",
                        json={"email": "a@x.test", "password": PASSWORD_A}
                        ).json()["token"]
    for response in (
        client.post("/api/auth/login",
                    json={"email": "a@x.test", "password": PASSWORD_A}),
        client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}),
    ):
        body = response.text
        assert "argon2" not in body
        assert "password_hash" not in body
        assert "is_active" not in body


# ------------------------------------------------------------------ tokens


def test_an_altered_signature_is_rejected():
    user_id, _ = make_user("a@x.test", PASSWORD_A)
    token = auth.issue_token(user_id)
    body, _, signature = token.partition(".")
    forged = f"{body}.{'A' * len(signature)}"
    assert auth.read_token(forged) is None


def test_a_repackaged_payload_naming_another_user_is_rejected():
    """The forgery that matters: keep a valid signature, swap the subject."""
    import base64
    import json

    a, _ = make_user("a@x.test", PASSWORD_A)
    make_user("b@x.test", PASSWORD_B)
    token = auth.issue_token(a)
    body_b64, _, signature = token.partition(".")
    claims = json.loads(auth._unb64(body_b64))
    claims["u"] = "user_b"
    tampered = base64.urlsafe_b64encode(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode()
    ).decode().rstrip("=")
    assert auth.read_token(f"{tampered}.{signature}") is None


def test_an_expired_token_is_simply_not_a_token():
    user_id, _ = make_user("a@x.test", PASSWORD_A)
    token = auth.issue_token(user_id, now=time.time() - settings.auth_token_seconds - 10)
    assert auth.read_token(token) is None


def test_a_token_signed_with_a_different_secret_is_rejected(monkeypatch):
    """Proves the secret is actually consumed rather than decorative."""
    user_id, _ = make_user("a@x.test", PASSWORD_A)
    token = auth.issue_token(user_id)
    monkeypatch.setattr(settings, "auth_secret", "y" * 48)
    assert auth.read_token(token) is None


def test_an_unsigned_or_absent_token_reaches_no_documents():
    client = TestClient(app)
    for headers in ({}, {"Authorization": "Bearer "}, {"Authorization": "nonsense"},
                    {"Authorization": "Bearer not.a.token"}):
        assert client.get("/api/documents", headers=headers).json() == []


# --------------------------------------- the scope never comes from the request


def test_the_scope_never_comes_from_the_request():
    """Four ways to claim an identity beside a valid token. All ignored.

    This is the test that catches a resolver which has grown a fallback -
    reading a header when the token is absent, or trusting a query parameter
    "just for the admin UI". The boundary is `resolve_user_id`'s return type,
    and this is what watches it.
    """
    a, role_a = make_user("a@x.test", PASSWORD_A)
    b, role_b = make_user("b@x.test", PASSWORD_B, role="reviewer")
    grant_document(role_a, "doc_aaa")
    grant_document(role_b, "doc_bbb")

    assert role_a != role_b, "both users in one role - a leak would be invisible"
    assert access.scope_for_user(a).allowed_document_ids == frozenset({"doc_aaa"})
    assert access.scope_for_user(b).allowed_document_ids == frozenset({"doc_bbb"})

    client = TestClient(app)
    token = auth.issue_token(a)
    auth_header = {"Authorization": f"Bearer {token}"}

    attempts = [
        ("header", {**auth_header, "X-User-Id": b}, "/api/documents"),
        ("query", auth_header, f"/api/documents?user_id={b}"),
        ("cookie", auth_header, "/api/documents"),
        ("role header", {**auth_header, "X-Roles": "admin"}, "/api/documents"),
    ]
    for label, headers, url in attempts:
        client.cookies.set("user_id", b)
        response = client.get(url, headers=headers)
        assert response.status_code in (200, 422), f"{label}: {response.status_code}"
        if response.status_code == 200:
            ids = {d["id"] for d in response.json()}
            assert ids == {"doc_aaa"}, f"{label} changed what the caller saw: {ids}"


# ------------------------------------------------------------- revocation


def test_deactivating_a_user_takes_effect_on_the_next_request():
    a, role_a = make_user("a@x.test", PASSWORD_A)
    grant_document(role_a, "doc_aaa")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {auth.issue_token(a)}"}
    assert len(client.get("/api/documents", headers=headers).json()) == 1

    conn = db.connect()
    with conn:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (a,))

    assert client.get("/api/documents", headers=headers).json() == []
    # 404, never 403: a document the caller may not see must not be confirmed
    # to exist.
    assert client.get("/api/documents/doc_aaa", headers=headers).status_code == 404


def test_deleting_a_user_cascades_and_does_not_crash():
    a, role_a = make_user("a@x.test", PASSWORD_A)
    grant_document(role_a, "doc_aaa")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {auth.issue_token(a)}"}

    conn = db.connect()
    with conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM users WHERE id = ?", (a,))

    response = client.get("/api/documents", headers=headers)
    assert response.status_code == 200
    assert response.json() == []


# ----------------------------------------------------------- rate limiting


def test_repeated_failures_are_locked_out_and_say_how_long():
    make_user("a@x.test", PASSWORD_A)
    client = TestClient(app)
    for _ in range(settings.auth_max_attempts):
        client.post("/api/auth/login",
                    json={"email": "a@x.test", "password": "wrong"})
    blocked = client.post("/api/auth/login",
                          json={"email": "a@x.test", "password": PASSWORD_A})
    assert blocked.status_code == 429
    assert blocked.headers.get("Retry-After")


def test_the_lockout_does_not_become_the_oracle_the_hashing_closed():
    """A 429 for a real address and an unknown one must be identical.

    Constant-time verification removes the timing oracle; a limiter that only
    engages for real accounts puts it straight back, in a form that is easier
    to read.
    """
    make_user("a@x.test", PASSWORD_A)
    client = TestClient(app)
    for email in ("a@x.test", "nobody@x.test"):
        for _ in range(settings.auth_max_attempts):
            client.post("/api/auth/login", json={"email": email, "password": "no"})
    real = client.post("/api/auth/login", json={"email": "a@x.test", "password": "no"})
    unknown = client.post("/api/auth/login",
                          json={"email": "nobody@x.test", "password": "no"})
    assert real.status_code == 429
    assert _shape(real) == _shape(unknown)


def test_one_users_exhausted_budget_does_not_lock_out_another():
    make_user("a@x.test", PASSWORD_A)
    make_user("b@x.test", PASSWORD_B)
    client = TestClient(app)
    for _ in range(settings.auth_max_attempts + 2):
        client.post("/api/auth/login", json={"email": "a@x.test", "password": "no"})
    ok = client.post("/api/auth/login",
                     json={"email": "b@x.test", "password": PASSWORD_B})
    assert ok.status_code == 200


# -------------------------------------------------------------- the secret


def test_startup_refuses_a_weak_secret_when_auth_is_required(monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "short")
    with pytest.raises(RuntimeError, match="AUTH_SECRET"):
        auth.check_secret_or_refuse()


def test_a_weak_secret_is_fine_when_auth_is_disabled(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(settings, "auth_secret", "")
    auth.check_secret_or_refuse()


# ------------------------------------------------------------ health parity


def test_health_exposes_the_same_keys_signed_in_or_not(monkeypatch):
    """Set equality, not `in`.

    An `in` check passes when a field is ADDED, which is the direction this
    endpoint leaks in. The health surface was narrowed deliberately; it must
    not re-widen because authentication arrived.
    """
    client = TestClient(app)
    anonymous = client.get("/api/health").json()
    assert set(anonymous) == {"ok", "embed_model_present",
                              "answer_model_present", "ingestion"}
    assert set(anonymous["ingestion"]) == {"alive", "stalled", "busy"}

    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    assert set(client.get("/api/health").json()) == set(anonymous)


# -------------------------------------------------------------- the timing


def test_the_two_login_failure_paths_do_the_same_work():
    """An unknown email must cost what a wrong password costs.

    Without the dummy-hash path, a missing user returns in microseconds and a
    wrong password in ~50 ms, and the gap enumerates the user list.

    The mechanism is the guarantee - a real Argon2 verify runs either way - and
    this measures that the mechanism is in place. Medians, never means: one GC
    pause destroys a mean. Interleaved, because CPU frequency scaling drifts
    over seconds and a block design would attribute the drift to the branch.
    A relative bound, because an absolute millisecond figure encodes this
    machine's speed into the assertion.

    NOT marked slow. It runs in the default suite, because the silent skip is
    how a test like this stops protecting anything.
    """
    make_user("a@x.test", PASSWORD_A)
    client = TestClient(app)

    known, unknown = [], []
    for _ in range(12):
        for email, samples in (("nobody@x.test", unknown), ("a@x.test", known)):
            auth.reset_limiter()
            start = time.perf_counter()
            client.post("/api/auth/login",
                        json={"email": email, "password": "definitely-wrong"})
            samples.append(time.perf_counter() - start)

    m_known = statistics.median(known)
    m_unknown = statistics.median(unknown)

    # The floor first: if BOTH paths are fast, no hashing ran and the ratio
    # below would be comparing two pieces of nothing.
    assert min(m_known, m_unknown) > 0.005, (
        f"both paths returned in under 5 ms (known {m_known*1000:.1f} ms, "
        f"unknown {m_unknown*1000:.1f} ms) - the Argon2 verify did not run, "
        f"so this test is measuring noise"
    )

    ratio = max(m_known, m_unknown) / min(m_known, m_unknown)
    assert ratio < 3.0, (
        f"the two failure paths differ by {ratio:.1f}x (known "
        f"{m_known*1000:.0f} ms, unknown {m_unknown*1000:.0f} ms) - that gap "
        f"tells an attacker which email addresses exist"
    )


# ------------------------------------------------------- how the UI finds out


def test_auth_me_says_no_sign_in_is_needed_when_auth_is_disabled(monkeypatch):
    """The frontend must not show a login form it cannot use.

    Under `disabled` there is nobody to be, so a 401 here would put a sign-in
    screen in front of a deployment that has authentication switched off.
    Telling an anonymous caller that authentication is off is not a leak:
    under `disabled` that same caller can already read every document.

    `/api/health` deliberately does NOT carry this. Health is unauthenticated
    and was narrowed on purpose.
    """
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    r = TestClient(app).get("/api/auth/me")
    assert r.status_code == 200
    assert r.json() == {"required": False, "user": None}


def test_auth_me_refuses_an_anonymous_caller_when_auth_is_required():
    r = TestClient(app).get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "unauthenticated"


def test_auth_me_names_the_caller_and_their_roles_but_never_their_documents():
    a, role_a = make_user("a@x.test", PASSWORD_A)
    grant_document(role_a, "doc_aaa")
    r = TestClient(app).get(
        "/api/auth/me", headers={"Authorization": f"Bearer {auth.issue_token(a)}"})
    assert r.status_code == 200
    body = r.json()
    assert body["required"] is True
    assert body["user"]["roles"] == ["engineer"]
    # Roles, never grants: handing the client its document list gives it
    # something to check its guesses against.
    assert "doc_aaa" not in r.text


# ------------------------------------------------- the startup announcement


def test_the_startup_line_names_the_mode_and_never_the_secret(monkeypatch, caplog):
    """One line, at startup, saying whether anybody has to log in.

    ITS ABSENCE COST TWO DAYS. `env_file` was a relative path, so a server
    launched from the repository root ignored backend/.env and came up with
    authentication OFF while that file said `demo_required`. Nothing said so -
    not a log line, not a health field, nothing - and the only symptom was a
    browser sidebar reading "Authentication disabled".
    """
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    monkeypatch.setattr(settings, "auth_secret", "x" * 64)
    with caplog.at_level("INFO", logger="uvicorn.error"):
        auth.announce_mode()

    line = " ".join(r.getMessage() for r in caplog.records)
    assert "demo_required" in line, f"the mode was not named: {line!r}"
    assert "present" in line and "64" in line, f"secret presence not stated: {line!r}"
    assert "x" * 32 not in line, "THE SECRET ITSELF REACHED THE LOG"


def test_the_startup_line_warns_when_authentication_is_off(monkeypatch, caplog):
    """`disabled` is the louder case: every request sees every document."""
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    with caplog.at_level("INFO", logger="uvicorn.error"):
        auth.announce_mode()

    records = [r for r in caplog.records if "AUTH_MODE" in r.getMessage()]
    assert records, "nothing was logged at all when authentication was off"
    assert records[0].levelname == "WARNING", (
        f"authentication being off was logged at {records[0].levelname}, which "
        "reads as routine")
    assert "disabled" in records[0].getMessage()
