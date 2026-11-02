"""ONE_CHECKED_DEFINITION_ENABLED: "ready" means every page and picture was read or listed
as not read, from the ledger, not from vectors alone. INVENTED files only; no model: the
OCR engine is a stub and the vectors are set directly."""

from __future__ import annotations

import io
import json
import zipfile

import pymupdf
import pytest
from PIL import Image

from app import (
    access,
    chunker,
    crs_mapping,
    db,
    document_refs,
    extract,
    fts_index,
    ingest,
    page_ledger,
    reading_state,
    review_audit,
    schemas,
    states,
    word_pictures,
)
from app.config import settings
from tests import docx_builder as d
from tests.fake_tokenizer import install_if_missing

NOW = "2026-11-02T00:00:00Z"
LONG = "shall be hydrostatically tested at one and a half times the design pressure."
PIC_NS = (
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)
APP_NS = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
MARK = "<w:r><w:lastRenderedPageBreak/></w:r>"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "reading.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(settings, "docx_input_enabled", True)
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    monkeypatch.setattr(settings, "word_page_markers_enabled", True)
    install_if_missing(monkeypatch)
    db.reset_connection()
    db.init_db()
    fts_index.ensure_schema()
    yield
    db.reset_connection()


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(out, "PNG")
    return out.getvalue()


def _drawing() -> str:
    return (
        f'<w:r><w:drawing {PIC_NS}><a:graphic><a:graphicData><a:blip r:embed="rId1"/>'
        "</a:graphicData></a:graphic></w:drawing></w:r>"
    )


def _word_file(tmp_path, *, pictures: int = 1, blank_page: bool = False, name="w.docx"):
    """Two or three real pages, with `pictures` pictures on page 1."""
    body = f"<w:p>{d.run('One ' + LONG)}{_drawing() * pictures}</w:p>"
    pages = 2
    if blank_page:
        body += f'<w:p>{MARK}<w:r><w:br w:type="page"/></w:r></w:p>'
        pages = 3
    body += f"<w:p>{MARK}{d.run('Two ' + LONG)}</w:p>"
    rels = (
        '<?xml version="1.0"?><Relationships><Relationship Id="rId1" Type="image" '
        'Target="media/a.png"/></Relationships>'
    )
    app = f'<?xml version="1.0"?><Properties xmlns="{APP_NS}"><Pages>{pages}</Pages></Properties>'
    path = d.build(
        tmp_path / name,
        body,
        extra={"word/_rels/document.xml.rels": rels, "docProps/app.xml": app},
    )
    with zipfile.ZipFile(path, "a") as zf:
        zf.writestr("word/media/a.png", _png())
    return path


def _pdf_file(tmp_path, *, name="p.pdf", picture: bool = False):
    doc = pymupdf.open()
    for number in range(2):
        page = doc.new_page()
        for line in range(30):
            page.insert_text(
                (40, 170 + 18 * line), f"{number}.{line} The vessel {LONG}", fontsize=9
            )
        if picture and number == 0:
            page.insert_image(pymupdf.Rect(72, 100, 120, 148), stream=_png())
    path = tmp_path / name
    doc.save(path)
    doc.close()
    return path


def _stub(monkeypatch, answers: dict):
    def recognise(items):
        out = []
        for no, _image in items:
            answer = answers.get(no, "")
            if isinstance(answer, Exception):
                out.append((no, "", None, 0.0, f"failed: {type(answer).__name__}"))
            else:
                out.append((no, answer, 0.9, 0.1, None))
        return out

    monkeypatch.setattr(word_pictures, "_recognise", recognise)


def _ingest(path, doc_id="doc1") -> str:
    """The production stages, then vectors set directly: no embedding model here."""
    import hashlib

    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,uploaded_at)"
            " VALUES (?,?,?,?,?,'extracting',?)",
            (doc_id, path.name, sha, path.stat().st_size, str(path), NOW),
        )
        conn.execute(
            "INSERT INTO jobs (id,document_id,stage,state,started_at,updated_at)"
            " VALUES (?,?,'extract','running',?,?)",
            (f"j{doc_id}", doc_id, NOW, NOW),
        )
    extract.extract_document(doc_id)
    chunker.chunk_document(doc_id)
    fts_index.index_document(
        doc_id,
        advance_to=states.PARTIALLY_SEARCHABLE,
        expect_status=states.INDEXING_KEYWORD,
    )
    return doc_id


def _finish(monkeypatch, doc_id: str) -> str:
    """`_finish_if_embedded` with every retrievable chunk holding a vector."""
    worker = ingest.IngestionWorker()
    for hook in (
        "_queue_extraction_if_standard",
        "_classify_equipment_type_if_contractor_submittal",
        "_classify_metadata_if_contractor_submittal",
        "_extract_facts_if_contractor_submittal",
    ):
        monkeypatch.setattr(ingest, hook, lambda _doc: None)
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO chunk_vectors (chunk_id, document_id, dim, vector, model, created_at)"
            " SELECT id, document_id, 1, x'00000000', ?, ? FROM chunks WHERE document_id = ? AND retrievable = 1",
            (ingest.embedding_tag(), NOW, doc_id),
        )
    worker._finish_if_embedded(doc_id)
    return conn.execute(
        "SELECT status FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()[0]


# ------------------------------------------------------------------ each case


def test_all_read_is_ready_and_fully_read_with_its_denominator(tmp_path, monkeypatch):
    _stub(monkeypatch, {1: "Tank label"})
    doc = _ingest(_word_file(tmp_path))
    assert _finish(monkeypatch, doc) == states.READY
    got = reading_state.stored(doc)
    assert got["fully_read"] is True
    assert (got["pages_read"], got["pages_total"]) == (2, 2)
    assert (got["pictures_read"], got["pictures_total"]) == (1, 1)
    assert got["line"] == "Read 2 of 2 pages, 1 of 1 pictures; 0 not read, listed"


def test_a_picture_absent_from_the_ledger_is_not_ready_and_the_status_says_so(
    tmp_path, monkeypatch
):
    _stub(monkeypatch, {1: "Tank label"})
    doc = _ingest(_word_file(tmp_path))
    with db.connect() as conn:
        conn.execute("DELETE FROM word_picture_readings")
    assert _finish(monkeypatch, doc) == states.PARTIALLY_SEARCHABLE
    got = reading_state.stored(doc)
    assert got["ready"] is False
    assert got["unaccounted"] == 1
    assert got["unaccounted_list"][0]["reason"] == reading_state.WHY_NO_ANSWER
    assert "not ready: 1 not accounted for (page 1)" in got["line"]


def test_a_page_absent_from_the_ledger_is_not_ready(tmp_path, monkeypatch):
    _stub(monkeypatch, {1: "Tank label"})
    doc = _ingest(_word_file(tmp_path))
    monkeypatch.setattr(
        page_ledger, "refresh", lambda *_a, **_k: 0
    )  # the ledger never written
    assert _finish(monkeypatch, doc) == states.PARTIALLY_SEARCHABLE
    got = reading_state.stored(doc)
    assert got["unaccounted"] >= 2
    assert {i["reason"] for i in got["unaccounted_list"] if i["kind"] == "page"} == {
        reading_state.WHY_NO_LEDGER_ROW
    }


def test_one_listed_unread_is_ready_but_never_fully_read(tmp_path, monkeypatch):
    """A picture with no text in it answered: accounted for, and a gap."""
    _stub(monkeypatch, {1: "Tank label", 2: ""})
    doc = _ingest(_word_file(tmp_path, pictures=2))
    assert _finish(monkeypatch, doc) == states.READY
    got = reading_state.stored(doc)
    assert got["ready"] is True
    assert got["fully_read"] is False
    assert (got["pictures_read"], got["pictures_total"]) == (1, 2)
    item = next(i for i in got["not_read"] if i["kind"] == "picture")
    assert (item["page"], item["reason"]) == (1, word_pictures.WHY_NO_TEXT)
    assert got["line"].endswith("1 not read, listed")


def test_a_picture_the_engine_cannot_open_is_listed_with_page_and_reason(
    tmp_path, monkeypatch
):
    path = _word_file(tmp_path)
    data = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        parts = {n: zf.read(n) for n in zf.namelist()}
    parts["word/media/a.png"] = b"not an image"
    with zipfile.ZipFile(path, "w") as zf:
        for name, value in parts.items():
            zf.writestr(name, value)
    _stub(monkeypatch, {})
    doc = _ingest(path)
    assert _finish(monkeypatch, doc) == states.READY
    item = reading_state.stored(doc)["not_read"][0]
    assert (item["kind"], item["page"]) == ("picture", 1)
    assert "cannot be opened" in item["reason"]


def test_one_failed_ocr_is_listed_and_a_re_read_can_still_answer(tmp_path, monkeypatch):
    _stub(monkeypatch, {1: RuntimeError("engine")})
    doc = _ingest(_word_file(tmp_path))
    assert _finish(monkeypatch, doc) == states.READY
    got = reading_state.stored(doc)
    assert got["fully_read"] is False
    assert got["not_read"][0]["reason"] == "failed: RuntimeError"


def test_a_page_with_no_text_is_listed_and_counted_as_not_read(tmp_path, monkeypatch):
    _stub(monkeypatch, {1: "Tank label"})
    doc = _ingest(_word_file(tmp_path, blank_page=True))
    assert _finish(monkeypatch, doc) == states.READY
    got = reading_state.stored(doc)
    assert (got["pages_read"], got["pages_total"]) == (2, 3)
    assert [(i["kind"], i["page"]) for i in got["not_read"]] == [("page", 2)]
    assert got["fully_read"] is False


def test_recognition_still_pending_is_not_accounted_for():
    row = {
        "native_status": "needs_ocr",
        "ocr_status": "pending",
        "index_status": "not_chunked",
        "index_reason": None,
        "ocr_mean_conf": None,
        "facts_reason": None,
    }
    got = reading_state.assess(1, [{**row, "page_no": 1}], [], 0, True)
    assert got["ready"] is False
    assert got["unaccounted_list"][0]["reason"] == reading_state.WHY_RECOGNITION_PENDING


def test_vectors_still_have_to_be_complete():
    row = {
        "native_status": "text",
        "ocr_status": "not_required",
        "index_status": "retrievable",
        "index_reason": None,
        "ocr_mean_conf": None,
        "facts_reason": None,
        "page_no": 1,
    }
    assert reading_state.assess(1, [row], [], 0, False)["ready"] is False
    assert reading_state.assess(1, [row], [], 0, True)["fully_read"] is True


def test_recognition_that_read_nothing_is_not_read():
    row = {
        "native_status": "empty",
        "ocr_status": "done",
        "index_status": "retrievable",
        "index_reason": None,
        "ocr_mean_conf": None,
        "facts_reason": None,
        "page_no": 1,
    }
    got = reading_state.assess(1, [row], [], 0, True)
    assert got["pages_read"] == 0 and got["not_read_listed"] == 1


def test_pictures_not_counted_are_unaccounted_never_zero():
    row = {
        "native_status": "text",
        "ocr_status": "not_required",
        "index_status": "retrievable",
        "index_reason": None,
        "ocr_mean_conf": None,
        "facts_reason": None,
        "page_no": 1,
    }
    got = reading_state.assess(1, [row], None, 0, True)
    assert got["ready"] is False
    assert got["pictures_total"] is None
    assert "pictures not counted" in got["line"]


def test_headers_and_footers_are_one_listed_line_outside_the_denominator():
    row = {
        "native_status": "text",
        "ocr_status": "not_required",
        "index_status": "retrievable",
        "index_reason": None,
        "ocr_mean_conf": None,
        "facts_reason": None,
        "page_no": 1,
    }
    got = reading_state.assess(1, [row], [], 7, True)
    assert got["ready"] is True
    assert got["fully_read"] is False
    assert got["pictures_total"] == 0
    assert got["not_read_listed"] == 7
    assert [i["reason"] for i in got["not_read"]] == [reading_state.WHY_FURNITURE]


# ------------------------------------------------------------------ every kind, one function


def test_a_pdf_goes_through_the_same_function(tmp_path, monkeypatch):
    doc = _ingest(_pdf_file(tmp_path), "pdf1")
    assert _finish(monkeypatch, doc) == states.READY
    got = reading_state.stored(doc)
    assert (got["pages_read"], got["pages_total"]) == (2, 2)
    assert got["pictures_total"] == 0
    assert got["fully_read"] is True


def test_a_pdf_picture_on_a_text_page_is_listed_as_a_page(tmp_path, monkeypatch):
    doc = _ingest(_pdf_file(tmp_path, picture=True), "pdf2")
    assert _finish(monkeypatch, doc) == states.READY
    got = reading_state.stored(doc)
    assert got["picture_unit"] == reading_state.UNIT_PAGE
    assert (got["pictures_read"], got["pictures_total"]) == (0, 1)
    item = got["not_read"][0]
    assert (item["page"], item["reason"]) == (1, reading_state.WHY_PDF_NOT_RECOGNISED)
    assert "0 of 1 pages holding pictures recognised" in got["line"]


def test_a_workbook_picture_is_listed_and_an_image_stands_with_its_page(tmp_path):
    book = tmp_path / "b.xlsx"
    with zipfile.ZipFile(book, "w") as zf:
        zf.writestr("xl/workbook.xml", "<workbook/>")
        zf.writestr(
            "xl/drawings/drawing1.xml", "<x><xdr:pic></xdr:pic><xdr:pic></xdr:pic></x>"
        )
    pictures = reading_state._sheet_pictures(str(book))["items"]
    assert [(p["state"], p["count"]) for p in pictures] == [
        (reading_state.STATE_LISTED, 2)
    ]
    assert reading_state._on_page(None, 1)["state"] == reading_state.STATE_UNACCOUNTED


def test_a_missing_file_is_unaccounted_not_zero_pictures(tmp_path, monkeypatch):
    _stub(monkeypatch, {1: "Tank label"})
    path = _word_file(tmp_path)
    doc = _ingest(path)
    path.unlink()
    assert _finish(monkeypatch, doc) == states.PARTIALLY_SEARCHABLE
    assert reading_state.stored(doc)["pictures_total"] is None


def test_with_the_word_switch_off_a_word_picture_is_unaccounted(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "word_page_markers_enabled", False)
    doc = _ingest(_word_file(tmp_path))
    assert _finish(monkeypatch, doc) == states.PARTIALLY_SEARCHABLE
    item = reading_state.stored(doc)["unaccounted_list"][0]
    assert item["reason"] == reading_state.WHY_WORD_NOT_COUNTED


# ------------------------------------------------------------------ what a held document does


def test_a_held_document_is_not_reclaimed_and_its_jobs_are_done(tmp_path, monkeypatch):
    _stub(monkeypatch, {1: "x"})
    doc = _ingest(_word_file(tmp_path))
    with db.connect() as conn:
        conn.execute("DELETE FROM word_picture_readings")
    _finish(monkeypatch, doc)
    conn = db.connect()
    assert conn.execute(
        "SELECT indexed_at FROM documents WHERE id = ?", (doc,)
    ).fetchone()[0]
    assert (
        conn.execute("SELECT state FROM jobs WHERE document_id = ?", (doc,)).fetchone()[
            0
        ]
        == "done"
    )
    assert ingest.IngestionWorker()._next_document() is None


def test_a_held_document_stays_searchable_and_its_hooks_still_run(
    tmp_path, monkeypatch
):
    _stub(monkeypatch, {1: "x"})
    doc = _ingest(_word_file(tmp_path))
    with db.connect() as conn:
        conn.execute("DELETE FROM word_picture_readings")
    ran = []
    assert _finish(monkeypatch, doc) == states.PARTIALLY_SEARCHABLE
    assert states.PARTIALLY_SEARCHABLE in states.ANSWERABLE_STATES
    assert reading_state.hooks_may_run(doc, states.PARTIALLY_SEARCHABLE) is True
    monkeypatch.setattr(
        ingest, "_queue_extraction_if_standard", lambda d: ran.append(d)
    )
    monkeypatch.setattr(ingest, "_refresh_page_ledger", lambda d: None)
    monkeypatch.setattr(
        ingest.sheet_chunks,
        "status_after_role",
        lambda d: {"status": states.PARTIALLY_SEARCHABLE},
    )
    monkeypatch.setattr(ingest.claude_auto_approve, "on_upload", lambda d: None)
    ingest.on_role_changed(doc)
    assert ran == [doc]


def test_a_document_merely_still_embedding_runs_no_hooks(tmp_path, monkeypatch):
    doc = _ingest(_pdf_file(tmp_path), "pdf3")
    assert reading_state.hooks_may_run(doc, states.PARTIALLY_SEARCHABLE) is False


def test_the_summary_refusal_says_what_is_missing_not_still_processing(
    tmp_path, monkeypatch
):
    _stub(monkeypatch, {1: "x"})
    doc = _ingest(_word_file(tmp_path))
    with db.connect() as conn:
        conn.execute("DELETE FROM word_picture_readings")
    _finish(monkeypatch, doc)
    words = reading_state.not_ready_words([{"document_id": doc}])
    assert "not ready: 1 not accounted for" in words
    assert (
        reading_state.not_ready_words([{"document_id": "other"}])
        == reading_state.STILL_PROCESSING
    )


def test_the_record_ledger_and_crs_state_the_count(tmp_path, monkeypatch):
    _stub(monkeypatch, {1: "x"})
    doc = _ingest(_word_file(tmp_path))
    _finish(monkeypatch, doc)
    line = "Read 2 of 2 pages, 1 of 1 pictures; 0 not read, listed"
    assert reading_state.readable(access.unrestricted_scope())[doc]["line"] == line
    assert page_ledger.coverage(doc)["reading"]["line"] == line
    notes = crs_mapping.build_review_notes([{"document_id": doc}], [])
    assert any(n["note"] == reading_state.NOTE and line in n["detail"] for n in notes)


def test_deleting_the_document_deletes_its_stored_decision(tmp_path, monkeypatch):
    _stub(monkeypatch, {1: "x"})
    doc = _ingest(_word_file(tmp_path))
    _finish(monkeypatch, doc)
    assert ("document_reading", "document_id") in document_refs.REGISTRY
    conn = db.connect()
    with conn:
        conn.execute("DELETE FROM documents WHERE id = ?", (doc,))
    assert conn.execute("SELECT COUNT(*) FROM document_reading").fetchone()[0] == 0


# ------------------------------------------------------------------ the audit reads the same count


def test_the_audit_counts_pictures_that_returned_text_as_ready_does(
    tmp_path, monkeypatch
):
    """A Word picture's text goes on its page, so the old page count said 0."""
    _stub(monkeypatch, {1: "Tank label", 2: ""})
    doc = _ingest(_word_file(tmp_path, pictures=2))
    _finish(monkeypatch, doc)
    section = review_audit._pages_section(doc)
    got = reading_state.decide(doc)
    assert (
        (section["read_picture"], section["pictures_total"])
        == (got["pictures_read"], got["pictures_total"])
        == (1, 2)
    )
    assert "read (picture): 1 of 2 pictures" in "\n".join(
        review_audit._md_pages({"pages": section})
    )


def test_with_only_the_word_switch_on_the_audit_counts_the_same(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "one_checked_definition_enabled", False)
    _stub(monkeypatch, {1: "Tank label"})
    doc = _ingest(_word_file(tmp_path))
    _finish(monkeypatch, doc)
    section = review_audit._pages_section(doc)
    assert (section["read_picture"], section["pictures_total"]) == (1, 1)


def test_both_switches_off_the_audit_keeps_its_page_count(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "one_checked_definition_enabled", False)
    monkeypatch.setattr(settings, "word_page_markers_enabled", False)
    doc = _ingest(_word_file(tmp_path))
    _finish(monkeypatch, doc)
    section = review_audit._pages_section(doc)
    assert section["read_picture"] == 0
    assert "pictures_total" not in section
    assert "pictures" not in "\n".join(review_audit._md_pages({"pages": section}))


# ------------------------------------------------------------------ second review


def _row(page: int = 1, **more) -> dict:
    return {
        "page_no": page,
        "native_status": "text",
        "ocr_status": "not_required",
        "index_status": "retrievable",
        "index_reason": None,
        "ocr_mean_conf": None,
        "facts_reason": None,
        "ocr_reason": None,
        **more,
    }


def test_one_ocr_box_never_says_each_picture_on_a_pdf_page_was_read(
    tmp_path, monkeypatch
):
    """Four pictures on one page, one box of text: the page was recognised, and that is
    all that is known. So the count is in pages, and the audit does not call them pictures."""
    doc_file = pymupdf.open()
    page = doc_file.new_page()
    for line in range(30):
        page.insert_text((40, 170 + 18 * line), f"{line} The vessel {LONG}", fontsize=9)
    for x in range(4):
        out = io.BytesIO()
        Image.new("RGB", (8 + x, 8), "white").save(out, "PNG")
        page.insert_image(
            pymupdf.Rect(40 + 60 * x, 40, 90 + 60 * x, 90), stream=out.getvalue()
        )
    path = tmp_path / "four.pdf"
    doc_file.save(path)
    doc_file.close()
    doc = _ingest(path, "pdf4")
    conn = db.connect()
    values = {
        "document_id": doc,
        "page_no": 1,
        "text": "one box",
        "char_count": 7,
        "mean_conf": 0.9,
        "min_conf": 0.9,
        "box_count": 1,
        "engine": "stub",
        "model": "stub",
        "dpi": 150,
    }
    for col in conn.execute("PRAGMA table_info('page_ocr')"):
        if col["notnull"] and col["dflt_value"] is None:
            values.setdefault(col["name"], 0)
    with conn:
        conn.execute(
            f"INSERT INTO page_ocr ({','.join(values)}) VALUES ({','.join('?' * len(values))})",
            tuple(values.values()),
        )
    page_ledger.refresh(doc)
    got = reading_state.decide(doc)
    assert got["picture_unit"] == reading_state.UNIT_PAGE
    assert (got["pictures_read"], got["pictures_total"]) == (1, 1)
    assert "1 of 1 pages holding pictures recognised" in got["line"]
    assert " pictures;" not in got["line"]
    assert reading_state.picture_counts(doc) is None


def test_no_page_count_and_no_ledger_rows_is_held_and_says_why():
    got = reading_state.assess(None, [], [], 0, True)
    assert got["ready"] is False and got["fully_read"] is False
    assert got["pages_total"] is None
    assert "0 of 0 pages" not in got["line"]
    assert "pages not counted" in got["line"]
    assert reading_state.WHY_NO_PAGES in got["line"]


def test_no_marks_word_says_reading_parts_never_pages(tmp_path, monkeypatch):
    path = d.build(
        tmp_path / "parts.docx",
        d.para("Scope", style="Heading1") + d.para("One " + LONG),
    )
    doc = _ingest(path)
    _finish(monkeypatch, doc)
    line = reading_state.stored(doc)["line"]
    assert "reading parts" in line and "no page numbers" in line
    assert " pages," not in line


def test_partial_marks_say_their_reach_against_words_own_count():
    got = reading_state.assess(
        1, [_row()], [], 0, True, page_source="partial", word_saved_pages=69
    )
    assert got["line"].startswith(
        "Read 1 of the 1 pages its page marks reach (Word saved 69)"
    )
    got = reading_state.assess(1, [_row()], [], 0, True, page_source="partial")
    assert "Word saved no count" in got["line"]


def test_the_held_line_gives_the_reason_and_the_route_keeps_it(tmp_path, monkeypatch):
    _stub(monkeypatch, {1: "x"})
    doc = _ingest(_word_file(tmp_path))
    with db.connect() as conn:
        conn.execute("DELETE FROM word_picture_readings")
    _finish(monkeypatch, doc)
    got = reading_state.readable(access.unrestricted_scope())[doc]
    assert got["line"].endswith(
        f"{reading_state.WHY_NO_ANSWER}. {reading_state.WAY_FORWARD_REREAD}"
    )
    assert got["unaccounted_list"][0]["reason"] == reading_state.WHY_NO_ANSWER


def test_the_word_switch_dependency_is_on_the_screen(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "word_page_markers_enabled", False)
    doc = _ingest(_word_file(tmp_path))
    _finish(monkeypatch, doc)
    assert (
        "WORD_PAGE_MARKERS_ENABLED"
        in reading_state.readable(access.unrestricted_scope())[doc]["line"]
    )


def test_the_route_only_narrows_what_a_caller_may_read(tmp_path, monkeypatch):
    _stub(monkeypatch, {1: "x"})
    doc = _ingest(_word_file(tmp_path))
    _finish(monkeypatch, doc)
    scope = access.AccessScope(user_id="u", allowed_document_ids=frozenset({"other"}))
    assert reading_state.readable(scope) == {}
    scope = access.AccessScope(user_id="u", allowed_document_ids=frozenset({doc}))
    assert set(reading_state.readable(scope)) == {doc}


def test_a_guess_when_body_gaps_are_listed_and_not_for_a_header_alone():
    listed = reading_state.assess(
        1, [_row()], [{"state": "listed", "page": 1, "reason": "x"}], 7, True
    )
    assert listed["body_gaps"] == 1 and listed["not_read_listed"] == 8
    alone = reading_state.assess(1, [_row()], [], 7, True)
    assert alone["body_gaps"] == 0


def test_not_found_is_said_as_a_guess_with_the_count(monkeypatch):
    monkeypatch.setattr(reading_state, "stored", lambda _doc: {"body_gaps": 3})
    assert reading_state.not_found_words("d", "not found") == (
        "not found (a guess: 3 pages or pictures of the body are listed as not read, and it may be in one of them)"
    )
    monkeypatch.setattr(reading_state, "stored", lambda _doc: {"body_gaps": 0})
    assert reading_state.not_found_words("d", "not found") == "not found"


def test_not_found_keeps_its_words_with_the_switch_off_whatever_is_stored(monkeypatch):
    monkeypatch.setattr(settings, "one_checked_definition_enabled", False)
    monkeypatch.setattr(reading_state, "stored", lambda _doc: {"body_gaps": 3})
    assert reading_state.not_found_words("d", "not found") == "not found"


# ------------------------------------------------------------------ rollback


def _held(tmp_path, monkeypatch) -> str:
    _stub(monkeypatch, {1: "x"})
    doc = _ingest(_word_file(tmp_path))
    with db.connect() as conn:
        conn.execute("DELETE FROM word_picture_readings")
    assert _finish(monkeypatch, doc) == states.PARTIALLY_SEARCHABLE
    return doc


def test_rollback_with_the_switch_off_a_held_document_goes_to_ready_at_server_start(
    tmp_path, monkeypatch
):
    doc = _held(tmp_path, monkeypatch)
    ran = []
    monkeypatch.setattr(ingest, "_worker", None)
    monkeypatch.setattr(
        ingest.IngestionWorker, "start", lambda self: ran.append("started")
    )
    monkeypatch.setattr(settings, "one_checked_definition_enabled", False)
    ingest.start_worker()
    conn = db.connect()
    row = conn.execute(
        "SELECT status, indexed_at FROM documents WHERE id = ?", (doc,)
    ).fetchone()
    assert (row["status"], bool(row["indexed_at"])) == (states.READY, True)
    assert ran == ["started"]
    assert conn.execute("SELECT COUNT(*) FROM document_reading").fetchone()[0] == 0
    assert reading_state.release_held() == 0


def test_rollback_with_the_switch_on_nothing_is_released(tmp_path, monkeypatch):
    doc = _held(tmp_path, monkeypatch)
    assert reading_state.release_held() == 0
    status = (
        db.connect()
        .execute("SELECT status FROM documents WHERE id = ?", (doc,))
        .fetchone()[0]
    )
    assert status == states.PARTIALLY_SEARCHABLE


def test_rollback_leaves_a_document_still_embedding_alone(tmp_path, monkeypatch):
    held = _held(tmp_path, monkeypatch)
    pdf = _ingest(_pdf_file(tmp_path), "still")
    with db.connect() as conn:
        conn.execute(
            "UPDATE documents SET embedded_count = 0, chunk_count = 3, indexed_at = ? WHERE id = ?",
            (NOW, pdf),
        )
        conn.execute(
            "INSERT INTO document_reading (document_id, summary, decided_at)"
            " SELECT ?, summary, decided_at FROM document_reading WHERE document_id = ?",
            (pdf, held),
        )
    monkeypatch.setattr(settings, "one_checked_definition_enabled", False)
    assert reading_state.release_held() == 1
    conn = db.connect()
    assert (
        conn.execute("SELECT status FROM documents WHERE id = ?", (pdf,)).fetchone()[0]
        == states.PARTIALLY_SEARCHABLE
    )
    assert (
        conn.execute("SELECT status FROM documents WHERE id = ?", (held,)).fetchone()[0]
        == states.READY
    )


def _finished_partial(tmp_path, doc_id: str, *, chunks: int = 3) -> str:
    """Partially searchable, every vector there and indexed: what a held document looks like."""
    doc = _ingest(_pdf_file(tmp_path, name=f"{doc_id}.pdf"), doc_id)
    with db.connect() as conn:
        conn.execute(
            "UPDATE documents SET chunk_count = ?, embedded_count = ?, indexed_at = ? WHERE id = ?",
            (chunks, chunks, NOW, doc),
        )
    return doc


def _store_row(doc: str, unaccounted: int) -> None:
    conn = db.connect()
    reading_state._ensure_table(conn)
    with conn:
        conn.execute(
            "INSERT INTO document_reading (document_id, summary, decided_at) VALUES (?,?,?)",
            (
                doc,
                json.dumps({"unaccounted": unaccounted, "ready": unaccounted == 0}),
                NOW,
            ),
        )


def _status(doc: str) -> str:
    return (
        db.connect()
        .execute("SELECT status FROM documents WHERE id = ?", (doc,))
        .fetchone()[0]
    )


def test_rollback_leaves_an_older_document_with_no_decision_alone(
    tmp_path, monkeypatch
):
    held = _held(tmp_path, monkeypatch)
    older = _finished_partial(tmp_path, "older")
    monkeypatch.setattr(settings, "one_checked_definition_enabled", False)
    assert reading_state.release_held() == 1
    assert _status(held) == states.READY
    assert _status(older) == states.PARTIALLY_SEARCHABLE


def test_rollback_needs_a_stored_decision_saying_something_is_unaccounted(
    tmp_path, monkeypatch
):
    doc = _finished_partial(tmp_path, "saidready")
    _store_row(doc, 0)
    monkeypatch.setattr(settings, "one_checked_definition_enabled", False)
    assert reading_state.release_held() == 0
    assert _status(doc) == states.PARTIALLY_SEARCHABLE


def test_rollback_leaves_a_document_with_no_chunks_alone(tmp_path, monkeypatch):
    doc = _finished_partial(tmp_path, "nochunks", chunks=0)
    _store_row(doc, 1)
    monkeypatch.setattr(settings, "one_checked_definition_enabled", False)
    assert reading_state.release_held() == 0
    assert _status(doc) == states.PARTIALLY_SEARCHABLE


def test_a_failed_release_never_stops_the_worker_starting(monkeypatch):
    ran = []

    def broken():
        raise OSError("no database")

    monkeypatch.setattr(ingest, "_worker", None)
    monkeypatch.setattr(
        ingest.IngestionWorker, "start", lambda self: ran.append("started")
    )
    monkeypatch.setattr(settings, "one_checked_definition_enabled", False)
    monkeypatch.setattr(reading_state, "connect", broken)
    ingest.start_worker()
    assert ran == ["started"]


def test_rollback_with_nothing_ever_held_writes_nothing(monkeypatch):
    monkeypatch.setattr(settings, "one_checked_definition_enabled", False)
    assert reading_state.release_held() == 0
    assert (
        not db.connect()
        .execute("SELECT 1 FROM sqlite_master WHERE name = 'document_reading'")
        .fetchone()
    )


def test_the_schema_is_not_changed_by_this_work():
    assert "extra" not in schemas.Document.model_config
    assert "reading" not in schemas.Document.model_fields


# ------------------------------------------------------------------ switch off


def test_switch_off_nothing_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "one_checked_definition_enabled", False)
    monkeypatch.setattr(settings, "word_page_markers_enabled", False)
    doc = _ingest(_word_file(tmp_path))
    assert (
        _finish(monkeypatch, doc) == states.READY
    )  # the picture nobody read, as today
    conn = db.connect()
    assert not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'document_reading'"
    ).fetchone()
    assert reading_state.decide(doc) is None
    assert reading_state.stored(doc) is None
    assert reading_state.readable(access.unrestricted_scope()) == {}
    assert "reading" not in page_ledger.coverage(doc)
    assert crs_mapping.build_review_notes([{"document_id": doc}], []) == []
    assert reading_state.finish_status(doc) == states.READY
    assert reading_state.hooks_may_run(doc, states.PARTIALLY_SEARCHABLE) is False
