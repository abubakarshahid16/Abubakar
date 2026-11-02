"""#1522 / #1476: a PDF's section headings read from font size and weight.

The Word copy of a procedure gave headings from its styles; the PDF copy of the
same procedure gave none, so the playbook section-presence check said "could not
be checked" for every element. Every PDF here is built in code (rule 3: no
client file), and every signal is general (rule 13):

  * numbered bold headings ("1. AIMS OF THE WORK", "4.1 Item list"),
  * a bold-only heading, a size-only heading,
  * NOT a heading: a numbered list item in body style ("1. Close the valve."),
    a table row with numbers, a bold table header with a cell beside it, a
    bold running header and an italic running footer, a bold title wrapped
    over two lines.

Switch PDF_HEADING_DETECTION_ENABLED, off by default: off, chunk sections and the
chunk signature are exactly as before.
"""

from __future__ import annotations

import pymupdf
import pytest

from app import chunker, db, pdf_headings
from app.config import settings

NOW = "2026-11-01T00:00:00Z"
BODY = 10
NUMBERED_BOLD = [
    "1. AIMS OF THE WORK",
    "4.1 Item list",
    "5. Features of a Good Sample",
]
BOLD_ONLY = ["Plant Outline"]
SIZE_ONLY = ["Review Panel"]
#: a bold heading over a bold definitions label; a short body-type line with a dotted number
OVER_LABEL = ["2. TERMS USED"]
DOTTED_BODY = ["4.5.1 Later steps"]
HEADINGS = NUMBERED_BOLD + BOLD_ONLY + SIZE_ONLY + OVER_LABEL + DOTTED_BODY
#: bold and title-like, but a requirement: the chunker keeps it in the text
REQUIREMENT = "All Valves Shall Be Hydrotested"
SHORT_REQUIREMENTS = ["Bolts Must Be Torqued", "Do Not Exceed 10 Bar"]
SENTENCE = "The panel will check every sample of the batch during the working sessions."


def _page(pdf, n: int, items: list[tuple]) -> None:
    """items: (text, font, size) top to bottom, or ("cells", [texts], font) for one row."""
    page = pdf.new_page(width=600, height=800)
    page.insert_text(
        (40, 40), "ACME PLANT PROJECT REVIEW", fontname="hebo", fontsize=12
    )
    page.insert_text(
        (40, 780), f"Company general use - page {n} of 3", fontname="heit", fontsize=8
    )
    y = 120
    for item in items:
        if item[0] == "cells":
            for k, cell in enumerate(item[1]):
                page.insert_text(
                    (40 + 160 * k, y), cell, fontname=item[2], fontsize=BODY
                )
        else:
            text, font, size = item
            page.insert_text((40, y), text, fontname=font, fontsize=size)
        y += 22


def _body(k: int) -> list[tuple]:
    return [(SENTENCE, "helv", BODY)] * k


def build(path) -> list[str]:
    pdf = pymupdf.open()
    _page(
        pdf,
        1,
        [
            ("1. AIMS OF THE WORK", "hebo", BODY),
            *_body(4),
            ("Plant Outline", "hebo", BODY),
            *_body(3),
            ("1. Close the valve.", "helv", BODY),
            ("2. Open the drain", "helv", BODY),
            *_body(2),
        ],
    )
    _page(
        pdf,
        2,
        [
            ("Review Panel", "helv", 15),
            *_body(3),
            ("cells", ["Item", "Value"], "hebo"),
            ("cells", ["Flow", "10"], "helv"),
            ("10   20   30", "hebo", BODY),
            *_body(2),
            ("Requirements for the protection of", "hebo", BODY),
            ("Buried Pipes", "hebo", BODY),
            *_body(2),
        ],
    )
    _page(
        pdf,
        3,
        [
            ("4.1 Item list", "hebo", BODY),
            *_body(5),
            # a styled title whose text resumes in lower case is still a title
            ("5. Features of a Good Sample", "hebo", BODY),
            ("samples are chosen so that each holds one batch.", "helv", BODY),
            *_body(2),
        ],
    )
    _page(
        pdf,
        4,
        [
            ("2. TERMS USED", "hebo", BODY),
            ("OWNER:", "hebo", BODY),
            *_body(2),
            ("4.5.1 Later steps", "helv", BODY),
            *_body(2),
            # a numbered requirement: its sentence resumes in lower case
            ("4.2.1 Stud bolts for flanges in hydrocarbon service", "helv", BODY),
            ("shall be of the grade listed in the table below.", "helv", BODY),
            *_body(2),
        ],
    )
    _page(
        pdf,
        5,
        [
            *_body(3),
            (REQUIREMENT, "hebo", BODY),
            *_body(2),
            (SHORT_REQUIREMENTS[0], "hebo", BODY),
            *_body(2),
            (SHORT_REQUIREMENTS[1], "hebo", BODY),
            *_body(2),
            ("4.2 MPa", "helv", BODY),
            *_body(2),
            ("3.5 Bar", "hebo", BODY),
            *_body(2),
            ("25 Psi", "hebo", BODY),
            *_body(2),
        ],
    )
    pdf.save(str(path))
    texts = [p.get_text() for p in pdf]
    pdf.close()
    return texts


def _found(path) -> list[str]:
    with pymupdf.open(str(path)) as pdf:
        return [
            h
            for heads in pdf_headings.detect(pdf_headings.read_lines(pdf)).values()
            for h in heads
        ]


def test_styled_headings_are_found(tmp_path):
    build(tmp_path / "p.pdf")
    found = _found(tmp_path / "p.pdf")
    for heading in HEADINGS:
        assert heading in found, heading


def test_lines_that_are_not_headings_are_not(tmp_path):
    build(tmp_path / "p.pdf")
    found = set(_found(tmp_path / "p.pdf"))
    assert found == set(
        HEADINGS
    )  # nothing else: list items, table rows, header, footer, wrapped title


def test_numbering_alone_never_makes_a_heading():
    # body-style numbered lines are list items, whatever their number
    pages = {
        1: [
            pdf_headings.Line("1. Close the valve", BODY, False, 100, 110, 800),
            pdf_headings.Line(SENTENCE, BODY, False, 120, 130, 800),
        ]
    }
    assert pdf_headings.detect(pages) == {}


def test_section_number_is_not_a_word_or_a_value():
    for text in (
        "1. SCOPE",
        "4.2 Scope",
        "A.1 Scope",
        "Appendix B",
        "PART A",
        "Part IV",
    ):
        assert pdf_headings.numbered(text), text
    for text in (
        "Part of the plant",
        "PART OF THE PLANT",
        "2500 Psi",
        "4.2 MPa",
        "25 Psi",
    ):
        assert not pdf_headings.numbered(text), text


def test_a_value_is_not_a_title_and_a_title_word_is_kept():
    for text in ("4.2 MPa", "3.5 Bar", "25 Psi", "4.2 20 Bar", "4.2 MPa at Inlet"):
        assert pdf_headings.states_a_value(text), text
    # a word that is also a unit, opening a real title
    for text in ("4.2 Bar Screens", "4.2 Scope", "Appendix B", "4.5 A Review"):
        assert not pdf_headings.states_a_value(text), text


def test_a_requirement_or_a_limit_is_not_a_heading():
    for text in (
        "Bolts Must Be Torqued",
        "Pumps Should Be Vented",
        "Do Not Exceed 10 Bar",
        "Not To Exceed Rating",
        "Maximum 10 Bar",
        "10 Bar Maximum",
        "Valves Will Be Tested",
        "4.1 Lines Shall Be Drained",
    ):
        assert pdf_headings.states_a_requirement(text), text
    for text in (
        "Required Documents",
        "Class 150 Pipe",
        "4.2 Scope",
        "Part 2 In Service",
    ):
        assert not pdf_headings.states_a_requirement(text), text


def test_a_title_with_a_dotted_number_and_a_unit_word_is_kept():
    # past a dotted or dotted-off number a unit word can open a title; a bare integer cannot
    assert not pdf_headings.states_a_requirement("4.2 Bar Screens")
    assert not pdf_headings.states_a_requirement("1. Bar Screens")
    assert pdf_headings.states_a_requirement("25 Psi Rating")


def test_a_label_alone_is_a_title():
    assert pdf_headings._reads_as_title("Appendix B")
    assert not pdf_headings._reads_as_title("A.1")


# ------------------------------------------------------- through the chunker


@pytest.fixture
def stored(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "headings.sqlite")
    db.reset_connection()
    db.init_db()
    (tmp_path / "uploads").mkdir()
    texts = build(tmp_path / "uploads" / "proc.pdf")
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES ('doc_h','proc.pdf','sha-h',1,'uploads/proc.pdf','chunking',3,?)""",
            (NOW,),
        )
        for n, text in enumerate(texts, start=1):
            conn.execute(
                "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
                " VALUES ('doc_h',?,?,?,0,0)",
                (n, text, len(text)),
            )
    yield
    db.reset_connection()


def _sections() -> set[str]:
    with db.connect() as conn:
        return {
            r[0]
            for r in conn.execute(
                "SELECT section FROM chunks WHERE document_id='doc_h' AND section IS NOT NULL"
            )
        }


def test_on_the_chunks_carry_the_styled_headings(stored, monkeypatch):
    monkeypatch.setattr(settings, "pdf_heading_detection_enabled", True)
    chunker.chunk_document("doc_h", force=True)
    sections = _sections()
    for heading in HEADINGS:
        assert heading in sections, heading
    assert "1. Close the valve." not in sections
    # a requirement set in bold is no section, and its words stay in the chunk text
    for line in [REQUIREMENT, *SHORT_REQUIREMENTS]:
        assert line not in sections, line
    with db.connect() as conn:
        texts = " ".join(
            r[0]
            for r in conn.execute("SELECT text FROM chunks WHERE document_id='doc_h'")
        )
    folded = " ".join(texts.split())
    for line in [REQUIREMENT, *SHORT_REQUIREMENTS, *HEADINGS]:
        assert line in folded, line  # a heading never removes its words from the text
    with db.connect() as conn:
        contexts = {
            r[0]
            for r in conn.execute(
                "SELECT context FROM chunks WHERE document_id='doc_h' AND section='Plant Outline'"
            )
        }
    # an unnumbered font-set heading sits under the numbered one in force
    assert contexts == {"1. AIMS OF THE WORK > Plant Outline"}


def test_off_nothing_changes(stored, monkeypatch):
    monkeypatch.setattr(settings, "pdf_heading_detection_enabled", False)
    chunker.chunk_document("doc_h", force=True)
    # the text rules alone read only the dotted numbers; the rest needed the font
    assert _sections() & set(HEADINGS) == {"4.1 Item list", "4.5.1 Later steps"}
    with db.connect() as conn:
        pages, tables, _ = chunker._load_pages(conn, "doc_h")
        sig = conn.execute(
            "SELECT chunk_signature FROM documents WHERE id='doc_h'"
        ).fetchone()[0]
    assert sig == chunker._chunk_signature(
        "sha-h", pages, tables
    )  # the signature as before


def test_switching_on_marks_the_pdf_stale(stored, monkeypatch):
    monkeypatch.setattr(settings, "pdf_heading_detection_enabled", False)
    chunker.chunk_document("doc_h", force=True)
    with db.connect() as conn:
        assert not chunker.is_stale(conn, "doc_h")
        monkeypatch.setattr(settings, "pdf_heading_detection_enabled", True)
        assert chunker.is_stale(conn, "doc_h")
