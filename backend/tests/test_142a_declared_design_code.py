"""Order 142 A, standard level: a code the datasheet declares is never "not
applicable", and an unsure equipment type holds for the engineer.

A sheet guessed to be one equipment type, whose own field VALUE states a code
for another type, is read as unsure (`subject_scope.read_equipment`). Then no
standard is ruled in or out by the disputed type: the guessed type's codes are
not demanded, the AI scope exclusions become "engineer to check", and the
declared code is listed for the engineer, never called "does not appear to
apply". Invented documents and values only.
"""

from __future__ import annotations

from app import applicability, crs_mapping, db
from app import applicability_v2 as v2
from tests.test_754_required_vs_cited import _fact
from tests.test_applicability import _doc, _run, _scope, temp_storage  # noqa: F401

VESSEL_TEXT = "Design code: ASME Sec VIII Div.1. The vessel shell shall be hydrotested."


def _sheet(text=VESSEL_TEXT, code="ASME Sec VIII Div.1", **meta):
    """A sheet classified as an exchanger whose Design code field states `code`."""
    sub = _doc(
        "sub",
        "vessel-sheet.pdf",
        "CONTRACTOR_SUBMITTAL",
        text=text,
        equipment_type="Heat Exchanger",
        **meta,
    )
    _fact(sub, "Design code", code, page=1)
    return sub


def _psv(text):
    return _doc(
        "sub",
        "psv-sheet.pdf",
        "CONTRACTOR_SUBMITTAL",
        text=text,
        equipment_type="relief valve",
    )


def _check(*ids):
    return applicability.standards_check(ids[0], allowed_document_ids=_scope(*ids))


def _is_asme_viii(identifier):
    return "ASME" in identifier and "VIII" in identifier


def test_a_declared_code_is_never_cited_but_not_applicable():
    sub = _sheet()
    check = _check(sub)
    assert not [
        r for r in check["cited_not_applicable"] if _is_asme_viii(r["identifier"])
    ]
    declared = [r for r in check["declared_check"] if _is_asme_viii(r["identifier"])]
    assert len(declared) == 1 and "engineer" in declared[0]["reason"]
    assert "Design code" in declared[0]["reason"] and "page 1" in declared[0]["reason"]
    missed = {r["identifier"] for r in check["required_not_cited"]}
    assert "API 660" not in missed and "API 661" not in missed
    assert check["equipment_unsure"] and "engineer" in check["equipment_unsure"]
    rows = crs_mapping.standards_check_rows(check, "vessel-sheet.pdf")
    text = " ".join(r["comment"] for r in rows)
    assert "does not appear to apply" not in text
    assert "API 660" not in text and "API 661" not in text


def test_unsure_holds_type_only_standards_for_the_engineer():
    std_660 = _doc(
        "std_660",
        "API-660.pdf",
        "COMPANY_STANDARD",
        document_number="API 660",
        equipment_type="Heat Exchanger",
    )
    std_asme = _doc(
        "std_asme",
        "ASME-VIII.pdf",
        "COMPANY_STANDARD",
        document_number="ASME BPVC Section VIII Division 1",
    )
    sub = _sheet()
    ids = _scope(sub, std_660, std_asme)
    result = applicability.select(sub, allowed_document_ids=ids, persist=False)
    rows = {r["standard_document_id"]: r for r in result["selected"]}
    assert rows[std_asme]["included"] is True
    assert rows[std_asme]["method"] == applicability.METHOD_REFERENCED
    assert "engineer" in rows[std_asme]["reason"]
    assert rows[std_660]["included"] is False
    assert "unsure" in rows[std_660]["held_for_engineer"]
    run = _run(sub)
    applicability.select(sub, allowed_document_ids=ids, review_run_id=run)
    stored = (
        db.connect()
        .execute(
            "SELECT included, exclusion_reason FROM review_applicable_standards"
            " WHERE review_run_id = ? AND standard_document_id = ?",
            (run, std_660),
        )
        .fetchone()
    )
    assert stored["included"] == 0 and "engineer" in stored["exclusion_reason"]


def _scope_says_not_applicable(monkeypatch, standard_id):
    def fake(candidates, profile, heartbeat=None):
        return {
            standard_id: {
                "decision": v2.NOT_APPLICABLE,
                "quote": "for drums only",
                "page": 1,
            }
        }, None

    monkeypatch.setattr(applicability, "scope_decisions_by_reasoning", fake)


def _service_row(code):
    std = _doc(
        "std_svc",
        "svc.pdf",
        "COMPANY_STANDARD",
        document_number="XQ-9001",
        service="Hydrogen",
    )
    sub = _sheet(code=code, service="Hydrogen")
    result = applicability.select(
        sub, allowed_document_ids=_scope(sub, std), persist=False
    )
    return {r["standard_document_id"]: r for r in result["selected"]}[std]


def test_unsure_never_excludes_by_scope_reading(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "applicability_reasoning_enabled", True)
    _scope_says_not_applicable(monkeypatch, "std_svc")
    row = _service_row("ASME Sec VIII Div.1")
    # AI-first: the scope reading still ran, and is shown for the engineer.
    assert row["scope_decision"] == v2.NOT_APPLICABLE
    assert row["included"] is True
    assert "engineer to check" in row["reason"] and "for drums only" in row["reason"]


def test_a_sure_sheet_is_still_excluded_by_its_scope_reading(monkeypatch):
    """Control: a sheet whose declared code is its own type's is not unsure."""
    from app.config import settings

    monkeypatch.setattr(settings, "applicability_reasoning_enabled", True)
    _scope_says_not_applicable(monkeypatch, "std_svc")
    row = _service_row("API 660")
    assert (
        row["included"] is False
        and "excludes this equipment" in row["excluded_by_scope"]
    )


def test_a_field_declared_code_for_another_type_on_a_sure_sheet_is_engineer_check():
    sub = _psv("Relief valve per API 526. Pump code: API 610.")
    _fact(sub, "Pump code", "API 610", page=1)
    check = _check(sub)
    # The sheet's own text names its type's code (API 526), so it stays sure:
    # the reader is given the whole record, document id included.
    assert check["equipment_types"] == ["relief valve"]
    assert "API 610" not in {r["identifier"] for r in check["cited_not_applicable"]}
    assert check["equipment_unsure"] is None
    declared = {r["identifier"]: r for r in check["declared_check"]}
    assert "API 610" in declared
    assert (
        "engineer" in declared["API 610"]["reason"]
        and "page 1" in declared["API 610"]["reason"]
    )
    assert "does not appear to apply" not in " ".join(
        r["comment"] for r in crs_mapping.standards_check_rows(check, "psv-sheet.pdf")
    )


def test_a_body_text_citation_for_another_type_still_gives_the_note():
    """Guard (passes before and after): a code cited only in the text, for
    another type, still gets the #754 note."""
    sub = _psv("Pump per API 610. Relief valve per API 526.")
    check = _check(sub)
    assert "API 610" in {r["identifier"] for r in check["cited_not_applicable"]}
    rows = crs_mapping.standards_check_rows(check, "psv-sheet.pdf")
    note = [
        r for r in rows if r["row_kind"] == crs_mapping.ROW_KIND_STANDARD_NOT_APPLICABLE
    ]
    assert len(note) == 1 and note[0]["comment"].startswith(
        "API 610 is cited but does not appear to apply"
    )


def test_a_relief_valve_citing_asme_viii_is_not_called_not_applicable():
    sub = _psv("Relief valve per API 526. Body per ASME BPVC Section VIII Division 1.")
    check = _check(sub)
    assert not [
        r for r in check["cited_not_applicable"] if _is_asme_viii(r["identifier"])
    ]
    assert check["equipment_unsure"] is None
    declared = [r for r in check["declared_check"] if _is_asme_viii(r["identifier"])]
    assert len(declared) == 1
    assert "in part" in declared[0]["reason"] and "engineer" in declared[0]["reason"]
    rows = crs_mapping.standards_check_rows(check, "psv-sheet.pdf")
    assert not [
        r for r in rows if r["row_kind"] == crs_mapping.ROW_KIND_STANDARD_NOT_APPLICABLE
    ]


def _status(code):
    std = _doc(
        "std_pv",
        "pv.pdf",
        "COMPANY_STANDARD",
        text="Unrelated wording about paint.",
        document_number="XQ-7001",
        equipment_type="Pressure Vessel",
    )
    sub = _sheet(code=code)
    out = applicability.applicability_with_reasons(
        sub, allowed_document_ids=_scope(sub, std)
    )
    return {r["standard_document_id"]: r for r in out}[std]


def test_applicability_with_reasons_does_not_rule_out_by_a_disputed_type():
    row = _status("ASME Sec VIII Div.1")
    assert row["status"] == applicability.STATUS_UNKNOWN
    assert "does not match" not in row["reason"]


def test_applicability_with_reasons_still_compares_a_sure_type():
    """Control: the same standard against a sheet that is sure of its type."""
    row = _status("API 660")
    assert row["status"] == applicability.STATUS_NOT_APPLICABLE
    assert "does not match" in row["reason"]
