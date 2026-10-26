"""Order 225: a checklist finding can open the standard at the clause's page.

A checklist item cites "API 520-I" clause "3.26". The finding it writes carried
that text and no document or page, so nothing could be opened. These tests hold
the location: the standard of the run, the one page where the clause opens a
heading (contents pages left out, OCR-style text included) and "not located"
(never a guessed page) for everything else. Invented standard and pages only.
"""

from __future__ import annotations

import uuid

import pytest

from app import datasheet_checks, db, standard_clause_page, submittal_review
from app import review as review_mod
from app.config import settings

NOW = "2026-10-26T00:00:00"

CONTENTS = (
    "Contents\n"
    "3.1 Scope ........ 9\n3.2 Terms ........ 9\n3.16 Design pressure ........ 12\n"
    "3.26 Maximum allowable working pressure ........ 14\n3.49 Set pressure ........ 17\n"
)
DEFINITIONS = (
    "3 Definitions\n"
    "3.25 limit state\n  a state beyond which the item is unfit.\n"
    "3.26 maximum allowable working pressure (MAWP)\n  the greatest pressure the vessel can hold.\n"
    "3.27 operating pressure\n  the pressure in service.\n"
)
OCR_STYLE = "3.49\nset pressure\n  the pressure at which the valve is set to open.\n"
CROSS_REFERENCE = (
    "The valve shall be sized with the pressure in 3.26 and 3.49 stated.\n"
)


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    review_mod.ensure_schema()
    standard_clause_page._page_of.cache_clear()
    yield
    db.reset_connection()


def _document(name: str, pages: list[str] | None = None) -> str:
    doc = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES (?,?,?,1,'/x','ready',?,?)",
            (doc, name, f"sha-{doc}", len(pages or []), NOW),
        )
        for number, text in enumerate(pages or [], start=1):
            conn.execute(
                "INSERT INTO pages (document_id,page_no,text,char_count,batch_no) VALUES (?,?,?,?,0)",
                (doc, number, text, len(text)),
            )
    return doc


def _run(sheet: str, standards: list[str]) -> str:
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,outcome_json,created_at,updated_at)"
            " VALUES (?,?,'completed','{}',?,?)",
            (run, sheet, NOW, NOW),
        )
        for i, std in enumerate(standards):
            conn.execute(
                "INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,"
                "selection_reason,selection_method,included,created_at) VALUES (?,?,?,?,'rule',1,?)",
                (f"ras-{run}-{i}", run, std, "invented", f"{NOW}{i}"),
            )
    return run


def _world(pages: list[str], name: str = "API-520-I.pdf"):
    std = _document(name, pages)
    run = _run(_document("sheet.pdf", ["x"]), [std])
    return std, run


def test_the_clause_is_found_on_the_page_where_it_opens_a_heading():
    std, run = _world(["Foreword text\n", DEFINITIONS])
    assert standard_clause_page.locate(run, "API 520-I", "3.26") == (std, 2)


def test_a_contents_page_and_a_cross_reference_are_not_the_clause():
    std, run = _world([CONTENTS, CROSS_REFERENCE, DEFINITIONS])
    assert standard_clause_page.locate(run, "API 520-I", "3.26") == (std, 3)


def test_a_clause_number_alone_on_its_line_is_found_in_ocr_style_text():
    std, run = _world([CONTENTS, OCR_STYLE])
    assert standard_clause_page.locate(run, "API 520-I", "3.49") == (std, 2)


def test_a_clause_that_is_on_no_page_is_not_located():
    _std, run = _world([DEFINITIONS])
    assert standard_clause_page.locate(run, "API 520-I", "3.99") == (None, None)
    assert standard_clause_page.locate(run, "API 520-I", "3.2") == (
        None,
        None,
    )  # not 3.26


def test_a_clause_on_two_real_pages_is_not_guessed():
    _std, run = _world([DEFINITIONS, "Annex\n" + DEFINITIONS])
    assert standard_clause_page.locate(run, "API 520-I", "3.26") == (None, None)


def test_a_standard_the_run_did_not_read_is_not_located():
    _std, run = _world([DEFINITIONS], name="ISO-9999.pdf")
    assert standard_clause_page.locate(run, "API 520-I", "3.26") == (None, None)
    other_run = _run(_document("sheet2.pdf", ["x"]), [])
    assert standard_clause_page.locate(other_run, "ISO 9999", "3.26") == (None, None)


def test_nothing_is_located_without_a_label_or_a_clause():
    _std, run = _world([DEFINITIONS])
    assert standard_clause_page.locate(run, None, "3.26") == (None, None)
    assert standard_clause_page.locate(run, "API 520-I", None) == (None, None)
    assert standard_clause_page.locate(run, "API 520-I", " ") == (None, None)


def _result(standard: str, clause: str) -> dict:
    return {
        "rule_id": "PSV-02",
        "status": datasheet_checks.MISSING_INFORMATION,
        "text": "The MAWP is stated.",
        "detail": "not stated",
        "severity": "major",
        "field": "mawp",
        "value": None,
        "page": None,
        "fact_id": None,
        "equipment_tag": None,
        "standard": standard,
        "clause": clause,
        "checklist": True,
        "text_searched": True,
    }


def _findings(run: str, sheet: str) -> list[dict]:
    return (
        [f for f in review_mod.list_for_run(run)]
        if hasattr(review_mod, "list_for_run")
        else []
    )


def test_a_checklist_finding_is_written_with_its_standard_and_page_when_located():
    std, run = _world([CONTENTS, DEFINITIONS])
    sheet = (
        db.connect()
        .execute("SELECT submittal_document_id FROM review_runs WHERE id=?", (run,))
        .fetchone()[0]
    )
    written = datasheet_checks.store(
        run, sheet, [_result("API 520-I", "3.26")], pages_read={}
    )
    row = (
        db.connect()
        .execute(
            "SELECT standard_document_id, standard_page, standard_clause FROM review_findings WHERE id=?",
            (written[0]["id"],),
        )
        .fetchone()
    )
    assert (
        row["standard_document_id"],
        row["standard_page"],
        row["standard_clause"],
    ) == (std, 2, "API 520-I 3.26")


def test_a_checklist_finding_whose_clause_is_not_located_stores_no_page():
    _std, run = _world([DEFINITIONS])
    sheet = (
        db.connect()
        .execute("SELECT submittal_document_id FROM review_runs WHERE id=?", (run,))
        .fetchone()[0]
    )
    written = datasheet_checks.store(
        run, sheet, [_result("API 520-I", "3.99")], pages_read={}
    )
    row = (
        db.connect()
        .execute(
            "SELECT standard_document_id, standard_page, standard_clause FROM review_findings WHERE id=?",
            (written[0]["id"],),
        )
        .fetchone()
    )
    assert row["standard_document_id"] is None and row["standard_page"] is None
    assert row["standard_clause"] == "API 520-I 3.99"


def test_the_crs_reference_of_a_checklist_row_names_the_clause_and_page_only_when_located():
    from app import crs_mapping

    row = {
        "origin": "datasheet_check",
        "requirement_source_text": "Datasheet check PSV-02: The MAWP is stated.",
        "standard_clause": "API 520-I 3.26",
    }
    assert crs_mapping._standard_reference({**row, "standard_page": 14}) == (
        "Datasheet check PSV-02: API 520-I 3.26 (p.14)"
    )
    # not located: the contractor copy says nothing about a missing page
    assert (
        crs_mapping._standard_reference({**row, "standard_page": None})
        == "Datasheet check PSV-02"
    )
    assert crs_mapping._standard_reference(
        {**row, "standard_clause": None, "standard_page": 14}
    ) == ("Datasheet check PSV-02")
