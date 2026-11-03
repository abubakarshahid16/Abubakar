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


def test_on_it_is_a_query_for_the_engineer_never_does_not_apply(monkeypatch):
    monkeypatch.setattr(settings, "standard_scope_not_no_enabled", True)
    check = _check(_pump(TEXT))
    assert "API 610" not in {r["identifier"] for r in check["cited_not_applicable"]}
    declared = {r["identifier"]: r for r in check["declared_check"]}
    assert "nothing shown excludes" in declared["API 610"]["reason"]
    assert "engineer" in declared["API 610"]["reason"]
    rows = crs_mapping.standards_check_rows(check, "pump-sheet.pdf")
    assert "does not appear to apply" not in " ".join(r["comment"] for r in rows)
