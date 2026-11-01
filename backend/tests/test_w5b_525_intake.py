"""W5b-01 (#525) part 1: ONE_INTAKE_ENABLED. Every file goes through
`intake.read`; PDF and Word store what they store today, Excel becomes one page
per visible sheet, an image is one page waiting for OCR, and what cannot be read
is refused or named with a reason. INVENTED files, generated here.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pymupdf
import pytest
from PIL import Image

from app import access, db, extract, intake, page_ledger, upload
from app.config import settings
from tests import docx_builder as d

SENT = "The vessel shall be hydrostatically tested at one and a half times the design pressure."


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "w5b525intake.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(settings, "docx_input_enabled", True)
    monkeypatch.setattr(settings, "datasheet_office_input", False)
    monkeypatch.setattr(settings, "one_intake_enabled", False)
    db.reset_connection()
    db.init_db()
    yield


LONG = [SENT + f" Clause {i}." for i in range(4)]


def _pdf(path, texts=("\n".join(LONG), "", "\n".join(LONG))):
    doc = pymupdf.open()
    for t in texts:
        page = doc.new_page()
        for i, line in enumerate(t.split("\n") if t else []):
            page.insert_text((72, 72 + 14 * i), line)
    doc.save(str(path))
    doc.close()
    return path


def _word(path):
    body = (
        d.para("Piping", style="Heading1")
        + d.para(SENT)
        + d.table([["Size", "Rating"], ["1", "150"], ["2", "300"]])
    )
    return d.build(path, body)


def _xlsx(path, *, hidden=True, empty=True):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["Design pressure", "12", "bar"])
    ws.append(["Design temperature", "150", "C"])
    if empty:
        wb.create_sheet("Blank")
    if hidden:
        wb.create_sheet("Secret").sheet_state = "hidden"
    wb.save(path)
    return path


def _png(path, fmt="PNG"):
    Image.new("RGB", (40, 30), "white").save(path, fmt)
    return path


def _upload(path, name):
    with Path(path).open("rb") as fh:
        row, _job, _dup = upload.ingest(fh, name)
    return row["id"]


def _pages(doc_id):
    return [
        tuple(r)
        for r in db.connect().execute(
            "SELECT page_no, text, char_count, needs_ocr, equation_heavy, batch_no, ocr_route,"
            " ocr_route_version, tables_json FROM pages WHERE document_id = ? ORDER BY page_no",
            (doc_id,),
        )
    ]


def _ledger(doc_id):
    page_ledger.refresh(doc_id)
    return [
        {k: v for k, v in dict(r).items() if k not in ("updated_at", "created_at")}
        for r in page_ledger.rows(doc_id)
    ]


def _run(path, name, switch):
    """Upload (fresh DB each time) and extract with the switch as given."""
    db.reset_connection()
    settings.db_path.unlink(missing_ok=True)
    db.init_db()
    settings.one_intake_enabled = switch
    doc_id = _upload(path, name)
    extract.extract_document(doc_id)
    pagination = (
        db.connect()
        .execute("SELECT pagination FROM documents WHERE id = ?", (doc_id,))
        .fetchone()[0]
    )
    return _pages(doc_id), _ledger(doc_id), pagination


# ------------------------------------------------------- switch off / identical


def test_switch_defaults_off():
    from app.config import Settings

    assert Settings.model_fields["one_intake_enabled"].default is False


def test_pdf_stores_the_same_pages_and_ledger_with_the_switch_on(tmp_path, monkeypatch):
    path = _pdf(tmp_path / "a.pdf")
    off = _run(path, "a.pdf", False)
    on = _run(path, "a.pdf", True)
    assert off[0] and len(off[0]) == 3
    assert on == off


def test_word_stores_the_same_pages_and_ledger_with_the_switch_on(tmp_path):
    path = _word(tmp_path / "a.docx")
    off = _run(path, "a.docx", False)
    on = _run(path, "a.docx", True)
    assert off[2] == "flow" and off[0]
    assert on == off


def test_word_with_the_datasheet_seam_is_the_same_through_intake(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "datasheet_office_input", True)
    path = _word(tmp_path / "b.docx")
    assert _run(path, "b.docx", True) == _run(path, "b.docx", False)


def test_intake_pdf_rows_equal_extract_batch(tmp_path):
    path = _pdf(tmp_path / "c.pdf")
    got = intake.as_rows(intake.read(path))
    assert got == extract.extract_batch(str(path), 1, 3)


# ----------------------------------------------------------- reasons per page


def test_blank_pdf_page_states_why_and_text_pages_do_not(tmp_path):
    result = intake.read(_pdf(tmp_path / "d.pdf"))
    assert result.not_read() == {2: intake.WHY_SCANNED}
    assert all(p.source == intake.SOURCE_NATIVE for p in result.pages)


def test_word_page_source_and_flow(tmp_path):
    result = intake.read(_word(tmp_path / "e.docx"))
    assert result.kind == intake.KIND_WORD and result.flow
    assert {p.source for p in result.pages} == {intake.SOURCE_WORD}
    assert result.not_read() == {}


# ------------------------------------------------------------------- Excel


def test_xlsx_one_page_per_visible_sheet_with_reason_for_the_empty_one(tmp_path):
    result = intake.read(_xlsx(tmp_path / "f.xlsx"))
    assert result.kind == intake.KIND_SHEET
    assert [p.source for p in result.pages] == [intake.SOURCE_SHEET] * 2
    assert "Design pressure" in result.pages[0].text and "12" in result.pages[0].text
    assert result.pages[0].tables_json and result.pages[0].not_read_reason is None
    assert result.not_read() == {2: intake.WHY_EMPTY_SHEET}
    assert any("hidden sheet 3 skipped" in n for n in result.notes)


def test_xlsx_with_no_visible_sheet_is_reported_not_silent(tmp_path):
    wb = openpyxl.Workbook()
    wb.create_sheet("Second")
    wb.active.sheet_state = "hidden"
    wb.save(tmp_path / "g.xlsx")
    result = intake.read(tmp_path / "g.xlsx")
    assert result.pages and result.pages[0].source == intake.SOURCE_SHEET
    assert any("hidden sheet 1 skipped" in n for n in result.notes)


def test_xlsx_is_indexed_by_extraction_only_when_the_switch_is_on(
    tmp_path, monkeypatch
):
    path = _xlsx(tmp_path / "h.xlsx")
    monkeypatch.setattr(
        settings, "datasheet_office_input", True
    )  # so upload indexes it
    doc_id = _upload(path, "h.xlsx")
    monkeypatch.setattr(settings, "datasheet_office_input", False)
    settings.one_intake_enabled = True
    extract.extract_document(doc_id)
    rows = _pages(doc_id)
    assert [r[0] for r in rows] == [1, 2]
    assert "Design pressure" in rows[0][1] and rows[0][3] == 0 and rows[0][8]


# ------------------------------------------------------------------- images


@pytest.mark.parametrize("fmt,name", [("PNG", "i.png"), ("JPEG", "i.jpg")])
def test_image_is_one_page_waiting_for_ocr_with_its_reason(tmp_path, fmt, name):
    result = intake.read(_png(tmp_path / name, fmt))
    assert result.kind == intake.KIND_IMAGE and len(result.pages) == 1
    page = result.pages[0]
    assert (page.source, page.needs_ocr, page.text) == (intake.SOURCE_IMAGE, True, "")
    assert page.not_read_reason == intake.WHY_IMAGE
    assert intake.as_rows(result)[0][2] is True


def test_a_broken_image_is_refused_with_a_reason(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"\x89PNG\r\n\x1a\n" + b"not really a picture")
    with pytest.raises(intake.IntakeRefused) as err:
        intake.read(bad)
    assert err.value.code == "bad_image" and err.value.message


# ------------------------------------------------------------------ refusals


@pytest.mark.parametrize(
    "content,code",
    [
        (b"just some text", "unsupported_type"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest", "unsupported_office"),
        (b"PK\x03\x04 broken", "corrupt_zip"),
    ],
)
def test_unsupported_files_are_refused_with_a_code_and_a_sentence(
    tmp_path, content, code
):
    f = tmp_path / "x.bin"
    f.write_bytes(content)
    with pytest.raises(intake.IntakeRefused) as err:
        intake.read(f)
    assert err.value.code == code and len(err.value.message) > 10


def test_pptx_and_unknown_zips_are_refused(tmp_path):
    import zipfile

    for entry, code in (
        ("ppt/presentation.xml", "unsupported_office"),
        ("a.txt", "unsupported_zip"),
    ):
        f = tmp_path / (code + entry.replace("/", "_") + ".zip")
        with zipfile.ZipFile(f, "w") as zf:
            zf.writestr(entry, "x")
        with pytest.raises(intake.IntakeRefused) as err:
            intake.read(f)
        assert err.value.code == code


def test_word_is_refused_with_a_reason_when_word_input_is_off(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "docx_input_enabled", False)
    with pytest.raises(intake.IntakeRefused) as err:
        intake.read(_word(tmp_path / "j.docx"))
    assert err.value.code == "word_not_enabled"


def test_extraction_with_the_switch_on_raises_the_refusal_not_an_empty_document(
    tmp_path,
):
    f = tmp_path / ("k" * 64 + ".pdf")
    f.write_bytes(b"plain text pretending to be a pdf")
    conn = db.connect()
    with conn:
        conn.execute(
            "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path, status,"
            " uploaded_at, priority) VALUES ('doc_k', 'k.pdf', ?, 3, ?, 'queued', 'now', 0)",
            ("k" * 64, str(f)),
        )
        conn.execute(
            "INSERT INTO jobs (id, document_id, stage, state, started_at, updated_at, priority)"
            " VALUES ('job_k', 'doc_k', 'extract', 'running', 'now', 'now', 0)"
        )
    settings.one_intake_enabled = True
    with pytest.raises(intake.IntakeRefused) as err:
        extract.extract_document("doc_k")
    assert err.value.code == "unsupported_type"
    assert _pages("doc_k") == []
