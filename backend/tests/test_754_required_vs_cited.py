"""#754 F5b: review a submittal against the standards that APPLY to it, and
say when the contractor did not reference one.

REQUIRED = governing standards for the equipment type + the standards of a
service condition the datasheet declares present. Each outcome is a result:
required-not-cited gives ONE CRS row (never one per requirement), cited-not-
held stays the missing-standards list and is never met, cited-not-applicable
gives a note, an unknown type behaves as before. Invented documents only.
"""
from __future__ import annotations

from app import applicability, crs_mapping, datasheets
from tests.test_applicability import _doc, _run, _scope, temp_storage  # noqa: F401


def _psv(text="Set pressure 340 psig.", **meta):
    return _doc("sub", "psv-datasheet.pdf", "CONTRACTOR_SUBMITTAL", text=text,
                equipment_type="relief valve", **meta)


def _fact(sub, label, value, page=1):
    datasheets.create_fact(submittal_document_id=sub, chunk_id=f"{sub}-c1",
                           field_label=label, raw_value=value, page=page,
                           review_run_id=_run(sub))


def _check(*ids):
    return applicability.standards_check(ids[0], allowed_document_ids=_scope(*ids))


def _not_cited(check):
    return {r["identifier"]: r for r in check["required_not_cited"]}


def test_a_required_standard_the_contractor_did_not_cite_gives_exactly_one_crs_row():
    """THE MUTATION TARGET."""
    std = _doc("std_520", "API-520-I.pdf", "COMPANY_STANDARD", document_number="API 520 Part I")
    sub = _psv(text="Sizing per API 526. Set pressure 340 psig.")
    check = _check(sub, std)
    missed = _not_cited(check)
    assert "API 520 Part I" in missed and "API 526" not in missed
    assert missed["API 520 Part I"]["held"] is True
    assert missed["API 520 Part I"]["standard_document_id"] == std
    assert "relief valve" in missed["API 520 Part I"]["reason"]
    rows = crs_mapping.build_crs_rows([], [], "psv-datasheet.pdf", standards_check=check)
    mine = [r for r in rows if r["row_kind"] == crs_mapping.ROW_KIND_STANDARD_NOT_CITED
            and r["standard_reference"] == "API 520 Part I"]
    assert len(mine) == 1
    assert mine[0]["comment"].startswith(
        "Contractor did not reference API 520 Part I; confirm compliance with API 520 Part I")
    assert mine[0]["engineer_confirmed"] is False and mine[0]["comment_by"] == "AI Review"
    # One row per missed standard, however many there are: no duplicates.
    keys = [r["comment_key"] for r in rows]
    assert len(keys) == len(set(keys))


def test_a_required_standard_is_reviewed_even_when_not_cited():
    std = _doc("std_520", "API-520-I.pdf", "COMPANY_STANDARD", document_number="API 520 Part I")
    sub = _psv()
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub), persist=False)
    row = {s["standard_document_id"]: s for s in result["selected"]}[std]
    assert row["included"] is True
    assert result["standards_check"]["required_not_cited"]


def test_citing_a_required_standard_by_another_spelling_counts_as_cited():
    sub = _psv(text="Relief valve sized per API RP 520 Pt-1 and API 520 Part II, API 521, "
                    "API 526, API 527 and SAES-J-600.")
    assert _check(sub)["required_not_cited"] == []


def test_a_declared_service_condition_adds_its_standard():
    nace = _doc("std_nace", "nace.pdf", "COMPANY_STANDARD", document_number="NACE MR0175")
    sub = _psv(text="API 520 Part I, API 520 Part II, API 521, API 526, API 527, SAES-J-600.")
    _fact(sub, "Sour service", "Yes", page=1)
    check = _check(sub, nace)
    missed = _not_cited(check)
    assert list(missed) == ["NACE MR0175"]
    assert "sour service" in missed["NACE MR0175"]["reason"]
    assert "page 1" in missed["NACE MR0175"]["reason"]
    result = applicability.select(sub, allowed_document_ids=_scope(sub, nace), persist=False)
    assert {s["standard_document_id"]: s for s in result["selected"]}[nace]["included"] is True


def test_iso_15156_cited_covers_the_sour_service_requirement():
    sub = _psv(text="API 520 Part I, API 520 Part II, API 521, API 526, API 527, SAES-J-600. "
                    "Materials per ISO 15156.")
    _fact(sub, "Sour service", "Yes")
    assert _check(sub)["required_not_cited"] == []


def test_an_undeclared_or_absent_condition_requires_nothing():
    sub = _psv(text="API 520 Part I, API 520 Part II, API 521, API 526, API 527, SAES-J-600.")
    assert _check(sub)["required_not_cited"] == []
    _fact(sub, "Sour service", "No")
    assert _check(sub)["required_not_cited"] == []


def test_a_cited_standard_not_held_is_listed_and_never_met():
    sub = _psv(text="Sizing per API 526.")
    check = _check(sub)
    assert check["cited_not_held"] == ["API 526"]
    rows = crs_mapping.build_crs_rows([], ["API 526"], "psv.pdf", standards_check=check)
    # Never a CRS verdict row: it stays a Review note (build_review_notes).
    assert not [r for r in rows if r["standard_reference"] == "API 526"
                and r["row_kind"] != crs_mapping.ROW_KIND_STANDARD_NOT_CITED]
    notes = crs_mapping.build_review_notes([], check["cited_not_held"])
    assert notes[0]["standard"] == "API 526"


def test_a_cited_standard_for_another_equipment_type_gives_a_note():
    sub = _psv(text="Pump per API 610. Relief valve per API 526.")
    check = _check(sub)
    na = {r["identifier"]: r for r in check["cited_not_applicable"]}
    assert "API 610" in na and "API 526" not in na
    assert "pump" in na["API 610"]["reason"] and "relief valve" in na["API 610"]["reason"]
    rows = crs_mapping.standards_check_rows(check, "psv.pdf")
    note = [r for r in rows if r["row_kind"] == crs_mapping.ROW_KIND_STANDARD_NOT_APPLICABLE]
    assert len(note) == 1 and note[0]["comment"].startswith(
        "API 610 is cited but does not appear to apply")


def test_a_cited_condition_standard_on_a_sheet_declaring_it_absent_gives_a_note():
    sub = _psv(text="Materials per NACE MR0175.")
    _fact(sub, "Sour service", "No", page=1)
    na = {r["identifier"]: r for r in _check(sub)["cited_not_applicable"]}
    assert "NACE MR0175" in na and "no sour service" in na["NACE MR0175"]["reason"]


def test_a_submittal_with_no_known_type_behaves_as_before():
    sub = _doc("sub", "misc.pdf", "CONTRACTOR_SUBMITTAL", text="Pump per API 610.")
    check = _check(sub)
    assert check["required_not_cited"] == [] and check["cited_not_applicable"] == []
    assert crs_mapping.standards_check_rows(check, "misc.pdf") == []


def test_every_other_library_standard_is_counted_not_listed():
    _doc("std_a", "a.pdf", "COMPANY_STANDARD", document_number="API 650")
    _doc("std_b", "b.pdf", "COMPANY_STANDARD", document_number="API 520 Part I")
    sub = _psv(text="API 520 Part I")
    check = applicability.standards_check(sub, allowed_document_ids=_scope(sub, "std_a", "std_b"))
    assert check["not_used"] == 1


def test_the_crs_preview_carries_the_missed_standard_row():
    """End to end through `main._crs_content`: the preview of a relief-valve
    submittal's run shows the one 'did not reference' row."""
    import uuid

    from fastapi.testclient import TestClient

    from app import access, db
    from app.main import app
    sub = _psv(text="Sizing per API 526.")
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
                     " VALUES (?,?,'completed','2026-10-10T00:00:00Z','2026-10-10T00:00:00Z')", (run, sub))
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="eng", allowed_document_ids=frozenset({sub}))
    try:
        preview = TestClient(app).get(f"/api/reviews/runs/{run}/crs/preview")
    finally:
        app.dependency_overrides.clear()
    assert preview.status_code == 200, preview.text
    text = str(preview.json()["rows"])
    assert "Contractor did not reference API 520 Part I" in text
    assert text.count("Contractor did not reference SAES-J-600") == 1
