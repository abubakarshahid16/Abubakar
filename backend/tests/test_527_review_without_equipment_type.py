"""#527 (W5b-03): a review of a document with NO equipment type still runs.

An invented procedure (no datasheet, no classified equipment type) cites a standard the library
holds. The review must select that standard because the procedure NAMES it, and the comparison must
produce findings from the standard's requirements, each with a named status; it must never stop for
want of an equipment type and never end in a silent pass. Invented data only.
"""

from __future__ import annotations

import pytest

from app import applicability, comparison, db
from tests.test_applicability import _doc, _scope, temp_storage  # noqa: F401
from tests.test_b3_page_ledger import _review

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


def test_the_review_of_that_procedure_produces_findings_with_a_named_status(procedure):
    sub, _std = procedure
    run, scope = _review(sub)
    comparison.run_comparison(run, allowed_document_ids=scope)
    findings = [
        dict(r)
        for r in db.connect().execute(
            "SELECT compliance_status, requirement FROM review_findings WHERE review_run_id = ?",
            (run,),
        )
    ]
    assert findings, "a review with no equipment type produced no finding at all"
    assert all(f["compliance_status"] for f in findings)
    # nothing the procedure does not state is passed
    assert not [f for f in findings if f["compliance_status"] == "COMPLIANT"]
