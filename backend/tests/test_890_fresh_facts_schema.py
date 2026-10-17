"""#890: a FRESH database must accept a fact that belongs to no review run.

The server's startup migration (`migrate_facts_to_per_document`) is not run by
loaders or tests; before the fix a fresh `init_db` + `ensure_schema` gave
`submittal_facts.review_run_id` NOT NULL, so the upload-time read of a sheet's
values failed with 'review_run_id may not be empty'.
"""
import pytest

from app import db, submittal_review
from app.config import settings

NOW = "2026-10-17T00:00:00Z"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t890.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()      # NO startup migration, on purpose
    yield
    db.reset_connection()


def test_fresh_schema_has_a_nullable_review_run_id():
    conn = db.connect()
    cols = {r[1]: r for r in conn.execute("PRAGMA table_info(submittal_facts)")}
    assert cols["review_run_id"][3] == 0


def test_a_fact_with_no_review_run_can_be_stored_on_a_fresh_database():
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,"
            " uploaded_at) VALUES ('d1','a.pdf','h',1,'p',?)", (NOW,))
        conn.execute(
            "INSERT INTO submittal_facts (id, review_run_id, submittal_document_id,"
            " field_name, created_at, updated_at) VALUES ('f1', NULL, 'd1', 'x', ?, ?)",
            (NOW, NOW))
    assert conn.execute("SELECT COUNT(*) FROM submittal_facts").fetchone()[0] == 1


def test_the_migration_still_leaves_a_nullable_table_alone():
    submittal_review.migrate_facts_to_per_document()
    cols = {r[1]: r for r in db.connect().execute("PRAGMA table_info(submittal_facts)")}
    assert cols["review_run_id"][3] == 0
