"""Owner order section 3 (screen, part B): "Read unread pages".

Minimum-testing mode (owner decision, 2026-09-27): a few tests for the new
behaviour and the safety rules only - permissions, no data loss, and the
route never sets a compliance verdict.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import comparison, db
from app.main import app
from tests.test_b3_page_ledger import _review, _sheet, temp_storage  # noqa: F401 - autouse
from tests.test_model_matching import _signed_in
from tests.test_review_screen import world  # noqa: F401 - fixture reuse


def test_reread_pages_re_extracts_and_returns_the_readiness_strip(world, monkeypatch):
    sub, _run, scope = world
    _signed_in(monkeypatch, scope)
    calls = []
    import app.main as main_mod
    real = main_mod.datasheets_mod.extract_facts

    def spy(document_id, **kwargs):
        calls.append((document_id, kwargs))
        return real(document_id, **kwargs)

    monkeypatch.setattr(main_mod.datasheets_mod, "extract_facts", spy)
    response = TestClient(app).post(f"/api/reviews/readiness/{sub}/reread-pages")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["submittal_document_id"] == sub
    # Re-extraction runs with replace=True, so a page found unreadable last
    # time is genuinely tried again - not answered from a stale cache.
    [(doc_id, kwargs)] = calls
    assert doc_id == sub and kwargs["replace"] is True


def test_a_caller_without_access_gets_404(world, monkeypatch):
    """Privacy/permissions: re-extracting a submittal is still reading it."""
    sub, _run, _scope = world
    _signed_in(monkeypatch, frozenset(), user_id="outsider")
    assert TestClient(app).post(f"/api/reviews/readiness/{sub}/reread-pages").status_code == 404


def test_nothing_is_deleted_by_a_re_read(world, monkeypatch):
    """No data loss: the run's existing findings survive a re-read of the
    submittal they were about."""
    sub, run, scope = world
    before = db.connect().execute(
        "SELECT COUNT(*) FROM review_findings WHERE review_run_id = ?", (run,)).fetchone()[0]
    _signed_in(monkeypatch, scope)
    assert TestClient(app).post(f"/api/reviews/readiness/{sub}/reread-pages").status_code == 200
    after = db.connect().execute(
        "SELECT COUNT(*) FROM review_findings WHERE review_run_id = ?", (run,)).fetchone()[0]
    assert after == before


def test_reread_pages_writes_no_compliance_verdict(world, monkeypatch):
    """AI never sets pass/fail here: this route reads fields, it does not
    compare them - no new review_findings row and no compliance_status
    written by this call."""
    sub, run, scope = world
    before = {r["id"] for r in db.connect().execute(
        "SELECT id FROM review_findings WHERE review_run_id = ?", (run,))}
    _signed_in(monkeypatch, scope)
    TestClient(app).post(f"/api/reviews/readiness/{sub}/reread-pages")
    after = {r["id"] for r in db.connect().execute(
        "SELECT id FROM review_findings WHERE review_run_id = ?", (run,))}
    assert after == before, "reread-pages must never itself create a finding"
