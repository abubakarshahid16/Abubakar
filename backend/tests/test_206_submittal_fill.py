"""Order 206.1: a contractor datasheet's empty title and equipment type are filled
from its own heading, and again when its review starts.

PF1: a pump sheet reached a review with no equipment type, title or discipline
(the READY hooks ran only for a document already marked a submittal), so the
part-scope step found nothing the sheet said about itself and held every clause.
Invented sheets only; no model, no socket.
"""

from __future__ import annotations

import json

import pytest

from app import (
    access,
    auth,
    classification,
    datasheets,
    db,
    fts_index,
    review_jobs,
    standards,
    submittal_fill,
    submittal_review,
)
from app.config import settings
from tests import test_p3_review_jobs as p3

NOW = "2026-10-25T00:00:00Z"


@pytest.fixture(autouse=True)
def _storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    monkeypatch.setattr(settings, "auth_secret", "x" * 48)
    monkeypatch.setattr(settings, "geometry_reader_enabled", False)
    monkeypatch.setattr(settings, "job_max_running", 1)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    fts_index.ensure_schema()
    access.set_user_resolver(auth.resolve_user_id)
    yield
    access.set_user_resolver(None)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()


PUMP = "CENTRIFUGAL PUMP DATASHEET\nDoc No.: INV-DS-1\nTag No.: P-1\nRev: 0\nDesign pressure 9 barg"
TANK = "ATMOSPHERIC STORAGE TANK DATASHEET\nDoc No.: INV-DS-7\nTag No.: T-1\nRev: 0"
WRAPPED = "OPERATOR NAME\nProject: INV\nSOME EXCHANGER DATA\nSHEET\nDoc No.: INV-DS-9"
FOR_FORM = "EXAMPLE CO\nDATA SHEET FOR\nPRESSURE SAFETY VALVES (PSVs)\nDoc. No.: X"


def _sheet(doc_id, text, role="CONTRACTOR_SUBMITTAL", **cols):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES (?,?,?,1,'x','ready',1,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", NOW),
        )
        conn.execute(
            "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
            " VALUES (?,1,?,?,0,0)",
            (doc_id, text, len(text)),
        )
        conn.execute(
            "INSERT INTO document_classification (document_id,suggested_by,document_role)"
            " VALUES (?,?,?)",
            (doc_id, "test", role),
        )
        for col, value in cols.items():
            conn.execute(
                f"UPDATE document_classification SET {col} = ? WHERE document_id = ?",
                (value, doc_id),
            )
    return doc_id


def _row(doc_id):
    return dict(
        db.connect()
        .execute(
            "SELECT * FROM document_classification WHERE document_id = ?", (doc_id,)
        )
        .fetchone()
    )


# ------------------------------------------------------------------ the heading
def test_the_heading_is_the_first_line_that_calls_itself_a_data_sheet():
    assert submittal_fill.heading([{"page_no": 1, "text": PUMP}]) == (
        1,
        "CENTRIFUGAL PUMP DATASHEET",
    )
    assert submittal_fill.heading([{"page_no": 1, "text": WRAPPED}]) == (
        1,
        "SOME EXCHANGER DATA SHEET",
    )
    assert submittal_fill.heading([{"page_no": 1, "text": FOR_FORM}]) == (
        1,
        "DATA SHEET FOR PRESSURE SAFETY VALVES (PSVs)",
    )


@pytest.mark.parametrize(
    "text",
    [
        "Doc No.: A1\nDatasheet no.: 12\nnothing else",  # a label line is not a heading
        "A VERY LONG TITLE OF A DATA SHEET THAT RUNS ON FOR MORE THAN TWELVE WORDS HERE OK",
        "\n".join(["line"] * 15 + ["PUMP DATASHEET"]),  # below the first 15 lines
        "no heading here at all",
        "",
    ],
)
def test_a_page_with_no_clear_heading_has_none(text):
    assert submittal_fill.heading([{"page_no": 1, "text": text}]) is None


def test_only_the_first_page_is_read():
    pages = [{"page_no": 1, "text": "cover page text"}, {"page_no": 2, "text": PUMP}]
    assert submittal_fill.heading(pages) is None


@pytest.mark.parametrize(
    "line,name",
    [
        ("ATMOSPHERIC STORAGE TANK DATASHEET", "Atmospheric Storage Tank"),
        ("SOME EXCHANGER DATA SHEET", "Some Exchanger"),
        ("PUMP DATA SHEET FOR RECYCLE WATER", "Pump"),
        ("DATA SHEET FOR PRESSURE SAFETY VALVES (PSVs)", "Pressure Safety Valves"),
        ("TECHNICAL DATA SHEET FOR CONTROL VALVE", "Control Valve"),
        ("DATA SHEET", None),
        ("DATASHEET NO 12", None),
    ],
)
def test_the_equipment_a_heading_names(line, name):
    assert submittal_fill.equipment_name(line) == name


# --------------------------------------------------------------------- the fill
def test_an_empty_title_and_equipment_type_are_filled_with_the_line_as_the_evidence():
    doc = _sheet("d_tank", TANK)
    written = submittal_fill.fill(doc)
    assert written == {
        "title": "ATMOSPHERIC STORAGE TANK DATASHEET",
        "equipment_type": "Atmospheric Storage Tank",
    }
    row = _row(doc)
    assert row["title"] == "ATMOSPHERIC STORAGE TANK DATASHEET"
    assert row["equipment_type"] == "Atmospheric Storage Tank"
    assert row["confirmed_by"] is None  # a suggestion, never a confirmation
    ev = json.loads(row["equipment_type_evidence"])
    assert ev["quote"] == "ATMOSPHERIC STORAGE TANK DATASHEET" and ev["page"] == 1
    assert ev["method"] == "heading_phrase" and ev["confidence"] < 0.9
    title_ev = json.loads(row["field_evidence"])["title"]
    assert (
        title_ev["quote"] == "ATMOSPHERIC STORAGE TANK DATASHEET"
        and title_ev["page"] == 1
    )
    assert submittal_fill.fill(doc) == {}  # nothing left to fill


def test_a_value_somebody_already_wrote_is_never_replaced():
    doc = _sheet("d_has", TANK, title="Tank farm sheet", equipment_type="Storage Tank")
    assert submittal_fill.fill(doc) == {}
    row = _row(doc)
    assert row["title"] == "Tank farm sheet" and row["equipment_type"] == "Storage Tank"
    only_title = _sheet("d_t", TANK, title="Mine")
    assert submittal_fill.fill(only_title) == {
        "equipment_type": "Atmospheric Storage Tank"
    }
    assert _row(only_title)["title"] == "Mine"


@pytest.mark.parametrize(
    "role,confirmed",
    [(None, None), ("COMPANY_STANDARD", None), ("CONTRACTOR_SUBMITTAL", "someone")],
)
def test_a_document_that_is_not_a_submittal_or_is_confirmed_is_left_alone(
    role, confirmed
):
    doc = _sheet("d_other", TANK, role=role)
    if confirmed:
        with db.connect() as conn:
            conn.execute(
                "UPDATE document_classification SET confirmed_by = NULL WHERE document_id = ?",
                (doc,),
            )
            conn.execute(
                "INSERT INTO users (id,email,display_name,password_hash,is_active,created_at)"
                " VALUES ('someone','s@x','s','x',1,?)",
                (NOW,),
            )
            conn.execute(
                "UPDATE document_classification SET confirmed_by = 'someone' WHERE document_id = ?",
                (doc,),
            )
    assert submittal_fill.fill(doc) == {}
    assert _row(doc)["title"] is None and _row(doc)["equipment_type"] is None


def test_the_classifier_names_the_equipment_first_the_heading_only_when_it_does_not():
    pump = _sheet("d_pump", PUMP)
    classification.classify_equipment_type_for_submittal(
        pump
    )  # the READY hook runs it first
    submittal_fill.classify(pump)
    row = _row(pump)
    assert row["equipment_type"] == "Centrifugal Pump"
    assert json.loads(row["equipment_type_evidence"])["method"] == "title_phrase_match"
    assert (
        row["title"] == "CENTRIFUGAL PUMP DATASHEET"
    )  # the title was never written before
    assert row["document_number"] == "INV-DS-1"  # the metadata classifier still ran
    tank = _sheet("d_tank", TANK)
    submittal_fill.classify(tank)
    assert _row(tank)["equipment_type"] == "Atmospheric Storage Tank"


# ------------------------------------------------------------------- at review start
def test_a_review_start_fills_what_an_earlier_read_left_empty():
    doc = _sheet("d_late", PUMP)
    assert _row(doc)["equipment_type"] is None
    submittal_fill.for_review(doc)
    row = _row(doc)
    assert (
        row["equipment_type"] == "Centrifugal Pump"
        and row["title"] == "CENTRIFUGAL PUMP DATASHEET"
    )


def test_a_review_start_leaves_a_complete_record_and_a_non_submittal_alone(monkeypatch):
    calls = []
    monkeypatch.setattr(
        classification,
        "classify_equipment_type_for_submittal",
        lambda d: calls.append(d),
    )
    full = _sheet(
        "d_full", PUMP, title="T", equipment_type="Pump", discipline="Mechanical"
    )
    assert submittal_fill.for_review(full) == {} and calls == []
    std = _sheet("d_std", PUMP, role="COMPANY_STANDARD")
    assert submittal_fill.for_review(std) == {} and calls == []
    assert submittal_fill.for_review("no-such-document") == {}


def test_a_failure_at_review_start_is_logged_and_never_raised(monkeypatch, caplog):
    doc = _sheet("d_boom", PUMP)

    def boom(_):
        raise RuntimeError("SECRET-SHEET-TEXT")

    monkeypatch.setattr(classification, "classify_metadata_for_submittal", boom)
    with caplog.at_level("WARNING"):
        assert submittal_fill.for_review(doc) == {}
    assert "RuntimeError" in caplog.text and "SECRET-SHEET-TEXT" not in caplog.text


def test_the_review_job_fills_the_submittals_fields_before_it_selects_standards(
    monkeypatch,
):
    std = p3._doc(
        "std_api",
        "COMPANY_STANDARD",
        "Equipment noise level shall not exceed 90 dB(A).",
    )
    sub = p3._doc(
        "sub_pump",
        "CONTRACTOR_SUBMITTAL",
        "Pump shall comply with API 610. Noise level 95 dB(A)",
    )
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET document_number = 'API 610'"
            " WHERE document_id = ?",
            (std,),
        )
    standards.extract_requirements(std, allowed_document_ids=frozenset({std}))
    datasheets.create_fact(
        submittal_document_id=sub,
        chunk_id=f"{sub}-c1",
        field_label="Noise level",
        raw_value="95",
        unit="dB(A)",
        page=1,
    )
    p3._user("adm", [std, sub], admin=True)
    text = "ATMOSPHERIC STORAGE TANK DATASHEET\nDoc No.: INV-DS-7"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
            " VALUES (?,1,?,?,0,0)",
            (sub, text, len(text)),
        )
    seen = {}
    from app import applicability

    real = applicability.select

    def select(*args, **kw):
        row = _row(sub)
        seen["title"], seen["equipment_type"] = row["title"], row["equipment_type"]
        return real(*args, **kw)

    monkeypatch.setattr(applicability, "select", select)
    _, job_id = review_jobs.enqueue(
        sub, allowed_document_ids=frozenset({std, sub}), requested_by="adm"
    )
    review_jobs.claim_next(p3.W)
    review_jobs.run(job_id, p3.W)
    assert seen == {
        "title": "ATMOSPHERIC STORAGE TANK DATASHEET",
        "equipment_type": "Atmospheric Storage Tank",
    }


def test_every_invented_pf1_sheet_gets_a_title_and_an_equipment_type_from_its_own_text():
    """The nine tuning sheets in the repository, read as the app reads them: all
    nine end with a title and an equipment type, none from a name written in code."""
    import pathlib

    import pymupdf

    folder = pathlib.Path(__file__).resolve().parent / "fixtures" / "synthetic" / "pf1"
    sheets = sorted(folder.glob("*.datasheet.pdf"))
    assert len(sheets) >= 9
    for n, path in enumerate(sheets):
        with pymupdf.open(path) as pdf:
            pages = [x.get_text() for x in pdf]
        doc = _sheet(f"d_pf1_{n}", pages[0])
        for number, text in enumerate(pages[1:], start=2):
            with db.connect() as conn:
                conn.execute(
                    "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
                    " VALUES (?,?,?,?,0,0)",
                    (doc, number, text, len(text)),
                )
        classification.classify_equipment_type_for_submittal(doc)
        submittal_fill.classify(doc)
        row = _row(doc)
        assert row["equipment_type"], path.name
        assert row["title"] and row["title"].isupper(), path.name
        assert row["title"].split()[0].lower() in row["equipment_type"].lower() or (
            row["equipment_type"].lower().split()[-1] in row["title"].lower()
        ), path.name


def test_the_ready_hook_in_ingest_fills_the_title():
    from app import ingest

    doc = _sheet("d_hook", TANK)
    ingest._classify_metadata_if_contractor_submittal(doc)
    row = _row(doc)
    assert row["title"] == "ATMOSPHERIC STORAGE TANK DATASHEET"
    assert row["equipment_type"] == "Atmospheric Storage Tank"
    assert row["document_number"] == "INV-DS-7"


def test_a_heading_that_ends_in_data_is_still_a_heading():
    pages = [{"page_no": 1, "text": "CENTRIFUGAL COMPRESSOR DATA\nDoc No.: X1"}]
    assert submittal_fill.heading(pages) == (1, "CENTRIFUGAL COMPRESSOR DATA")
    assert (
        submittal_fill.equipment_name("CENTRIFUGAL COMPRESSOR DATA")
        == "Centrifugal Compressor"
    )
    assert submittal_fill.heading([{"page_no": 1, "text": "DATA\nx"}]) is None


def test_a_sentence_that_mentions_a_data_sheet_is_not_a_heading():
    page = [
        {
            "page_no": 1,
            "text": "ACME CONTRACTING LLC\nThis datasheet supports the piping package for the new transfer pumps.\n",
        }
    ]
    assert submittal_fill.heading(page) is None


def test_a_heading_with_a_discipline_word_names_no_equipment():
    assert submittal_fill.equipment_name("MECHANICAL DATASHEET") is None
    assert submittal_fill.equipment_name("PIPING DATA SHEET") is None
    assert (
        submittal_fill.equipment_name("CENTRIFUGAL PUMP DATA SHEET")
        == "Centrifugal Pump"
    )


@pytest.mark.parametrize(
    "line, expected",
    [
        ("MECHANICAL DATA SHEET FOR CENTRIFUGAL PUMPS", "Centrifugal Pumps"),
        ("INSTRUMENT DATA SHEET FOR LEVEL TRANSMITTER", "Level Transmitter"),
        ("VENDOR DATA SHEET", None),
        ("EQUIPMENT DATA SHEET", None),
        ("GENERAL DATA SHEET", None),
        ("REVISION DATA SHEET", None),
        ("SAFETY DATA SHEET", None),
        ("MATERIAL SAFETY DATA SHEET", None),
        ("CONTRACTOR DATA SHEET", None),
        ("MECHANICAL EQUIPMENT DATA SHEET", None),
        ("API 610 PUMP DATA SHEET", "Pump"),
        ("ISO 9001 DATA SHEET", None),
    ],
)
def test_the_object_after_for_and_the_stop_words(line, expected):
    assert submittal_fill.equipment_name(line) == expected
