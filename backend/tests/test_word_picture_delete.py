"""A Word picture's OCR text goes when the last document holding that file goes
(PR 1581, review of it). Readings are keyed by file hash, so no foreign key does it."""

from __future__ import annotations

import sqlite3

from app import document_refs, word_pictures
from app.db import connect
from tests.r2_security_support import h, temp_storage, world  # noqa: F401


def _seed_reading(sha: str) -> None:
    conn = connect()
    word_pictures._ensure_table(conn)
    with conn:
        word_pictures._store(
            conn, sha, 1, word_pictures.STATUS_READ, "SENTINEL-OCR", 0.9, 0.1, None
        )


def _readings() -> int:
    return connect().execute("SELECT COUNT(*) FROM word_picture_readings").fetchone()[0]


def _sha(doc_id: str) -> str:
    row = (
        connect()
        .execute("SELECT sha256 FROM documents WHERE id = ?", (doc_id,))
        .fetchone()
    )
    return row[0]


def test_deleting_the_document_deletes_its_picture_text(world):  # noqa: F811
    _seed_reading(_sha("doc_sub"))
    _seed_reading("some-other-file")
    r = world.delete("/api/documents/doc_sub?confirm=true", headers=h("u_admin"))
    assert r.status_code == 200, r.text
    assert r.json()["rows_removed"]["word_picture_readings"] == 1
    rows = connect().execute("SELECT file_sha256 FROM word_picture_readings").fetchall()
    assert [row[0] for row in rows] == ["some-other-file"]


def test_a_second_document_with_the_same_file_keeps_the_text():
    """`documents.sha256` is unique today, so the rule is proved on a table without that limit."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE documents (id TEXT, sha256 TEXT)")
    conn.execute("CREATE TABLE word_picture_readings (file_sha256 TEXT)")
    conn.executemany(
        "INSERT INTO documents VALUES (?, ?)", [("a", "s"), ("b", "s"), ("c", "t")]
    )
    conn.executemany("INSERT INTO word_picture_readings VALUES (?)", [("s",), ("t",)])
    assert document_refs.forget_picture_readings(conn, "a") == {
        "word_picture_readings": 0
    }
    assert document_refs.forget_picture_readings(conn, "c") == {
        "word_picture_readings": 1
    }
    held = conn.execute("SELECT file_sha256 FROM word_picture_readings").fetchall()
    assert held == [("s",)]


def test_no_table_means_no_new_key_in_the_delete_answer(world):  # noqa: F811
    r = world.delete("/api/documents/doc_sub?confirm=true", headers=h("u_admin"))
    assert r.status_code == 200, r.text
    assert "word_picture_readings" not in r.json()["rows_removed"]
