"""`standard_labels`: how a review names its standards (moved out of the review
run, #882 follow-up). Same words as before: the library file name, then the
recorded number and title where they exist."""

from __future__ import annotations

import pytest

from app import db, standard_labels, submittal_review
from app.config import settings

NOW = "2026-10-20T00:00:00Z"


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "labels.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    with db.connect() as conn:
        for doc_id, number, title in (("s1", "STD-1", "Pumps"), ("s2", None, None)):
            conn.execute(
                "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
                "status,page_count,uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
                (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf", NOW),
            )
            conn.execute(
                "INSERT INTO document_classification (document_id,suggested_by,"
                "document_role,document_number,title) VALUES (?,?,?,?,?)",
                (doc_id, "test", "COMPANY_STANDARD", number, title),
            )
    yield
    db.reset_connection()


def test_no_standards_is_an_empty_mapping_and_no_query():
    assert standard_labels.filenames([]) == {}
    assert standard_labels.labels([], {}) == {}


def test_filenames_are_the_library_file_names(library):
    assert standard_labels.filenames(["s1", "s2", "nope"]) == {
        "s1": "s1.pdf",
        "s2": "s2.pdf",
    }


def test_a_label_is_the_file_name_then_the_number_and_title_where_recorded(library):
    names = standard_labels.filenames(["s1", "s2"])
    assert standard_labels.labels(["s1", "s2"], names) == {
        "s1": "s1.pdf STD-1 Pumps",
        "s2": "s2.pdf",
    }


def test_a_standard_with_no_file_name_and_no_record_has_an_empty_label(library):
    assert standard_labels.labels(["ghost"], {}) == {"ghost": ""}
