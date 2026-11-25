"""#525 slice 3 (INTAKE_BLOCKS_ENABLED, with ONE_INTAKE_ENABLED): every file
becomes the same blocks. The same content in a PDF, a Word file, a workbook and
a scan gives the same blocks, hashes and citations. Either switch off: nothing
is stored and OCR returns what it returned. INVENTED files, generated here.
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pymupdf
import pytest
from PIL import Image

from app import (
    access,
    chunker,
    classification,
    db,
    extract,
    ingest,
    intake,
    intake_blocks,
    ocr,
    sheet_chunks,
    states,
    stored_paths,
    upload,
)
from app.config import settings
from tests import docx_builder as d
from tests.fake_tokenizer import install_if_missing

BEFORE = (
    "The contractor shall hydrotest every invented vessel before it is released"
    " for service at the invented site."
)
TABLE = [
    ["Tag", "Pressure", "Unit"],
    ["V-101", "12.5", "barg"],
    ["V-102", "15.0", "barg"],
]
AFTER = "All invented results shall be kept for the life of the plant."
PAGE_TWO = (
    "The second page of this invented file holds enough sentence text for the page"
    " to count as a usable text layer, so it is not sent to recognition."
)


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "w5b525s3.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(settings, "datasheet_office_input", False)
    monkeypatch.setattr(settings, "docx_input_enabled", True)
    monkeypatch.setattr(settings, "one_intake_enabled", True)
    monkeypatch.setattr(settings, "intake_images_xlsx_enabled", True)
    monkeypatch.setattr(settings, "intake_blocks_enabled", True)
    install_if_missing(monkeypatch)
    db.reset_connection()
    db.init_db()
    yield


# ---------------------------------------------------------- the invented files


def _pdf() -> bytes:
    pdf = pymupdf.open()
    page = pdf.new_page()
    y = 72
    cut = BEFORE.rfind(" ", 0, 60)
    for line in (
        BEFORE[:cut],
        BEFORE[cut + 1 :],
    ):  # wrapped, as a PDF wraps a paragraph
        page.insert_text((72, y), line, fontsize=11)
        y += 16
    top = y + 20
    left, width, height = 72, 130, 30
    for r, row in enumerate(TABLE):
        for c, cell in enumerate(row):
            rect = pymupdf.Rect(
                left + c * width,
                top + r * height,
                left + (c + 1) * width,
                top + (r + 1) * height,
            )
            page.draw_rect(rect, color=(0, 0, 0), width=0.8)
            page.insert_text((rect.x0 + 6, rect.y0 + 20), cell, fontsize=11)
    page.insert_text((72, top + 3 * height + 40), AFTER, fontsize=11)
    second, cut = pdf.new_page(), PAGE_TWO.rfind(" ", 0, 75)
    second.insert_text((72, 72), PAGE_TWO[:cut], fontsize=11)
    second.insert_text((72, 88), PAGE_TWO[cut + 1 :], fontsize=11)
    data = pdf.tobytes()
    pdf.close()
    return data


def _docx(tmp_path) -> bytes:
    body = (
        d.para(BEFORE)
        + d.table(TABLE)
        + d.para(AFTER)
        + d.para("", page_break=True)
        + d.para(PAGE_TWO)
    )
    return d.build(tmp_path / "same.docx", body).read_bytes()


def _workbook(table=TABLE) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "First"
    ws.append([BEFORE])
    for row in table:
        ws.append(row)
    ws.append([AFTER])
    wb.create_sheet("Second").append([PAGE_TWO])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _scan_tiff() -> bytes:
    """The PDF above as pictures at the OCR's own resolution: no text layer."""
    frames = []
    with pymupdf.open(stream=_pdf(), filetype="pdf") as pdf:
        for page in pdf:
            pix = page.get_pixmap(dpi=settings.ocr_dpi)
            frames.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    buf = io.BytesIO()
    frames[0].save(buf, "TIFF", save_all=True, append_images=frames[1:])
    return buf.getvalue()


def _fake_engine():
    """Recognition's lines and boxes, in image pixels, read from the source PDF
    (so the geometry is real; only the character recognition is stood in for)."""
    pages = []
    scale = settings.ocr_dpi / 72.0
    with pymupdf.open(stream=_pdf(), filetype="pdf") as pdf:
        for page in pdf:
            texts, boxes = [], []
            lines = [
                line
                for block in page.get_text("dict")["blocks"]
                for line in block.get("lines", [])
            ]
            for line in lines:
                x0, y0, x1, y1 = line["bbox"]
                texts.append("".join(span["text"] for span in line["spans"]))
                boxes.append(
                    [
                        [x0 * scale, y0 * scale],
                        [x1 * scale, y0 * scale],
                        [x1 * scale, y1 * scale],
                        [x0 * scale, y1 * scale],
                    ]
                )
            pages.append(
                SimpleNamespace(txts=texts, scores=[0.99] * len(texts), boxes=boxes)
            )
    feed = iter(pages)
    return lambda _image: next(feed)


def _doc_paths(doc_id):
    row = (
        db.connect()
        .execute("SELECT stored_path, sha256 FROM documents WHERE id = ?", (doc_id,))
        .fetchone()
    )
    return row["stored_path"], row["sha256"]


def _read_scan(doc_id):
    rows = ocr.recognise_batch(*_doc_paths(doc_id), [1, 2])
    ocr._commit_batch(doc_id, 1, rows, "test-model")
    chunker.chunk_document(doc_id)


def _ingest(data: bytes, name: str) -> str:
    row, _job, _dup = upload.ingest(io.BytesIO(data), name)
    if row["status"] == states.STORED_NOT_INDEXED:  # a workbook waits for its role
        classification.set_role(row["id"], "SUPPORTING_DOCUMENT")
    extract.extract_document(row["id"])
    chunker.chunk_document(row["id"])
    return row["id"]


def _ingested(fmt: str, tmp_path, monkeypatch) -> str:
    if fmt == "pdf":
        return _ingest(_pdf(), "same.pdf")
    if fmt == "docx":
        return _ingest(_docx(tmp_path), "same.docx")
    if fmt == "xlsx":
        return _ingest(_workbook(), "same.xlsx")
    doc_id = _ingest(_scan_tiff(), "same.tif")
    monkeypatch.setattr(ocr, "_build_engine", _fake_engine)
    _read_scan(doc_id)
    return doc_id


def _shape(blocks):
    """What must match across formats: place, kind, hash and citation."""
    return [(b.page_no, b.seq, b.kind, b.block_hash, b.citation) for b in blocks]


# -------------------------------------------------------------- the same blocks


def test_a_pdf_gives_its_text_and_table_blocks_in_page_order(tmp_path, monkeypatch):
    doc_id = _ingested("pdf", tmp_path, monkeypatch)
    intake_blocks.refresh(doc_id)
    blocks = intake_blocks.stored(doc_id)
    assert [(b.page_no, b.seq, b.kind) for b in blocks] == [
        (1, 1, "text"),
        (1, 2, "table"),
        (1, 3, "text"),
        (2, 1, "text"),
    ]
    assert blocks[0].text == BEFORE
    assert blocks[1].rows == TABLE
    assert blocks[3].citation == "page 2, block 1"
    assert all(len(b.block_hash) == 64 for b in blocks)


@pytest.mark.parametrize("fmt", ["docx", "xlsx", "scan"])
def test_the_same_content_gives_the_same_blocks_and_citations(
    fmt, tmp_path, monkeypatch
):
    pdf_doc = _ingested("pdf", tmp_path, monkeypatch)
    other = _ingested(fmt, tmp_path, monkeypatch)
    intake_blocks.refresh(pdf_doc)
    intake_blocks.refresh(other)
    assert _shape(intake_blocks.stored(other)) == _shape(intake_blocks.stored(pdf_doc))


def test_one_changed_value_changes_only_that_blocks_hash(tmp_path, monkeypatch):
    pdf_doc = _ingested("pdf", tmp_path, monkeypatch)
    changed = [TABLE[0], ["V-101", "12.6", "barg"], TABLE[2]]
    other = _ingest(_workbook(changed), "changed.xlsx")
    intake_blocks.refresh(pdf_doc)
    intake_blocks.refresh(other)
    same = [
        a.block_hash == b.block_hash
        for a, b in zip(
            intake_blocks.stored(pdf_doc), intake_blocks.stored(other), strict=True
        )
    ]
    assert same == [True, False, True, True]


def _text_hash(line):
    return intake_blocks._assemble(1, [("text", line)])[0].block_hash


def test_spacing_case_and_width_do_not_change_a_hash_but_a_digit_does():
    base = _text_hash("Rated 12.5 barg at site")
    assert _text_hash("RATED  12.5\n barg AT site") == base
    assert _text_hash("Rated 12\uff0e5 barg at site") == base  # a full-width stop
    assert _text_hash("Rated \uff11\uff12.5 barg at site") == base  # full-width digits
    assert _text_hash("Rated 12.6 barg at site") != base
    assert _text_hash("Rated -12.5 barg at site") != base


def test_nfc_forms_of_one_letter_hash_the_same():
    assert _text_hash("caf\u00e9") == _text_hash("cafe\u0301")


@pytest.mark.parametrize(
    "printed,plain",
    [
        ("10\u00b2", "102"),  # a superscript 2 after 10 is a power, not 102
        ("10\u207b\u2076", "10-6"),  # an exponent is not ten minus six
        ("1000 m\u00b3", "1000 m3"),  # a cubed sign, as the block holds it
        ("\u00bd inch", "1/2 inch"),  # a one-half sign
        ("x\u2082", "x2"),  # a subscript
    ],
)
def test_the_hash_folds_no_power_or_fraction_into_plain_digits(printed, plain):
    assert _text_hash(printed) != _text_hash(plain)


def test_a_superscript_or_fraction_in_a_table_cell_keeps_its_own_hash():
    def table_hash(cell):
        rows = [["Name", "Value"], ["Area", cell]]
        return intake_blocks._assemble(1, [("table", rows)])[0].block_hash

    assert table_hash("10\u00b2") != table_hash("102")
    assert table_hash("\u00bd") != table_hash("1/2")


def test_a_real_workbook_keeps_a_power_and_a_fraction_apart_from_plain_digits():
    def hashes(value):
        wb = openpyxl.Workbook()
        wb.active.append([f"The invented reading on this sheet is {value} here."])
        buf = io.BytesIO()
        wb.save(buf)
        doc_id = _ingest(buf.getvalue(), f"{value.encode().hex()}.xlsx")
        intake_blocks.refresh(doc_id)
        return intake_blocks.stored(doc_id)[0].block_hash

    assert hashes("10\u00b2") != hashes("102")
    assert hashes("\u00bd") != hashes("1/2")


@pytest.mark.slow
def test_a_real_engine_reads_the_scan_into_the_same_blocks():
    if not (settings.ocr_model_dir / settings.ocr_det_model).exists():
        pytest.skip("OCR weights not staged")
    pdf_doc = _ingest(_pdf(), "same.pdf")
    scan = _ingest(_scan_tiff(), "same.tif")
    _read_scan(scan)
    intake_blocks.refresh(pdf_doc)
    intake_blocks.refresh(scan)
    assert _shape(intake_blocks.stored(scan)) == _shape(intake_blocks.stored(pdf_doc))


# ------------------------------------------------------------------- the switch


def test_switch_defaults_off():
    from app.config import Settings

    assert Settings.model_fields["intake_blocks_enabled"].default is False


@pytest.mark.parametrize("one_intake,blocks", [(False, True), (True, False)])
def test_either_switch_off_nothing_is_stored(monkeypatch, one_intake, blocks):
    doc_id = _ingest(_pdf(), "same.pdf")
    monkeypatch.setattr(settings, "one_intake_enabled", one_intake)
    monkeypatch.setattr(settings, "intake_blocks_enabled", blocks)
    assert intake_blocks.refresh(doc_id) is None
    assert intake_blocks.stored(doc_id) == []


def test_switch_off_recognition_returns_what_it_returned(monkeypatch):
    monkeypatch.setattr(settings, "intake_blocks_enabled", False)
    doc_id = _ingest(_scan_tiff(), "same.tif")
    monkeypatch.setattr(ocr, "_build_engine", _fake_engine)
    rows = ocr.recognise_batch(*_doc_paths(doc_id), [1, 2])
    assert all(len(r) == 10 for r in rows)
    ocr._commit_batch(doc_id, 1, rows, "test-model")
    stored = db.connect().execute("SELECT tables_json FROM page_ocr").fetchall()
    assert [r["tables_json"] for r in stored] == [None, None]


def _process(monkeypatch, doc_id, recognise=None):
    """The worker's own stages for one document; no embedding model is run."""
    worker = ingest.IngestionWorker()
    monkeypatch.setattr(worker, "_needs_embedding", lambda _d: False)
    if recognise:
        monkeypatch.setattr(ingest.ocr, "recognise_document", recognise)
    return worker.process(doc_id)


def test_the_worker_stores_blocks_after_chunking(monkeypatch):
    row, _job, _dup = upload.ingest(io.BytesIO(_pdf()), "same.pdf")
    result = _process(monkeypatch, row["id"])
    assert "ocr" not in result["stages"]  # the chunk stage stored them
    assert [b.kind for b in intake_blocks.stored(row["id"])] == [
        "text",
        "table",
        "text",
        "text",
    ]


def test_the_worker_stores_nothing_with_the_switch_off(monkeypatch):
    monkeypatch.setattr(settings, "intake_blocks_enabled", False)
    row, _job, _dup = upload.ingest(io.BytesIO(_pdf()), "same.pdf")
    _process(monkeypatch, row["id"])
    assert intake_blocks.stored(row["id"]) == []


def test_a_worker_ocr_round_that_only_fails_still_names_the_page(monkeypatch):
    row, _job, _dup = upload.ingest(io.BytesIO(_scan_tiff()), "same.tif")

    def failed_round(doc_id, max_pages=None):
        ocr._commit_batch(
            doc_id, 1, ocr.failed_rows(ocr.pending_pages(doc_id), "boom"), "m"
        )
        return {"pages_recognised": 0, "seconds": 0.0, "pages_with_text": 0}

    _process(monkeypatch, row["id"], failed_round)
    assert {b.reason for b in intake_blocks.stored(row["id"])} == {
        intake_blocks.WHY_OCR_FAILED
    }


# --------------------------------------------------- nothing passes in silence


def test_a_scan_waiting_for_ocr_is_named_and_has_no_hash():
    doc_id = _ingest(_scan_tiff(), "same.tif")
    intake_blocks.refresh(doc_id)
    blocks = intake_blocks.stored(doc_id)
    assert [(b.page_no, b.kind, b.reason) for b in blocks] == [
        (1, "not_read", intake.WHY_SCANNED),
        (2, "not_read", intake.WHY_SCANNED),
    ]
    assert all(b.block_hash is None and b.citation is None for b in blocks)


def test_a_page_ocr_failed_on_is_named_apart_from_a_blank_one():
    doc_id = _ingest(_scan_tiff(), "same.tif")
    rows = [
        (1, "", None, None, 0, 0, 0.1, 0, "", "RuntimeError: boom"),
        (2, "", None, None, 0, 0, 0.1, 0, "", None),
    ]
    ocr._commit_batch(doc_id, 1, rows, "test-model")
    intake_blocks.refresh(doc_id)
    assert [b.reason for b in intake_blocks.stored(doc_id)] == [
        intake_blocks.WHY_OCR_FAILED,
        intake.WHY_BLANK_PDF,
    ]


def test_an_empty_sheet_is_named():
    wb = openpyxl.Workbook()
    wb.active.append([PAGE_TWO])
    wb.create_sheet("Blank")
    buf = io.BytesIO()
    wb.save(buf)
    doc_id = _ingest(buf.getvalue(), "blank.xlsx")
    intake_blocks.refresh(doc_id)
    assert [(b.page_no, b.kind, b.reason) for b in intake_blocks.stored(doc_id)] == [
        (1, "text", None),
        (2, "not_read", intake.WHY_EMPTY_SHEET),
    ]


def test_a_file_that_cannot_be_read_is_could_not_check_never_empty(monkeypatch, caplog):
    doc_id = _ingest(_pdf(), "same.pdf")

    def broken(_doc_id):
        raise ValueError(BEFORE)

    monkeypatch.setattr(intake_blocks, "build", broken)
    with caplog.at_level(logging.DEBUG):
        intake_blocks.refresh(doc_id)
    blocks = intake_blocks.stored(doc_id)
    assert [(b.page_no, b.kind) for b in blocks] == [(0, "not_read")]
    assert blocks[0].reason == intake_blocks.WHY_COULD_NOT_CHECK
    assert BEFORE not in caplog.text  # ids and counts only, never document text


def _drop_stored_page(doc_id, page_no):
    conn = db.connect()
    with conn:
        conn.execute(
            "DELETE FROM pages WHERE document_id = ? AND page_no = ?",
            (doc_id, page_no),
        )


def test_a_pdf_page_with_no_stored_row_is_named_not_skipped():
    doc_id = _ingest(_pdf(), "same.pdf")
    _drop_stored_page(doc_id, 1)
    intake_blocks.refresh(doc_id)
    blocks = intake_blocks.stored(doc_id)
    assert (blocks[0].page_no, blocks[0].kind, blocks[0].reason) == (
        1,
        "not_read",
        intake_blocks.WHY_NOT_STORED,
    )
    assert [b.page_no for b in blocks[1:]] == [2]
    assert [b.page_no for b in intake_blocks.build(doc_id)] == [1, 2]  # page order


def test_a_sheet_with_no_stored_row_is_named_not_skipped():
    doc_id = _ingest(_workbook(), "same.xlsx")
    _drop_stored_page(doc_id, 2)
    intake_blocks.refresh(doc_id)
    assert intake_blocks.stored(doc_id)[-1].reason == intake_blocks.WHY_NOT_STORED


def test_a_document_with_no_stored_page_at_all_is_not_an_empty_pass():
    doc_id = _ingest(_pdf(), "same.pdf")
    _drop_stored_page(doc_id, 1)
    _drop_stored_page(doc_id, 2)
    intake_blocks.refresh(doc_id)
    assert [(b.page_no, b.reason) for b in intake_blocks.stored(doc_id)] == [
        (1, intake_blocks.WHY_NOT_STORED),
        (2, intake_blocks.WHY_NOT_STORED),
    ]


def test_a_file_missing_from_disk_is_could_not_check():
    doc_id = _ingest(_pdf(), "same.pdf")
    Path(stored_paths.local(_doc_paths(doc_id)[0])).unlink()
    intake_blocks.refresh(doc_id)
    assert [b.reason for b in intake_blocks.stored(doc_id)] == [
        intake_blocks.WHY_COULD_NOT_CHECK
    ]


def test_a_refresh_logs_no_document_text(caplog, tmp_path, monkeypatch):
    doc_id = _ingested("pdf", tmp_path, monkeypatch)
    with caplog.at_level(logging.DEBUG):
        intake_blocks.refresh(doc_id)
    assert "contractor" not in caplog.text


def test_a_refresh_replaces_what_was_stored():
    doc_id = _ingest(_pdf(), "same.pdf")
    intake_blocks.refresh(doc_id)
    first = _shape(intake_blocks.stored(doc_id))
    intake_blocks.refresh(doc_id)
    assert _shape(intake_blocks.stored(doc_id)) == first


# ------------------------------------------------------------- held out, deleted


def test_a_workbook_waiting_for_its_role_holds_no_blocks():
    row, _job, _dup = upload.ingest(io.BytesIO(_workbook()), "same.xlsx")
    intake_blocks.refresh(row["id"])
    assert intake_blocks.stored(row["id"]) == []


def test_a_workbook_that_leaves_the_index_loses_its_blocks():
    doc_id = _ingest(_workbook(), "same.xlsx")
    intake_blocks.refresh(doc_id)
    assert intake_blocks.stored(doc_id)
    classification.set_role(doc_id, sheet_chunks.CRS_TEMPLATE)
    sheet_chunks.withhold(doc_id)
    assert intake_blocks.stored(doc_id) == []
    intake_blocks.refresh(doc_id)  # its pages are still stored; it stays out
    assert intake_blocks.stored(doc_id) == []


def test_deleting_a_document_deletes_its_blocks():
    doc_id = _ingest(_pdf(), "same.pdf")
    intake_blocks.refresh(doc_id)
    conn = db.connect()
    with conn:
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    assert intake_blocks.stored(doc_id) == []


# ------------------------------------------------------------- the scan's tables


def _box(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _grid(lines):
    texts = [t for t, _ in lines]
    boxes = [_box(*b) for _, b in lines]
    return intake_blocks.ocr_tables(texts, boxes, "\n".join(texts))


def _cells(raw):
    return [t["rows"] for t in json.loads(raw)["tables"]] if raw else []


def test_aligned_rows_are_a_table_and_a_gap_stays_an_empty_cell():
    raw = _grid(
        [
            ("Tag", (100, 100, 180, 120)),
            ("Unit", (300, 100, 360, 120)),
            ("V-1", (100, 140, 170, 160)),
            ("barg", (300, 140, 370, 160)),
            ("V-2", (100, 180, 170, 200)),
            ("Note", (500, 180, 570, 200)),
            ("Head", (100, 220, 170, 240)),
            ("Mid", (300, 220, 370, 240)),
            ("Last", (500, 220, 570, 240)),
        ]
    )
    assert _cells(raw) == [
        [
            ["Tag", "Unit", ""],
            ["V-1", "barg", ""],
            ["V-2", "", "Note"],
            ["Head", "Mid", "Last"],
        ]
    ]


def test_a_right_aligned_column_is_still_one_column():
    raw = _grid(
        [
            ("Pressure", (100, 100, 200, 120)),
            ("Limit value", (300, 100, 420, 120)),
            ("Low", (100, 140, 150, 160)),
            ("7", (405, 140, 420, 160)),
        ]
    )
    assert _cells(raw) == [[["Pressure", "Limit value"], ["Low", "7"]]]


def test_two_columns_of_running_text_are_not_a_table():
    left = "the quick invented words run on here"
    right = "and the other column keeps running too"
    lines = []
    for i in range(4):
        y = 100 + i * 30
        lines.append((left, (50, y, 280, y + 20)))
        lines.append((right, (320, y, 560, y + 20)))
    assert _grid(lines) is None


def test_a_cell_over_two_columns_is_no_table_rather_than_a_wrong_grid():
    raw = _grid(
        [
            ("Alpha", (100, 100, 150, 120)),
            ("Beta", (300, 100, 350, 120)),
            ("Gamma", (100, 140, 150, 160)),
            ("spans both", (120, 140, 340, 160)),
        ]
    )
    assert raw is None


def test_a_line_alone_breaks_the_run():
    raw = _grid(
        [
            ("Alpha", (100, 100, 150, 120)),
            ("Beta", (300, 100, 350, 120)),
            ("A line alone", (100, 140, 300, 160)),
            ("Gamma", (100, 180, 150, 200)),
            ("Delta", (300, 180, 350, 200)),
        ]
    )
    assert raw is None  # one row each side: neither reaches the table minimum


def test_a_box_of_an_odd_shape_stores_no_table_and_keeps_the_page():
    assert intake_blocks.ocr_tables(["Alpha", "Beta"], [None, 7], "Alpha\nBeta") is None


def test_text_whose_lines_moved_stores_no_table():
    texts = ["Alpha", "Beta", "Gamma", "Delta"]
    boxes = [
        _box(100, 100, 150, 120),
        _box(300, 100, 350, 120),
        _box(100, 140, 150, 160),
        _box(300, 140, 350, 160),
    ]
    assert _cells(intake_blocks.ocr_tables(texts, boxes, "Alpha\nBeta\nGamma\nDelta"))
    moved = "Alpha\nBeta\nGamma\nDelta\nExtra"  # a line more than was recognised
    assert intake_blocks.ocr_tables(texts, boxes, moved) is None
