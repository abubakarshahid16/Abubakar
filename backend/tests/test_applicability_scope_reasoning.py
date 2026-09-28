"""The AI-reasoning scope decision wired into `applicability.select()`
(owner request 2026-09-28, `APPLICABILITY_REASONING_ENABLED`). No taxonomy
involved: a standard's stored, verified scope record is compared against the
submittal's own classified equipment type by a reasoning model.

Mirrors the fixture/helper pattern in test_applicability.py; the fake
provider pattern in test_scope_records.py and test_applicability_reasoning.py."""
from __future__ import annotations

import json
import uuid

import pytest

from app import applicability, applicability_v2, db, keyword, submittal_review
from app import reasoning_provider as rp
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "app.sqlite")
    monkeypatch.setattr(settings, "applicability_reasoning_enabled", True)
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    keyword.ensure_schema()
    yield
    db.reset_connection()


def _doc(doc_id: str, filename: str, role: str, text: str = "", **meta) -> str:
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',1,'2026-09-18T00:00:00Z')""",
            (doc_id, filename, f"sha-{doc_id}", filename))
        columns = ["document_id", "suggested_by", "document_role", *meta]
        values = [doc_id, "test", role, *meta.values()]
        conn.execute(
            f"INSERT INTO document_classification ({','.join(columns)})"
            f" VALUES ({','.join('?' * len(values))})", values)
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES (?,?,?,0,1,1,NULL,'prose',?,1,?,1)""",
            (f"{doc_id}-c1", doc_id, filename, text or filename, f"h-{doc_id}"))
    keyword.index_document(doc_id)
    return doc_id


def _scope(*ids): return frozenset(ids)


RECORD_EXCLUDES_DOMESTIC = {
    "covered_equipment": [{"term": "centrifugal pumps", "quote": "covers centrifugal pumps", "page": 2}],
    "covered_activities": [], "explicit_limits": [],
    "explicit_exclusions": [{"term": "domestic water pumps",
                            "quote": "does not apply to pumps in domestic water service", "page": 2}],
    "generic_scope": False,
}


class FakeProvider:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def reason(self, packet):
        text = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return rp.Response(text=text, provider="claude", model_tag="fake", digest="d", finish_reason="stop",
                           prompt_sha256=packet.sha256, schema_errors=rp.schema_errors(text, packet.json_schema))


def _answer(decision, quote=None, page=None, basis="because"):
    return json.dumps({"decision": decision, "basis": basis, "quote": quote, "page": page})


def test_a_standard_with_no_stored_scope_record_is_not_decided(monkeypatch):
    """The explicit reading step (generate_scope_records.py) has not run for
    this standard yet - select() must not guess in its place."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", equipment_type="Centrifugal Pump")
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub), persist=False)
    assert result["scope_decision_not_run"] is not None
    row = next((s for s in result["selected"] if s["standard_document_id"] == std), None)
    assert row is None or row.get("scope_decision") is None


def test_applicable_scope_decision_includes_the_standard(monkeypatch):
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", equipment_type="Centrifugal Pump")
    applicability.store_scope_record(std, RECORD_EXCLUDES_DOMESTIC)
    applicable = _answer(applicability_v2.APPLICABLE, basis="covered equipment matches")
    provider = FakeProvider([applicable])
    monkeypatch.setattr(rp, "get_provider", lambda *a, **k: provider)
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub), persist=False)
    row = next(s for s in result["selected"] if s["standard_document_id"] == std)
    assert row["method"] == applicability.METHOD_SCOPE
    assert row["scope_decision"] == applicability_v2.APPLICABLE


def test_not_applicable_confirmed_three_times_excludes_the_standard(monkeypatch):
    # The standard shares equipment_type with the submittal, so it IS
    # selected by that method first - proving the scope decision actually
    # changes something observable, not just that nothing crashed.
    std = _doc("std", "s.pdf", "COMPANY_STANDARD", equipment_type="Domestic Water Pump")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", equipment_type="Domestic Water Pump")
    applicability.store_scope_record(std, RECORD_EXCLUDES_DOMESTIC)
    na = _answer(applicability_v2.NOT_APPLICABLE,
                quote="does not apply to pumps in domestic water service", page=2)
    provider = FakeProvider([na, na, na, na])
    monkeypatch.setattr(rp, "get_provider", lambda *a, **k: provider)
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub), persist=False)
    row = next(s for s in result["selected"] if s["standard_document_id"] == std)
    assert row.get("excluded_by_scope") is not None


def test_a_fabricated_not_applicable_quote_never_excludes_a_standard(monkeypatch):
    """THE SAFETY ANCHOR, proven at the select() level, not just inside
    applicability_reasoning's own unit tests: a model that invents evidence
    for an exclusion must never remove a standard from the engineer's list.
    Same equipment_type match as the test above, so this is the same
    situation with only the quote changed from real to fabricated."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD", equipment_type="Domestic Water Pump")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", equipment_type="Domestic Water Pump")
    applicability.store_scope_record(std, RECORD_EXCLUDES_DOMESTIC)
    fabricated = _answer(applicability_v2.NOT_APPLICABLE,
                         quote="this is definitely not covered, trust me", page=2)
    provider = FakeProvider([fabricated, fabricated, fabricated, fabricated])
    monkeypatch.setattr(rp, "get_provider", lambda *a, **k: provider)
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub), persist=False)
    row = next(s for s in result["selected"] if s["standard_document_id"] == std)
    assert row.get("excluded_by_scope") is None
    assert row["method"] == applicability.METHOD_EQUIPMENT


def test_a_model_exception_is_held_back_not_crashed(monkeypatch):
    """A down model or a hit budget cap must leave the review workable, not
    raise out of select()."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", equipment_type="Centrifugal Pump")
    applicability.store_scope_record(std, RECORD_EXCLUDES_DOMESTIC)

    def _boom(*a, **k):
        raise RuntimeError("model unavailable")
    monkeypatch.setattr(rp, "get_provider", _boom)
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub), persist=False)
    assert result is not None  # did not raise
