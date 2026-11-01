"""#525 slice 2 (INTAKE_IMAGES_XLSX_ENABLED, with ONE_INTAKE_ENABLED): the
upload accepts PNG / JPEG / TIFF images and reads them like a scanned PDF page,
and an .xlsx upload is indexed, each chunk cited by sheet and cell range.
Either switch off: exactly as before. INVENTED files, generated here.
"""

from __future__ import annotations

import io
from pathlib import Path

import openpyxl
import pymupdf
import pytest
from PIL import Image

from app import (
    access,
    chunker,
    db,
    extract,
    intake,
    page_ledger,
    sheet_chunks,
    states,
    stored_paths,
    upload,
)
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "w5b525s2.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(settings, "datasheet_office_input", False)
    monkeypatch.setattr(settings, "one_intake_enabled", True)
    monkeypatch.setattr(settings, "intake_images_xlsx_enabled", True)
    db.reset_connection()
    db.init_db()
    yield


def _image(fmt: str, size=(300, 200), frames: int = 1) -> bytes:
    buf = io.BytesIO()
    pics = [Image.new("RGB", size, (255, 255 - 40 * i, 255)) for i in range(frames)]
    if frames > 1:
        pics[0].save(buf, fmt, save_all=True, append_images=pics[1:])
    else:
        pics[0].save(buf, fmt)
    return buf.getvalue()


def _workbook() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Line list"
    ws["B3"] = "Line number"
    ws["C3"] = "Design pressure"
    ws["D3"] = "Unit"
    ws.append([None, "L-101", 12, "barg"])
    ws.append([None, "L-102", 15, "barg"])
    wb.create_sheet("Blank")
    wb.create_sheet("Secret").sheet_state = "hidden"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _ingest(data: bytes, name: str):
    return upload.ingest(io.BytesIO(data), name)


def _stored(row) -> Path:
    return Path(stored_paths.local(row["stored_path"]))


# ------------------------------------------------------------------ switch off


def test_switch_defaults_off():
    from app.config import Settings

    assert Settings.model_fields["intake_images_xlsx_enabled"].default is False


@pytest.mark.parametrize(
    "one_intake,slice2", [(False, False), (True, False), (False, True)]
)
@pytest.mark.parametrize(
    "fmt,name", [("PNG", "a.png"), ("JPEG", "a.jpg"), ("TIFF", "a.tif")]
)
def test_either_switch_off_an_image_is_refused_as_today(
    monkeypatch, one_intake, slice2, fmt, name
):
    monkeypatch.setattr(settings, "one_intake_enabled", one_intake)
    monkeypatch.setattr(settings, "intake_images_xlsx_enabled", slice2)
    with pytest.raises(upload.UploadError) as exc:
        _ingest(_image(fmt), name)
    assert exc.value.code == "not_pdf"
    assert not any(settings.upload_dir.iterdir())


@pytest.mark.parametrize(
    "one_intake,slice2", [(False, False), (True, False), (False, True)]
)
def test_either_switch_off_a_workbook_is_stored_not_indexed_as_today(
    monkeypatch, one_intake, slice2
):
    monkeypatch.setattr(settings, "one_intake_enabled", one_intake)
    monkeypatch.setattr(settings, "intake_images_xlsx_enabled", slice2)
    row, job_id, _dup = _ingest(_workbook(), "lines.xlsx")
    assert row["status"] == states.STORED_NOT_INDEXED and job_id is None


# ------------------------------------------------------------------- images


@pytest.mark.parametrize(
    "fmt,name,suffix",
    [
        ("PNG", "scan.png", ".png"),
        ("JPEG", "scan.jpg", ".jpg"),
        ("TIFF", "scan.tiff", ".tif"),
    ],
)
def test_an_image_is_accepted_queued_and_its_original_kept(fmt, name, suffix):
    data = _image(fmt)
    row, job_id, dup = _ingest(data, name)
    assert dup is None and job_id and row["status"] == states.QUEUED
    assert row["filename"].endswith(suffix)
    original = settings.upload_dir / f"{row['sha256']}{suffix}"
    assert original.read_bytes() == data  # the upload itself is never rewritten
    read = _stored(row)
    assert read == original.with_name(original.name + ".pdf")
    with pymupdf.open(read) as pdf:
        assert pdf.page_count == 1
        page = pdf[0]
        assert page.get_text().strip() == ""  # a picture, no text layer
        scale = 72.0 / settings.ocr_dpi
        assert page.rect.width == pytest.approx(300 * scale)
        assert page.rect.height == pytest.approx(200 * scale)


def test_every_page_of_a_multi_page_tiff_becomes_a_page():
    row, _job, _dup = _ingest(_image("TIFF", frames=3), "three.tif")
    with pymupdf.open(_stored(row)) as pdf:
        assert pdf.page_count == 3


def test_an_image_gets_pages_and_a_page_ledger_like_a_scanned_pdf():
    row, _job, _dup = _ingest(_image("PNG", size=(1200, 1600)), "scan.png")
    extract.extract_document(row["id"])
    pages = (
        db.connect()
        .execute(
            "SELECT page_no, needs_ocr, ocr_route FROM pages WHERE document_id = ?",
            (row["id"],),
        )
        .fetchall()
    )
    assert [(p["page_no"], p["needs_ocr"]) for p in pages] == [(1, 1)]
    assert pages[0]["ocr_route"]  # the routing reason is stored, as for a scan
    page_ledger.refresh(row["id"])
    assert [r["page_no"] for r in page_ledger.rows(row["id"])] == [1]


def test_a_broken_image_is_refused_with_a_reason_and_nothing_is_stored():
    with pytest.raises(upload.UploadError) as exc:
        _ingest(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "broken.png")
    assert exc.value.code == "bad_image"
    assert not any(settings.upload_dir.iterdir())
    assert db.connect().execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


def test_an_image_over_the_pixel_limit_is_refused(monkeypatch):
    monkeypatch.setattr(intake, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(upload.UploadError) as exc:
        _ingest(_image("PNG"), "big.png")
    assert exc.value.code == "image_too_large"
    assert not any(settings.upload_dir.iterdir())


def test_a_tiff_over_the_frame_limit_is_refused_and_leaves_nothing(monkeypatch):
    monkeypatch.setattr(intake, "MAX_IMAGE_FRAMES", 2)
    with pytest.raises(upload.UploadError) as exc:
        _ingest(_image("TIFF", frames=3), "many.tif")
    assert exc.value.code == "image_too_many_frames"
    assert not any(settings.upload_dir.iterdir())


# ----------------------------------------------------------------- workbooks


def _indexed_workbook():
    row, job_id, _dup = _ingest(_workbook(), "lines.xlsx")
    assert row["status"] == states.QUEUED and job_id
    extract.extract_document(row["id"])
    chunker.chunk_document(row["id"])
    return row["id"]


def test_a_workbook_is_indexed_and_every_chunk_cites_sheet_and_cells():
    doc_id = _indexed_workbook()
    chunks = (
        db.connect()
        .execute(
            "SELECT page_start, page_end, kind, section, locator, retrievable, text FROM chunks"
            " WHERE document_id = ? ORDER BY ordinal",
            (doc_id,),
        )
        .fetchall()
    )
    assert len(chunks) == 1
    c = chunks[0]
    assert c["locator"] == "'Line list'!B3:D5"
    assert (c["page_start"], c["page_end"], c["kind"], c["section"]) == (
        1,
        1,
        "table",
        "Line list",
    )
    assert c["retrievable"] == 1
    assert "| L-101 | 12 | barg |" in c["text"] and "| L-102 | 15 | barg |" in c["text"]


def test_a_workbook_hidden_and_empty_sheets_are_reported_not_dropped():
    doc_id = _indexed_workbook()
    stored = {(r["page_no"], r["code"]) for r in intake.reasons_for(doc_id)}
    assert (0, "hidden_sheet") in stored  # the hidden sheet, named for the whole file
    assert (2, "page_not_read") in stored  # the empty sheet, with its reason
    page_ledger.refresh(doc_id)
    cov = page_ledger.coverage(doc_id)
    assert cov["intake_reasons"]["0"] == [
        "not read: hidden sheet 3 (workbook position)"
    ]
    secret = (
        db.connect()
        .execute(
            "SELECT COUNT(*) FROM chunks WHERE document_id = ? AND locator LIKE 'Secret%'",
            (doc_id,),
        )
        .fetchone()[0]
    )
    assert secret == 0


def test_a_sheet_larger_than_one_chunk_is_split_with_contiguous_ranges(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    for i in range(1, 201):
        ws.append([f"Item {i}", f"Value {i * 3}", "kPa"])
    wb.save(tmp_path / "long.xlsx")
    chunks = sheet_chunks.build_chunks(tmp_path / "long.xlsx")
    assert len(chunks) > 1
    assert all(c.tokens <= settings.chunk_max_tokens for c in chunks)
    assert chunks[0].locator.startswith("Data!A1:C")
    last = [int(c.locator.split(":C")[1]) for c in chunks]
    firsts = [int(c.locator.split("!A")[1].split(":")[0]) for c in chunks]
    assert firsts[0] == 1 and last[-1] == 200
    assert all(f == prev + 1 for f, prev in zip(firsts[1:], last[:-1]))


def test_a_row_too_long_for_one_chunk_is_windowed_and_keeps_its_cells(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Notes"
    ws["A1"] = " ".join(f"word{i}" for i in range(900))
    wb.save(tmp_path / "wide.xlsx")
    chunks = sheet_chunks.build_chunks(tmp_path / "wide.xlsx")
    assert len(chunks) > 1
    assert all(c.tokens <= settings.chunk_max_tokens for c in chunks)
    assert {c.locator for c in chunks} == {"Notes!A1"}


@pytest.mark.parametrize(
    "sheet,expected",
    [
        ("Data", "Data!A1:B2"),
        ("Line list", "'Line list'!A1:B2"),
        ("O'Brien", "'O''Brien'!A1:B2"),
        ("2024", "'2024'!A1:B2"),
    ],
)
def test_cell_range_quotes_the_sheet_name_as_excel_does(sheet, expected):
    assert sheet_chunks.cell_range(sheet, 1, 1, 2, 2) == expected


def test_switch_off_a_workbook_indexed_by_the_older_seam_is_chunked_as_before(
    monkeypatch,
):
    """DATASHEET_OFFICE_INPUT indexes a workbook already; with slice 2 off its
    chunks are built by the PDF chunker from page text, with no locator."""
    monkeypatch.setattr(settings, "intake_images_xlsx_enabled", False)
    monkeypatch.setattr(settings, "datasheet_office_input", True)
    row, _job, _dup = _ingest(_workbook(), "lines.xlsx")
    extract.extract_document(row["id"])
    chunker.chunk_document(row["id"])
    locators = {
        r[0]
        for r in db.connect().execute(
            "SELECT locator FROM chunks WHERE document_id = ?", (row["id"],)
        )
    }
    assert locators == {None}
