"""Order 196 / 206.1: a datasheet reviewed as a contractor submittal gets its
equipment type and title from its own heading when they are empty.

Found on the invented pump sheet: its stored equipment type, title and
discipline were empty, so the part-scope step had nothing that named the
equipment and held every clause. The readers existed, but ran only for a
document whose role was already CONTRACTOR_SUBMITTAL. Invented text only; no
model; no real document."""

from __future__ import annotations

import json

import pytest

from app import classification, db, submittal_fill, submittal_review
from app.config import settings

NOW = "2026-10-25T00:00:00Z"
FORM_LINE = (
    "CENTRIFUGAL PUMP DATASHEET Doc No.: PF1-DS-0101 Tag No.: SYN-P-0101 Rev: 0 "
    "Project: Synthetic Plant 0001 Sheet 1 of 2"
)
MULTI = (
    "CENTRIFUGAL PUMP DATASHEET\nDoc No.: PF1-DS-0101\nTag No.: SYN-P-0101\nRev: 0\n"
)


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "fill.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    yield
    db.reset_connection()


def _doc(text, role=None, **meta):
    db.connect().execute("PRAGMA foreign_keys = OFF")  # confirmed_by names a user
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES ('d','s.pdf','sha',1,'s.pdf','ready',1,?)",
            (NOW,),
        )
        cols = ["document_id", "suggested_by", "document_role", *meta]
        conn.execute(
            f"INSERT INTO document_classification ({','.join(cols)})"
            f" VALUES ({','.join('?' * len(cols))})",
            ["d", "test", role, *meta.values()],
        )
        conn.execute(
            "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
            " VALUES ('d',1,?,?,0,0)",
            (text, len(text)),
        )


def _row():
    return classification.of_document("d")


@pytest.mark.parametrize("text", [MULTI, FORM_LINE])
def test_a_reviewed_sheet_with_no_role_gets_its_type_and_title(temp_storage, text):
    _doc(text)
    submittal_fill.ensure("d")
    row = _row()
    assert row["equipment_type"] == "Centrifugal Pump"
    assert row["title"] == "CENTRIFUGAL PUMP DATASHEET"
    # the role is not decided by a review, and nothing is confirmed
    assert row["document_role"] is None and row["confirmed_by"] is None
    # the quote is kept, so the engineer can see where it came from
    evidence = (
        json.loads(row["field_evidence"])
        if isinstance(row["field_evidence"], str)
        else row["field_evidence"]
    )
    assert "CENTRIFUGAL PUMP" in evidence["title"]["quote"]
    assert evidence["title"]["page"] == 1


def test_without_a_review_a_document_with_no_role_is_left_alone(temp_storage):
    _doc(MULTI)
    classification.classify_equipment_type_for_submittal("d")
    classification.classify_metadata_for_submittal("d")
    row = _row()
    assert row["equipment_type"] is None and row["title"] is None


def test_another_role_is_never_taken_for_a_submittal(temp_storage):
    _doc(MULTI, role="COMPANY_STANDARD")
    submittal_fill.ensure("d")
    row = _row()
    assert row["equipment_type"] is None and row["title"] is None


def test_a_confirmed_record_is_not_overwritten(temp_storage):
    _doc(MULTI, role="CONTRACTOR_SUBMITTAL", confirmed_by="eng", title="Mine")
    submittal_fill.ensure("d")
    assert _row()["title"] == "Mine" and _row()["equipment_type"] is None


def test_a_value_a_person_put_there_is_kept(temp_storage):
    _doc(MULTI, title="Pump sheet by hand")
    submittal_fill.ensure("d")
    row = _row()
    assert row["title"] == "Pump sheet by hand"
    assert row["equipment_type"] == "Centrifugal Pump"


def test_a_heading_that_names_no_equipment_gets_no_title(temp_storage):
    _doc("ACME PROJECTS LTD\nDoc No.: X-1\n")
    submittal_fill.ensure("d")
    row = _row()
    assert row["title"] is None and row["equipment_type"] is None


def test_a_failure_never_fails_the_review(temp_storage, monkeypatch):
    _doc(MULTI)

    def boom(*a, **k):
        raise RuntimeError("no")

    monkeypatch.setattr(classification, "classify_equipment_type_for_submittal", boom)
    submittal_fill.ensure("d")  # does not raise
    assert _row()["title"] == "CENTRIFUGAL PUMP DATASHEET"


def test_the_heading_lead_cuts_at_a_field_label_and_drops_the_labels_word():
    lead = submittal_fill.heading_lead
    assert lead(FORM_LINE) == "CENTRIFUGAL PUMP DATASHEET"
    assert lead("CENTRIFUGAL PUMP DATASHEET") == "CENTRIFUGAL PUMP DATASHEET"
    prose = "This sheet is issued by the vendor for the purchaser of the equipment named below"
    assert lead(prose) == ""


# ------------------- the whole review: a sheet with no stored type or title

import uuid  # noqa: E402

from app import comparison, datasheets, scope_ledger, standards  # noqa: E402
from tests.test_141_division_scope import FakeModel  # noqa: E402,F401
from tests.test_141_division_scope import _doc as _std_doc

PUMP_SCOPE = "This invented standard covers centrifugal pumps."
PUMP_PAGES = [
    (
        1,
        "PART PP\nREQUIREMENTS FOR CENTRIFUGAL PUMPS\nPP-1 SCOPE\n"
        + PUMP_SCOPE
        + "\nPP-2 The casing shall be tested at 12 bar.\n",
    )
]
LIMITED = {"limited": "yes", "construction": "centrifugal pumps", "quote": PUMP_SCOPE}
YES = {
    "equipment_is": "centrifugal pump",
    "quote": "equipment type: Centrifugal Pump",
    "is_that": "yes",
}


def _review(monkeypatch, model):
    from app import ai_task_runner

    monkeypatch.setattr(settings, "match_enabled", False)
    monkeypatch.setattr(settings, "ai_clause_checks_enabled", False)
    monkeypatch.setattr(settings, "ai_division_scope_enabled", True)
    monkeypatch.setattr(ai_task_runner, "make_provider", lambda model_name=None: model)
    _std_doc("std", "PUMP-STD.pdf", "COMPANY_STANDARD", PUMP_PAGES)
    # no role, no equipment type, no title: only the page heading says what it is
    _std_doc(
        "sub",
        "sheet.pdf",
        None,
        [(1, "CENTRIFUGAL PUMP DATASHEET\nDESIGN PRESSURE 9 barg\n")],
    )
    rid = standards.create_requirement(
        standard_document_id="std",
        chunk_id="std-1",
        clause=None,
        page=1,
        requirement_text="The casing shall be tested at 12 bar.",
        source_text="PP-2 The casing shall be tested at 12 bar.",
        structured={"requirement_type": "statement"},
    )["id"]
    datasheets.create_fact(
        submittal_document_id="sub",
        chunk_id="sub-1",
        field_label="Design pressure",
        raw_value="9 barg",
        page=1,
    )
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,created_at,updated_at)"
            " VALUES (?,?,'pending',?,?)",
            (run, "sub", NOW, NOW),
        )
        conn.execute(
            "INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,"
            "selection_method,included,created_at) VALUES (?,?,?,'manual',1,?)",
            (str(uuid.uuid4()), run, "std", NOW),
        )
    comparison.run_comparison(run, allowed_document_ids=frozenset({"std", "sub"}))
    return {d["requirement_id"]: d for d in scope_ledger.decisions_for(run)}[rid]


def test_a_review_fills_the_type_and_title_so_the_part_is_compared(
    temp_storage, monkeypatch
):
    decision = _review(monkeypatch, FakeModel(scope=LIMITED, construction=YES))
    row = _row_of("sub")
    assert row["equipment_type"] == "Centrifugal Pump"
    assert row["title"] == "CENTRIFUGAL PUMP DATASHEET"
    assert decision["state"] != scope_ledger.APPLIES_NOT_CHECKED, decision


def test_without_the_fill_the_same_review_holds_the_part(temp_storage, monkeypatch):
    monkeypatch.setattr(submittal_fill, "ensure", lambda _id: None)
    decision = _review(monkeypatch, FakeModel(scope=LIMITED, construction=YES))
    assert decision["state"] == scope_ledger.APPLIES_NOT_CHECKED
    assert decision["reason_code"] == "applicability_unsure"


def _row_of(doc_id):
    return classification.of_document(doc_id)
