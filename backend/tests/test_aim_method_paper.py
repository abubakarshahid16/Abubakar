"""The general review reads each page of the paper in VISUAL order from the app's stored upload (`aim_review.paper.load_paper`).

A PDF whose fields were filled in after it was made holds the added value at the END of its content stream, so the stored
`pages.text` (`get_text("text")`) puts the value alone at the bottom, away from its label. The method reads the stored PDF with
`get_text("text", sort=True)`; it falls back to the stored text, then the recognised text, for a scanned page, a Word file or a
file it cannot open. The judge and the quote check read the same text. Invented PDFs, built here; no paid call, no socket."""

from __future__ import annotations

import pymupdf
import pytest

from app import aim_review
from app.aim_review import engine as E
from app.aim_review import paper as P
from app.aim_review.verify import quote_in
from tests.test_aim_method_helpers import (
    BOOK_A,
    BOOK_B,
    PAPER,
    MemoryStore,
    open_aim_db,
)


@pytest.fixture
def aim_db(tmp_path, monkeypatch):
    yield from open_aim_db(tmp_path, monkeypatch)


LABEL_VALUE = "Set pressure 380 psig"


def _late_value_pdf(path) -> str:
    """An invented one-page sheet whose value is drawn AFTER the rest of the page, on its label's line. Returns the stored
    text ingestion would keep (content-stream order)."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Relief valve data sheet, invented sample")
    page.insert_text((72, 140), "Set pressure")
    page.insert_text((260, 140), "psig (By Contractor)")
    page.insert_text((72, 180), "Body material of the invented valve: carbon steel")
    page.insert_text((180, 140), "380")  # filled in later: last in the content stream
    stored = page.get_text("text")
    doc.save(str(path))
    doc.close()
    return stored


def _normal_pdf(path) -> str:
    doc = pymupdf.open()
    for n in (1, 2):
        page = doc.new_page()
        page.insert_text((72, 100), f"Invented general note {n} of the sample sheet")
        page.insert_text(
            (72, 120), f"Second line of page {n}: design to the buyer list"
        )
    stored = "\n".join(p.get_text("text") for p in doc)
    pages = [p.get_text("text") for p in doc]
    doc.save(str(path))
    doc.close()
    return pages if stored else []


def _point_paper_at(conn, path, pages: dict[int, str], pagination: str | None = None):
    """The invented paper's row now points at `path`, with `pages` as its stored text."""
    with conn:
        conn.execute(
            "UPDATE documents SET stored_path = ?, pagination = ? WHERE id = ?",
            (str(path), pagination, PAPER),
        )
        conn.execute("DELETE FROM pages WHERE document_id = ?", (PAPER,))
        for n, t in pages.items():
            conn.execute(
                "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?, ?, ?, ?, 0)",
                (PAPER, n, t, len(t)),
            )


def _line_of(text: str, word: str) -> str:
    return next(ln for ln in text.splitlines() if word in ln)


def test_a_value_drawn_after_the_page_is_read_on_its_labels_line(aim_db, tmp_path):
    stored = _late_value_pdf(tmp_path / "late.pdf")
    _point_paper_at(aim_db, tmp_path / "late.pdf", {1: stored})
    # the stored text has the value apart from its label: the quote a person would copy is not in it
    assert "380" not in _line_of(stored, "Set pressure")
    assert not quote_in(LABEL_VALUE, stored)
    paper = P.load_paper(aim_db, PAPER)
    line = _line_of(paper.pages[1], "Set pressure")
    assert "380" in line and "psig" in line
    assert quote_in(LABEL_VALUE, paper.pages[1])
    assert paper.sources == {1: P.FROM_PDF}
    assert paper.source_note() == "pages: 1 pdf_visual_order"


def test_a_normal_pdf_gives_the_same_words_as_the_stored_text(aim_db, tmp_path):
    stored = _normal_pdf(tmp_path / "normal.pdf")
    _point_paper_at(aim_db, tmp_path / "normal.pdf", {1: stored[0], 2: stored[1]})
    paper = P.load_paper(aim_db, PAPER)
    assert sorted(paper.pages) == [1, 2]
    # the stated harmless difference: trailing newline and blank-line runs only; the words and their order are the same
    for n in (1, 2):
        assert paper.pages[n].split() == stored[n - 1].split()
    assert set(paper.sources.values()) == {P.FROM_PDF}


def test_a_scanned_page_falls_back_to_its_recognised_text(aim_db, tmp_path):
    doc = pymupdf.open()
    doc.new_page().insert_text(
        (72, 100), "Invented page one with a text layer of its own"
    )
    doc.new_page()  # a scan: no text layer at all
    doc.save(str(tmp_path / "scan.pdf"))
    doc.close()
    _point_paper_at(
        aim_db,
        tmp_path / "scan.pdf",
        {1: "Invented page one with a text layer of its own", 2: ""},
    )
    with aim_db:
        aim_db.execute(
            "INSERT INTO page_ocr (document_id, page_no, text, char_count, engine, model, dpi, box_count, seconds,"
            " recognised_at, batch_no) VALUES (?, 2, ?, 49, 'test-ocr', 'test-model', 200, 9, 0.1, 'x', 0)",
            (PAPER, "Recognised words of the invented scanned page two"),
        )
    paper = P.load_paper(aim_db, PAPER)
    assert paper.pages[2] == "Recognised words of the invented scanned page two"
    assert paper.sources == {1: P.FROM_PDF, 2: P.FROM_OCR}
    assert paper.source_note() == "pages: 1 pdf_visual_order, 1 recognised_text"


def test_a_word_document_uses_the_stored_text(aim_db, tmp_path):
    docx = tmp_path / "paper.docx"
    docx.write_bytes(b"PK\x03\x04 an invented word file, not a pdf")
    stored = {1: "Stored reading text of the invented word paper, first part"}
    _point_paper_at(aim_db, docx, stored, pagination="flow")
    paper = P.load_paper(aim_db, PAPER)
    assert paper.pages == stored and paper.sources == {1: P.FROM_STORED}
    assert paper.file_note == "no_printed_pages"
    # the same without the flow mark: the file is still not a PDF
    _point_paper_at(aim_db, docx, stored)
    paper = P.load_paper(aim_db, PAPER)
    assert paper.pages == stored and paper.file_note == "not_a_pdf"


def test_a_missing_or_broken_file_uses_the_stored_text(aim_db, tmp_path):
    stored = {1: "Stored text of the invented paper, the only reading there is"}
    _point_paper_at(aim_db, tmp_path / "gone.pdf", stored)
    paper = P.load_paper(aim_db, PAPER)
    assert paper.pages == stored and paper.file_note == "stored_file_missing"
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\n this is not a readable pdf body")
    _point_paper_at(aim_db, broken, stored)
    paper = P.load_paper(aim_db, PAPER)
    assert paper.pages == stored and paper.file_note.startswith("unreadable:")


def test_the_judge_sees_and_the_quote_check_verifies_the_visual_text(aim_db, tmp_path):
    """Through `run`: the judge's paper block holds "label value" on one line, a judgment quoting it is verified by code, and
    the run's trace names where the page came from (counts only)."""
    stored = _late_value_pdf(tmp_path / "late.pdf")
    _point_paper_at(aim_db, tmp_path / "late.pdf", {1: stored})

    def judge(_step, cached, prompt):
        import re

        assert "380" in _line_of(cached, "Set pressure")
        ids = re.findall(r'"id": "(C\d+)"', prompt)
        return {
            "judgments": [
                {"id": i, "label": "AI opinion", "field": "set pressure", "page": 1, "quote": LABEL_VALUE,
                 "comment": "invented"} for i in ids
            ]
        }  # fmt: skip

    model = E.FakeModel(
        kind="datasheet", subject_key="test_item", answers={"aim_judge": judge}
    )
    r = aim_review.run(
        aim_db,
        run_id="run_aim_p1",
        paper_id=PAPER,
        allowed_books=frozenset({BOOK_A, BOOK_B}),
        store=MemoryStore(),
        max_usd=5.0,
        model=model,
    )
    assert r.status == "done", r.stop_reason
    judged = [ln for ln in r.lines if ln["code_note"] != aim_review.NOT_JUDGED]
    assert judged and all(
        ln["quote"] == LABEL_VALUE and not ln["quote_unverified"] for ln in judged
    )
    read = [c for c in r.calls if c["step"] == "aim_read_pages"]
    assert read == [
        {"step": "aim_read_pages", "model": "code", "usd": 0.0, "input_tokens": 0, "output_tokens": 0,
         "seconds": 0.0, "ok": True, "code": "pages: 1 pdf_visual_order"}
    ]  # fmt: skip
