"""The database explorer's routes: who may look, and what they may see.

TWO CLAIMS, AND STANDING RULE 15 MEANS BOTH ARE ASSERTED ON THE WIRE.

  THE GATE. Every route depends on `admin.current_admin`, which answers a
  non-admin with 404 rather than 403 - a 403 confirms the route exists, and
  this surface names every table in the system. Phase 6 shipped an
  admin-gated route nobody could use because nine tests called the FUNCTION
  and never the route, and because the suite pins `AUTH_MODE=disabled`, where
  `current_admin` waves an ANONYMOUS caller straight through. So each route
  here is probed by a REAL non-admin with a REAL token under
  `demo_required` - the only arrangement that can see the gate at all.

  THE MASK. Credential-shaped columns never leave the process with their
  values. Asserted against the real `users` table, whose `password_hash`
  holds an argon2 digest, rather than against a fixture column invented to be
  masked - a mask proven only on a column nobody stores secrets in is a mask
  proven nowhere.

Mutations: M225-M229, `python scripts/mutation_check.py --phase 20`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import access, auth, db
from app.config import settings
from app.main import app

NOW = "2026-09-19T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "explorer.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    access.set_user_resolver(None)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()


def _user(user_id: str, *, is_admin: bool) -> None:
    """A real user with a real password, and the admin CAPABILITY or not.

    `admin.is_admin` reads the grant tables like everything else, so an admin
    here is made the way production makes one - not by setting a flag this
    test invented.
    """
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id,email,display_name,password_hash,"
            "is_active,created_at) VALUES (?,?,?,?,1,?)",
            (user_id, f"{user_id}@e.test", user_id.title(),
             auth._hasher.hash("explorer-pass"), NOW))
        if is_admin:
            conn.execute(
                "INSERT OR IGNORE INTO roles (id,name,description,kind,"
                "created_at) VALUES ('role_admin','admin','admins',"
                "'capability',?)", (NOW,))
            conn.execute("INSERT OR IGNORE INTO user_roles (user_id,role_id,"
                         "granted_at) VALUES (?,'role_admin',?)",
                         (user_id, NOW))


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(auth.resolve_user_id)
    return TestClient(app)


def _headers(client: TestClient, user_id: str) -> dict:
    login = client.post("/api/auth/login",
                        json={"email": f"{user_id}@e.test",
                              "password": "explorer-pass"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


#: Every route this file guards, so a new one cannot be added without a
#: decision about whether it is gated - the parametrised tests below sweep it.
ROUTES = (
    "/api/admin/db/tables",
    "/api/admin/db/tables/users",
    "/api/admin/db/tables/users/rows",
)


# ================================================================== the gate

@pytest.mark.parametrize("path", ROUTES)
def test_a_real_non_admin_with_a_real_token_gets_the_silent_404(
        path, monkeypatch):
    """STANDING RULE 15, ON EVERY ROUTE. Signed in, valid token, simply not an
    admin. 404 and not 403, because a 403 would confirm the route is there."""
    _user("plain", is_admin=False)
    client = _client(monkeypatch)

    response = client.get(path, headers=_headers(client, "plain"))

    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "not_found"


@pytest.mark.parametrize("path", ROUTES)
def test_an_unauthenticated_caller_gets_the_same_silent_404(path, monkeypatch):
    """No token at all reads identically to a non-admin's token. A caller
    cannot learn whether their credentials were the problem."""
    _user("plain", is_admin=False)
    client = _client(monkeypatch)

    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", ROUTES)
def test_a_real_admin_is_let_through(path, monkeypatch):
    """THE GUARD ON THE GUARD. Without this, a route that 404s at EVERYONE
    would pass every test above while the feature does not exist."""
    _user("boss", is_admin=True)
    client = _client(monkeypatch)

    response = client.get(path, headers=_headers(client, "boss"))

    assert response.status_code == 200, response.text


# ============================================================== what it shows

def test_the_table_list_carries_row_counts(monkeypatch):
    _user("boss", is_admin=True)
    client = _client(monkeypatch)

    body = client.get("/api/admin/db/tables",
                      headers=_headers(client, "boss")).json()

    tables = {t["name"]: t["row_count"] for t in body["tables"]}
    assert tables["users"] == 1, "the admin this test just created"
    assert "documents" in tables
    assert not any(n.startswith("sqlite_") for n in tables)


def test_an_unknown_table_is_not_found_rather_than_an_error(monkeypatch):
    _user("boss", is_admin=True)
    client = _client(monkeypatch)
    headers = _headers(client, "boss")

    assert client.get("/api/admin/db/tables/nope",
                      headers=headers).status_code == 404
    assert client.get("/api/admin/db/tables/nope/rows",
                      headers=headers).status_code == 404


def test_a_page_of_rows_states_the_whole_table_as_its_denominator(monkeypatch):
    """Rule 4: a page with no total implies completeness it does not have."""
    _user("boss", is_admin=True)
    with db.connect() as conn:
        for i in range(7):
            conn.execute(
                "INSERT INTO documents (id,filename,sha256,size_bytes,"
                "stored_path,status,page_count,uploaded_at)"
                " VALUES (?,?,?,1,?,'ready',1,?)",
                (f"d{i}", f"f{i}.pdf", f"sha{i}", f"f{i}.pdf", NOW))
    client = _client(monkeypatch)

    body = client.get("/api/admin/db/tables/documents/rows?limit=3&offset=2",
                      headers=_headers(client, "boss")).json()

    assert len(body["rows"]) == 3
    assert body["total"] == 7
    assert body["offset"] == 2 and body["limit"] == 3


def test_the_row_cap_holds_however_loudly_it_is_asked(monkeypatch):
    _user("boss", is_admin=True)
    client = _client(monkeypatch)

    body = client.get("/api/admin/db/tables/users/rows?limit=100000",
                      headers=_headers(client, "boss")).json()

    assert body["limit"] <= 200


# =================================================================== the mask

def test_the_real_password_hash_never_reaches_the_wire(monkeypatch):
    """THE WHOLE POINT, ON THE REAL COLUMN. `users.password_hash` holds an
    argon2 digest; an admin browsing tables must not be shown it."""
    _user("boss", is_admin=True)
    stored = db.connect().execute(
        "SELECT password_hash FROM users WHERE id = 'boss'").fetchone()[0]
    assert stored.startswith("$argon2"), "the fixture stored no real hash"
    client = _client(monkeypatch)

    body = client.get("/api/admin/db/tables/users/rows",
                      headers=_headers(client, "boss")).json()

    flat = "\n".join(str(v) for row in body["rows"] for v in row)
    assert stored not in flat, "the argon2 hash was rendered in full"
    assert "$argon2" not in flat, "some argon2 digest was rendered"
    column = body["columns"].index("password_hash")
    assert body["rows"][0][column] == "•••"


def test_the_column_name_is_never_hidden(monkeypatch):
    """ONLY THE VALUE GOES. Dropping the column would make the explorer
    misreport the shape of the table, which is the one thing it is for."""
    _user("boss", is_admin=True)
    client = _client(monkeypatch)
    headers = _headers(client, "boss")

    rows = client.get("/api/admin/db/tables/users/rows", headers=headers).json()
    info = client.get("/api/admin/db/tables/users", headers=headers).json()

    assert "password_hash" in rows["columns"]
    assert "password_hash" in rows["masked_columns"]
    names = {c["name"]: c["sensitive"] for c in info["columns"]}
    assert names["password_hash"] is True
    assert names["email"] is False


def test_unmasked_columns_in_the_same_row_are_untouched(monkeypatch):
    """The guard on the mask: a test that only checked the hash was gone
    would also pass against a route that returned nothing at all."""
    _user("boss", is_admin=True)
    client = _client(monkeypatch)

    body = client.get("/api/admin/db/tables/users/rows",
                      headers=_headers(client, "boss")).json()

    row = body["rows"][0]
    assert row[body["columns"].index("email")] == "boss@e.test"
    assert row[body["columns"].index("display_name")] == "Boss"
