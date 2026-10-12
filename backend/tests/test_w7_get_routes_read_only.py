"""#478: no GET route writes to the database or sends email.

Walks every GET route that takes no path parameter against a seeded throwaway
database whose connections REFUSE every INSERT, UPDATE and DELETE (SQLite's
authorizer). A GET that writes is recorded with its route and the table, and
the test fails. Email is watched at `notifications.send_email` and at
`smtplib.SMTP`.

KNOWN LIMIT, stated: routes with a path parameter (`/api/documents/{id}` and
the like) are not walked, because they need a real id.

SCHEMA BOOTSTRAP IS NOT A GET WRITE. Several modules create their tables and
seed fixed default rows (escalation rules, stakeholder backfill) the first time
they are used. Every module's `ensure_schema` is therefore run BEFORE the walk
(it is memoised, so it does not run again inside a request), and the walk then
forbids all writes.
"""
from __future__ import annotations

import hashlib
import smtplib
import sqlite3

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import db, deliverables, notifications, review, risks
from app.config import settings

#: (sqlite action, table) pairs a GET may perform: the idempotent
#: `INSERT OR IGNORE` statements inside `deliverables._ensure_tables` (the
#: default escalation rules and the owner backfill). That function is
#: memoised and re-runs only after ANOTHER module changes the schema (a table
#: created on first use), so on a fresh database the first deliverables GET can
#: re-run them. They insert fixed defaults or copy existing owner columns; no
#: user data is created. Anything else a GET writes fails the test.
SCHEMA_BOOTSTRAP = {(sqlite3.SQLITE_INSERT, "escalation_rules"),
                    (sqlite3.SQLITE_INSERT, "deliverable_stakeholders")}



@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "walk.sqlite")
    monkeypatch.setattr(settings, "startup_warmup", False)
    db.reset_connection()
    db.init_db()
    for module in (deliverables, review, risks):
        module.ensure_schema()
    with db.connect() as con:
        con.execute("INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at)"
                    " VALUES ('doc','a.pdf',?,1,'x','ready','2020-01-01')", (hashlib.sha256(b"d").hexdigest(),))
    # Old, open, with unresolved evidence: what the old GET /api/risks acted on.
    review.create({"document_id": "doc", "category": "requirement_deviation", "severity": "major",
                   "requirement": "r", "finding": "f", "required_action": "a",
                   "unresolved_evidence": ["missing citation"]}, created_by=None)
    deliverables.create({"wbs_code": "1.1", "title": "Parent", "deliverable_type": "report",
                         "due_date": "2020-01-01"}, created_by=None)
    db.reset_connection()
    yield
    db.reset_connection()


def test_no_get_route_writes_or_emails(seeded, monkeypatch):
    state = {"on": False, "route": None, "writes": [], "mail": []}
    real_init = db.SchemaRetryConnection.__init__

    def authorizer(action, arg1, arg2, dbname, source):
        if (state["on"] and action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE,
                                       sqlite3.SQLITE_DELETE)
                and dbname != "temp" and not str(arg1).startswith("sqlite_")):
            if (action, arg1) in SCHEMA_BOOTSTRAP:
                return sqlite3.SQLITE_OK
            state["writes"].append((state["route"], action, arg1))
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def guarded_init(self, *args, **kwargs):
        # EVERY connection the app opens, however a module imported `connect`.
        real_init(self, *args, **kwargs)
        self.set_authorizer(authorizer)

    monkeypatch.setattr(db.SchemaRetryConnection, "__init__", guarded_init)
    db.reset_connection()
    monkeypatch.setattr(notifications, "send_email",
                        lambda **kw: state["mail"].append((state["route"], "send_email")) or True)
    monkeypatch.setattr(smtplib, "SMTP",
                        lambda *a, **k: state["mail"].append((state["route"], "smtplib")) or (_ for _ in ()).throw(OSError))
    import sys

    from app.main import app
    for name, module in list(sys.modules.items()):
        if name.startswith("app.") and callable(getattr(module, "ensure_schema", None)):
            module.ensure_schema()
    client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)
    routes = sorted({r.path for r in app.routes
                     if isinstance(r, APIRoute) and "GET" in r.methods and "{" not in r.path})
    assert len(routes) >= 30, "the walk found too few routes to mean anything"
    state["on"] = True
    for path in routes:
        state["route"] = path
        client.get(path)
    state["on"] = False
    offenders = sorted({(route, action, table) for route, action, table in state["writes"]})
    assert offenders == [], f"GET routes that write: {offenders}"
    assert state["mail"] == [], f"GET routes that send email: {state['mail']}"
