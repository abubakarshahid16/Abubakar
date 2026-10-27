"""#474 (W6-04): a database migrated from an older build has the same schema as a
fresh one, and the lookups the app makes by document id are indexed.

The oldest supported build is rebuilt from today's schema by taking away every
column a migration adds (found by reading `db.py`), then running `init_db`
again. A migration whose column definition (type, NOT NULL, default) differs
from the one in a fresh database, or that forgets an index, shows as a named
difference. Invented data only; no model, no socket.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import db
from app.config import settings

#: A column that cannot be taken away on this SQLite build, with the reason the
#: build gives. Listed so a column never leaves the check without a trace.
UNDROPPABLE = {("chunks", "locator")}
#: The fewest migration-added columns the check must actually exercise.
MIN_EXERCISED = 20


def _migration_columns() -> set[tuple[str, str]]:
    src = Path(db.__file__).read_text(encoding="utf-8")
    pairs = set(re.findall(r"ALTER TABLE (\w+)\s+ADD COLUMN\s+(\w+)", src))
    pairs |= set(
        re.findall(r'add_column_if_missing\(\s*conn,\s*"(\w+)",\s*"(\w+)"', src)
    )
    return pairs


def _shape(conn) -> tuple[dict, set]:
    names = [
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    tables = {
        t: {
            r["name"]: (r["type"], r["notnull"], r["dflt_value"], r["pk"])
            for r in conn.execute(f"PRAGMA table_info({t})")
        }
        for t in names
    }
    indexes = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        )
    }
    return tables, indexes


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield db.connect()
    db.reset_connection()


def _take_away_migration_columns(conn) -> list[tuple[str, str]]:
    gone = []
    for table, column in sorted(_migration_columns()):
        if column not in {
            r["name"] for r in conn.execute(f"PRAGMA table_info({table})")
        }:
            continue
        # an index on the column must go first; the schema or the migration
        # puts it back, and the comparison below checks that it did
        for name, sql in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=?"
            " AND sql IS NOT NULL",
            (table,),
        ).fetchall():
            if re.search(rf"\b{column}\b", sql):
                conn.execute(f"DROP INDEX {name}")
        try:
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        except Exception:  # noqa: BLE001 - named in UNDROPPABLE or the test fails
            assert (table, column) in UNDROPPABLE, (table, column)
            continue
        gone.append((table, column))
    conn.commit()
    return gone


def test_a_database_migrated_from_an_older_build_has_the_schema_of_a_fresh_one(fresh):
    before = _shape(fresh)
    gone = _take_away_migration_columns(fresh)
    assert len(gone) >= MIN_EXERCISED, (
        f"only {len(gone)} migration columns were exercised"
    )
    after_drop = _shape(fresh)
    assert after_drop != before  # the older build really differs
    path = settings.db_path
    db.reset_connection()
    settings.db_path = path
    db.init_db()
    migrated = _shape(db.connect())
    differences = [
        (
            table,
            column,
            before[0][table].get(column),
            migrated[0].get(table, {}).get(column),
        )
        for table in before[0]
        for column in before[0][table]
        if before[0][table].get(column) != migrated[0].get(table, {}).get(column)
    ]
    assert differences == [], differences
    assert before[1] - migrated[1] == set(), "indexes a migration did not put back"
    assert migrated[1] - before[1] == set()


def test_running_init_db_again_changes_nothing(fresh):
    before = _shape(fresh)
    db.init_db()
    db.init_db()
    assert _shape(db.connect()) == before


def test_a_lookup_of_report_documents_by_document_id_uses_an_index(fresh):
    plan = fresh.execute(
        "EXPLAIN QUERY PLAN SELECT report_id FROM report_documents WHERE document_id = ?",
        ("x",),
    ).fetchall()
    text = " ".join(str(r["detail"]) for r in plan)
    assert "USING" in text and "INDEX" in text, text
    assert "SCAN" not in text, text
