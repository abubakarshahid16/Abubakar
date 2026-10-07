"""W1: every column that points at a document is accounted for, and a delete leaves a record.

Two defects, one cause. `DELETE /api/documents/{id}` depended on each table's
author having thought about it, and nothing checked that anyone had. Later
tables (reports, deliverables, field names, chat filing, acquisitions) each
chose differently, and a delete wrote no audit row at all.

 * `app/document_refs.py` lists every document reference with a disposition.
   This test builds the full schema, finds every reference by column name, and
   fails if one is missing, if a registry entry names a column that no longer
   exists, or if a declared foreign-key action differs from the database.
 * A delete writes one `document.deleted` audit row, ids and counts only.

Names are invented (SUBMITTAL-A-001).
"""

from __future__ import annotations

import re

from app import document_refs, field_naming, standards_acquisition
from app.db import connect

from tests.r2_security_support import h, temp_storage, world  # noqa: F401


def _full_schema() -> None:
    """Tables created lazily by their own module are created here too."""
    standards_acquisition.ensure_schema()
    with connect() as conn:
        conn.execute(field_naming._TABLE)


def _tables(conn) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]


def _columns(conn, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info('{table}')")]


def test_every_document_reference_is_in_the_registry(world):
    _full_schema()
    conn = connect()
    pattern = re.compile(document_refs.REFERENCE_COLUMN_PATTERN)
    found = {(t, c) for t in _tables(conn) if t not in document_refs.NOT_REFERENCES
             for c in _columns(conn, t) if pattern.search(c)}
    missing = sorted(found - set(document_refs.REGISTRY))
    assert not missing, (
        "columns that name a document but are not in app/document_refs.py: "
        f"{missing}. Decide what a delete does to each and add a row.")


def test_every_registry_entry_still_exists_and_has_a_reason(world):
    _full_schema()
    conn = connect()
    for (table, column), (disposition, reason) in document_refs.REGISTRY.items():
        assert table in _tables(conn), f"registry names a missing table: {table}"
        assert column in _columns(conn, table), f"{table}.{column} no longer exists"
        assert disposition in document_refs.DISPOSITIONS, (table, column, disposition)
        assert len(reason.strip()) >= 15, f"{table}.{column}: say WHY in the reason"


def test_declared_foreign_key_actions_match_the_database(world):
    _full_schema()
    conn = connect()
    actions = {}
    for table in _tables(conn):
        for row in conn.execute(f"PRAGMA foreign_key_list('{table}')"):
            if row[2] == "documents":
                actions[(table, row[3])] = row[6]
    for (table, column), (disposition, _) in document_refs.REGISTRY.items():
        actual = actions.get((table, column))
        if disposition == document_refs.FK_CASCADE:
            assert actual == "CASCADE", f"{table}.{column} is declared cascade but is {actual}"
        elif disposition == document_refs.FK_SET_NULL:
            assert actual == "SET NULL", f"{table}.{column} is declared set-null but is {actual}"
        else:
            assert actual is None, (
                f"{table}.{column} has a foreign key to documents ({actual}) but is "
                f"registered as {disposition}; register the real behaviour")


def test_a_delete_writes_one_audit_row_without_the_filename(world):
    r = world.delete("/api/documents/doc_sub?confirm=true", headers=h("u_admin"))
    assert r.status_code == 200, r.text
    rows = connect().execute(
        "SELECT actor_user_id, actor_username, resource_id, outcome, detail"
        " FROM audit_events WHERE action = 'document.deleted'").fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["resource_id"] == "doc_sub" and row["outcome"] == "ok"
    assert row["actor_user_id"] == "u_admin"
    assert row["actor_username"] == "u_admin@example.com"
    assert "documents=1" in row["detail"]
    assert "SUBMITTAL-A-001" not in row["detail"], "the audit row carried a filename"


def test_a_refused_delete_writes_no_deleted_row(world):
    """Without confirm the document stays, so no record may claim it went."""
    r = world.delete("/api/documents/doc_sub", headers=h("u_admin"))
    assert r.status_code == 400
    n = connect().execute(
        "SELECT COUNT(*) FROM audit_events WHERE action = 'document.deleted'").fetchone()[0]
    assert n == 0
    assert connect().execute("SELECT COUNT(*) FROM documents WHERE id='doc_sub'").fetchone()[0] == 1


def test_a_non_admin_cannot_delete_and_nothing_is_recorded(world):
    r = world.delete("/api/documents/doc_sub?confirm=true", headers=h("u_sub"))
    assert r.status_code == 404
    n = connect().execute(
        "SELECT COUNT(*) FROM audit_events WHERE action = 'document.deleted'").fetchone()[0]
    assert n == 0
