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
    standard_clause_page._pages_of.cache_clear()
    standard_clause_page._running_of.cache_clear()
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


def _run(sheet: str, standards: list[str], included: int = 1) -> str:
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
                "selection_reason,selection_method,included,created_at) VALUES (?,?,?,?,'rule',?,?)",
                (f"ras-{run}-{i}", run, std, "invented", included, f"{NOW}{i}"),
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
    # order 228.1: the source the item cites, never the program's check id
    assert crs_mapping._standard_reference({**row, "standard_page": 14}) == (
        "API 520-I 3.26 (p.14)"
    )
    # not located: the clause alone, no page is claimed
    assert (
        crs_mapping._standard_reference({**row, "standard_page": None})
        == "API 520-I 3.26"
    )
    # no source at all: no id either
    assert crs_mapping._standard_reference(
        {**row, "standard_clause": None, "standard_page": 14}
    ) == ("Datasheet check")


def test_two_applicable_standards_that_are_both_the_label_are_not_picked_between():
    first = _document("API-520-I.pdf", [DEFINITIONS])
    second = _document("API 520-I (copy).pdf", [DEFINITIONS])
    run = _run(_document("sheet.pdf", ["x"]), [first, second])
    assert standard_clause_page.locate(run, "API 520-I", "3.26") == (None, None)


@pytest.mark.parametrize(
    "page",
    [
        "see the pressure stated in\n3.26 shall be used for the test.\n",  # a wrapped cross-reference
        "Table 4 limits\n3.26 mm\n3.27 mm\n",  # a table value
        "Contents\n3.26 Maximum allowable working pressure\n14\n",  # a page number wrapped to the next line
        "3.26 Maximum allowable working pressure ........ 14\n",  # dot leaders
        "3,26 maximum allowable working pressure\n",  # OCR comma: not read as 3.26
    ],
)
def test_a_line_that_only_looks_like_the_heading_is_not_the_page(page):
    _std, run = _world([page, "no clause here\n"])
    assert standard_clause_page.locate(run, "API 520-I", "3.26") == (None, None)


def test_a_bare_page_number_is_not_a_whole_number_clause():
    _std, run = _world(
        ["Page header\n10\nPump datasheet requirements\n", "8 Scope\nthe scope.\n"]
    )
    assert standard_clause_page.locate(run, "API 520-I", "10") == (None, None)
    assert (
        standard_clause_page.locate(run, "API 520-I", "8")[1] == 2
    )  # a titled whole-number heading is found


def test_a_heading_that_ends_in_a_number_is_still_a_heading():
    std, run = _world(
        ["3.26 Design to ISO 4126\nbody text.\n", "3.40 Flange Class 150\nbody.\n"]
    )
    assert standard_clause_page.locate(run, "API 520-I", "3.26") == (std, 1)
    assert standard_clause_page.locate(run, "API 520-I", "3.40") == (std, 2)


def test_an_annex_clause_is_found():
    std, run = _world(["Annex A\nA.2.1 Relief load\nbody text.\n"])
    assert standard_clause_page.locate(run, "API 520-I", "A.2.1") == (std, 1)


def test_a_contents_page_of_single_spaced_entries_is_skipped_as_a_whole():
    contents = "Contents\n" + "".join(
        f"3.{n} Term number {n} 1{n}\n" for n in range(20, 30)
    )
    std, run = _world([contents, "3.26 term number 26\nbody text.\n"])
    assert standard_clause_page.locate(run, "API 520-I", "3.26") == (std, 2)


def test_a_standard_the_engineer_excluded_from_the_run_is_not_linked():
    std = _document("API-520-I.pdf", [DEFINITIONS])
    run = _run(_document("sheet.pdf", ["x"]), [std], included=0)
    assert standard_clause_page.locate(run, "API 520-I", "3.26") == (None, None)


def test_an_ocr_digit_confusion_in_the_clause_number_is_not_located():
    _std, run = _world(["3.2G maximum allowable working pressure\nbody text.\n"])
    assert standard_clause_page.locate(run, "API 520-I", "3.26") == (None, None)


def test_a_failure_to_attach_never_fails_the_store_and_leaves_the_findings(monkeypatch):
    _std, run = _world([DEFINITIONS])
    sheet = (
        db.connect()
        .execute("SELECT submittal_document_id FROM review_runs WHERE id=?", (run,))
        .fetchone()[0]
    )

    def boom(*args):
        raise RuntimeError("pages table locked")

    monkeypatch.setattr(standard_clause_page, "locate", boom)
    written = datasheet_checks.store(
        run, sheet, [_result("API 520-I", "3.26")], pages_read={}
    )
    assert len(written) == 1 and written[0].get("standard_page") is None


def test_a_connection_that_cannot_be_opened_never_fails_the_store(monkeypatch):
    """`attach` opens its own connection inside the guarded block: a database that
    cannot be reached after the findings are written must not undo them."""
    _std, run = _world([DEFINITIONS])
    sheet = (
        db.connect()
        .execute("SELECT submittal_document_id FROM review_runs WHERE id=?", (run,))
        .fetchone()[0]
    )
    real = standard_clause_page.connect
    calls = {"after_store": False}

    def flaky():
        if calls["after_store"]:
            raise RuntimeError("database is locked")
        return real()

    monkeypatch.setattr(standard_clause_page, "connect", flaky)
    original_attach = standard_clause_page.attach

    def attach_with_locked_db(run_id, findings):
        calls["after_store"] = True
        return original_attach(run_id, findings)

    monkeypatch.setattr(standard_clause_page, "attach", attach_with_locked_db)
    written = datasheet_checks.store(
        run, sheet, [_result("API 520-I", "3.26")], pages_read={}
    )
    assert len(written) == 1 and written[0].get("standard_page") is None


def test_a_running_header_is_not_a_whole_number_heading_and_the_real_heading_is_found():
    header = "4 API STANDARD 520, PART I\nbody text of the page.\n"
    pages = [header.replace("body", f"body {n}") for n in range(6)] + [
        "4 Scope\nthe scope.\n"
    ]
    _std, run = _world(pages)
    assert (
        standard_clause_page.locate(run, "API 520-I", "4")[1] == 7
    )  # the page of "4 Scope"
    # the same number only in the running header: no heading at all
    _std2, run2 = _world(
        [header.replace("body", f"body {n}") for n in range(6)], name="API-520-II.pdf"
    )
    assert standard_clause_page.locate(run2, "API 520-II", "4") == (None, None)


def test_a_supplement_whose_title_names_the_base_standard_is_not_the_base_standard():
    supplement = _document("scan-0099.pdf", [DEFINITIONS])
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO document_classification (document_id, title, suggested_by) VALUES (?,?,?)",
            (supplement, "Pressure Relief Valves - Supplement to API 520", "test"),
        )
    run = _run(_document("sheet.pdf", ["x"]), [supplement])
    assert standard_clause_page.locate(run, "API 520-I", "3.26") == (None, None)


def test_the_title_still_identifies_a_standard_when_it_is_exactly_the_label():
    std = _document("scan-0042.pdf", [DEFINITIONS])
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO document_classification (document_id, title, suggested_by) VALUES (?,?,?)",
            (std, "API 520-I", "test"),
        )
    run = _run(_document("sheet.pdf", ["x"]), [std])
    assert standard_clause_page.locate(run, "API 520-I", "3.26") == (std, 1)


def test_repeated_line_shapes_of_a_scanned_book_are_not_dropped_as_headers():
    """A lone clause number on its own line and repeated titles are headings, not headers:
    only a line that repeats with a plain page number is a running header."""
    clauses = ["3.1", "3.2", "3.26", "3.49", "3.50", "3.51"]
    titles = [
        "accumulation",
        "back pressure",
        "maximum allowable working pressure",
        "set pressure",
        "blowdown",
        "burst pressure",
    ]
    pages = [
        f"{c}\n{t}\n  the definition of the term.\n" for c, t in zip(clauses, titles)
    ]
    pages += [f"{n}.1 General\nthe general part {n}.\n" for n in (4, 5, 6, 7)]
    std, run = _world(pages)
    assert standard_clause_page.locate(run, "API 520-I", "3.26") == (std, 3)
    assert standard_clause_page.locate(run, "API 520-I", "3.49") == (std, 4)
    assert standard_clause_page.locate(run, "API 520-I", "5.1") == (std, 8)
    # and a header with a page number is still dropped
    assert standard_clause_page._line_key("Page 12") == standard_clause_page._line_key(
        "Page 13"
    )
    assert standard_clause_page._line_key(
        "4 API STANDARD 520, PART I"
    ) == standard_clause_page._line_key("5 API STANDARD 520, PART I")
    assert standard_clause_page._line_key("3.26") != standard_clause_page._line_key(
        "3.27"
    )
    assert standard_clause_page._line_key(
        "5.1 General"
    ) != standard_clause_page._line_key("6.1 General")
