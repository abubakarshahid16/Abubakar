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


def _indexed_workbook(data=None, role="SUPPORTING_DOCUMENT"):
    """Upload a workbook, set its role (it waits for one), extract and chunk it."""
    from app import classification

    row, job_id, _dup = _ingest(data or _workbook(), "lines.xlsx")
    assert row["status"] == states.STORED_NOT_INDEXED and job_id is None
    classification.set_role(row["id"], role)
    extract.extract_document(row["id"])
    chunker.chunk_document(row["id"])
    return row["id"]


def _index_rows(doc_id):
    conn = db.connect()
    from app import fts_index

    fts_index.ensure_schema(conn)
    return tuple(
        conn.execute(
            f"SELECT COUNT(*) FROM {t} WHERE document_id = ?", (doc_id,)
        ).fetchone()[0]
        for t in ("chunks", "chunks_fts", "chunk_vectors")
    )


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
    n = len(chunks)
    assert [c.locator for c in chunks] == [
        f"Notes!A1 (part {i} of {n})" for i in range(1, n + 1)
    ]
    words = " ".join(c.text.split("\n")[1].strip("| ") for c in chunks).split()
    assert words == ws["A1"].value[:2000].split()  # the cell, cut only at its limit


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


# ------------------------------------------------- review of #1560 (round 2)


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def test_deleting_an_image_removes_the_original_and_its_pages(client):
    data = _image("PNG")
    row, _job, _dup = _ingest(data, "scan.png")
    pages = _stored(row)
    original = settings.upload_dir / f"{row['sha256']}.png"
    assert pages.exists() and original.exists()
    served = client.get(f"/api/documents/{row['id']}/original")
    assert (
        served.status_code == 200 and served.content == data
    )  # the image, not its pages
    r = client.delete(f"/api/documents/{row['id']}", params={"confirm": "true"})
    assert r.status_code == 200, r.text
    assert not pages.exists() and not original.exists()
    assert r.json()["files_removed"] >= 2


def _md_cells(ws, first_row, first_col, last_row, last_col) -> list[str]:
    lines = []
    for r in range(first_row, last_row + 1):
        cells = [ws.cell(r, c).value for c in range(first_col, last_col + 1)]
        if any(v not in (None, "") for v in cells):
            lines.append(
                "| " + " | ".join("" if v is None else str(v) for v in cells) + " |"
            )
    return lines


def test_every_chunk_of_a_padded_sheet_is_exactly_its_cited_cells(tmp_path):
    """Sparse rows over 20 columns: padded to the chunk's range, the rows used
    to overflow the budget and be windowed mid-row under the whole range."""
    from openpyxl.utils.cell import range_boundaries

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "CRS"
    for r in range(1, 33):
        ws.cell(r, (r * 7) % 20 + 1, (f"Comment {r} " + "word " * 18).strip())
    wb.save(tmp_path / "padded.xlsx")
    chunks = sheet_chunks.build_chunks(tmp_path / "padded.xlsx")
    assert len(chunks) > 1
    covered = []
    for c in chunks:
        assert c.tokens <= settings.chunk_max_tokens
        sheet, ref = c.locator.split("!")
        assert sheet == "CRS"
        min_col, min_row, max_col, max_row = range_boundaries(ref)
        title, *lines = c.text.split("\n")
        assert title == "CRS"
        assert lines == _md_cells(ws, min_row, min_col, max_row, max_col)
        covered += list(range(min_row, max_row + 1))
    assert covered == list(range(1, 33))  # every row once, in order


def test_a_huge_later_tiff_page_is_refused_before_any_page_is_decoded(
    tmp_path, monkeypatch
):
    from PIL import ImageOps

    small = Image.new("RGB", (10, 10), "white")
    big = Image.new("RGB", (100, 100), "white")
    small.save(tmp_path / "two.tif", "TIFF", save_all=True, append_images=[big])
    monkeypatch.setattr(intake, "MAX_IMAGE_PIXELS", 1000)
    decoded = []
    real = ImageOps.exif_transpose
    monkeypatch.setattr(
        ImageOps, "exif_transpose", lambda im, **kw: decoded.append(im.size) or real(im)
    )
    with pytest.raises(intake.IntakeRefused) as exc:
        intake.image_to_pdf(tmp_path / "two.tif", tmp_path / "two.pdf")
    assert exc.value.code == "image_too_large"
    assert decoded == []
    assert not (tmp_path / "two.pdf").exists()


def _template_workbook() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Comments"
    ws.append(
        [
            "Instructions: the contractor shall answer every comment below in the"
            " reply column and return this sheet with the next revision."
        ]
    )
    ws.append(["No.", "Comment", "Reply"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _fake_index(doc_id):
    """The keyword and vector rows indexing would write (no model is run)."""
    conn = db.connect()
    with conn:
        for r in conn.execute(
            "SELECT id, text FROM chunks WHERE document_id = ?", (doc_id,)
        ):
            conn.execute(
                "INSERT INTO chunks_fts (chunk_id, document_id, text) VALUES (?, ?, ?)",
                (r["id"], doc_id, r["text"]),
            )
            conn.execute(
                "INSERT INTO chunk_vectors (chunk_id, document_id, dim, vector, model,"
                " created_at) VALUES (?, ?, 1, x'00000000', 'm', 'now')",
                (r["id"], doc_id),
            )


def _status(doc_id):
    return (
        db.connect()
        .execute("SELECT status FROM documents WHERE id = ?", (doc_id,))
        .fetchone()[0]
    )


def test_a_workbook_waits_for_its_role_before_anything_is_indexed():
    from app import classification

    row, job_id, _dup = _ingest(_template_workbook(), "book.xlsx")
    assert job_id is None and _status(row["id"]) == states.STORED_NOT_INDEXED
    assert _index_rows(row["id"]) == (0, 0, 0)
    assert [r["reason"] for r in intake.reasons_for(row["id"])] == [
        sheet_chunks.WHY_WAITING
    ]
    classification.set_role(row["id"], "CONTRACTOR_SUBMITTAL")
    assert _status(row["id"]) == states.QUEUED
    job = (
        db.connect()
        .execute("SELECT stage, state FROM jobs WHERE document_id = ?", (row["id"],))
        .fetchone()
    )
    assert tuple(job) == ("extract", "running")
    extract.extract_document(row["id"])
    chunker.chunk_document(row["id"])
    assert _index_rows(row["id"])[0] > 0


def test_a_crs_template_is_never_indexed_even_when_chunking_is_forced():
    from app import classification

    row, _job, _dup = _ingest(_template_workbook(), "crs-template.xlsx")
    classification.set_role(row["id"], "CRS_TEMPLATE")
    assert _status(row["id"]) == states.STORED_NOT_INDEXED
    assert [r["reason"] for r in intake.reasons_for(row["id"])] == [
        sheet_chunks.WHY_TEMPLATE
    ]
    chunker.chunk_document(row["id"], force=True)  # even if something ran it
    assert _index_rows(row["id"]) == (0, 0, 0)
    assert _status(row["id"]) == states.STORED_NOT_INDEXED


def test_a_workbook_turned_crs_template_leaves_the_index_and_closes_its_job():
    from app import classification

    doc_id = _indexed_workbook(_template_workbook())
    _fake_index(doc_id)
    assert all(n > 0 for n in _index_rows(doc_id))
    classification.set_role(doc_id, "CRS_TEMPLATE")
    assert _index_rows(doc_id) == (0, 0, 0)  # chunks, keyword rows and vectors
    assert _status(doc_id) == states.STORED_NOT_INDEXED
    states_ = {
        r[0]
        for r in db.connect().execute(
            "SELECT state FROM jobs WHERE document_id = ?", (doc_id,)
        )
    }
    assert "running" not in states_  # no job left running for ever


def test_a_queued_workbook_turned_crs_template_has_its_running_job_closed():
    from app import classification

    row, _job, _dup = _ingest(_template_workbook(), "book.xlsx")
    classification.set_role(row["id"], "SUPPORTING_DOCUMENT")  # queued, job running
    classification.set_role(row["id"], "CRS_TEMPLATE")
    jobs = [
        tuple(r)
        for r in db.connect().execute(
            "SELECT stage, state FROM jobs WHERE document_id = ?", (row["id"],)
        )
    ]
    assert jobs == [("extract", "cancelled")]
    assert _status(row["id"]) == states.STORED_NOT_INDEXED


def test_the_worker_stops_on_a_held_workbook_without_an_error():
    from app import ingest

    row, _job, _dup = _ingest(_template_workbook(), "book.xlsx")
    conn = db.connect()
    with conn:  # as if something queued it with no role set
        conn.execute(
            "UPDATE documents SET status = ? WHERE id = ?", (states.CHUNKING, row["id"])
        )
    result = ingest.IngestionWorker().process(row["id"])
    assert "error" not in result, result
    assert _status(row["id"]) == states.STORED_NOT_INDEXED
    assert _index_rows(row["id"]) == (0, 0, 0)


def test_a_vector_is_not_written_for_a_chunk_withdrawn_mid_embedding(monkeypatch):
    import numpy as np

    from app import classification, ingest

    doc_id = _indexed_workbook(_template_workbook())

    class Stub:
        config = type("C", (), {"model_file": "stub.onnx"})()

        def embed_passages(self, texts):
            classification.set_role(doc_id, "CRS_TEMPLATE")  # withdrawn meanwhile
            return [np.zeros(4, dtype="float32") for _ in texts]

    monkeypatch.setattr(ingest.Embedder, "instance", staticmethod(lambda cfg: Stub()))
    monkeypatch.setattr(ingest, "_passage_text", lambda emb, r: r["text"])
    ingest.IngestionWorker().embed_pending(doc_id)
    assert _index_rows(doc_id) == (0, 0, 0)


def test_only_a_slice2_workbook_is_held_by_role(monkeypatch):
    from app import classification

    row, _job, _dup = _ingest(_image("PNG"), "scan.png")  # a PDF-read document
    classification.set_role(row["id"], "CRS_TEMPLATE")
    assert _status(row["id"]) == states.QUEUED


def test_a_row_merged_label_is_written_on_every_row_as_the_page_text_is(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Pump"
    ws["A1"], ws["B1"] = "Casing", "CS"
    ws["B2"], ws["B3"] = "SS316", "Duplex"
    ws.merge_cells("A1:A3")
    wb.save(tmp_path / "merged.xlsx")
    [chunk] = sheet_chunks.build_chunks(tmp_path / "merged.xlsx")
    assert chunk.text.split("\n")[1:] == [
        "| Casing | CS |",
        "| Casing | SS316 |",
        "| Casing | Duplex |",
    ]
    page = intake.read(tmp_path / "merged.xlsx").pages[0].text
    assert page.count("Casing") == 3


def test_a_cell_is_cited_as_excel_displays_it(tmp_path):
    from datetime import datetime

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws["A1"], ws["B1"] = "Corrosion allowance share", 0.125
    ws["B1"].number_format = "0.0%"
    ws["A2"], ws["B2"] = "Design flow", 1234.5
    ws["B2"].number_format = "#,##0.00"
    ws["A3"], ws["B3"] = "Issued", datetime(2026, 3, 4)
    ws["B3"].number_format = "dd/mm/yyyy"
    wb.save(tmp_path / "shown.xlsx")
    [chunk] = sheet_chunks.build_chunks(tmp_path / "shown.xlsx")
    assert chunk.text.split("\n")[1:] == [
        "| Corrosion allowance share | 12.5% |",
        "| Design flow | 1,234.50 |",
        "| Issued | 04/03/2026 |",
    ]


def test_an_indexed_workbook_is_classified_from_its_first_sheet():
    from app import classification

    wb = openpyxl.Workbook()
    wb.active.append(["Centrifugal pump data sheet", "Rev 0"])
    buf = io.BytesIO()
    wb.save(buf)
    row, _job, _dup = _ingest(buf.getvalue(), "book1.xlsx")
    record = classification.of_document(row["id"])
    assert record is not None and record["doc_class"] == "DATASHEET"


def test_an_old_office_file_names_what_is_read_with_the_switch_on():
    with pytest.raises(upload.UploadError) as exc:
        _ingest(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 old excel", "legacy.xls")
    assert exc.value.code == "unsupported_office"
    assert ".xlsx" in exc.value.message and "PNG" in exc.value.message
