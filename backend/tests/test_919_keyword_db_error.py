"""A5/#919: keyword search must not read a locked or corrupt database as
"no results". Only a malformed MATCH expression (a caller-typed query
SQLite's FTS5 grammar rejects) stays silent; every other OperationalError
must surface. Invented data only.
"""
from __future__ import annotations

import sqlite3

import pytest

from app import db, fts_index
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    fts_index.ensure_schema()
    yield
    db.reset_connection()


def _run(conn, match):
    where, params = fts_index._scope_clause(None, frozenset({"doc"}))
    return fts_index._run_match(conn, match, where, params, 10)


# ---------------------------------------------- malformed MATCH still silent

@pytest.mark.parametrize("bad_match", [
    "AND",                  # fts5: syntax error near "AND"
    '"unterminated',        # unterminated string
    "*not_a_real_query",    # unknown special query: not_a_real_query
    "no_such_col:term",     # no such column: no_such_col
])
def test_a_malformed_match_expression_still_returns_no_results(bad_match):
    conn = db.connect()
    assert _run(conn, bad_match) == []


def test_the_malformed_match_classifier_matches_what_sqlite_actually_says():
    """Proves `_is_malformed_match` is driven by real SQLite messages, not a
    guess at their wording."""
    conn = db.connect()
    for bad_match in ("AND", '"unterminated', "*nope", "no_such_col:x"):
        with pytest.raises(sqlite3.OperationalError) as caught:
            conn.execute(
                "SELECT * FROM chunks_fts WHERE chunks_fts MATCH ?", (bad_match,)
            ).fetchall()
        assert fts_index._is_malformed_match(caught.value), caught.value


# --------------------------------------------- a real DB error must surface

def test_a_locked_database_is_not_reported_as_no_results(monkeypatch):
    def _raise(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    conn = db.connect()
    monkeypatch.setattr(conn, "execute", _raise)
    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        _run(conn, "pump")


def test_a_corrupt_database_is_not_reported_as_no_results(monkeypatch):
    def _raise(*a, **k):
        raise sqlite3.OperationalError("database disk image is malformed")
    conn = db.connect()
    monkeypatch.setattr(conn, "execute", _raise)
    with pytest.raises(sqlite3.OperationalError, match="malformed"):
        _run(conn, "pump")


def test_a_disk_io_error_is_not_reported_as_no_results(monkeypatch):
    def _raise(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")
    conn = db.connect()
    monkeypatch.setattr(conn, "execute", _raise)
    with pytest.raises(sqlite3.OperationalError, match="I/O"):
        _run(conn, "pump")
