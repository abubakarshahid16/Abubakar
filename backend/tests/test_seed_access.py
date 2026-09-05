"""`scripts/seed_access.py` - the four disciplines, and admin as a capability.

This script decides who can see what, so the properties asserted here are the
ones that would be silently wrong: that `admin` is orthogonal to discipline
rather than a fifth one, that "seeded but useless" is still detected, and that
no password can arrive except by being typed.

The script is loaded by path rather than imported as a package: `scripts/` is
not a package and never has been.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app import db
from app.config import settings
from app.db import connect

ROOT = Path(__file__).resolve().parents[2]
SEED_PATH = ROOT / "scripts" / "seed_access.py"


def _load():
    spec = importlib.util.spec_from_file_location("seed_access_under_test", SEED_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "u")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


@pytest.fixture
def seed():
    return _load()


NOW = "2026-09-05T00:00:00Z"


def _doc(conn, did):
    conn.execute(
        """INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,
                                  status, uploaded_at)
           VALUES (?,?,?,?,?,'ready',?)""",
        (did, f"{did}.pdf", did * 4, 1, f"/{did}", NOW))
    conn.commit()


def _user(conn, uid, email):
    conn.execute(
        "INSERT INTO users (id, email, display_name, password_hash, created_at)"
        " VALUES (?,?,?,?,?)", (uid, email, uid, "argon2:not-a-real-hash", NOW))
    conn.commit()


def _join(conn, uid, role_name):
    rid = conn.execute("SELECT id FROM roles WHERE name = ?", (role_name,)).fetchone()["id"]
    conn.execute("INSERT INTO user_roles (user_id, role_id, granted_at) VALUES (?,?,?)",
                 (uid, rid, NOW))
    conn.commit()


# --------------------------------------------------------------- the model

def test_the_four_disciplines_are_the_client_requirement(seed):
    assert set(seed.DISCIPLINES) == {
        "Civil Engineering", "Mechanical", "Chemical-Process", "IT"}


def test_admin_is_a_capability_not_a_fifth_discipline(seed):
    """The whole modelling decision, asserted rather than commented.

    If admin were a discipline, an administrator would have to choose between
    administering the system and seeing their own team's documents.
    """
    assert seed.ROLES["admin"][0] == seed.CAPABILITY
    assert "admin" not in seed.DISCIPLINES


def test_seed_roles_creates_five_rows_with_the_right_kinds(seed):
    conn = connect()
    assert seed.seed_roles(conn) == 0
    rows = {r["name"]: r["kind"] for r in conn.execute("SELECT name, kind FROM roles")}
    assert rows == {
        "Civil Engineering": "discipline",
        "Mechanical": "discipline",
        "Chemical-Process": "discipline",
        "IT": "discipline",
        "admin": "capability",
    }


def test_seed_roles_is_idempotent_and_keeps_role_ids(seed):
    """Re-running must not orphan a grant.

    A role id is what every grant and every membership hangs off. Recreating a
    role would silently revoke everything pointing at the old id.
    """
    conn = connect()
    seed.seed_roles(conn)
    before = {r["name"]: r["id"] for r in conn.execute("SELECT name, id FROM roles")}
    seed.seed_roles(conn)
    after = {r["name"]: r["id"] for r in conn.execute("SELECT name, id FROM roles")}
    assert before == after


def test_a_user_holds_a_discipline_and_the_admin_capability_at_once(seed):
    """An IT administrator is IT *and* admin - the false choice, absent."""
    conn = connect()
    seed.seed_roles(conn)
    _user(conn, "u1", "it-admin@example.com")
    _join(conn, "u1", "IT")
    _join(conn, "u1", "admin")
    kinds = {r["kind"] for r in conn.execute(
        """SELECT r.kind FROM user_roles ur JOIN roles r ON r.id = ur.role_id
           WHERE ur.user_id = 'u1'""")}
    assert kinds == {"discipline", "capability"}


# --------------------------------------------------------------- the grants

def test_a_document_is_granted_to_a_discipline(seed):
    conn = connect()
    seed.seed_roles(conn)
    _doc(conn, "doc_civil")
    assert seed.grant(conn, "Civil Engineering", "doc_civil") == 0
    assert conn.execute("SELECT COUNT(*) c FROM document_role_access").fetchone()["c"] == 1


def test_granting_a_document_to_the_admin_capability_is_refused(seed, capsys):
    """A grant to `admin` reaches nobody, so it must fail loudly, not quietly.

    Nobody holds `admin` *as* their discipline; a document granted only to it
    is invisible to every user while looking, in the tables, granted.
    """
    conn = connect()
    seed.seed_roles(conn)
    _doc(conn, "doc_x")
    assert seed.grant(conn, "admin", "doc_x") == 2
    assert conn.execute("SELECT COUNT(*) c FROM document_role_access").fetchone()["c"] == 0
    assert "capability" in capsys.readouterr().err


def test_grant_to_an_unknown_document_is_refused(seed):
    conn = connect()
    seed.seed_roles(conn)
    assert seed.grant(conn, "IT", "doc_missing") == 2


# ---------------------------------------------------------- --verify-only

def test_verify_reports_a_user_with_no_discipline(seed, capsys):
    conn = connect()
    seed.seed_roles(conn)
    _user(conn, "u1", "nobody@example.com")
    assert seed.verify(conn) == 1
    assert "NO ROLES" in capsys.readouterr().out


def test_verify_reports_an_admin_only_user_as_useless(seed, capsys):
    """The capability alone is not access. This is the exact demo-morning bug:
    an administrator signs in successfully and sees an empty corpus."""
    conn = connect()
    seed.seed_roles(conn)
    _user(conn, "u1", "admin@example.com")
    _join(conn, "u1", "admin")
    assert seed.verify(conn) == 1
    assert "NO DISCIPLINE" in capsys.readouterr().out


def test_verify_reports_a_discipline_with_no_document_grants(seed, capsys):
    conn = connect()
    seed.seed_roles(conn)
    assert seed.verify(conn) == 1
    assert "NO DOCUMENT GRANTS" in capsys.readouterr().out


def test_verify_does_not_flag_the_admin_capability_for_having_no_grants(seed, capsys):
    """A check that cries wolf is a check people learn to skip.

    `admin` legitimately has zero document grants forever, so it must never be
    counted as a problem - otherwise `--verify-only` can never reach zero and
    stops meaning anything.
    """
    conn = connect()
    seed.seed_roles(conn)
    _doc(conn, "doc_a")
    _user(conn, "u1", "a@example.com")
    for name in seed.DISCIPLINES:
        seed.grant(conn, name, "doc_a")
        _join(conn, "u1", name)
    capsys.readouterr()
    assert seed.verify(conn) == 0
    out = capsys.readouterr().out
    assert "0 problem(s)" in out
    assert "capability admin" in out          # reported
    assert "NO DOCUMENT GRANTS" not in out    # but not as a problem


def test_verify_names_roles_it_did_not_seed_rather_than_deleting_them(seed, capsys):
    """A legacy `engineer` role from an earlier build keeps its grants."""
    conn = connect()
    conn.execute(
        "INSERT INTO roles (id, name, description, created_at) VALUES (?,?,?,?)",
        ("role_legacy", "engineer", "from an earlier build", NOW))
    conn.commit()
    seed.seed_roles(conn)
    seed.verify(conn)
    out = capsys.readouterr().out
    assert "engineer" in out
    assert conn.execute(
        "SELECT COUNT(*) c FROM roles WHERE name='engineer'").fetchone()["c"] == 1


# ------------------------------------------------------------- the password

def test_there_is_no_password_flag(seed):
    """The docstring's guarantee, asserted against the source.

    "A password can only ever arrive by being typed, interactively, twice."
    """
    source = SEED_PATH.read_text(encoding="utf-8")
    assert 'add_argument("--password' not in source
    assert "getpass.getpass" in source
    assert "os.environ" not in source


def test_weak_passwords_are_refused_with_every_reason_at_once(seed):
    problems = seed.check_password("demo", "demo@example.com")
    assert len(problems) >= 2


def test_a_strong_password_is_accepted(seed):
    assert seed.check_password("Kd8#vqLp2ZrT", "ali@example.com") == []


def test_seeding_a_user_with_only_the_capability_is_refused_before_any_prompt(
        seed, monkeypatch):
    """Refused BEFORE getpass, so the operator is not asked for a secret that
    is about to be thrown away."""
    def _never(*a, **k):
        raise AssertionError("a password was requested for a refused seeding")
    monkeypatch.setattr(seed, "prompt_password", _never)
    conn = connect()
    seed.seed_roles(conn)
    assert seed.seed_user(conn, "a@example.com", ["admin"], force=False) == 2


def test_an_unknown_role_is_refused_before_any_prompt(seed, monkeypatch):
    def _never(*a, **k):
        raise AssertionError("a password was requested for a refused seeding")
    monkeypatch.setattr(seed, "prompt_password", _never)
    conn = connect()
    seed.seed_roles(conn)
    assert seed.seed_user(conn, "a@example.com", ["Electrical"], force=False) == 2


# ------------------------------------------------------------------ schema

def test_roles_kind_defaults_to_discipline_for_rows_written_by_other_code(seed):
    """Every existing caller inserts a role without `kind`. The default must
    keep those rows meaningful rather than NULL."""
    conn = connect()
    conn.execute(
        "INSERT INTO roles (id, name, description, created_at) VALUES (?,?,?,?)",
        ("role_z", "Piping", "d", NOW))
    conn.commit()
    assert conn.execute(
        "SELECT kind FROM roles WHERE id='role_z'").fetchone()["kind"] == "discipline"


def test_an_older_database_gains_kind_and_admin_becomes_a_capability(seed, tmp_path):
    """The migration path: a roles table created before `kind` existed."""
    import sqlite3
    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    old.execute("""CREATE TABLE roles (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                   description TEXT NOT NULL, created_at TEXT NOT NULL)""")
    old.execute("INSERT INTO roles VALUES ('r1','admin','d',?)", (NOW,))
    old.execute("INSERT INTO roles VALUES ('r2','IT','d',?)", (NOW,))
    old.commit()
    old.close()

    settings.db_path = path
    db.reset_connection()
    db.init_db()
    conn = connect()
    rows = {r["name"]: r["kind"] for r in conn.execute("SELECT name, kind FROM roles")}
    assert rows == {"admin": "capability", "IT": "discipline"}
    assert conn.execute("SELECT id FROM roles WHERE name='admin'").fetchone()["id"] == "r1"
