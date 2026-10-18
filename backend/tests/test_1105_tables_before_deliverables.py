"""#1105: with the deliverables routes in their own router, a structured search
or a scoped risk read can be the first call on a fresh database. Neither may
fail on a `deliverables` table that no deliverables call has created yet.

Invented data only.
"""

from __future__ import annotations

import pytest

from app import db, risks, structured_search
from app.config import settings


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "fresh.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def test_a_structured_search_on_a_fresh_database_finds_nothing_and_does_not_fail():
    assert (
        structured_search.search(
            "pump", allowed_document_ids=frozenset({"d1"}), include_unowned=False
        )
        == []
    )


def test_a_scoped_risk_read_on_a_fresh_database_finds_nothing_and_does_not_fail():
    assert risks.list_items(allowed_document_ids=frozenset({"d1"})) == []
