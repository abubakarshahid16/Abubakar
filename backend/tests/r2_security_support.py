"""Shared setup for the r2 security tests (test_r2_security_*.py).

One world, built through the real tables and REAL bearer tokens, under
`AUTH_MODE=demo_required` - under `disabled` every caller is unrestricted and a
negative assertion passes for the wrong reason, so `world` asserts the mode.

    u_admin   the admin capability
    u_sub     read grant on doc_sub (a submittal) only
    u_full    read grants on doc_sub AND doc_std (the standard)
    u_none    an account with no grant at all

Names are invented (STD-A-001); no real document or client appears anywhere.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import access, admin, auth, db
from app.config import settings
from app.db import connect
from app.main import app


RAISE = False


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def h(user_id: str) -> dict:
    return {"Authorization": f"Bearer {auth.issue_token(user_id)}"}


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "u")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    db.reset_connection()
    db.init_db()
    from app import keyword
    keyword.ensure_schema()
    from app import deliverables, review, risks, submittal_review
    for mod in (review, submittal_review, deliverables, risks):
        mod.ensure_schema()
    yield
    access.set_user_resolver(None)
    db.reset_connection()


def add_document(doc_id: str, filename: str, tmp_path) -> None:
    stored = tmp_path / f"{doc_id}.bin"
    stored.write_bytes(b"x")
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,"
            " status, page_count, uploaded_at) VALUES (?, ?, ?, 1, ?, 'ready', 3, ?)",
            (doc_id, filename, secrets.token_hex(32), str(stored), now()))


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", secrets.token_urlsafe(48))
    admin.ensure_schema()
    conn = connect()
    with conn:
        for rid, name, kind in (("r_admin", "admin", "capability"),
                                ("r_sub", "SubReader", "discipline"),
                                ("r_full", "FullReader", "discipline")):
            conn.execute("INSERT INTO roles (id, name, description, kind, created_at)"
                         " VALUES (?, ?, '', ?, ?)", (rid, name, kind, now()))
        for uid, rid in (("u_admin", "r_admin"), ("u_sub", "r_sub"),
                         ("u_full", "r_full"), ("u_none", None)):
            conn.execute("INSERT INTO users (id, email, display_name, password_hash,"
                         " is_active, created_at) VALUES (?, ?, ?, 'x', 1, ?)",
                         (uid, f"{uid}@example.com", uid, now()))
            if rid:
                conn.execute("INSERT INTO user_roles (user_id, role_id, granted_at)"
                             " VALUES (?, ?, ?)", (uid, rid, now()))
    add_document("doc_sub", "SUBMITTAL-A-001.pdf", tmp_path)
    add_document("doc_std", "STD-A-001.pdf", tmp_path)
    with conn:
        for doc, role in (("doc_sub", "r_sub"), ("doc_sub", "r_full"),
                          ("doc_std", "r_full"), ("doc_sub", "r_admin"),
                          ("doc_std", "r_admin")):
            conn.execute("INSERT INTO document_role_access (document_id, role_id,"
                         " permission, granted_at) VALUES (?, ?, 'read', ?)",
                         (doc, role, now()))
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(auth.resolve_user_id)
    assert settings.auth_mode == access.AUTH_REQUIRED, \
        "fixture ran under `disabled`; every negative assertion would be vacuous"
    yield TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=RAISE)
