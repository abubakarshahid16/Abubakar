"""#195: a role set AFTER the document is READY runs the READY hooks.

WHAT WAS WRONG. The ingest hooks ask what a document is at the moment it
becomes READY. An upload has no role then; the role comes afterwards, from
the bulk role action (`set_role`) or the Details form (`confirm`). Only a
COMPANY_STANDARD had a second hook, so a document that became a
CONTRACTOR_SUBMITTAL after READY never got its facts, its equipment type or
its title-block metadata.

These tests hold the WIRING: which READY hooks run, from which route, in
which state. What each hook does (and its own role gate) is held by
`test_ingest_fact_extraction.py` and the classifier tests.
"""
from __future__ import annotations

import pytest

from app import classification, db, ingest
from app.config import settings
from app.db import connect

# Order 211 (audit R1): the classifiers run BEFORE the facts are read, so the
# reader knows what the sheet is (`test_211_classify_before_read.py`).
HOOKS = ("_queue_extraction_if_standard",
         "_classify_equipment_type_if_contractor_submittal",
         "_classify_metadata_if_contractor_submittal",
         "_extract_facts_if_contractor_submittal", "_refresh_page_ledger")
CLASSIFIERS = HOOKS[1:3]


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def _document(doc_id: str, status: str = "ready") -> str:
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,uploaded_at)"
            " VALUES (?, 'sheet.pdf', ?, 1, '/nowhere', ?, '2026-01-01')",
            (doc_id, f"sha-{doc_id}", status))
    return doc_id


@pytest.fixture
def ran(monkeypatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    for name in HOOKS:
        monkeypatch.setattr(ingest, name, lambda d, _n=name: calls.append((_n, d)))
    return calls


def test_set_role_after_ready_runs_every_ready_hook_in_the_worker_order(ran):
    _document("d1")
    assert classification.set_role("d1", "CONTRACTOR_SUBMITTAL")
    assert ran == [(name, "d1") for name in HOOKS]


def test_a_standard_set_after_ready_still_queues_extraction(ran):
    _document("d1")
    classification.set_role("d1", "COMPANY_STANDARD")
    assert ("_queue_extraction_if_standard", "d1") in ran


def test_confirm_after_ready_runs_the_hooks_but_never_the_classifiers(ran):
    """The form IS the classification: with authentication off `confirmed_by`
    is NULL, and a classifier would otherwise overwrite what was just typed."""
    _document("d1")
    classification.confirm("d1", doc_type=None, discipline=None, doc_class=None,
                           subject_ids=(), confirmed_by=None,
                           metadata={"document_role": "CONTRACTOR_SUBMITTAL"})
    names = [name for name, _ in ran]
    assert "_extract_facts_if_contractor_submittal" in names
    assert not set(CLASSIFIERS) & set(names)


def test_confirm_without_a_role_runs_nothing(ran):
    _document("d1")
    classification.confirm("d1", doc_type=None, discipline=None, doc_class=None,
                           subject_ids=(), confirmed_by=None, metadata={"title": "x"})
    assert ran == []


def test_an_unchanged_role_runs_nothing_again(ran):
    _document("d1")
    classification.set_role("d1", "CONTRACTOR_SUBMITTAL")
    ran.clear()
    assert not classification.set_role("d1", "CONTRACTOR_SUBMITTAL")
    assert ran == []


def test_a_document_still_ingesting_is_left_to_the_ingest_hooks(ran):
    _document("d1", status="chunking")
    classification.set_role("d1", "CONTRACTOR_SUBMITTAL")
    assert ran == []


def test_a_classifier_failure_is_recorded_and_does_not_fail_the_role_change(monkeypatch):
    _document("d1")
    monkeypatch.setattr(ingest, "_extract_facts_if_contractor_submittal", lambda d: None)
    monkeypatch.setattr(ingest, "_refresh_page_ledger", lambda d: None)

    def boom(document_id):
        raise RuntimeError("classifier down")

    monkeypatch.setattr(classification, "classify_equipment_type_for_submittal", boom)
    assert classification.set_role("d1", "CONTRACTOR_SUBMITTAL")
    failed = connect().execute(
        "SELECT COUNT(*) FROM jobs WHERE document_id = 'd1'"
        " AND stage = 'equipment_type_classify' AND state = 'failed'").fetchone()[0]
    assert failed == 1, "the failure is recorded as a visible jobs row"
