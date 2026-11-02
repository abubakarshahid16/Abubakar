"""PR 1581: a playbook row's page, rendered through the real CRS path (`main._crs_content`).
A Word file with no page marks never shows a reading part as a page, and no row says its
page twice. INVENTED documents only; no model (`playbooks.review` with no proposer)."""

from __future__ import annotations

import re

import pytest

from app import (
    access,
    chunker,
    db,
    extract,
    fts_index,
    procedure_playbook_rows,
    submittal_review,
    word_pages,
)
from app import main as main_mod
from app.config import settings
from tests import docx_builder as d
from tests.fake_tokenizer import install_if_missing
from tests.test_1522_presence_without_standard import CUT, _moved
from tests.test_1522_procedure_playbook_rows import _doc as pdf_doc
from tests.test_w5b_679_playbooks import HAZOP_SECTIONS, hold

NOW = "2026-11-02T00:00:00Z"
MARK = "<w:r><w:lastRenderedPageBreak/></w:r>"
APP_NS = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
#: A page named by number, in any shape a cell or a comment can print it.
PAGE_WORDS = re.compile(r"\b(?:pages? \d|p\.\d)")


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "playbook.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(settings, "docx_input_enabled", True)
    monkeypatch.setattr(settings, "procedure_playbook_rows_enabled", True)
    install_if_missing(monkeypatch)
    db.reset_connection()
    db.init_db()
    fts_index.ensure_schema()
    submittal_review.ensure_schema()
    yield
    db.reset_connection()


def _word_doc(
    tmp_path,
    doc_id: str,
    *,
    marks: bool,
    saved_pages: int | None,
    sections=HAZOP_SECTIONS,
) -> str:
    """The playbook's sections as a Word file: each on its own page when `marks`."""
    body = d.para("HAZOP Procedure") + d.para("Document HP-001 revision 0")
    for title, text in sections:
        heading = d.para(title, style="Heading3")
        if marks:
            heading = f"<w:p>{MARK}{d.run(title)}</w:p>".replace(
                "<w:p>", '<w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr>', 1
            )
        body += heading + d.para(text)
    extra = {}
    if saved_pages is not None:
        extra["docProps/app.xml"] = (
            f'<?xml version="1.0"?><Properties xmlns="{APP_NS}"><Pages>{saved_pages}</Pages></Properties>'
        )
    path = d.build(tmp_path / f"{doc_id}.docx", body, extra=extra)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,uploaded_at)"
            " VALUES (?,?,?,?,?,'extracting',?)",
            (doc_id, path.name, f"sha-{doc_id}", path.stat().st_size, str(path), NOW),
        )
        conn.execute(
            "INSERT INTO jobs (id, document_id, stage, state, started_at, updated_at)"
            " VALUES (?,?,'extract','running',?,?)",
            (f"job-{doc_id}", doc_id, NOW, NOW),
        )
        conn.execute(
            "INSERT INTO document_kinds (document_id,kind,state,routed_at) VALUES (?,'procedure','confirmed',?)",
            (doc_id, NOW),
        )
    extract.extract_document(doc_id)
    chunker.chunk_document(doc_id)
    with db.connect() as conn:
        conn.execute("UPDATE documents SET status = 'ready' WHERE id = ?", (doc_id,))
    return doc_id


def _not_held(monkeypatch) -> None:
    """The standard is not held, so a row can cite the page of an unclear section."""
    monkeypatch.setattr(settings, "playbook_section_presence_enabled", True)
    monkeypatch.setattr(settings, "playbook_presence_without_standard_enabled", True)


def _cites_a_page(rows: list[dict]) -> list[dict]:
    return [
        r
        for r in rows
        if "unclear:" in r["comment"] or "section found at" in r["comment"]
    ]


def _rows(doc_id: str, held: bool = True) -> list[dict]:
    if held:
        hold("IEC 61882")
    run = submittal_review.create_review_run(
        submittal_document_id=doc_id, allowed_document_ids=frozenset({doc_id})
    )
    rows, _meta, _name, _stamp = main_mod._crs_content(
        run, access.unrestricted_scope(), "internal"
    )
    mine = [r for r in rows if r["row_kind"] == procedure_playbook_rows.ROW_KIND]
    assert mine
    return mine


@pytest.mark.parametrize("fields", [False, True])
def test_no_page_marks_no_row_names_a_page(tmp_path, monkeypatch, fields):
    monkeypatch.setattr(settings, "word_page_markers_enabled", True)
    monkeypatch.setattr(settings, "procedure_crs_fields_enabled", fields)
    rows = _rows(_word_doc(tmp_path, "none", marks=False, saved_pages=None))
    cells = [r["page_section"] for r in rows if r["page_section"]]
    assert cells
    for row in rows:
        assert not PAGE_WORDS.search(row["page_section"]), row["page_section"]
        assert not PAGE_WORDS.search(row["comment"]), row["comment"]
        assert row["page_section"].count(" - ") <= 1


@pytest.mark.parametrize("fields", [False, True])
def test_no_page_marks_an_unclear_row_cites_no_part_as_a_page(
    tmp_path, monkeypatch, fields
):
    """The owner's case: `cited_page` used to print as a bare "page 1" and, with the
    procedure fields on, after the heading cell as "... - page 1"."""
    _not_held(monkeypatch)
    monkeypatch.setattr(settings, "word_page_markers_enabled", True)
    monkeypatch.setattr(settings, "procedure_crs_fields_enabled", fields)
    doc_id = _word_doc(
        tmp_path, "none", marks=False, saved_pages=None, sections=_moved()
    )
    rows = _rows(doc_id, held=False)
    cited = _cites_a_page(rows)
    assert cited
    assert any("unclear:" in r["comment"] for r in cited)
    for row in rows:
        assert not PAGE_WORDS.search(row["page_section"]), row["page_section"]
        assert not PAGE_WORDS.search(row["comment"]), row["comment"]
    assert any("no page number" in r["comment"] for r in cited)
    assert any("no page number" in r["page_section"].lower() for r in cited)


@pytest.mark.parametrize("fields", [False, True])
def test_real_pages_an_unclear_row_says_its_page_once(tmp_path, monkeypatch, fields):
    _not_held(monkeypatch)
    monkeypatch.setattr(settings, "word_page_markers_enabled", True)
    monkeypatch.setattr(settings, "procedure_crs_fields_enabled", fields)
    sections = _moved()
    doc_id = _word_doc(
        tmp_path, "real", marks=True, saved_pages=len(sections) + 1, sections=sections
    )
    rows = _cites_a_page(_rows(doc_id, held=False))
    assert rows
    for row in rows:
        if PAGE_WORDS.search(row["page_section"]):
            assert len(PAGE_WORDS.findall(row["page_section"])) == 1, row[
                "page_section"
            ]
        assert PAGE_WORDS.search(row["comment"]), row["comment"]


@pytest.mark.parametrize("fields", [False, True])
def test_real_pages_say_their_page_once(tmp_path, monkeypatch, fields):
    monkeypatch.setattr(settings, "word_page_markers_enabled", True)
    monkeypatch.setattr(settings, "procedure_crs_fields_enabled", fields)
    pages = len(HAZOP_SECTIONS) + 1
    rows = _rows(_word_doc(tmp_path, "real", marks=True, saved_pages=pages))
    numbered = [r["page_section"] for r in rows if PAGE_WORDS.search(r["page_section"])]
    assert numbered
    for cell in numbered:
        assert len(PAGE_WORDS.findall(cell)) == 1, cell


@pytest.mark.parametrize("fields", [False, True])
def test_partial_marks_are_said_on_the_cell_and_the_comment(
    tmp_path, monkeypatch, fields
):
    monkeypatch.setattr(settings, "word_page_markers_enabled", True)
    monkeypatch.setattr(settings, "procedure_crs_fields_enabled", fields)
    rows = _rows(_word_doc(tmp_path, "part", marks=True, saved_pages=99))
    numbered = [r for r in rows if PAGE_WORDS.search(r["page_section"])]
    assert numbered
    for row in numbered:
        assert "page marks partial" in row["page_section"], row["page_section"]
        assert len(PAGE_WORDS.findall(row["page_section"])) == 1, row["page_section"]
    for row in rows:
        if PAGE_WORDS.search(row["comment"]):
            assert "page marks partial" in row["comment"], row["comment"]


def test_a_pdf_row_keeps_its_words_with_both_switches_off():
    rows = _rows(pdf_doc("pdf2", HAZOP_SECTIONS))
    numbered = [r["page_section"] for r in rows if PAGE_WORDS.search(r["page_section"])]
    assert numbered
    assert all(c.startswith("page ") for c in numbered)


def _cited_doubles(rows: list[dict]) -> list[str]:
    return [
        r["page_section"]
        for r in rows
        if re.match(r"^p\.\d+ - page \d", r["page_section"])
    ]


@pytest.mark.parametrize("markers", [True, False], ids=["markers-on", "markers-off"])
def test_a_pdf_cell_says_its_page_once_with_the_default_pair_on(monkeypatch, markers):
    """#1652: with the default-on pair (#1630) a PDF playbook cell printed
    "p.5 - page 5". The verified lead is the page; the page already named in
    words beside it is taken off, for any file, so the cell says it once."""
    monkeypatch.setattr(settings, "word_page_markers_enabled", markers)
    monkeypatch.setattr(settings, "procedure_crs_fields_enabled", True)
    rows = _rows(pdf_doc(f"pdf4-{markers}", HAZOP_SECTIONS))
    assert not _cited_doubles(rows)
    numbered = [r["page_section"] for r in rows if PAGE_WORDS.search(r["page_section"])]
    assert numbered, "anti-vacuity: some playbook row must still print a page"
    for cell in numbered:
        assert len(PAGE_WORDS.findall(cell)) == 1, cell


def test_switch_off_a_word_cell_says_its_page_once_with_fields_on(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "procedure_crs_fields_enabled", True)
    pages = len(HAZOP_SECTIONS) + 1
    doc_id = _word_doc(tmp_path, "off", marks=True, saved_pages=pages)
    # This module's own lead is still a Word-file matter only...
    assert word_pages.without_lead("page 2, a > para 1", doc_id) == "page 2, a > para 1"
    rows = _rows(doc_id)
    assert rows
    # ...but the cell never says its page twice (#1652).
    assert not _cited_doubles(rows)
    for row in rows:
        assert len(PAGE_WORDS.findall(row["page_section"])) <= 1, row["page_section"]


@pytest.mark.parametrize("held_standard", [True, False])
def test_not_found_is_marked_a_guess_when_body_gaps_are_listed(
    monkeypatch, held_standard
):
    """Both homes: the section can sit in an unread body picture."""
    from app import reading_state

    if not held_standard:
        _not_held(monkeypatch)
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    monkeypatch.setattr(reading_state, "stored", lambda _doc: {"body_gaps": 2})
    cut = [s for s in HAZOP_SECTIONS if s[0] != CUT]
    rows = _rows(pdf_doc("gap", cut), held=held_standard)
    found = [r for r in rows if "ot found" in r["comment"]]
    assert found
    assert all("a guess: 2 pages or pictures" in r["comment"] for r in found)


@pytest.mark.parametrize("held_standard", [True, False])
def test_not_found_keeps_its_words_with_the_switch_off(monkeypatch, held_standard):
    if not held_standard:
        _not_held(monkeypatch)
    cut = [s for s in HAZOP_SECTIONS if s[0] != CUT]
    rows = _rows(pdf_doc("nogap", cut), held=held_standard)
    assert all("a guess" not in r["comment"] for r in rows)


def test_a_section_not_found_keeps_the_heading_guess_and_the_listed_gaps(monkeypatch):
    """Two different doubts, and the row says both."""
    from app import playbooks, reading_state

    _not_held(monkeypatch)
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    monkeypatch.setattr(reading_state, "stored", lambda _doc: {"body_gaps": 2})
    monkeypatch.setattr(playbooks, "_structure_is_a_guess", lambda _body: True)
    cut = [s for s in HAZOP_SECTIONS if s[0] != CUT]
    rows = _rows(pdf_doc("both", cut), held=False)
    found = [r for r in rows if "Section not found" in r["comment"]]
    assert found
    for row in found:
        assert "known only from how lines are printed" in row["comment"]
        assert "a guess: 2 pages or pictures" in row["comment"]
