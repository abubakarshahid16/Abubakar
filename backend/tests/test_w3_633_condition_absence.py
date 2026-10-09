"""#633: two absence paths that read as an answer.

1. THE CONDITION GATE'S NOT_APPLICABLE ON ABSENCE. In the v1 term gate a
   stated material that did not contain the clause's term was "proof" the
   condition did not hold, so a Cr-Mo clause was excused against "SA-516 Gr
   70": a value this list cannot name, not a different material. Now only a
   field naming ANOTHER recognised value of the same kind excuses a clause;
   anything else is UNKNOWN, an engineer's question.
2. THE SCOPE RECORD'S FAILED SEARCH SOURCE was only logged. The result and
   the stored record now say which passage source failed (error type only).

Invented values only. Mutations: M6701-M6707
(scripts/mutations/w3_633_condition_absence.py).
"""
from __future__ import annotations

import pytest

from app import comparison, conditions, db, scope_records
from app.config import settings
from tests.test_condition_gate import fact, material, req


# ------------------------------------------------------- 1. the condition gate


def test_an_unrecognised_material_does_not_excuse_a_clause():
    """THE MUTATION TARGET: before #633 this was NOT_APPLICABLE."""
    out = comparison.compare(req(condition="Cr-Mo"), fact(), submittal_facts=[material("SA-516 Gr 70")])
    assert out["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert out["condition"]["state"] == conditions.UNKNOWN
    assert "recognises" in out["condition"]["reason"]


def test_a_different_recognised_material_still_excuses_it_with_proof():
    out = comparison.compare(req(condition="Cr-Mo"), fact(),
                             submittal_facts=[material("316L stainless steel")])
    assert out["status"] == comparison.NOT_APPLICABLE
    assert out["condition"]["state"] == conditions.NOT_SATISFIED
    assert out["condition"]["evidence"]["field_value"] == "316L stainless steel"
    assert "'stainless steel'" in out["condition"]["reason"] or "'stainless'" in out["condition"]["reason"]


@pytest.mark.parametrize("condition, field, value", [
    ("sour service", "service", "process water"),
    ("pump", "equipment type", "skid package"),
])
def test_other_kinds_follow_the_same_rule(condition, field, value):
    result = conditions._evaluate_terms(conditions.classify(condition), condition,
                                        [material(value, field_name=field)])
    assert result["state"] == conditions.UNKNOWN


def test_a_named_other_service_is_proof():
    # The first field names nothing recognised; the second is the proof.
    result = conditions._evaluate_terms(conditions.SHAPE_SERVICE, "sour service",
                                        [material("process duty", field_name="service", id="f1"),
                                         material("sweet service", field_name="fluid service", id="f2")])
    assert result["state"] == conditions.NOT_SATISFIED
    assert result["evidence"]["field_value"] == "sweet service"


# ------------------------------------------------------- 2. the scope record


@pytest.fixture
def scope_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "s633.sqlite")
    db.reset_connection()
    db.init_db()
    with db.connect() as conn:
        conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,"
                     "uploaded_at) VALUES ('std','s.pdf','sha',1,'s.pdf','ready',1,'2026-10-09T00:00:00Z')")
    yield
    db.reset_connection()


def _broken_search(*a, **k):
    raise TimeoutError("the index is busy")


def test_a_failed_search_source_is_named_on_the_passages_call(scope_db):
    failures: list[str] = []
    scope_records.find_passages("std", search_fn=_broken_search, failures=failures)
    assert failures == ["hybrid-search: TimeoutError"]


def test_a_read_with_no_passage_says_a_source_failed(scope_db, monkeypatch):
    real = scope_records.find_passages
    monkeypatch.setattr(scope_records, "find_passages",
                        lambda d, **kw: real(d, search_fn=_broken_search, **kw))
    result = scope_records.read_scope("std", provider=None, lexicon={}, step="test")
    assert result["status"] == "UNKNOWN"
    assert result["sources_failed"] == ["hybrid-search: TimeoutError"]
    assert "a passage source failed: hybrid-search: TimeoutError" in result["why"]
    assert "the index is busy" not in str(result), "error text must never be recorded"


def test_a_stored_record_carries_the_failed_source(monkeypatch):
    passages = [{"page": 1, "method": "first-pages", "text": "This standard covers centrifugal pumps."}]
    monkeypatch.setattr(scope_records, "usable", lambda r: {"x": 1})
    monkeypatch.setattr(scope_records, "verify", lambda parsed, ps, d, lex: ({"covered_equipment": []}, [], 1))

    class R:
        model_tag, prompt_sha256 = "fake", "sha"

    result = scope_records.record_from("std", passages, [R()], lexicon={},
                                       sources_failed=["hybrid-search: TimeoutError"])
    assert result["status"] == "PROPOSED"
    assert result["record"]["sources_failed"] == ["hybrid-search: TimeoutError"]
    clean = scope_records.record_from("std", passages, [R()], lexicon={})
    assert "sources_failed" not in clean["record"] and clean["sources_failed"] == []
