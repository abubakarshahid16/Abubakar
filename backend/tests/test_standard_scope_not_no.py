"""Owner 3 Nov 12:20: a standard the table lists for other equipment is a Query for the engineer, never "does not
appear to apply", unless a scope shows it excludes this equipment. Invented documents only."""

from __future__ import annotations

from app import applicability, crs_mapping
from app.config import settings
from tests.test_applicability import _doc, _scope, temp_storage  # noqa: F401


def _pump(text):
    return _doc(
        "sub",
        "pump-sheet.pdf",
        "CONTRACTOR_SUBMITTAL",
        text=text,
        equipment_type="relief valve",
    )


def _check(sub):
    return applicability.standards_check(sub, allowed_document_ids=_scope(sub))


TEXT = "Pump per API 610. Relief valve per API 526."


def test_off_the_other_types_code_is_still_called_not_applicable(monkeypatch):
    monkeypatch.setattr(settings, "standard_scope_not_no_enabled", False)
    check = _check(_pump(TEXT))
    assert "API 610" in {r["identifier"] for r in check["cited_not_applicable"]}


def test_on_it_is_a_query_row_for_the_engineer_never_does_not_apply(monkeypatch):
    monkeypatch.setattr(settings, "standard_scope_not_no_enabled", True)
    check = _check(_pump(TEXT))
    assert "API 610" not in {r["identifier"] for r in check["cited_not_applicable"]}
    declared = {r["identifier"]: r for r in check["declared_check"]}
    assert "no scope clause of the standard was read" in declared["API 610"]["reason"]
    assert "nothing shown excludes" not in declared["API 610"]["reason"]
    rows = crs_mapping.standards_check_rows(check, "pump-sheet.pdf")
    mine = [r for r in rows if r["standard_reference"] == "API 610"]
    assert len(mine) == 1  # the Query reaches a CRS row
    assert mine[0]["row_kind"] == crs_mapping.ROW_KIND_NEEDS_ENGINEER_REVIEW
    assert "engineer to check which clauses apply" in mine[0]["comment"]
    assert "does not appear to apply" not in mine[0]["comment"]


def test_off_there_is_no_scope_query_row(monkeypatch):
    monkeypatch.setattr(settings, "standard_scope_not_no_enabled", False)
    rows = crs_mapping.standards_check_rows(_check(_pump(TEXT)), "pump-sheet.pdf")
    assert [r for r in rows if "scope clause" in r["comment"]] == []
    assert any("does not appear to apply" in r["comment"] for r in rows)
