# ruff: noqa: F811
"""Pages not read, said plainly (order 14, #1905): a page counts as read only when text or a picture reading came back. Invented values."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import aim_review, db, ocr
from app.aim_review import engine as E
from app.aim_review import unread as U
from app.aim_review.paper import load_paper
from tests.test_aim_method_helpers import MemoryStore, _doc, open_aim_db
from tests.test_aim_sheet_rule import world  # noqa: F401 - fixture
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture

LONG = "Design pressure of the invented test item is stated here in full words."


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


def _paper(conn, pages: dict[int, str], doc="doc_u1", name="invented.pdf"):
    with conn:
        _doc(conn, doc, name, "CONTRACTOR_SUBMITTAL", pages)
    return doc


def test_a_page_with_no_text_is_not_read_and_one_with_text_is(aim_db):
    doc = _paper(aim_db, {1: LONG, 2: "", 3: "7", 4: LONG})
    paper = U.with_unread(aim_db, doc, load_paper(aim_db, doc), load_paper)
    assert [(i["where"], i["why"]) for i in paper.unread] == [
        ("page 2", U.NO_TEXT),
        ("page 3", U.NO_TEXT),
    ]  # a bare number is no text


def test_the_reason_says_whether_the_picture_reading_is_waiting_failed_or_came_back_empty(
    aim_db, monkeypatch
):
    monkeypatch.setattr(
        ocr, "recognise_document", lambda *a, **k: {}
    )  # the recognition is not what this test is about
    doc = _paper(aim_db, {1: LONG, 2: "", 3: "", 4: "", 5: ""})
    with aim_db:
        aim_db.execute(
            "UPDATE pages SET needs_ocr = 1 WHERE document_id = ? AND page_no = 2",
            (doc,),
        )
        for n, text, err in ((3, "", "worker_failed: x"), (4, "ok", None)):
            aim_db.execute(
                "INSERT INTO page_ocr (document_id, page_no, text, char_count, engine, model, dpi, box_count, seconds, recognised_at, batch_no, error)"
                " VALUES (?, ?, ?, ?, 'e', 'm', 150, 0, 0, 'x', 0, ?)",
                (doc, n, text, len(text), err),
            )
    paper = U.with_unread(aim_db, doc, load_paper(aim_db, doc), load_paper)
    assert {i["where"]: i["why"] for i in paper.unread} == {
        "page 2": U.WAITING, "page 3": U.FAILED, "page 4": U.NO_TEXT_AFTER, "page 5": U.NO_TEXT,
    }  # fmt: skip


def test_pages_waiting_for_picture_reading_are_read_first_and_then_count_as_read(
    aim_db, monkeypatch
):
    doc = _paper(aim_db, {1: LONG, 2: ""})
    with aim_db:
        aim_db.execute(
            "UPDATE pages SET needs_ocr = 1 WHERE document_id = ? AND page_no = 2",
            (doc,),
        )
    asked = []

    def recognise(document_id, progress=None, max_pages=None):
        asked.append((document_id, max_pages))
        with db.connect() as c:
            c.execute(
                "INSERT INTO page_ocr (document_id, page_no, text, char_count, engine, model, dpi, box_count, seconds, recognised_at, batch_no)"
                " VALUES (?, 2, ?, ?, 'e', 'm', 150, 1, 0, 'x', 0)",
                (document_id, LONG, len(LONG)),
            )
        return {}

    monkeypatch.setattr(ocr, "recognise_document", recognise)
    paper = U.with_unread(aim_db, doc, load_paper(aim_db, doc), load_paper)
    assert asked == [
        (doc, U.MAX_RECOGNISE)
    ]  # the app's own local recognition, a few pages at a time
    assert (
        paper.unread == []
        and paper.pages[2] == LONG
        and paper.sources[2] == "recognised_text"
    )


def test_a_failed_recognition_never_fails_the_review_the_pages_stay_unread(
    aim_db, monkeypatch
):
    doc = _paper(aim_db, {1: LONG, 2: ""})
    with aim_db:
        aim_db.execute(
            "UPDATE pages SET needs_ocr = 1 WHERE document_id = ? AND page_no = 2",
            (doc,),
        )
    monkeypatch.setattr(
        ocr,
        "recognise_document",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("engine gone")),
    )
    paper = U.with_unread(aim_db, doc, load_paper(aim_db, doc), load_paper)
    assert [(i["where"], i["why"]) for i in paper.unread] == [("page 2", U.WAITING)]


def test_a_word_file_picture_with_no_reading_is_a_picture_not_read(aim_db, monkeypatch):
    doc = _paper(aim_db, {1: LONG}, name="invented.docx")
    pics = [
        SimpleNamespace(no=1, kind="image", targets=["x"]),
        SimpleNamespace(no=2, kind="image", targets=["y"]),
    ]
    from app import docx_pages, docx_reader, word_pictures

    monkeypatch.setattr(docx_pages, "PICTURE_IMAGE", "image")
    monkeypatch.setattr(
        docx_reader,
        "read_structure",
        lambda path, picture_readings=None: SimpleNamespace(pictures=pics),
    )
    monkeypatch.setattr(word_pictures, "_sha256", lambda path: "sha")
    monkeypatch.setattr(
        U,
        "_ref",
        lambda conn, pid: {"word": True, "path": "/nowhere/f.docx", "pages": 1},
    )
    paper = U.with_unread(aim_db, doc, load_paper(aim_db, doc), load_paper)
    assert [(i["where"], i["why"]) for i in paper.unread] == [
        ("picture 1", U.PICTURE_NOT_READ),
        ("picture 2", U.PICTURE_NOT_READ),
    ]


def test_the_record_round_trips_into_plain_sentences():
    items = [
        {"where": "page 7", "why": U.NO_TEXT},
        {"where": "picture 3", "why": U.PICTURE_NOT_READ},
    ]
    calls = [
        {"step": "aim_read_pages", "code": "pages: 9 pdf_visual_order"},
        {"step": U.STEP, "code": U.note(items)},
    ]
    got = U.from_calls(calls)
    assert [g["where"] for g in got] == ["page 7", "picture 3"]
    assert (
        got[0]["sentence"]
        == "Page 7 was not read: it has no text and no picture reading came back."
    )
    assert U.summary(got).endswith("page 7; picture 3.")
    assert (
        U.from_calls([{"step": "aim_read_pages", "code": "pages: 9"}]) == []
    )  # a run that read every page says nothing


def test_a_review_of_a_paper_with_an_unread_page_records_it_and_the_page_serves_it(
    aim_db,
):
    doc = _paper(aim_db, {1: LONG, 2: "", 3: LONG})
    result = aim_review.run(
        aim_db, run_id="run_u1", paper_id=doc, allowed_books=frozenset(), store=MemoryStore(), max_usd=5.0,
        model=E.FakeModel(kind="datasheet", subject_key="test_item"),
    )  # fmt: skip
    assert U.from_calls(result.calls)[0]["where"] == "page 2"


def test_the_page_and_the_team_file_say_which_pages_were_not_read(world):
    import json

    from app import aim_review_sheet, aim_review_store
    from tests.test_aim_sheet_rule import BOOK, PAPER, RUN, _sheet, client

    calls = [
        {"step": "aim_read_pages", "code": "pages: 8 pdf_visual_order"},
        {"step": U.STEP, "code": "page 4: no_text; picture 2: picture_not_read"},
    ]
    with db.connect() as conn:
        conn.execute(
            f"UPDATE {aim_review_store.RUNS} SET calls_json = ? WHERE run_id = ?",
            (json.dumps(calls), RUN),
        )
    page = client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general").json()
    assert [x["where"] for x in page["pages_not_read"]] == ["page 4", "picture 2"]
    ws = _sheet(client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general/sheet"))[
        aim_review_sheet.SUMMARY
    ]
    cells = [str(c) for row in ws.iter_rows(values_only=True) for c in row if c]
    assert any(c.startswith("Page 4 was not read: it has no text") for c in cells)
    with db.connect() as conn:
        conn.execute(
            f"UPDATE {aim_review_store.RUNS} SET calls_json = ? WHERE run_id = ?",
            (json.dumps(calls[:1]), RUN),
        )
    again = client(PAPER, BOOK).get(f"/api/reviews/papers/{PAPER}/general").json()
    assert again["pages_not_read"] == []  # a run that read every page says none
