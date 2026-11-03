"""#1474: a document's KIND is decided from its title block and cover, never
from a body-text equipment mention. Invented documents only."""

from __future__ import annotations

import json

import pytest

from app import classification, db, doc_router, document_kind
from app.config import settings


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


BODY_MENTION = (
    "5.2 The relief valve and the centrifugal compressor shall be checked "
    "against the cause and effect chart before the study starts."
)

PROCEDURE_PAGE = (
    "ACME PLANT PROJECT\n999\nHAZARD STUDY PROCEDURE\nPAGE 1 OF 9\n"
    "99999-00-HSE-PD-0001\nREV.: 00\n"
    + "\n".join(f"Filler line {i}" for i in range(14))
    + "\nPurpose and scope\n"
    + BODY_MENTION
    + "\n"
    + "\n".join(f"Closing line {i}" for i in range(14))
)


def _doc(doc_id, pages, *, role="CONTRACTOR_SUBMITTAL", with_row=True, confirmed=False):
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,"
            " status, uploaded_at) VALUES (?,?,?,?,?,?,?)",
            (doc_id, f"{doc_id}.pdf", doc_id, 1, "x", "ready", "2026-11-01"),
        )
        for n, text in enumerate(pages, start=1):
            conn.execute(
                "INSERT INTO pages (document_id, page_no, text, char_count, batch_no)"
                " VALUES (?,?,?,?,0)",
                (doc_id, n, text, len(text)),
            )
            conn.execute(
                "INSERT INTO chunks (id, document_id, filename, ordinal, page_start,"
                " page_end, text, token_count, content_hash, retrievable)"
                " VALUES (?,?,?,?,?,?,?,1,?,1)",
                (f"{doc_id}_c{n}", doc_id, "f", n, n, n, text, f"{doc_id}{n}"),
            )
        if with_row:
            conn.execute(
                "INSERT INTO document_classification (document_id, suggested_by,"
                " document_role, confirmed_by) VALUES (?,?,?,?)",
                (doc_id, "t", role, None),
            )
            if confirmed:
                conn.execute(
                    "INSERT INTO users (id, email, display_name, password_hash,"
                    " created_at) VALUES ('u1','u@x.test','u','x','2026-11-01')"
                )
                conn.execute(
                    "UPDATE document_classification SET confirmed_by='u1'"
                    " WHERE document_id=?",
                    (doc_id,),
                )


def _kind(doc_id):
    """(kind, state, evidence) from the ONE kind table, or (None, None, None)."""
    row = (
        db.connect()
        .execute(
            "SELECT kind, state, evidence FROM document_kinds WHERE document_id = ?",
            (doc_id,),
        )
        .fetchone()
    )
    if row is None:
        return None, None, None
    return row["kind"], row["state"], json.loads(row["evidence"] or "null")


def _equipment(doc_id):
    return (
        db.connect()
        .execute(
            "SELECT equipment_type FROM document_classification WHERE document_id=?",
            (doc_id,),
        )
        .fetchone()["equipment_type"]
    )


@pytest.mark.parametrize(
    "page,expected",
    [
        ("PUMP DATA SHEET\nDoc. No.: AB-123-DS-0001\nTag 10-P-1", "datasheet"),
        ("ACME PROJECT\nHAZARD STUDY PROCEDURE\nREV 00", "procedure"),
        ("ACME PROJECT\nSPECIFICATION FOR PAINTING\nREV 00", "specification"),
        ("DOCUMENT TRANSMITTAL\nTo: Company", "transmittal"),
        ('SCHEDULE "K"\nINSURANCE REQUIREMENTS\n1.0 General', "contract"),
        ("GENERAL ARRANGEMENT DRAWING\nSheet 1", "drawing"),
        ("FRONT END ENGINEERING DESIGN\nBasis", "feed"),
        ("ISO 99999-1\nSomething about valves", "standard"),
        ("Some memo about nothing in particular.", "unknown"),
    ],
)
def test_kind_from_the_title_block(page, expected):
    evidence = document_kind.decide_document_kind([{"page_no": 1, "text": page}])
    assert evidence.kind == expected
    assert evidence.guess == (expected == "unknown")


def test_the_number_type_code_beats_a_datasheet_word_and_the_conflict_is_kept():
    page = (
        "ACME PROJECT\nMECHANICAL DATASHEET\nSOME VESSEL\n"
        "CONTRACTOR DOC NO: 99999-0001-SP-9910-0003\n"
    )
    evidence = document_kind.decide_document_kind([{"page_no": 1, "text": page}])
    assert evidence.kind == "specification"
    assert evidence.method == "number_type_code"
    assert evidence.conflict == "datasheet" and evidence.guess is True
    assert "SP-9910" in evidence.quote and evidence.page == 1


def test_a_body_mention_of_equipment_never_decides_the_kind():
    evidence = document_kind.decide_document_kind(
        [{"page_no": 1, "text": "Notes\n" + BODY_MENTION}]
    )
    assert evidence.kind == "unknown"


def test_a_label_naming_a_standard_is_not_the_title():
    page = "Design Standard: ISO 99999\nSome memo"
    assert (
        document_kind.decide_document_kind([{"page_no": 1, "text": page}]).kind
        == "unknown"
    )


def test_a_contract_is_recognised_from_its_own_opening_words():
    page = "Part 3\nThe Contractor shall comply with this CONTRACT at all times."
    evidence = document_kind.decide_document_kind([{"page_no": 1, "text": page}])
    assert (evidence.kind, evidence.guess) == ("contract", True)


def test_a_title_naming_equipment_is_a_datasheet_guess():
    page = "ACME PLANT\nCENTRIFUGAL PUMP\nItem 10-P-1"
    evidence = document_kind.decide_document_kind([{"page_no": 1, "text": page}])
    assert (evidence.kind, evidence.method, evidence.guess) == (
        "datasheet",
        "title_equipment",
        True,
    )


def test_switch_off_writes_nothing(monkeypatch):
    monkeypatch.setattr(settings, "document_kind_enabled", False)
    _doc("d1", [PROCEDURE_PAGE])
    assert classification.classify_document_kind("d1") is None
    assert _kind("d1") == (None, None, None)


def test_switch_on_stores_a_suggestion_with_quote_and_page(monkeypatch):
    monkeypatch.setattr(settings, "document_kind_enabled", True)
    _doc("d1", [PROCEDURE_PAGE])
    classification.classify_document_kind("d1")
    kind, state, evidence = _kind("d1")
    assert (kind, state) == ("procedure", "suggested")
    assert evidence["page"] == 1 and "PD-0001" in evidence["quote"]
    assert evidence["guess"] is False


def test_a_document_without_a_classification_row_gets_a_kind_and_no_row(monkeypatch):
    monkeypatch.setattr(settings, "document_kind_enabled", True)
    _doc("d1", ['SCHEDULE "H"\nATTACHMENT I'], with_row=False)
    classification.classify_document_kind("d1")
    assert _kind("d1")[0] == "contract"
    assert (
        db.connect()
        .execute("SELECT 1 FROM document_classification WHERE document_id='d1'")
        .fetchone()
        is None
    )


def test_an_unknown_document_asks_the_engineer(monkeypatch):
    monkeypatch.setattr(settings, "document_kind_enabled", True)
    _doc("d1", ["A memo."])
    classification.classify_document_kind("d1")
    assert _kind("d1")[:2] == (None, "needs_engineer")


def test_a_kind_the_engineer_confirmed_wins_over_the_title(monkeypatch):
    monkeypatch.setattr(settings, "document_kind_enabled", True)
    _doc("d1", [PROCEDURE_PAGE])
    doc_router.confirm("d1", "datasheet", None)
    assert classification.classify_document_kind("d1") is None
    assert _kind("d1")[:2] == ("datasheet", "confirmed")
    # the confirmed datasheet may take the body-text equipment guess
    classification.classify_equipment_type_for_submittal("d1")
    assert _equipment("d1") is not None


def test_a_confirmed_non_datasheet_blocks_the_body_fallback_despite_the_title(
    monkeypatch,
):
    monkeypatch.setattr(settings, "document_kind_enabled", True)
    page = "UNIT DATA SHEET\n" + "\n".join(f"Filler {i}" for i in range(14))
    page += "\n" + BODY_MENTION + "\n" + "\n".join(f"Tail {i}" for i in range(14))
    _doc("d1", [page])
    doc_router.confirm("d1", "procedure", None)
    classification.classify_equipment_type_for_submittal("d1")
    assert _equipment("d1") is None


def test_the_body_equipment_fallback_is_stopped_for_a_procedure(monkeypatch):
    monkeypatch.setattr(settings, "document_kind_enabled", True)
    _doc("d1", [PROCEDURE_PAGE])
    classification.classify_equipment_type_for_submittal("d1")
    assert _kind("d1")[0] == "procedure"
    assert _equipment("d1") is None


def test_the_fallback_is_unchanged_with_the_switch_off(monkeypatch):
    monkeypatch.setattr(settings, "document_kind_enabled", False)
    _doc("d1", [PROCEDURE_PAGE])
    classification.classify_equipment_type_for_submittal("d1")
    assert _equipment("d1") is not None  # the old behaviour, kept off-switch


def test_a_datasheet_still_gets_its_equipment_type(monkeypatch):
    monkeypatch.setattr(settings, "document_kind_enabled", True)
    _doc("d1", ["CENTRIFUGAL PUMP DATA SHEET\nDoc. No.: AB-123-DS-0001"])
    evidence = classification.classify_equipment_type_for_submittal("d1")
    assert evidence is not None and evidence.equipment_type == "Centrifugal Pump"


def test_an_unknown_kind_keeps_the_body_guess_but_marks_it_and_asks(monkeypatch):
    monkeypatch.setattr(settings, "document_kind_enabled", True)
    page = "VENDOR DOCUMENT\nTag P-101\n" + "\n".join(f"Row {i}" for i in range(14))
    page += "\n" + BODY_MENTION + "\n" + "\n".join(f"Tail {i}" for i in range(14))
    _doc("d1", [page])
    classification.classify_equipment_type_for_submittal("d1")
    assert _equipment("d1") is not None
    kind, state, evidence = _kind("d1")
    assert (kind, state) == (None, "needs_engineer")
    assert evidence["equipment_guessed_from_body"] is True


def test_a_standard_or_other_role_is_not_given_a_kind_here(monkeypatch):
    monkeypatch.setattr(settings, "document_kind_enabled", True)
    _doc("d1", [PROCEDURE_PAGE], role="COMPANY_STANDARD")
    classification.classify_equipment_type_for_submittal("d1")
    assert _kind("d1") == (None, None, None)


def test_counts_give_unknown_and_its_rate_with_the_denominator(monkeypatch):
    monkeypatch.setattr(settings, "document_kind_enabled", True)
    _doc("d1", [PROCEDURE_PAGE])
    _doc("d2", ["A memo."])
    _doc("d3", ["Another memo."])
    classification.classify_document_kind("d1")
    classification.classify_document_kind("d2")
    assert document_kind.document_kind_counts() == {
        "total": 3,
        "decided": 2,
        "kinds": {"procedure": 1},
        "unknown": 1,
        "not_classified": 1,
        "unknown_rate": 0.5,
    }


def test_the_report_gives_two_numbers_each_with_its_boundary(monkeypatch):
    monkeypatch.setattr(settings, "document_kind_enabled", True)
    _doc("d1", [PROCEDURE_PAGE])
    _doc("d2", ["A memo."])
    for n in range(3, 11):
        _doc(f"d{n}", ["Another memo."])
    classification.classify_document_kind("d1")
    classification.classify_document_kind("d2")
    text = "\n".join(document_kind.rate_lines(document_kind.document_kind_counts()))
    assert "unknown of documents with a kind decision: 1/2 = 50.0%" in text
    assert "documents decided at all: 2/10" in text
    assert "1/10" not in text  # the undecided are never in the unknown rate


@pytest.mark.parametrize(
    "page",
    [
        "DRAWING PRACTICE STANDARD\nSheet 1",
        "PUMP DATA SHEET STANDARD\nSheet 1",
        "INSPECTION PROCEDURE STANDARD\nDoc. No.: AB-123-PD-0001",
    ],
)
def test_a_company_standard_stays_a_standard_whatever_its_title(page):
    evidence = document_kind.decide_document_kind(
        [{"page_no": 1, "text": page}], document_role="COMPANY_STANDARD"
    )
    assert (evidence.kind, evidence.method, evidence.guess) == (
        "standard",
        "document_role",
        True,
    )
    # the same page of a submittal is read by its title
    assert (
        document_kind.decide_document_kind([{"page_no": 1, "text": page}]).kind
        != "standard"
    )
