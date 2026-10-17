"""#1017: GET /api/reviews/readiness/{id} writes nothing (#478: a GET never
writes). It used to rebuild `page_ledger` on every read.

What must hold: the GET runs on a connection that REFUSES every write and
still answers with the same numbers; a ledger the writers have not built, or
built for another file, or built before the document was a submittal, is
SAID (`ledger_state`, `ledger_note`) with null page counts - never 0 for
"nobody looked"; the re-read route, a POST, still rebuilds it. Invented
sheets only.
"""
from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from app import db, page_ledger
from app.main import app
from tests.test_b3_page_ledger import _sheet, temp_storage  # noqa: F401 - autouse
from tests.test_review_screen import world  # noqa: F401 - an extracted, reviewed sheet


def _get(sub):
    r = TestClient(app).get(f"/api/reviews/readiness/{sub}")
    assert r.status_code == 200, r.text
    return r.json()


def _deny_writes(monkeypatch, writes: list):
    """Every connection opened from now on refuses INSERT/UPDATE/DELETE and
    records the attempt (the #478 walk's own trick)."""
    real_init = db.SchemaRetryConnection.__init__

    def authorizer(action, arg1, arg2, dbname, source):
        if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE) \
                and dbname != "temp" and not str(arg1).startswith("sqlite_"):
            writes.append((action, arg1))
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def guarded(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        self.set_authorizer(authorizer)
    monkeypatch.setattr(db.SchemaRetryConnection, "__init__", guarded)
    db.reset_connection()


def test_the_readiness_get_writes_nothing_and_answers_the_same(world, monkeypatch):
    sub, run, _scope = world
    before = _get(sub)
    assert before["ledger_state"] == "current" and before["pages_total"] >= 1
    rows_before = page_ledger.rows(sub)
    writes: list = []
    _deny_writes(monkeypatch, writes)
    after = _get(sub)
    assert writes == [], f"the GET tried to write: {writes}"
    assert after == before
    assert page_ledger.rows(sub) == rows_before


def test_a_ledger_nobody_built_is_said_not_counted_as_zero(tmp_path):
    sub = _sheet(tmp_path, notes_page=True)
    assert page_ledger.rows(sub) == []
    body = _get(sub)
    assert body["ledger_state"] == "missing"
    assert (body["pages_total"], body["pages_read"], body["unread_pages"]) == (None, None, [])
    assert "not built yet" in body["ledger_note"]
    assert page_ledger.rows(sub) == [], "the GET built the ledger"


def test_a_ledger_built_before_the_document_was_a_submittal_is_said(tmp_path):
    sub = _sheet(tmp_path, notes_page=True)
    page_ledger.refresh(sub)                     # ingest's refresh: no role yet
    assert page_ledger.state(sub) == "not_as_submittal"
    body = _get(sub)
    assert body["ledger_state"] == "not_as_submittal" and body["pages_read"] is None
    from app import datasheets
    datasheets.extract_facts(sub, allowed_document_ids=frozenset({sub}))   # a writer
    body = _get(sub)
    assert body["ledger_state"] == "current" and body["ledger_note"] is None
    assert body["pages_total"] == 2 and body["unread_pages"] == [2]


def test_a_ledger_for_another_file_or_page_count_is_stale(world):
    sub, _run, _scope = world
    with db.connect() as conn:
        conn.execute("UPDATE documents SET sha256 = 'another-file' WHERE id = ?", (sub,))
    assert _get(sub)["ledger_state"] == "stale"
    with db.connect() as conn:
        conn.execute("UPDATE documents SET sha256 = (SELECT file_sha256 FROM page_ledger"
                     " WHERE document_id = ? LIMIT 1), page_count = page_count + 1 WHERE id = ?",
                     (sub, sub))
    body = _get(sub)
    assert body["ledger_state"] == "stale" and body["pages_total"] is None


def test_the_reread_route_a_post_still_rebuilds_the_ledger(tmp_path):
    sub = _sheet(tmp_path, notes_page=True)
    assert _get(sub)["ledger_state"] == "missing"
    r = TestClient(app).post(f"/api/reviews/readiness/{sub}/reread-pages")
    assert r.status_code == 200, r.text
    assert r.json()["ledger_state"] == "current" and r.json()["pages_total"] == 2
