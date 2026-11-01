"""#1476: the procedure path. The document is the evidence.

Invented procedure text only. Mutations: M<PR>-NN in scripts/mutations/c1_1476_procedure_path.py.
"""

from __future__ import annotations

import pytest

from app import comparison, db, procedure_text, submittal_review
from app.config import settings

PAGES = [
    (1, "Scope of the work. This procedure covers hydrostatic testing of the pipe spools."),
    (2, "Welders shall be qualified before production welding begins.\nRecords are kept on site."),
]

STATEMENT = {
    "requirement_type": "statement", "operator": None, "raw_value": None, "raw_unit": None,
    "field": None,
    "requirement_text": "Welding procedures shall be qualified before production welding.",
    "source_text": "Welding procedures shall be qualified before production welding.",
}


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "pp.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    yield
    db.reset_connection()


def test_a_found_requirement_is_an_engineer_row_with_a_verified_quote_and_page():
    verdict = comparison.compare(STATEMENT, None, procedure_pages=PAGES)
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "found on page 2" in verdict["rationale"]
    assert "qualified before production welding" in verdict["rationale"]
    assert "engineer to confirm" in verdict["rationale"]
    quote = procedure_text.find_passage(STATEMENT["source_text"], PAGES)["quote"]
    assert quote in dict(PAGES)[2]


def test_nothing_found_is_missing_information_for_the_contractor():
    other = {**STATEMENT, "requirement_text": "Crane lifting plans must name the rigging inspector.",
             "source_text": "Crane lifting plans must name the rigging inspector."}
    verdict = comparison.compare(other, None, procedure_pages=PAGES)
    assert verdict["status"] == comparison.MISSING_INFORMATION
    assert "contractor to show where" in verdict["rationale"]


def test_a_text_match_is_never_compliant():
    for req in (STATEMENT, {**STATEMENT, "required_evidence_type": "procedure"}):
        verdict = comparison.compare(req, None, procedure_pages=PAGES)
        assert verdict["status"] not in (comparison.COMPLIANT, comparison.NON_COMPLIANT)


def test_a_procedure_evidence_demand_is_checked_against_the_text():
    req = {**STATEMENT, "requirement_type": "numeric_limit", "required_evidence_type": "procedure"}
    verdict = comparison.compare(req, None, procedure_pages=PAGES)
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "found on page 2" in verdict["rationale"]


@pytest.mark.parametrize("evidence", ["certificate", "drawing", "report", "calculation", "record"])
def test_a_certificate_or_drawing_demand_still_goes_to_another_document(evidence):
    req = {**STATEMENT, "required_evidence_type": evidence}
    verdict = comparison.compare(req, None, procedure_pages=PAGES)
    assert verdict["status"] == comparison.NOT_IN_DOCUMENT_SCOPE


def test_a_datasheet_submittal_is_unchanged():
    """No pages given (not a procedure): both branches behave as before."""
    assert comparison.compare(STATEMENT, None)["status"] == comparison.NOT_IN_DOCUMENT_SCOPE
    cert = {**STATEMENT, "required_evidence_type": "procedure"}
    assert comparison.compare(cert, None)["status"] == comparison.NOT_IN_DOCUMENT_SCOPE


def test_the_switch_is_off_by_default_and_needs_a_kind(monkeypatch):
    assert settings.procedure_path_enabled is False
    monkeypatch.setattr(settings, "procedure_path_document_ids", "doc1")
    assert procedure_text.is_procedure_submittal("doc1") is False
    monkeypatch.setattr(settings, "procedure_path_enabled", True)
    assert procedure_text.is_procedure_submittal("doc1") is True
    assert procedure_text.is_procedure_submittal("doc2") is False


def test_a_clause_that_only_asks_to_be_stated_on_the_datasheet_is_not_looked_up_in_the_text():
    text = "The relief valve set pressure shall be stated on the datasheet."
    req = {**STATEMENT, "requirement_text": text, "source_text": text}
    pages = [(1, "The relief valve set pressure is tested before the valve is installed.")]
    verdict = comparison.compare(req, None, procedure_pages=pages)
    assert verdict["status"] == comparison.MISSING_INFORMATION
    assert "found on page" not in verdict["rationale"]
    assert "procedure_text" not in verdict["rationale"]
