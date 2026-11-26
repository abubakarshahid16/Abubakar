"""Update 13 (lead-4, 26 Nov 2026): "needs pictures" is decided PER PAPER, page by page. For a paper the app recorded as a DRAWING before the
review: a page with a text layer and a title block (or drawn over a quarter of the page) is reviewed on its text and named "picture part not
read"; a page under 50 characters is picture only; a page with no text is named as before. Any other kind: exactly as before. The PDFs are
invented and made here; no paid call, no socket."""

from __future__ import annotations

import pymupdf
import pytest

from app.aim_review import drawing_pages as DP
from app.aim_review import unread as U
from app.aim_review.paper import load_paper
from tests.test_aim_method_helpers import _doc, open_aim_db

TITLE = "TITLE Invented skid layout\nDRAWING NO. ZZ-0001  REV 2\nSCALE 1:50  DATE 2026-11-26\nDRAWN AB  CHECKED CD  APPROVED EF\nSHEET 1 OF 1"
NOTES = "NOTES: 1. All invented dimensions are in millimetres unless stated otherwise. 2. Invented note two."
SHORT = "Invented label 30 characters."
PLAIN = "An invented paragraph of plain text only, long enough to be a page of words and nothing else at all."


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


def _lines(page, n=60):
    for i in range(n):  # a drawing: many lines over the page
        y = 40 + i * 12
        page.draw_line((30, y), (560, y + 30))
        page.draw_line((30 + i * 9, 30), (30 + i * 9, 800))


def _pdf(path, pages):
    doc = pymupdf.open()
    for kind in pages:
        page = doc.new_page()
        if kind == "titled":
            page.insert_text((40, 700), TITLE, fontsize=9)
            _lines(page, 10)
        elif kind == "notes_drawn":
            page.insert_text((40, 60), NOTES, fontsize=9)
            _lines(page)
        elif kind == "short":
            page.insert_text((40, 60), SHORT, fontsize=9)
        elif kind == "scan":
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 80), 0)
            pix.clear_with(200)
            page.insert_image(page.rect, pixmap=pix)
        elif kind == "plain":
            page.insert_text((40, 60), PLAIN, fontsize=9)
    doc.save(path)
    doc.close()
    return {
        i + 1: {
            "titled": TITLE,
            "notes_drawn": NOTES,
            "short": SHORT,
            "scan": "",
            "plain": PLAIN,
        }[k]
        for i, k in enumerate(pages)
    }


def _paper(conn, tmp_path, pages, kind, doc="doc_dr1", confirmed=True):
    path = tmp_path / f"{doc}.pdf"
    texts = _pdf(path, pages)
    with conn:
        _doc(conn, doc, f"{doc}.pdf", "CONTRACTOR_SUBMITTAL", texts)
        conn.execute(
            "UPDATE documents SET stored_path = ? WHERE id = ?", (str(path), doc)
        )
        if kind:
            conn.execute(
                "INSERT INTO document_kinds (document_id, kind, state, routed_at) VALUES (?, ?, ?, '2026-11-26T00:00:00Z')",
                (doc, kind, "confirmed" if confirmed else "suggested"),
            )
    return doc


def _marks(conn, doc):
    paper = U.with_unread(conn, doc, load_paper(conn, doc), load_paper)
    return [(i["where"], i["why"]) for i in paper.unread], paper


def test_a_mixed_drawing_says_per_page_what_was_read(aim_db, tmp_path):
    doc = _paper(
        aim_db, tmp_path, ["titled", "notes_drawn", "short", "scan", "plain"], "drawing"
    )
    got, paper = _marks(aim_db, doc)
    assert sorted(got) == sorted(
        [
            (
                "page 1",
                DP.PICTURE_PART,
            ),  # title block: read on its text, the drawing not read
            ("page 2", DP.PICTURE_PART),  # notes over a drawn page
            ("page 3", DP.PICTURE_ONLY),  # a label only: picture only
            ("page 4", U.NO_TEXT),  # a scan: not read, as for every kind
        ]
    )  # page 5 is plain text: read, nothing said
    assert paper.unread_checked is True


def test_a_text_layer_drawing_is_read_on_its_text_and_says_the_picture_part_was_not(
    aim_db, tmp_path
):
    doc = _paper(aim_db, tmp_path, ["titled", "titled"], "drawing")
    got, paper = _marks(aim_db, doc)
    assert got == [("page 1", DP.PICTURE_PART), ("page 2", DP.PICTURE_PART)]
    record = [c.as_dict() for c in U.read_calls(paper)]
    said = U.from_calls(record)
    assert said[0]["sentence"] == (
        "Page 1: the picture part was not read (its text and title block were read; the drawing itself (its lines and symbols) was not)."
    )
    assert (
        U.summary(said)
        == "Picture part not read (text and title block read): pages 1, 2."
    )
    assert U.record_state(record) == U.LISTED


def test_a_scan_only_drawing_is_named_not_read_page_by_page(aim_db, tmp_path):
    doc = _paper(aim_db, tmp_path, ["scan", "scan"], "drawing")
    got, _ = _marks(aim_db, doc)
    assert got == [("page 1", U.NO_TEXT), ("page 2", U.NO_TEXT)]


@pytest.mark.parametrize(
    ("kind", "confirmed"), [("datasheet", True), (None, True), ("drawing", False)]
)
def test_any_other_kind_or_an_unconfirmed_guess_is_exactly_as_before(
    aim_db, tmp_path, kind, confirmed, monkeypatch
):
    import app.agent_review_kind as ARK

    if kind is None:  # no stored kind and no cue: unknown
        monkeypatch.setattr(
            ARK, "read_kind", lambda conn, d: {"kind": None, "known": False}
        )
    doc = _paper(
        aim_db,
        tmp_path,
        ["titled", "notes_drawn", "short", "scan", "plain"],
        kind,
        confirmed=confirmed,
    )
    if (
        kind == "drawing" and not confirmed
    ):  # a suggestion only: the code's own reading decides, and it reads no drawing here
        monkeypatch.setattr(
            ARK, "read_kind", lambda conn, d: {"kind": "datasheet", "known": True}
        )
    got, _ = _marks(aim_db, doc)
    assert got == [
        ("page 4", U.NO_TEXT)
    ]  # only the page with no text, as before this change


def test_the_mixed_summary_names_pages_not_read_and_picture_parts_apart():
    items = [
        {"where": "page 3", "why": DP.PICTURE_ONLY},
        {"where": "page 4", "why": U.NO_TEXT},
        {"where": "page 1", "why": DP.PICTURE_PART},
    ]
    got = U.summary(items)
    assert got.startswith(
        "Not read (no text and no picture reading came back, or it has not run): pages 3, 4."
    )
    assert got.endswith("Picture part not read (text and title block read): page 1.")
