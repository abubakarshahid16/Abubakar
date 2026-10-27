"""#527 (W5b-03): a review of a document with NO equipment type still runs.

An invented procedure (no datasheet, no classified equipment type) cites a standard the library
holds. The review must select that standard because the procedure NAMES it, and the comparison must
produce findings from the standard's requirements, each with a named status; it must never stop for
want of an equipment type and never end in a silent pass. Invented data only.
"""

from __future__ import annotations

import pytest

from app import applicability, comparison, db, standards, submittal_review
from tests.test_applicability import _doc, _scope, temp_storage  # noqa: F401

PROCEDURE = (
    "Operating procedure OP-12. Before start-up the operator shall follow STD-100 and record the "
    "noise level of the pump house."
)


@pytest.fixture
def procedure(temp_storage):  # noqa: F811
    sub = _doc(
        "proc", "operating-procedure.pdf", "CONTRACTOR_SUBMITTAL", text=PROCEDURE
    )
    std = _doc(
        "stdlib",
        "STD-100.pdf",
        "COMPANY_STANDARD",
        text="The noise level shall be recorded.",
        document_number="STD-100",
    )
    return sub, std


def _equipment_type(doc_id):
    row = (
        db.connect()
        .execute(
            "SELECT equipment_type FROM document_classification WHERE document_id = ?",
            (doc_id,),
        )
        .fetchone()
    )
    return row[0] if row else None


def test_the_procedure_has_no_equipment_type(procedure):
    sub, _std = procedure
    assert _equipment_type(sub) is None


def test_the_standard_the_procedure_names_is_selected_without_an_equipment_type(
    procedure,
):
    sub, std = procedure
    chosen = applicability.select(
        sub, allowed_document_ids=_scope(sub, std), persist=False
    )
    [entry] = [s for s in chosen["selected"] if s["standard_document_id"] == std]
    assert entry["method"] == "referenced" and entry["included"] is True
    assert "STD-100" in entry["reason"]
    # a part that could not be decided says so; it is not skipped silently
    assert chosen["scope_decision_not_run"]


def test_the_review_of_that_procedure_produces_findings_from_the_standard_it_named(
    procedure,
):
    """The REAL path (s3's review): the run's applicable standards come from `applicability.select`
    for this procedure, STD-100's own requirement is the one compared, and a finding carries its
    standard. With the selection broken (M1365-01) no finding of STD-100 appears."""
    sub, std = procedure
    scope = _scope(sub, std)
    run = submittal_review.create_review_run(
        submittal_document_id=sub, allowed_document_ids=scope
    )
    applicability.select(
        sub, allowed_document_ids=scope, review_run_id=run, persist=True
    )
    standards.create_requirement(
        standard_document_id=std,
        chunk_id="stdlib-c1",
        clause="4.1",
        page=1,
        requirement_text="The noise level shall not exceed 90 dB(A).",
        source_text="The noise level shall not exceed 90 dB(A).",
        structured={
            "requirement_type": "numeric_limit",
            "operator": "<=",
            "value": 90,
            "unit": "dB(A)",
            "raw_value": "90",
            "raw_unit": "dB(A)",
            "field": "noise level",
            "subject": "the noise level",
        },
    )
    comparison.run_comparison(run, allowed_document_ids=scope)
    findings = [
        dict(r)
        for r in db.connect().execute(
            "SELECT compliance_status, standard_document_id FROM review_findings"
            " WHERE review_run_id = ?",
            (run,),
        )
    ]
    from_the_named_standard = [f for f in findings if f["standard_document_id"] == std]
    assert from_the_named_standard, "no finding from the standard the procedure names"
    assert all(f["compliance_status"] for f in from_the_named_standard)
    # a procedure that states no noise level is never passed on it
    assert not [
        f for f in from_the_named_standard if f["compliance_status"] == "COMPLIANT"
    ]
