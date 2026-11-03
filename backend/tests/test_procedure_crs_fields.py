"""Order 4c: a procedure's CRS fields, checked the export way
(`main._crs_workbook` -> `_crs_content` -> `crs_export.build_crs`).

INVENTED documents only (CLAUDE.md rule 3); no model. Each test fails without the
code it names.
"""

from __future__ import annotations

import io
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from app import access, crs_numbers, crs_reply, db, procedure_crs, submittal_review
from app import main as main_mod
from app.config import settings

NOW = "2026-11-02T00:00:00Z"
DOC = "doc_abcdef123456"
FRAGMENT = "ABCDEF12"
RUN = "run-order-4c"
QUOTE = "the invented study team shall record every invented node in its log"
GOVERNING = {
    "equipment_types": {"invented compressor": ["INV-STD-77"]},
    "partial_standards": {},
    "subtypes": {},
}


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t4c.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    yield
    db.reset_connection()


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "procedure_crs_fields_enabled", True)


def _document(
    *,
    kind="procedure",
    guess=False,
    state="suggested",
    number=None,
    equipment="invented compressor",
    pages=(),
    filename="invented-procedure.pdf",
):
    """One invented submittal and its run; returns the run id."""
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,"
            "uploaded_at) VALUES (?,?,?,1,'x','ready',?,?)",
            (DOC, filename, uuid.uuid4().hex, len(pages), NOW),
        )
        conn.execute(
            "INSERT INTO document_classification (document_id, document_role, equipment_type,"
            " document_number, suggested_by) VALUES (?, 'CONTRACTOR_SUBMITTAL', ?, ?, 'test')",
            (DOC, equipment, number),
        )
        for no, text in enumerate(pages, start=1):
            conn.execute(
                "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
                " VALUES (?,?,?,?,0,0)",
                (DOC, no, text, len(text)),
            )
        if kind:
            conn.execute(
                "INSERT INTO document_kinds (document_id,kind,state,evidence,routed_at)"
                " VALUES (?,?,?,?,?)",
                (DOC, kind, state, json.dumps({"guess": guess}), NOW),
            )
    return submittal_review.create_review_run(
        submittal_document_id=DOC, allowed_document_ids=frozenset({DOC})
    )


def _other_document(document_id, filename, pages=()):
    """A second invented document with its own run; returns the run id."""
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,"
            "uploaded_at) VALUES (?,?,?,1,'x','ready',?,?)",
            (document_id, filename, uuid.uuid4().hex, len(pages), NOW),
        )
        conn.execute(
            "INSERT INTO document_classification (document_id, document_role, suggested_by)"
            " VALUES (?, 'CONTRACTOR_SUBMITTAL', 'test')",
            (document_id,),
        )
        for no, text in enumerate(pages, start=1):
            conn.execute(
                "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
                " VALUES (?,?,?,?,0,0)",
                (document_id, no, text, len(text)),
            )
    return submittal_review.create_review_run(
        submittal_document_id=document_id, allowed_document_ids=frozenset({document_id})
    )


def _scope():
    ids = frozenset(r["id"] for r in db.connect().execute("SELECT id FROM documents"))
    return access.AccessScope(user_id=None, allowed_document_ids=ids, unrestricted=True)


def _sheet(run, copy="internal"):
    data, _name = main_mod._crs_workbook(run, _scope(), copy)
    return load_workbook(io.BytesIO(data))


def _cells(ws):
    return [
        str(c.value) for row in ws.iter_rows() for c in row if c.value not in (None, "")
    ]


@pytest.fixture
def governed(monkeypatch):
    """A governing table that names the invented type, read from the stored record."""
    from app import applicability, subject_scope

    monkeypatch.setattr(applicability, "governing_table", lambda: GOVERNING)
    monkeypatch.setattr(
        subject_scope,
        "read_equipment",
        lambda record, facts, vocab: (
            {record["equipment_type"]} if record.get("equipment_type") else set(),
            "classification",
            None,
        ),
    )


# ------------------------------------------------------------- 1. equipment type


def test_a_procedure_crs_names_no_equipment_type(on, governed):
    run = _document(pages=["invented cover", "invented body"])
    text = " ".join(_cells(_sheet(run).worksheets[0]))
    assert "invented compressor" not in text
    assert "INV-STD-77" not in text
    assert "read from the submittal" not in text


def test_a_datasheet_keeps_its_equipment_rows(on, governed):
    run = _document(kind="datasheet", pages=["invented cover"])
    text = " ".join(_cells(_sheet(run).worksheets[0]))
    assert "invented compressor" in text and "INV-STD-77" in text


def test_a_guessed_kind_keeps_the_rows(on, governed):
    run = _document(guess=True, pages=["invented cover"])
    assert "INV-STD-77" in " ".join(_cells(_sheet(run).worksheets[0]))


def test_every_other_non_datasheet_kind_has_none_either(on, governed):
    run = _document(kind="specification", pages=["invented cover"])
    assert "INV-STD-77" not in " ".join(_cells(_sheet(run).worksheets[0]))


def test_the_stored_classification_keeps_its_value(on, governed):
    """Subject gates read it: blanking it moved 236 requirements (`kind_rules.for_run`)."""
    _sheet(_document(pages=["invented cover"]))
    stored = (
        db.connect()
        .execute(
            "SELECT equipment_type FROM document_classification WHERE document_id = ?",
            (DOC,),
        )
        .fetchone()
    )
    assert stored["equipment_type"] == "invented compressor"


def test_the_standards_sheet_keeps_the_standard_and_drops_the_type(on):
    _document(pages=["invented cover"])
    rows = [
        {
            "standard": "s.pdf",
            "method": "governing_standard",
            "evidence": "",
            "status": "x",
            "reason": "INV governs a invented compressor (read from the submittal's title)",
        },
        {
            "standard": "e.pdf",
            "method": "equipment_type",
            "evidence": "",
            "status": "x",
            "reason": "r",
        },
        {
            "standard": "r.pdf",
            "method": "referenced",
            "evidence": "",
            "status": "x",
            "reason": "named",
        },
    ]
    got = procedure_crs.standards_sheet(rows, DOC)
    assert [g["standard"] for g in got] == ["s.pdf", "e.pdf", "r.pdf"]
    assert (
        "invented compressor" not in got[0]["reason"]
        and "procedure" in got[0]["reason"]
    )
    assert got[1]["method"] == procedure_crs.METHOD_NOT_FOR_KIND
    assert got[2] == rows[2]


def test_the_title_block_note_is_not_on_a_procedure(on, monkeypatch):
    from app import equipment_title_block, export_status

    monkeypatch.setattr(
        equipment_title_block, "for_submittal", lambda *_a: [{"note": "n"}]
    )
    _document(pages=["invented cover"])
    notes = export_status.equipment_notes(DOC, "run", frozenset({DOC}))
    assert [
        n for n in notes if n.get("note") == "n"
    ] == []  # lane 6: the project specification line is there, not this


# ------------------------------------------------------------------- 2. page cell


def test_page_comes_from_the_page_the_quote_verifies_on(on):
    texts = {1: "cover", 2: f"before {QUOTE} after", 3: "other"}
    assert procedure_crs.verified_page(QUOTE, None, texts) == 2
    assert procedure_crs.verified_page(QUOTE, 3, texts) == 2


def test_a_quote_on_no_page_or_several_gives_no_page(on):
    assert procedure_crs.verified_page(QUOTE, 1, {1: "cover", 2: "other"}) is None
    assert procedure_crs.verified_page(QUOTE, None, {1: QUOTE, 2: QUOTE}) is None
    # Several pages, one stated: the stated page holds it, so it is not a guess.
    assert procedure_crs.verified_page(QUOTE, 2, {1: QUOTE, 2: QUOTE}) == 2


def test_fill_pages_fills_clears_and_leaves_alone(on):
    _document(pages=["invented cover", f"before {QUOTE} after"])
    rows = [
        {"quote": QUOTE, "page_section": "4.2 > para 3"},
        {
            "quote": "an invented sentence that stands on no page of this document",
            "page_section": "p.9 - Section",
        },
        {"page_section": "p.7 - No quote here"},
        {"quote": QUOTE, "page_section": ""},
    ]
    procedure_crs.fill_pages(rows, [], DOC)
    assert [r["page_section"] for r in rows] == [
        "p.2 - 4.2 > para 3",
        "Section",
        "p.7 - No quote here",
        "p.2",
    ]


def test_fill_pages_reads_clause_and_found_quotes_not_a_fact_value(on):
    from app.crs_draft_lanes import CLAUSE_ORIGIN
    from app.procedure_text import FOUND

    _document(pages=["invented cover", f"before {QUOTE} after"])
    findings = [
        {"id": "c", "origin": CLAUSE_ORIGIN, "contractor_evidence_text": QUOTE},
        {
            "id": "f",
            "ai_rationale": f'{FOUND}: found on page 1: "{QUOTE}" - this is the closest',
        },
        {"id": "v", "contractor_evidence_text": "12 mm"},
    ]
    rows = [
        {"finding_id": "c", "page_section": ""},
        {"finding_id": "f", "page_section": "p.1 - Field"},
        {"finding_id": "v", "page_section": "p.1 - Value"},
    ]
    procedure_crs.fill_pages(rows, findings, DOC)
    assert [r["page_section"] for r in rows] == ["p.2", "p.2 - Field", "p.1 - Value"]


def test_a_playbook_row_carries_its_quote_only_with_the_switch(monkeypatch):
    from app import playbooks
    from app import procedure_playbook_rows as ppr

    entry = {
        "id": "e",
        "title": "T",
        "state": playbooks.PRESENT,
        "reason": "",
        "source": {"standard": "S", "clause": "1"},
        "evidence": [{"locator": "4.2", "quote": QUOTE}],
    }

    class Book:
        id, title = "b", "B"

    report = {"playbook": {"notice": ""}}
    assert "quote" not in ppr._row(Book, report, entry, "n")
    monkeypatch.setattr(settings, "procedure_crs_fields_enabled", True)
    assert ppr._row(Book, report, entry, "n")["quote"] == QUOTE


# ------------------------------------------------------------------ 3. the number


COVER = (
    "INVENTED SAFETY PROCEDURE\nDocument No: INV-AB-PD-0007\nRevision 1\nSome body text"
)


def test_the_number_the_cover_states_is_a_marked_suggestion(on):
    _document(pages=[COVER, "invented body"])
    assert crs_numbers.scope_of_document(DOC, "") == (
        f"doc:{DOC}",
        "INV-AB-PD-0007-SUGGESTED",
    )


def test_a_whole_line_number_on_the_cover_is_read_and_a_label_with_next_line_value():
    bare = procedure_crs.read_number(
        [{"page_no": 1, "text": "TITLE\nINV-AB-PD-0007\nbody"}]
    )
    assert bare["number"] == "INV-AB-PD-0007" and bare["page"] == 1
    below = procedure_crs.read_number(
        [{"page_no": 1, "text": "Document Number\nINV/AB/0007\nbody"}]
    )
    assert below["number"] == "INV/AB/0007"


def test_two_different_numbers_or_none_suggest_nothing():
    two = "INV-AB-PD-0007\nINV-AB-PD-0008\nbody"
    assert procedure_crs.read_number([{"page_no": 1, "text": two}]) is None
    assert (
        procedure_crs.read_number(
            [{"page_no": 1, "text": "just words\nDocument No: NA"}]
        )
        is None
    )
    assert procedure_crs.read_number([]) is None


def test_no_number_gives_the_neutral_label_never_the_id(on):
    _document(pages=["invented cover with no number"])
    key, label = crs_numbers.scope_for("", DOC)
    assert (key, label) == (f"doc:{DOC}", "NO-NUMBER")
    got = crs_numbers.assign(
        key, label, ["k"], document_id=DOC, review_run_id=RUN, issued=False
    )
    assert got["k"]["ref"] == "CRS-NO-NUMBER-001"


def test_a_recorded_number_still_makes_the_number_sequence(on):
    _document(number="INV-1-2", pages=["invented cover"])
    assert crs_numbers.scope_of_document(DOC, "INV-1-2") == ("no:inv-1-2", "INV-1-2")


def test_an_existing_scope_row_is_shown_neutral_and_not_rewritten(on, monkeypatch):
    _document(pages=["invented cover with no number"])
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO crs_document_scope (document_id, scope_key, label, fixed_at)"
            " VALUES (?, ?, ?, ?)",
            (DOC, f"doc:{DOC}", FRAGMENT, NOW),
        )
        conn.execute(
            "INSERT INTO crs_comment_numbers (scope_key, row_key, seq, label, first_document_id,"
            " first_review_run_id, assigned_at, status, issued) VALUES (?, 'old', 4, ?, ?, ?, ?, 'Open', 1)",
            (f"doc:{DOC}", FRAGMENT, DOC, RUN, NOW),
        )
    key, label = crs_numbers.scope_of_document(DOC, "")
    assert (key, label) == (f"doc:{DOC}", "NO-NUMBER")
    assert crs_numbers.lookup(key, ["old"])["old"]["ref"] == "CRS-NO-NUMBER-004"
    assert crs_numbers.get(key, 4)["ref"] == "CRS-NO-NUMBER-004"
    assert crs_numbers.open_elsewhere(key, set())[0]["ref"] == "CRS-NO-NUMBER-004"
    # A new comment continues the same sequence, and nothing stored was rewritten.
    got = crs_numbers.assign(
        key, label, ["new"], document_id=DOC, review_run_id=RUN, issued=False
    )
    assert got["new"]["seq"] == 5
    assert (
        conn.execute(
            "SELECT label FROM crs_document_scope WHERE document_id = ?", (DOC,)
        ).fetchone()["label"]
        == FRAGMENT
    )
    assert (
        conn.execute(
            "SELECT label FROM crs_comment_numbers WHERE row_key = 'old'"
        ).fetchone()["label"]
        == FRAGMENT
    )


def test_the_export_prints_no_id_and_says_what_the_label_is(on):
    run = _document(pages=["invented cover with no number"])
    key, label = crs_numbers.scope_of_document(DOC, "")
    assert label == "NO-NUMBER"
    crs_numbers.assign(
        key, label, ["k"], document_id=DOC, review_run_id=run, issued=True
    )
    book = _sheet(run)
    assert any(c.startswith("CRS-NO-NUMBER-001") for c in _cells(book.worksheets[0]))
    assert not any(FRAGMENT in c for ws in book.worksheets for c in _cells(ws))
    notes = " ".join(_cells(book["Review notes"]))
    assert "NO-NUMBER is not a document number" in notes


def test_a_suggested_number_says_it_is_a_guess_with_its_page(on):
    _document(pages=[COVER])
    notes = procedure_crs.number_notes(DOC)
    assert "A guess" in notes[0]["detail"] and "page 1" in notes[0]["detail"]


def test_a_real_number_needs_no_note(on):
    _document(number="INV-1-2", pages=["invented cover"])
    assert procedure_crs.number_notes(DOC) == []


def test_a_reference_already_issued_still_belongs(on):
    key = f"doc:{DOC}"
    assert crs_numbers.ref_label_ok(FRAGMENT, "NO-NUMBER", key)
    assert crs_numbers.ref_label_ok("X-1-SUGGESTED", "X-1", key)
    assert not crs_numbers.ref_label_ok("ZZZZZZZZ", "NO-NUMBER", key)
    assert not crs_numbers.ref_label_ok("NO-NUMBER", "INV-1", "no:inv-1")


def test_a_real_number_is_not_this_documents_suggested_number(on):
    """A real number belongs to another sequence; only the marked label was printed here."""
    assert not crs_numbers.ref_label_ok("X-1", "X-1-SUGGESTED", f"doc:{DOC}")


def test_a_reply_without_this_documents_name_is_refused_with_its_reason(on):
    _document(pages=["invented cover"], filename="mine.pdf")
    other = procedure_crs.name_refusal
    assert "another document" in other({"document_name": "theirs.pdf"}, DOC)
    assert "Document Name" in other({"document_name": ""}, DOC)
    assert other({"document_name": " MINE.pdf "}, DOC) is None


def test_two_documents_of_one_name_cannot_take_a_shared_label(on):
    _document(pages=["invented cover"], filename="mine.pdf")
    _other_document("doc_second00000", filename="mine.pdf")
    assert "two documents" in procedure_crs.name_refusal(
        {"document_name": "mine.pdf"}, DOC
    )


def test_the_reply_reader_returns_the_document_name():
    book = Workbook()
    sheet = book.active
    sheet.append(["Item No", "Document Name", "Contractor's Response"])
    sheet.append(["CRS-NO-NUMBER-001", "mine.pdf", "Accepted"])
    out = io.BytesIO()
    book.save(out)
    assert crs_reply.read_replies(out.getvalue())[0]["document_name"] == "mine.pdf"


# ----------------------------------------------------------------- the switch off


def test_switch_off_keeps_every_field(governed):
    run = _document(pages=[COVER])
    assert crs_numbers.scope_for("", DOC) == (f"doc:{DOC}", FRAGMENT)
    assert crs_numbers.scope_of_document(DOC, "")[1] == FRAGMENT
    assert not procedure_crs.no_equipment(DOC)
    rows = [{"method": "equipment_type", "reason": "r"}]
    assert procedure_crs.standards_sheet(rows, DOC) is rows
    moved = [{"quote": "nowhere at all in this document", "page_section": "p.9"}]
    procedure_crs.fill_pages(moved, [], DOC)
    assert moved[0]["page_section"] == "p.9"
    assert procedure_crs.number_notes(DOC) == []
    assert not crs_numbers.ref_label_ok(FRAGMENT, "NO-NUMBER", f"doc:{DOC}")
    # The export, unchanged: the type's standard row stays.
    assert "INV-STD-77" in " ".join(_cells(_sheet(run).worksheets[0]))


# ------------------------------------------------- the wiring, the export way


def _page_cells(book):
    ws = book.worksheets[0]
    header = next(c.row for row in ws.iter_rows() for c in row if c.value == "Item No")
    return [r[2] for r in ws.iter_rows(min_row=header + 1, values_only=True)]


def _row_with_quote(quote):
    return {
        "finding_id": "",
        "document_name": "invented-procedure.pdf",
        "page_section": "4.2",
        "comment": "invented comment",
        "comment_by": "Playbook check (draft)",
        "standard_reference": "",
        "row_kind": "playbook_check",
        "severity": "",
        "engineer_confirmed": False,
        "comment_key": "invented-key",
        "priority": 3,
        "quote": quote,
    }


def test_the_export_prints_the_page_the_quote_verified_on(on, monkeypatch):
    from app import procedure_playbook_rows as ppr

    run = _document(pages=["invented cover", f"before {QUOTE} after"])
    monkeypatch.setattr(ppr, "crs_rows", lambda *_a: ([_row_with_quote(QUOTE)], []))
    assert "p.2 - 4.2" in _page_cells(_sheet(run))


def test_the_export_prints_no_page_for_an_unverified_quote(on, monkeypatch):
    from app import procedure_playbook_rows as ppr

    run = _document(pages=["invented cover", "invented body"])
    row = _row_with_quote(
        "an invented sentence that stands on no page of this document"
    )
    monkeypatch.setattr(ppr, "crs_rows", lambda *_a: ([row], []))
    cells = [c for c in _page_cells(_sheet(run)) if c]
    assert "4.2" in cells and not any(str(c).startswith("p.") for c in cells)


def test_the_export_standards_sheet_drops_the_type(on, monkeypatch):
    run = _document(pages=["invented cover"])
    stored = {
        "standard_document_id": DOC,
        "included": 1,
        "selection_method": "governing_standard",
        "selection_reason": "governs a invented compressor",
    }
    monkeypatch.setattr(
        submittal_review, "list_applicable_standards", lambda *_a, **_k: [stored]
    )
    text = " ".join(_cells(_sheet(run)["Applicable standards"]))
    assert "invented-procedure.pdf" in text and "invented compressor" not in text


def _reply_sheet(item, name):
    book = Workbook()
    sheet = book.active
    sheet.append(["Item No", "Document Name", "Contractor's Response"])
    sheet.append([item, name, "Accepted"])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _post_reply(run, data):
    return (
        TestClient(main_mod.app)
        .post(
            f"/api/reviews/runs/{run}/crs/reply",
            files={"file": ("reply.xlsx", data, "application/octet-stream")},
        )
        .json()
    )


@pytest.fixture
def named(monkeypatch):
    monkeypatch.setattr(main_mod, "_require_named_reviewer", lambda *_a: None)


def test_the_reply_route_takes_this_documents_no_number_and_refuses_anothers(on, named):
    run = _document(pages=["invented cover"], filename="mine.pdf")
    key, label = crs_numbers.scope_of_document(DOC, "")
    crs_numbers.assign(
        key, label, ["k"], document_id=DOC, review_run_id=run, issued=True
    )
    theirs = _post_reply(run, _reply_sheet("CRS-NO-NUMBER-001", "theirs.pdf"))
    assert theirs["other_submittal"] == 1 and theirs["updated"] == 0
    assert crs_numbers.get(key, 1)["response_code"] is None
    mine = _post_reply(run, _reply_sheet("CRS-NO-NUMBER-001", "mine.pdf"))
    assert mine["updated"] == 1
    assert crs_numbers.get(key, 1)["response_code"] == "Accepted"


def test_the_reply_route_takes_the_id_label_of_a_sheet_already_issued(on, named):
    run = _document(pages=["invented cover"], filename="mine.pdf")
    key, label = crs_numbers.scope_of_document(DOC, "")
    crs_numbers.assign(
        key, label, ["k"], document_id=DOC, review_run_id=run, issued=True
    )
    got = _post_reply(run, _reply_sheet(f"CRS-{FRAGMENT}-001", "mine.pdf"))
    assert got["updated"] == 1


def test_the_comment_route_takes_the_id_label_too(on):
    run = _document(pages=["invented cover"])
    key, label = crs_numbers.scope_of_document(DOC, "")
    crs_numbers.assign(
        key, label, ["k"], document_id=DOC, review_run_id=run, issued=True
    )
    assert main_mod._crs_comment(run, f"CRS-{FRAGMENT}-001", _scope()) == (key, 1)
    assert main_mod._crs_comment(run, "CRS-NO-NUMBER-001", _scope()) == (key, 1)


def test_a_suggested_number_is_printed_and_never_stored(on):
    run = _document(pages=[COVER])
    key, label = crs_numbers.scope_of_document(DOC, "")
    assert label.endswith("-SUGGESTED")
    crs_numbers.assign(
        key, label, ["k"], document_id=DOC, review_run_id=run, issued=False
    )
    conn = db.connect()
    stored = [
        conn.execute("SELECT label FROM crs_document_scope").fetchone()["label"],
        conn.execute("SELECT label FROM crs_comment_numbers").fetchone()["label"],
    ]
    assert stored == ["NO-NUMBER", "NO-NUMBER"]


# ------------------------------------------------------------- review of #1580


@pytest.mark.parametrize(
    ("cell", "printed"),
    [
        ("p.7 - 2 Close out", "p.2 - 2 Close out"),
        ("p.3, 5. Follow-up", "p.2 - p.3, 5. Follow-up"),
        ("p.1-2, 7 - Section", "p.2 - Section"),
        ("p.9", "p.2"),
        ("p.3 2 Close out", "p.2 - p.3 2 Close out"),
    ],
)
def test_only_an_exact_page_lead_is_replaced(on, cell, printed):
    _document(pages=["invented cover", f"before {QUOTE} after"])
    rows = [{"quote": QUOTE, "page_section": cell}]
    procedure_crs.fill_pages(rows, [], DOC)
    assert rows[0]["page_section"] == printed


def test_an_unverified_quote_keeps_a_section_that_starts_with_digits(on):
    _document(pages=["invented cover"])
    rows = [
        {
            "quote": "an invented sentence that stands on no page here",
            "page_section": cell,
        }
        for cell in ("p.7 - 2 Close out", "p.3, 5. Follow-up")
    ]
    procedure_crs.fill_pages(rows, [], DOC)
    assert [r["page_section"] for r in rows] == ["2 Close out", "p.3, 5. Follow-up"]


def _issue(run, document_id):
    key, label = crs_numbers.scope_of_document(document_id, "")
    crs_numbers.assign(
        key, label, ["k"], document_id=document_id, review_run_id=run, issued=True
    )
    return key


def test_two_documents_with_one_suggested_number_never_take_each_others_reply(
    on, named
):
    mine = _document(pages=[COVER], filename="mine.pdf")
    theirs = _other_document("doc_second00000", "theirs.pdf", pages=[COVER])
    my_key, their_key = _issue(mine, DOC), _issue(theirs, "doc_second00000")
    item = "CRS-INV-AB-PD-0007-SUGGESTED-001"
    got = _post_reply(mine, _reply_sheet(item, "theirs.pdf"))
    assert got["other_submittal"] == 1 and got["updated"] == 0
    assert "another document" in got["rows"][0]["outcome"]
    assert crs_numbers.get(my_key, 1)["response_code"] is None
    assert crs_numbers.get(their_key, 1)["response_code"] is None
    assert _post_reply(mine, _reply_sheet(item, "mine.pdf"))["updated"] == 1
    assert crs_numbers.get(their_key, 1)["response_code"] is None


def test_a_reply_with_no_document_name_is_refused_and_says_why(on, named):
    run = _document(pages=[COVER], filename="mine.pdf")
    key = _issue(run, DOC)
    got = _post_reply(run, _reply_sheet("CRS-INV-AB-PD-0007-SUGGESTED-001", ""))
    assert got["other_submittal"] == 1 and "Document Name" in got["rows"][0]["outcome"]
    assert crs_numbers.get(key, 1)["response_code"] is None


def test_a_real_number_reply_does_not_reach_a_suggested_sequence(on, named):
    run = _document(pages=[COVER], filename="mine.pdf")
    key = _issue(run, DOC)
    got = _post_reply(run, _reply_sheet("CRS-INV-AB-PD-0007-001", "mine.pdf"))
    assert got["other_submittal"] == 1 and got["updated"] == 0
    assert crs_numbers.get(key, 1)["response_code"] is None


def test_the_guard_stays_when_the_switch_is_turned_off_again(named, monkeypatch):
    run = _document(pages=["invented cover"], filename="mine.pdf")
    monkeypatch.setattr(settings, "procedure_crs_fields_enabled", True)
    key = _issue(run, DOC)
    monkeypatch.setattr(settings, "procedure_crs_fields_enabled", False)
    assert crs_numbers.get(key, 1)["ref"] == "CRS-NO-NUMBER-001"
    got = _post_reply(run, _reply_sheet("CRS-NO-NUMBER-001", "theirs.pdf"))
    assert got["other_submittal"] == 1 and got["updated"] == 0
    assert (
        _post_reply(run, _reply_sheet("CRS-NO-NUMBER-001", "mine.pdf"))["updated"] == 1
    )


def test_switch_off_with_an_id_label_takes_a_reply_with_no_name(named):
    """Never turned on: a reply sheet quoting the id label behaves as it always did."""
    run = _document(pages=["invented cover"], filename="mine.pdf")
    _issue(run, DOC)
    got = _post_reply(run, _reply_sheet(f"CRS-{FRAGMENT}-001", ""))
    assert got["updated"] == 1
    assert got["rows"][0]["outcome"] == "updated"


def test_replies_read_the_document_pages_once(on, named, monkeypatch):
    calls = []
    real = procedure_crs.read_number
    monkeypatch.setattr(
        procedure_crs, "read_number", lambda pages: calls.append(1) or real(pages)
    )
    run = _document(pages=[COVER], filename="mine.pdf")
    key = _issue(run, DOC)
    crs_numbers.assign(
        key, "x", ["k2", "k3"], document_id=DOC, review_run_id=run, issued=True
    )
    calls.clear()
    book = Workbook()
    sheet = book.active
    sheet.append(["Item No", "Document Name", "Contractor's Response"])
    for n in (1, 2, 3):
        sheet.append([f"CRS-INV-AB-PD-0007-SUGGESTED-00{n}", "mine.pdf", "Accepted"])
    out = io.BytesIO()
    book.save(out)
    assert _post_reply(run, out.getvalue())["updated"] == 3
    assert len(calls) <= 1


def test_changed_pages_are_read_again(on):
    _document(pages=["invented cover with no number"])
    assert procedure_crs.suggested_number(DOC) is None
    conn = db.connect()
    with conn:
        conn.execute(
            "UPDATE pages SET text = ?, char_count = ? WHERE document_id = ?",
            (COVER, len(COVER), DOC),
        )
    assert procedure_crs.suggested_number(DOC)["number"] == "INV-AB-PD-0007"


@pytest.mark.parametrize(
    "line", ["2026-11-02-01", "2026-11-02", "02/11/2026", "2026/1/5-3", "31-12-2026"]
)
def test_a_date_on_the_cover_is_not_a_document_number(line):
    assert (
        procedure_crs.read_number([{"page_no": 1, "text": f"TITLE\n{line}\nbody"}])
        is None
    )
    labelled = f"TITLE\nDocument No: {line}\nbody"
    assert procedure_crs.read_number([{"page_no": 1, "text": labelled}]) is None


def test_a_date_beside_the_real_number_does_not_hide_it():
    text = "TITLE\nINV-AB-PD-0007\n2026-11-02-01\nbody"
    assert (
        procedure_crs.read_number([{"page_no": 1, "text": text}])["number"]
        == "INV-AB-PD-0007"
    )


def test_a_number_that_only_starts_like_a_year_is_kept():
    text = "TITLE\n2026-77-99-07\nbody"
    assert (
        procedure_crs.read_number([{"page_no": 1, "text": text}])["number"]
        == "2026-77-99-07"
    )
