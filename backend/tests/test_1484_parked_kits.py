"""#1484 (preparation): the parked kit for a drawing, the same look-up as the specification kit routed
by document kind. Invented drawing text only (CLAUDE.md rule 3). No model, no socket. Each test
fails without the code it names.
"""

from __future__ import annotations

import pytest

from app import crs_mapping, db, procedure_text, spec_kit
from app.config import settings
from tests.test_1479_spec_kit import _doc, _rows
from tests.test_b3_page_ledger import _review, temp_storage  # noqa: F401 - autouse

DRAWING_PAGE1 = (
    "Plant No. 123. Drawing Type: PID. Piping and instrumentation diagram of unit 10. "
    "Job Order 765200. Revision block: Rev 00 date 01/02/2026 description issued for construction."
)
DRAWING_PAGE2 = "Scale 1:50. Review required: yes. General notes: all dimensions in mm."


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "parked_kits_draft_enabled", True)


def _world(kind="drawing", pages=(DRAWING_PAGE1, DRAWING_PAGE2)):
    sub = "doc_dwg"
    _doc(sub, list(pages), kind, number="DWG-1", equipment="piping")
    run, scope = _review(sub)
    return sub, run, frozenset(scope)


def test_the_drawing_kit_names_held_and_draft_items_and_cites_a_held_clause():
    kit = spec_kit.kind_kits()["drawing"]
    held, draft = spec_kit.held_count(kit)
    assert "DRAFT" in kit["label"] and held >= 5 and draft >= 4
    assert set(spec_kit.kind_kits()) == {"drawing"}  # transmittal, contract: no held standard
    for item in kit["items"]:
        assert bool(item.get("held")) != bool(item.get("draft_reason")), item["id"]
        if item.get("held"):
            assert item["held"]["standard"] == "SAES-A-202" and item["held"]["page"] > 0
        else:
            assert "DRAFT" in item["draft_reason"]


def test_found_items_are_engineer_rows_with_page_and_a_verified_quote(on):
    _sub, run, scope = _world()
    spec_kit.for_review(run, scope)
    rows = {r["requirement"]: r for r in _rows(run)}
    job = next(r for k, r in rows.items() if "Job Order" in k)
    assert job["compliance_status"] == "NEEDS_ENGINEER_REVIEW"
    assert job["requirement"].startswith("A drawing states: ")
    assert "SAES-A-202 cl. 6.9 (p.20)" in job["requirement"]
    assert job["contractor_page"] == 1 and job["contractor_evidence_text"] in DRAWING_PAGE1
    assert "of the drawing; engineer to confirm" in job["finding"]
    scale = next(r for k, r in rows.items() if k.startswith("A drawing states: Scale"))
    assert scale["contractor_page"] == 2
    assert "specification" not in job["finding"] + job["ai_rationale"]


def test_items_not_found_are_one_counted_note_and_never_missing_information(on):
    _sub, run, scope = _world()
    spec_kit.for_review(run, scope)
    rows = _rows(run)
    kit = spec_kit.kind_kits()["drawing"]
    unfound = [r for r in rows if r["ai_rationale"].startswith(spec_kit.NOT_FOUND)]
    assert len(rows) == len(kit["items"]) and len(unfound) >= 4
    assert all(r["contractor_page"] is None for r in unfound)
    notes = spec_kit.notes(rows)
    assert len(notes) == 1 and notes[0]["count"] == len(unfound)
    assert notes[0]["note"].startswith("Drawing check")
    assert "of the drawing must-contain list (a DRAFT list)" in notes[0]["detail"]
    assert "A drawing states" not in notes[0]["detail"]
    built = crs_mapping.build_crs_rows(rows, [], "dwg.pdf")
    assert len([b for b in built if b.get("row_kind") == "spec_kit"]) == len(rows) - len(
        unfound
    )


def test_a_drawing_is_never_compliant_or_missing_information(on):
    _sub, run, scope = _world(pages=("nothing useful here",))
    spec_kit.for_review(run, scope)
    statuses = {r["compliance_status"] for r in _rows(run)}
    assert statuses == {"NEEDS_ENGINEER_REVIEW"}


def test_a_drawing_with_no_stored_page_text_is_not_run_and_says_so_in_one_note(on):
    _sub, run, scope = _world(pages=("   ",))
    spec_kit.for_review(run, scope)
    rows = _rows(run)
    assert len(rows) == 1 and rows[0]["ai_rationale"].startswith(spec_kit.NOT_RUN)
    notes = spec_kit.notes(rows)
    assert len(notes) == 1 and "Drawing kit not run: no page text is stored" in notes[0]["note"]
    assert spec_kit.NOT_RUN_NOTE not in notes[0]["note"]
    built = crs_mapping.build_crs_rows(rows, [], "dwg.pdf")
    assert [b for b in built if b.get("row_kind") == "spec_kit"] == []


def test_switch_off_changes_nothing():
    _sub, run, scope = _world()
    spec_kit.for_review(run, scope)
    assert _rows(run) == []


def test_the_specification_switch_does_not_open_the_drawing_kit(monkeypatch):
    monkeypatch.setattr(settings, "spec_kit_enabled", True)
    _sub, run, scope = _world()
    spec_kit.for_review(run, scope)
    assert _rows(run) == []


def test_the_drawing_switch_does_not_open_the_specification_kit(on):
    _sub, run, scope = _world(kind="specification")
    assert not spec_kit.applies(_sub)
    spec_kit.for_review(run, scope)
    assert _rows(run) == []


@pytest.mark.parametrize("kind", ["transmittal", "contract", "datasheet", "procedure"])
def test_a_kind_without_a_kit_is_not_run(on, kind):
    _sub, run, scope = _world(kind=kind)
    assert not spec_kit.applies(_sub)
    spec_kit.for_review(run, scope)
    assert _rows(run) == []


def test_the_specification_kit_is_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "spec_kit_enabled", True)
    _sub, run, scope = _world(kind="specification", pages=("Design pressure shall be 12 bar.",))
    assert spec_kit.applies(_sub)
    spec_kit.for_review(run, scope)
    rows = _rows(run)
    assert rows and all(r["requirement"].startswith("A specification states: ") for r in rows)
    notes = spec_kit.notes(rows)
    assert notes[0]["note"] == spec_kit.NOTE
    assert "items of the specification must-contain list (a DRAFT list)" in notes[0]["detail"]
    assert spec_kit.item_row(
        spec_kit.kits()["pressure_vessel"]["items"][0], [(1, "x")]
    )["finding"].endswith("engineer to check.")


def test_a_kind_kit_row_goes_through_the_same_unfound_hooks(on):
    _sub, run, scope = _world()
    spec_kit.for_review(run, scope)
    rows = _rows(run)
    assert all(spec_kit.is_row(r) for r in rows)
    assert any(spec_kit.is_unfound(r) for r in rows)
    assert procedure_text.document_kind(_sub) == "drawing"
    with db.connect() as conn:
        conn.execute("UPDATE document_kinds SET kind = 'transmittal'")
    assert not spec_kit.applies(_sub)
