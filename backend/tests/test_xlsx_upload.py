"""XLSX upload: accepted, proven a workbook, stored, and never indexed.

Three separate claims, and they fail for different reasons:

  * a zip is not a workbook - `.docx`, `.pptx` and `.jar` share `PK\\x03\\x04`,
    so the magic bytes are a gate and `xl/workbook.xml` is the proof;
  * a decompression bomb is REFUSED rather than expanded, checked against the
    declared sizes in the central directory without decompressing anything;
  * a workbook is stored in a TERMINAL state with no job, so the ingestion
    worker never picks it up. That is a decision, not an extraction that
    happens to crash.

The PDF path is asserted unchanged here as well as in `test_upload.py`, which
was not modified.

Mutations: M16-M19, `python scripts/mutation_check.py --phase 2`.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from app import db, states, upload
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "xlsx.sqlite")
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    (tmp_path / "uploads").mkdir(parents=True, exist_ok=True)
    db.reset_connection(); db.init_db()
    yield
    db.reset_connection()


def _workbook(extra: dict[str, bytes] | None = None) -> bytes:
    """A minimal file that is genuinely an xlsx as far as this check goes."""
    buf = io.BytesIO()
    # DEFLATED, like every real workbook. Stored entries would make the bomb
    # test meaningless: the point is a file that is small on disk and large
    # when expanded.
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "<workbook><sheets/></workbook>")
        z.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
        for name, body in (extra or {}).items():
            z.writestr(name, body)
    return buf.getvalue()


def _docx() -> bytes:
    """A zip with the same magic bytes and no workbook part."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<document/>")
    return buf.getvalue()


def _pdf() -> bytes:
    return b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n"


# ------------------------------------------------------------- acceptance

def test_a_workbook_is_accepted_and_stored_as_xlsx():
    row, job_id, duplicate = upload.ingest(io.BytesIO(_workbook()), "CRS Template.xlsx")
    assert duplicate is None
    assert row["filename"] == "CRS Template.xlsx"
    assert row["stored_path"].endswith(".xlsx"), row["stored_path"]
    from pathlib import Path
    assert Path(row["stored_path"]).exists()


def test_the_stored_workbook_is_byte_identical_to_what_was_uploaded():
    """No conversion, no normalisation."""
    from pathlib import Path
    payload = _workbook()
    row, _, _ = upload.ingest(io.BytesIO(payload), "book.xlsx")
    assert Path(row["stored_path"]).read_bytes() == payload


def test_the_suffix_comes_from_the_bytes_not_the_filename():
    """A workbook named .pdf is still stored as .xlsx, and vice versa."""
    row, _, _ = upload.ingest(io.BytesIO(_workbook()), "pretending.pdf")
    assert row["stored_path"].endswith(".xlsx")
    assert row["filename"].endswith(".xlsx")
    row2, _, _ = upload.ingest(io.BytesIO(_pdf()), "pretending.xlsx")
    assert row2["stored_path"].endswith(".pdf")
    assert row2["filename"].endswith(".pdf")


# ------------------------------------------------------------- refusals

def test_a_docx_is_refused_although_its_magic_bytes_are_a_zip():
    """THE MUTATION TARGET (M16): the xl/workbook.xml requirement."""
    with pytest.raises(upload.UploadError) as exc:
        upload.ingest(io.BytesIO(_docx()), "notes.docx")
    assert exc.value.code == "not_xlsx"


def test_a_decompression_bomb_is_refused_rather_than_expanded(monkeypatch):
    """THE MUTATION TARGET (M17): the declared-size ceiling.

    A real zip through the real `ingest`. The limit is lowered rather than the
    payload inflated, so the test exercises the production path in a second
    instead of writing 256 MB - and it is the DECLARED size that is checked, so
    nothing is ever decompressed to find out.

    2 MB of zeros compresses to a few kilobytes: the file on disk is tiny and
    its declared expansion is not, which is exactly the shape of a bomb.
    """
    monkeypatch.setattr(upload, "MAX_XLSX_UNCOMPRESSED_BYTES", 64 * 1024)
    bomb = _workbook({"xl/worksheets/huge.xml": b"\0" * (2 * 1024 * 1024)})
    assert len(bomb) < 64 * 1024, "the compressed file should be small"
    with pytest.raises(upload.UploadError) as exc:
        upload.ingest(io.BytesIO(bomb), "bomb.xlsx")
    assert exc.value.code == "not_xlsx"
    # Refused, not expanded: nothing was written anywhere.
    assert list(settings.upload_dir.iterdir()) == []


def test_a_workbook_with_too_many_entries_is_refused(monkeypatch):
    monkeypatch.setattr(upload, "MAX_XLSX_ENTRIES", 5)
    many = _workbook({f"xl/worksheets/extra{i}.xml": b"<x/>" for i in range(10)})
    with pytest.raises(upload.UploadError) as exc:
        upload.ingest(io.BytesIO(many), "many.xlsx")
    assert exc.value.code == "not_xlsx"


def test_a_corrupt_zip_is_refused_as_not_a_file_we_accept():
    """`not_pdf`, deliberately, and NOT `not_xlsx`.

    Four bytes of coincidence is not a declaration of intent: this file opened
    with the zip magic and then failed to be a zip at all, so calling it a bad
    *workbook* would claim to know more about it than we do. It is simply not
    something this system accepts.

    This is also the contract `test_upload.py::
    test_non_pdf_is_rejected_and_leaves_nothing_behind` has always asserted,
    with the same `PK\\x03\\x04` bytes - and that test was not modified.
    """
    corrupt = b"PK\x03\x04" + b"garbage that is not a zip"
    with pytest.raises(upload.UploadError) as exc:
        upload.ingest(io.BytesIO(corrupt), "broken.xlsx")
    assert exc.value.code == "not_pdf"


def test_a_readable_zip_that_is_not_a_workbook_says_so_precisely():
    """The other half: here the intent IS clear, so the precise code is used."""
    with pytest.raises(upload.UploadError) as exc:
        upload.ingest(io.BytesIO(_docx()), "notes.docx")
    assert exc.value.code == "not_xlsx"


def test_a_refused_upload_stores_nothing():
    """Never partially stored: no temp file, no final file, no row."""
    with pytest.raises(upload.UploadError):
        upload.ingest(io.BytesIO(_docx()), "notes.docx")
    leftovers = list(settings.upload_dir.iterdir())
    assert leftovers == [], f"a refused upload left {leftovers}"
    assert db.connect().execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


@pytest.mark.parametrize("payload,name", [
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 old excel", "legacy.xls"),
    (b"name,value\n1,2\n", "data.csv"),
    (b"\x7fELF binary", "thing.bin"),
])
def test_other_formats_are_still_refused(payload, name):
    """xls (not OOXML) and csv are out of scope, and say so as `not_pdf` -
    the true sentence for anything that is neither a PDF nor a workbook."""
    with pytest.raises(upload.UploadError) as exc:
        upload.ingest(io.BytesIO(payload), name)
    assert exc.value.code == "not_pdf"


def test_an_xlsm_is_refused_because_macros_are_out_of_scope():
    """An xlsm IS a valid OOXML workbook, so it passes every structural check.

    It is refused on the macro part instead, which is the only thing that
    distinguishes it - and the reason to refuse it at all.
    """
    macro = _workbook({"xl/vbaProject.bin": b"\x00macro"})
    with pytest.raises(upload.UploadError) as exc:
        upload.ingest(io.BytesIO(macro), "template.xlsm")
    assert exc.value.code == "not_xlsx"


# --------------------------------------------------- never indexed

def test_a_workbook_is_stored_in_a_terminal_state_and_never_queued():
    """THE MUTATION TARGET (M18). The worker selects everything that is not
    terminal, so a non-terminal state here would be an infinite re-selection."""
    row, job_id, _ = upload.ingest(io.BytesIO(_workbook()), "crs.xlsx")
    assert row["status"] == states.STORED_NOT_INDEXED
    assert states.is_terminal(row["status"])
    assert not states.is_answerable(row["status"])
    # A job id is a promise that work is happening. None is.
    assert job_id is None
    jobs = db.connect().execute(
        "SELECT COUNT(*) FROM jobs WHERE document_id = ?", (row["id"],)).fetchone()[0]
    assert jobs == 0


def test_the_ingestion_worker_never_selects_a_workbook():
    """The property that actually matters, asserted against the worker's own
    query rather than against the state constant."""
    from app.ingest import IngestionWorker
    upload.ingest(io.BytesIO(_workbook()), "crs.xlsx")
    assert IngestionWorker()._next_document() is None


def test_a_pdf_is_still_queued_with_a_job():
    """The PDF path is unchanged - the control for the test above."""
    row, job_id, _ = upload.ingest(io.BytesIO(_pdf()), "spec.pdf")
    assert row["status"] == states.QUEUED
    assert job_id
    jobs = db.connect().execute(
        "SELECT COUNT(*) FROM jobs WHERE document_id = ?", (row["id"],)).fetchone()[0]
    assert jobs == 1


def test_a_workbook_produces_no_chunks_pages_or_vectors():
    """Nothing retrievable, asserted at the tables retrieval reads."""
    row, _, _ = upload.ingest(io.BytesIO(_workbook()), "crs.xlsx")
    conn = db.connect()
    for table in ("chunks", "pages", "chunk_vectors"):
        count = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE document_id = ?",
            (row["id"],)).fetchone()[0]
        assert count == 0, f"{table} holds rows for a workbook"


def test_a_workbook_still_appears_in_the_classification_queue():
    """Stored and not indexed is not the same as invisible."""
    row, _, _ = upload.ingest(io.BytesIO(_workbook()), "crs.xlsx")
    stored = db.connect().execute(
        "SELECT * FROM document_classification WHERE document_id = ?",
        (row["id"],)).fetchone()
    assert stored is not None, "the workbook is absent from the queue entirely"
    assert stored["confirmed_by"] is None, "a suggestion must never self-confirm"


# --------------------------------------------------- immutability (M19)

def test_an_xlsx_upload_never_rewrites_an_existing_stored_original():
    """The M15 guard, now under a derived suffix.

    The bug this catches is a stored `.xlsx` being overwritten because the
    guard checked a hardcoded `.pdf` path that never existed.
    """
    import hashlib
    payload = _workbook()
    digest = hashlib.sha256(payload).hexdigest()
    target = settings.upload_dir / f"{digest}.xlsx"
    target.write_bytes(b"PK\x03\x04ALREADY ON DISK")
    before = target.read_bytes()

    row, _, duplicate = upload.ingest(io.BytesIO(payload), "crs.xlsx")

    assert duplicate is None
    assert target.read_bytes() == before, "the stored workbook was rewritten"
    assert list(settings.upload_dir.glob(".incoming-*.part")) == []
