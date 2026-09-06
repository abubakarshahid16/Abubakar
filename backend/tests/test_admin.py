"""The admin screen's backend, tested against `docs/design-admin-screen.md`.

Every test here was written by asking the only question that matters in this
repo: IF I DELETE THE CODE THIS TESTS, DOES IT GO RED? Four of them were proven
that way before this file was committed - the rule was deleted or inverted, the
suite was run, the failure count was recorded, and the rule was put back. Those
numbers are in the change's report.

Two vacuity traps this project has already fallen into, and how this file
avoids them:

  * A FIXTURE THAT CANNOT PRODUCE THE CONDITION IT ASSERTS. `test_non_admin_
    gets_404_on_every_admin_route` would pass identically if the routes did not
    exist, if the app refused everybody, or if the token were simply invalid.
    So the same table of routes is driven twice - once as a non-admin, once as
    an admin - and the admin run asserts a NON-404. A guard nobody has watched
    succeed is as empty as one nobody has watched fail.

  * A TEST THAT PASSES BECAUSE THE DEVELOPER'S DATABASE HAPPENS TO EXIST.
    `temp_storage` creates its own tables in a temp directory, like
    test_market.py. The session fixture in conftest.py already points the
    default database at a temp path, so a file that forgot this would fail
    here exactly as it fails in CI rather than quietly reading the 62 MB
    development corpus.
"""

from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import access, admin, auth, db
from app.config import settings
from app.main import app

# Method, path, and a body where the route takes one. The 404 test walks this
# table so a route added later without an admin check cannot slip past it by
# not being listed - adding a route to main.py and forgetting it here is
# visible as a route this table does not mention.
ROUTES = [
    ("GET", "/api/admin/users", None),
    ("POST", "/api/admin/users", {"email": "x@example.com", "disciplines": []}),
    ("DELETE", "/api/admin/users/usr_00000000", None),
    ("GET", "/api/admin/disciplines", None),
    ("GET", "/api/admin/grants", None),
    ("PUT", "/api/admin/grants", {"document_id": "doc_1", "discipline": "Mechanical"}),
    ("DELETE", "/api/admin/grants", {"document_id": "doc_1", "discipline": "Mechanical"}),
]

DISCIPLINES = ("Civil Engineering", "Mechanical")


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    """Its own database, and authentication genuinely ON.

    `demo_required` is not decoration here: under `disabled` an unidentified
    caller is allowed through by design (see `admin.current_admin`), so the
    404 rule could not be tested at all. A fixture that cannot produce the
    condition it asserts is the failure mode this file exists to avoid.
    """
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    monkeypatch.setattr(settings, "auth_secret", secrets.token_urlsafe(48))
    db.reset_connection()
    db.init_db()
    admin.ensure_schema()
    (tmp_path / "uploads").mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_role(name: str) -> str:
    role_id = f"role_{secrets.token_hex(6)}"
    conn = db.connect()
    with conn:
        conn.execute("INSERT INTO roles (id, name, description, created_at) "
                     "VALUES (?, ?, '', ?)", (role_id, name, _now()))
    return role_id


def make_user(email: str, roles: tuple[str, ...] = ()) -> str:
    user_id = f"usr_{secrets.token_hex(4)}"
    conn = db.connect()
    with conn:
        conn.execute(
            """INSERT INTO users (id, email, display_name, password_hash,
                                  is_active, created_at)
               VALUES (?, ?, ?, 'x', 1, ?)""",
            (user_id, email, email.split("@")[0], _now()))
        for name in roles:
            row = conn.execute("SELECT id FROM roles WHERE name = ?",
                               (name,)).fetchone()
            conn.execute("INSERT INTO user_roles (user_id, role_id, granted_at) "
                         "VALUES (?, ?, ?)", (user_id, row["id"], _now()))
    return user_id


def make_document(document_id: str, filename: str = "spec.pdf") -> str:
    conn = db.connect()
    with conn:
        conn.execute(
            """INSERT INTO documents (id, filename, sha256, size_bytes,
                                      stored_path, status, uploaded_at)
               VALUES (?, ?, ?, 1, '/dev/null', 'ready', ?)""",
            (document_id, filename, secrets.token_hex(32), _now()))
    return document_id


def grant_row(document_id: str, role_name: str) -> None:
    conn = db.connect()
    row = conn.execute("SELECT id FROM roles WHERE name = ?", (role_name,)).fetchone()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO document_role_access "
            "(document_id, role_id, granted_at) VALUES (?, ?, ?)",
            (document_id, row["id"], _now()))


def auth_headers(user_id: str) -> dict:
    return {"Authorization": f"Bearer {auth.issue_token(user_id)}"}


def call(client: TestClient, method: str, path: str, body, headers: dict):
    """One helper for every route, including the two that take a body on a
    method most clients do not send one with. DELETE /api/admin/grants carries
    the grant it is revoking, which is what the contract specifies."""
    return client.request(method, path, json=body, headers=headers)


@pytest.fixture
def world():
    """Roles, an admin, a non-admin, a document, and a live grant."""
    for name in ("admin",) + DISCIPLINES:
        make_role(name)
    admin_id = make_user("boss@example.com", ("admin",))
    plain_id = make_user("worker@example.com", ("Mechanical",))
    doc = make_document("doc_1")
    grant_row(doc, "Mechanical")
    return {"admin": admin_id, "plain": plain_id, "document": doc}


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ------------------------------------------------------------------ rule 1


@pytest.mark.parametrize("method,path,body", ROUTES,
                         ids=[f"{m} {p}" for m, p, _ in ROUTES])
def test_non_admin_gets_404_on_every_admin_route(client, world, method, path, body):
    """404, never 403. A 403 confirms the route exists and what it guards.

    Three callers, three ways of not being an admin, and the same answer to
    all of them - because a probe must not be able to tell them apart either.
    """
    for headers in (auth_headers(world["plain"]),          # real user, no admin
                    {"Authorization": "Bearer not-a-token"},
                    {}):                                    # anonymous
        response = call(client, method, path, body, headers)
        assert response.status_code == 404, (
            f"{method} {path} answered {response.status_code} to a non-admin")
        assert response.json()["detail"]["code"] == "not_found"


@pytest.mark.parametrize("method,path,body", ROUTES,
                         ids=[f"{m} {p}" for m, p, _ in ROUTES])
def test_an_admin_reaches_every_route(client, world, method, path, body):
    """The other half of the test above, and the reason it means anything.

    Without this the 404 test would pass just as happily against an app with
    no admin routes at all, or one that refused every caller. Here the SAME
    table, with an admin token, must not 404 - so the 404s above are the guard
    firing rather than the routes being absent.
    """
    # The placeholder id in the table is deliberately unknown - an unknown id
    # is a legitimate 404 and would hide a route that refused the admin - so
    # the reachability run points it at a user that really exists.
    path = path.replace("usr_00000000", world["plain"])
    response = call(client, method, path, body, auth_headers(world["admin"]))
    assert response.status_code != 404, (
        f"{method} {path} refused an admin: {response.text[:200]}")


# ------------------------------------------------------------------ rule 2


def _scope_now(user_id: str) -> access.AccessScope:
    """The scope a request from this user would resolve to RIGHT NOW.

    Built through `access.current_scope` with a real bearer header rather than
    by calling `scope_for_user` directly, so the test exercises the same path a
    live request takes - resolver included. The token is issued once and reused
    across both calls: that is what makes this a next-REQUEST test rather than
    a next-LOGIN one.
    """
    token = auth.issue_token(user_id)
    request = Request({
        "type": "http", "method": "GET", "path": "/api/search",
        "query_string": b"", "root_path": "", "scheme": "http",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
    })
    return access.current_scope(request)


def test_revoke_is_visible_on_the_next_request(client, world):
    """A revoked document leaves the user's scope on their NEXT request.

    Not their next login: no new token is issued between the two checks below,
    and no state is reset. If a scope cache is ever added and `revoke_grant`
    does not invalidate it, this test is the one that goes red.
    """
    before = _scope_now(world["plain"])
    assert world["document"] in before.allowed_document_ids, (
        "the fixture did not grant the document, so a revoke would prove nothing")

    response = call(client, "DELETE", "/api/admin/grants",
                    {"document_id": world["document"], "discipline": "Mechanical"},
                    auth_headers(world["admin"]))
    assert response.status_code == 200
    assert response.json()["granted"] is False

    after = _scope_now(world["plain"])
    assert world["document"] not in after.allowed_document_ids
    assert after.may_read(world["document"]) is False


def test_a_grant_is_visible_on_the_next_request_too(client, world):
    """The same property in the other direction, so the test above cannot pass
    by the scope simply always being empty."""
    make_document("doc_2", "second.pdf")
    assert "doc_2" not in _scope_now(world["plain"]).allowed_document_ids

    call(client, "PUT", "/api/admin/grants",
         {"document_id": "doc_2", "discipline": "Mechanical"},
         auth_headers(world["admin"]))

    assert "doc_2" in _scope_now(world["plain"]).allowed_document_ids


def test_deactivation_takes_effect_on_the_next_request(client, world):
    """Deactivating a user empties their scope without touching their token.

    `auth.resolve_user_id` re-reads `is_active` on every request, so this holds
    for a token issued before the deactivation - which is the case that
    matters, because it is the only one an attacker controls.
    """
    assert _scope_now(world["plain"]).allowed_document_ids

    response = client.delete(f"/api/admin/users/{world['plain']}",
                             headers=auth_headers(world["admin"]))
    assert response.status_code == 200
    assert response.json() == {"user_id": world["plain"], "active": False}

    assert _scope_now(world["plain"]).allowed_document_ids == frozenset()


# ------------------------------------------------------------------ rule 3


def test_setup_token_is_returned_once_and_never_again(client, world):
    """It appears in the create response and in NO subsequent listing.

    The assertion is on the RAW BODY, not on a key. A token leaking under a
    differently-named field, or inside a message, would satisfy a
    `"setup_token" not in payload` check and fail this one.
    """
    created = client.post("/api/admin/users",
                          json={"email": "new@example.com",
                                "disciplines": ["Mechanical"]},
                          headers=auth_headers(world["admin"]))
    assert created.status_code == 201
    payload = created.json()
    token = payload["setup_token"]
    assert token and payload["shown_once"] is True
    assert payload["setup_token_expires_at"].endswith("Z")

    listed = client.get("/api/admin/users", headers=auth_headers(world["admin"]))
    assert listed.status_code == 200
    assert token not in listed.text
    assert "setup_token" not in listed.text
    for row in listed.json()["users"]:
        assert "setup_token" not in row

    # And it is not sitting in the database in plaintext either, which is what
    # makes "never again" a property of the storage rather than of the route.
    stored = db.connect().execute(
        "SELECT token_sha256 FROM user_setup_tokens WHERE user_id = ?",
        (payload["user_id"],)).fetchone()
    assert stored is not None
    assert stored["token_sha256"] != token
    import hashlib

    assert stored["token_sha256"] == hashlib.sha256(token.encode()).hexdigest()


def test_two_users_get_different_setup_tokens(client, world):
    """A constant token would pass the test above completely."""
    headers = auth_headers(world["admin"])
    one = client.post("/api/admin/users", json={"email": "a@example.com"},
                      headers=headers).json()["setup_token"]
    two = client.post("/api/admin/users", json={"email": "b@example.com"},
                      headers=headers).json()["setup_token"]
    assert one != two
    assert len(one) >= 32


# ------------------------------------------------------------------ rule 4


def test_an_admin_cannot_deactivate_themselves(client, world):
    """Without this the last admin locks everyone out of the system."""
    response = client.delete(f"/api/admin/users/{world['admin']}",
                             headers=auth_headers(world["admin"]))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "cannot_deactivate_self"

    row = db.connect().execute("SELECT is_active FROM users WHERE id = ?",
                               (world["admin"],)).fetchone()
    assert row["is_active"] == 1, "the refusal must not have half-applied"


def test_an_admin_can_deactivate_somebody_else(client, world):
    """The other half - otherwise the test above passes on a route that
    refuses every deactivation."""
    response = client.delete(f"/api/admin/users/{world['plain']}",
                             headers=auth_headers(world["admin"]))
    assert response.status_code == 200
    row = db.connect().execute("SELECT is_active FROM users WHERE id = ?",
                               (world["plain"],)).fetchone()
    assert row["is_active"] == 0


def test_deactivate_is_idempotent_and_never_deletes(client, world):
    """Deactivating twice is a 200 both times, and the row survives.

    A hard delete would orphan the conversations and reports that reference
    this user, and a report's whole value is that it says who asked for it.
    """
    headers = auth_headers(world["admin"])
    first = client.delete(f"/api/admin/users/{world['plain']}", headers=headers)
    second = client.delete(f"/api/admin/users/{world['plain']}", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert db.connect().execute("SELECT COUNT(*) AS n FROM users WHERE id = ?",
                                (world["plain"],)).fetchone()["n"] == 1


def test_deactivating_an_unknown_user_is_404_not_200(client, world):
    response = client.delete("/api/admin/users/usr_deadbeef",
                             headers=auth_headers(world["admin"]))
    assert response.status_code == 404


# ------------------------------------------------------------------ rule 5
#
# The contract's fifth test is a DOM assertion and belongs to the frontend.
# This is its backend half, and it is the half that decides the outcome: a UI
# cannot render nothing if the API hands it a placeholder.


def test_last_login_at_is_null_and_never_a_placeholder(client, world):
    """null, not "never", not "-", not 0, not "".

    Asserted on the RAW JSON as well as the parsed value, because a string
    "null" and a JSON null read identically once parsed by a lenient client
    and only one of them lets a UI decide to render nothing.
    """
    created = client.post("/api/admin/users", json={"email": "fresh@example.com"},
                          headers=auth_headers(world["admin"]))
    assert created.status_code == 201
    new_id = created.json()["user_id"]

    listed = client.get("/api/admin/users", headers=auth_headers(world["admin"]))
    row = next(u for u in listed.json()["users"] if u["user_id"] == new_id)

    assert row["last_login_at"] is None
    assert row["last_login_at"] not in ("never", "Never", "-", "N/A", "", 0)
    assert '"last_login_at":null' in listed.text.replace(" ", "")


def test_last_login_at_is_carried_through_when_it_exists(client, world):
    """So the test above cannot pass by the field always being null."""
    with db.connect() as conn:
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?",
                     ("2026-09-05T18:12:04+00:00", world["plain"]))
    listed = client.get("/api/admin/users", headers=auth_headers(world["admin"]))
    row = next(u for u in listed.json()["users"] if u["user_id"] == world["plain"])
    assert row["last_login_at"] == "2026-09-05T18:12:04Z"


# ------------------------------------------------------------------ rule 6


def test_put_twice_is_not_an_error_and_does_not_double_grant(client, world):
    """Idempotent, so the UI can retry a click that timed out."""
    make_document("doc_3", "third.pdf")
    body = {"document_id": "doc_3", "discipline": "Civil Engineering"}
    headers = auth_headers(world["admin"])

    first = call(client, "PUT", "/api/admin/grants", body, headers)
    second = call(client, "PUT", "/api/admin/grants", body, headers)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {
        "document_id": "doc_3", "discipline": "Civil Engineering", "granted": True}

    rows = db.connect().execute(
        "SELECT COUNT(*) AS n FROM document_role_access WHERE document_id = ?",
        ("doc_3",)).fetchone()["n"]
    assert rows == 1, f"{rows} grant rows after two identical PUTs"


def test_revoking_something_never_granted_is_200(client, world):
    """The client asked for a state, and the state is now true."""
    make_document("doc_4", "fourth.pdf")
    response = call(client, "DELETE", "/api/admin/grants",
                    {"document_id": "doc_4", "discipline": "Civil Engineering"},
                    auth_headers(world["admin"]))
    assert response.status_code == 200
    assert response.json()["granted"] is False


def test_a_grant_is_echoed_in_its_canonical_spelling(client, world):
    """`civil engineering` in, `Civil Engineering` back - so the UI never ends
    up with two labels for one discipline."""
    make_document("doc_5")
    response = call(client, "PUT", "/api/admin/grants",
                    {"document_id": "doc_5", "discipline": "civil ENGINEERING"},
                    auth_headers(world["admin"]))
    assert response.status_code == 200
    assert response.json()["discipline"] == "Civil Engineering"


# ------------------------------------------------------- the error contract


def test_error_codes_are_not_coerced_to_internal(client, world):
    """`errors.safe_error` turns an UNREGISTERED code into `internal`.

    Every code below is one the UI switches on, and every one of them reaching
    the client as "internal" would make a caller's own mistake look like a
    server crash - the exact failure errors.py exists to prevent. This test is
    what keeps `admin.ADMIN_ERROR_CODES` registered.
    """
    headers = auth_headers(world["admin"])
    cases = [
        (client.post("/api/admin/users", json={"email": "not-an-email"},
                     headers=headers), 422, "invalid_email"),
        (client.post("/api/admin/users", json={"email": "worker@example.com"},
                     headers=headers), 409, "email_in_use"),
        (client.post("/api/admin/users",
                     json={"email": "z@example.com", "disciplines": ["Astrology"]},
                     headers=headers), 422, "unknown_discipline"),
        (call(client, "PUT", "/api/admin/grants",
              {"document_id": "doc_missing", "discipline": "Mechanical"},
              headers), 404, "unknown_document"),
        (call(client, "PUT", "/api/admin/grants",
              {"document_id": "doc_1", "discipline": "Astrology"},
              headers), 422, "unknown_discipline"),
        (client.delete(f"/api/admin/users/{world['admin']}", headers=headers),
         409, "cannot_deactivate_self"),
    ]
    for response, status, code in cases:
        assert response.status_code == status, response.text[:200]
        assert response.json()["detail"]["code"] == code, (
            f"expected {code}, got {response.json()['detail']['code']}")


def test_a_refused_create_writes_no_user(client, world):
    """A user created and then refused a discipline is the "seeded but useless"
    state this screen exists to make visible."""
    before = db.connect().execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    response = client.post(
        "/api/admin/users",
        json={"email": "half@example.com", "disciplines": ["Mechanical", "Astrology"]},
        headers=auth_headers(world["admin"]))
    assert response.status_code == 422
    after = db.connect().execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    assert after == before


# ------------------------------------------------------------- no passwords


def test_no_password_is_accepted_or_returned(client, world):
    """There is no parameter for a password, and one sent anyway is inert.

    The account must be unusable until the setup token is redeemed. If the
    submitted value had reached `password_hash`, the verify below would
    succeed - which is exactly the browser password path the contract refuses.
    """
    response = client.post("/api/admin/users",
                           json={"email": "pw@example.com",
                                 "password": "hunter2hunter2"},
                           headers=auth_headers(world["admin"]))
    assert response.status_code == 201
    assert "password" not in response.text.lower()

    stored = db.connect().execute(
        "SELECT password_hash FROM users WHERE id = ?",
        (response.json()["user_id"],)).fetchone()["password_hash"]
    from argon2.exceptions import VerificationError, VerifyMismatchError

    with pytest.raises((VerifyMismatchError, VerificationError)):
        auth._hasher.verify(stored, "hunter2hunter2")


def test_two_created_users_do_not_share_a_password_hash(client, world):
    """A fixed placeholder hash would mean that the day one such account's
    secret leaked, every one of them was open."""
    headers = auth_headers(world["admin"])
    ids = [client.post("/api/admin/users", json={"email": f"u{n}@example.com"},
                       headers=headers).json()["user_id"] for n in (1, 2)]
    hashes = {db.connect().execute(
        "SELECT password_hash FROM users WHERE id = ?", (i,)
    ).fetchone()["password_hash"] for i in ids}
    assert len(hashes) == 2


# ---------------------------------------------------------------- warnings


def test_a_user_with_no_discipline_is_warned_about(client, world):
    """The "seeded but useless" state: this user logs in successfully and sees
    an empty corpus, which during a demo looks like broken search."""
    created = client.post("/api/admin/users", json={"email": "lonely@example.com",
                                                    "disciplines": []},
                          headers=auth_headers(world["admin"]))
    listed = client.get("/api/admin/users", headers=auth_headers(world["admin"])).json()
    rows = {u["user_id"]: u for u in listed["users"]}

    assert rows[created.json()["user_id"]]["warning"] == "no_discipline"
    assert rows[created.json()["user_id"]]["disciplines"] == []
    # And a user who HAS one is not warned about, so the field is not a
    # constant dressed up as a check.
    assert rows[world["plain"]]["warning"] is None
    assert rows[world["plain"]]["disciplines"] == ["Mechanical"]


def test_the_admin_capability_is_not_a_discipline(client, world):
    """An admin is IT *and* admin. Modelling admin as a fifth discipline forces
    a false choice and means an admin cannot see their own documents."""
    listed = client.get("/api/admin/users", headers=auth_headers(world["admin"])).json()
    row = next(u for u in listed["users"] if u["user_id"] == world["admin"])
    assert row["is_admin"] is True
    assert "admin" not in row["disciplines"]

    disciplines = client.get("/api/admin/disciplines",
                             headers=auth_headers(world["admin"])).json()
    assert "admin" not in [d["name"] for d in disciplines["disciplines"]]


def test_a_discipline_with_no_documents_is_warned_about(client, world):
    body = client.get("/api/admin/disciplines",
                      headers=auth_headers(world["admin"])).json()
    by_name = {d["name"]: d for d in body["disciplines"]}

    assert by_name["Civil Engineering"]["document_count"] == 0
    assert by_name["Civil Engineering"]["warning"] == "no_documents"
    assert by_name["Mechanical"]["document_count"] == 1
    assert by_name["Mechanical"]["warning"] is None
    assert by_name["Mechanical"]["user_count"] == 1
    assert by_name["Civil Engineering"]["user_count"] == 0


def test_a_document_nobody_can_see_is_warned_about(client, world):
    """It is invisible in every search and looks like a broken upload."""
    make_document("doc_orphan", "orphan.pdf")
    body = client.get("/api/admin/grants",
                      headers=auth_headers(world["admin"])).json()
    by_id = {d["document_id"]: d for d in body["documents"]}

    assert by_id["doc_orphan"]["warning"] == "no_discipline_can_see_this"
    assert by_id["doc_orphan"]["disciplines"] == []
    assert by_id[world["document"]]["warning"] is None
    assert by_id[world["document"]]["disciplines"] == ["Mechanical"]
    assert by_id[world["document"]]["filename"] == "spec.pdf"


def test_one_users_data_never_appears_in_anothers_row(client, world):
    """Every row is built from that user's own join, and this is the assertion
    that a shared cursor or a leaked loop variable would break."""
    listed = client.get("/api/admin/users",
                        headers=auth_headers(world["admin"])).json()["users"]
    rows = {u["email"]: u for u in listed}
    assert rows["worker@example.com"]["is_admin"] is False
    assert rows["boss@example.com"]["disciplines"] == []
    assert rows["worker@example.com"]["disciplines"] == ["Mechanical"]


def test_unknown_query_parameters_are_refused(client, world):
    """A client must never be able to believe it asked something it did not."""
    response = client.get("/api/admin/users?active=true",
                          headers=auth_headers(world["admin"]))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unknown_parameter"
