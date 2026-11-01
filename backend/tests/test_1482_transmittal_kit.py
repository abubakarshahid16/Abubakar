"""#1482 TRANSMITTAL KIT. INVENTED transmittals, held documents and required-submissions list
only (CLAUDE.md rules 1 and 3: the real list is client data and never enters a test). No model,
no socket. Each test fails without the code it names.
"""

from __future__ import annotations

import json

import pytest

from app import access, crs_mapping, db, procedure_text, spec_kit, transmittal_kit
from app.config import settings
from tests.test_1479_spec_kit import _doc, _rows
from tests.test_b3_page_ledger import _review, temp_storage  # noqa: F401 - autouse


@pytest.fixture(autouse=True)
def _resolver():
    yield
    access.set_user_resolver(None)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "transmittal_kit_enabled", True)


HEADER = (
    "TRANSMITTAL\n"
    "Transmittal No: TRN-0001\n"
    "Date: 01/02/2026\n"
    "From: Invented Contractor Ltd\n"
    "To: Invented Owner Co\n"
    "Purpose of Issue: For review\n"
)
TABLE = (
    "Doc No        Title             Rev    Sheets\n"
    "ABC-100-001   Pump datasheet    3      2\n"
    "ABC-100-002   Valve datasheet   1      1\n"
)
HELD = (("ABC-100-001", "3", 2), ("ABC-100-002", "1", 1))


def _transmittal(header=HEADER, table=TABLE):
    _doc("doc_tr", [header + "\n" + table], "transmittal", number="TRN-0001")
    return "doc_tr"


def _held(doc_id, number, rev, pages):
    cover = f"Document No: {number}\nRevision: {rev}\nInvented datasheet cover"
    _doc(
        doc_id,
        [cover] + [f"page {n}" for n in range(2, pages + 1)],
        "datasheet",
        number=number,
    )
    return doc_id


def _world(header=HEADER, table=TABLE, held=HELD, extra=()):
    sub = _transmittal(header, table)
    ids = [_held(f"doc_h{i}", n, r, p) for i, (n, r, p) in enumerate(held, 1)]
    ids += list(extra)
    run, scope = _review(sub)
    return sub, run, frozenset(scope | set(ids))


def _defects(run):
    return [
        r
        for r in _rows(run)
        if not r["ai_rationale"].startswith(transmittal_kit.NOTE_CODE)
    ]


def _notes(run):
    return [
        r for r in _rows(run) if r["ai_rationale"].startswith(transmittal_kit.NOTE_CODE)
    ]


def _items(run):
    return sorted(r["requirement_id"].split(":", 2)[2] for r in _defects(run))


def test_switch_off_changes_nothing():
    _sub, run, scope = _world(header=HEADER.replace("Date: 01/02/2026\n", ""))
    transmittal_kit.for_review(run, scope)
    assert _rows(run) == []


def test_a_complete_transmittal_has_no_defect_rows(on):
    _sub, run, scope = _world()
    transmittal_kit.for_review(run, scope)
    assert _defects(run) == []


def test_exactly_the_four_planted_defects_are_flagged_and_none_is_a_pass(on):
    header = HEADER.replace("Date: 01/02/2026\n", "").replace(
        "Purpose of Issue: For review", "Purpose of Issue:"
    )
    table = TABLE.replace("Valve datasheet   1 ", "Valve datasheet   2 ").replace(
        "Pump datasheet    3      2", "Pump datasheet    3      5"
    )
    _sub, run, scope = _world(header=header, table=table)
    transmittal_kit.for_review(run, scope)
    rows = _defects(run)
    assert _items(run) == [
        "header:date",
        "header:purpose",
        "revision:ABC-100-002",
        "sheets:ABC-100-001",
    ]
    assert {r["compliance_status"] for r in rows} == {"NEEDS_ENGINEER_REVIEW"}
    by = {r["requirement_id"].split(":", 2)[2]: r for r in rows}
    assert "not stated" in by["header:date"]["finding"]
    assert "not stated" in by["header:purpose"]["finding"]
    rev = by["revision:ABC-100-002"]["finding"]
    assert "2" in rev and "1" in rev and "page 1" in rev
    sheets = by["sheets:ABC-100-001"]["finding"]
    assert "5" in sheets and "2" in sheets


def test_a_listed_table_in_tables_json_is_read_like_a_text_table(on):
    sub = _transmittal(table="")
    grid = [
        ["Document Number", "Description", "Revision", "No. of Sheets"],
        ["ABC-100-001", "Pump datasheet", "3", "2"],
        ["ABC-100-002", "Valve datasheet", "9", "1"],
    ]
    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET tables_json = ? WHERE document_id = ? AND page_no = 1",
            (json.dumps({"v": 1, "tables": [{"rows": grid, "lines": []}]}), sub),
        )
    _held("doc_h1", "ABC-100-001", "3", 2)
    _held("doc_h2", "ABC-100-002", "1", 1)
    run, scope = _review(sub)
    transmittal_kit.for_review(run, scope | {"doc_h1", "doc_h2"})
    assert _items(run) == ["revision:ABC-100-002"]


REQUIRED_PAGE = (
    "Required submissions\n"
    "Item   Document Type            Due\n"
    "1      Pump datasheet           15/02/2026\n"
    "2      Relief valve calculation 01/03/2026\n"
)


def test_a_required_list_flags_a_missing_and_an_extra_item(on, monkeypatch):
    _doc("doc_req", [REQUIRED_PAGE], "specification", number="REQ-1")
    _sub, run, scope = _world(extra=("doc_req",))
    monkeypatch.setattr(settings, "transmittal_required_list_document_ids", "doc_req")
    transmittal_kit.for_review(run, scope)
    assert _items(run) == [
        "extra:ABC-100-002",
        "not_transmitted:relief valve calculation",
    ]
    by = {r["requirement_id"].split(":", 2)[2]: r for r in _defects(run)}
    missing = by["not_transmitted:relief valve calculation"]["finding"]
    assert "not transmitted - engineer to confirm whether due" in missing
    assert "01/03/2026" in missing and "page 1" in missing
    assert "Pump datasheet" not in missing


def test_no_required_list_named_is_one_note_and_no_step_4_rows(on):
    _sub, run, scope = _world()
    transmittal_kit.for_review(run, scope)
    notes = spec_kit.notes(_rows(run))
    assert any("no required-submissions list named" in n["note"] for n in notes)
    assert [
        i for i in _items(run) if i.startswith(("extra", "not_transmitted"))
    ] == []


def test_a_document_outside_the_allowed_ids_is_never_read(on, monkeypatch):
    # doc_h2 would be a revision mismatch and doc_req a required list, but neither is allowed
    _doc("doc_req", [REQUIRED_PAGE], "specification", number="REQ-1")
    table = TABLE.replace("Valve datasheet   1 ", "Valve datasheet   2 ")
    sub = _transmittal(table=table)
    _held("doc_h1", "ABC-100-001", "3", 2)
    _held("doc_h2", "ABC-100-002", "1", 1)
    run, scope = _review(sub)
    allowed = frozenset(scope | {"doc_h1"})
    read = []
    real = procedure_text.load_pages
    monkeypatch.setattr(
        procedure_text, "load_pages", lambda d: (read.append(d), real(d))[1]
    )
    monkeypatch.setattr(settings, "transmittal_required_list_document_ids", "doc_req")
    transmittal_kit.for_review(run, allowed)
    assert "doc_h2" not in read and "doc_req" not in read
    assert _items(run) == []
    assert any(
        "not in the documents you may read" in n["note"]
        for n in spec_kit.notes(_rows(run))
    )


def test_another_kind_is_not_touched(on):
    _doc("doc_x", [HEADER + TABLE], "datasheet", number="DS-1")
    run, scope = _review("doc_x")
    transmittal_kit.for_review(run, scope)
    assert _rows(run) == []


def test_rows_reach_the_crs_as_transmittal_engineer_rows_and_notes_are_not_lines(on):
    header = HEADER.replace("Date: 01/02/2026\n", "")
    _sub, run, scope = _world(header=header)
    transmittal_kit.for_review(run, scope)
    rows = _rows(run)
    assert all(spec_kit.is_row(r) for r in rows)
    assert all(spec_kit.is_unfound(r) for r in _notes(run))
    assert not any(spec_kit.is_unfound(r) for r in _defects(run))
    assert spec_kit.noun_of(_defects(run)[0]) == "transmittal"
    built = [
        b
        for b in crs_mapping.build_crs_rows(rows, [], "tr.pdf")
        if b.get("row_kind") == "spec_kit"
    ]
    assert len(built) == len(_defects(run)) == 1
    assert built[0]["comment_by"].startswith("Transmittal check")
    assert built[0]["comment"] in crs_mapping.WAITING_COMMENTS
