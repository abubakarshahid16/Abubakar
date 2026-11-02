"""OCR_FILE_ERROR_HOLD_ENABLED (#1568): pages recognition failed on because the stored
file could not be opened do not end in "ready", and the pool workers see the same data
directory as the parent. INVENTED files only; the OCR engine is a stub, no model."""

from __future__ import annotations

import concurrent.futures as cf
import errno
import hashlib
import io
import multiprocessing
from typing import ClassVar

import pymupdf
import pytest
from PIL import Image

from app import (
    access,
    chunker,
    crs_mapping,
    db,
    extract,
    fts_index,
    ingest,
    ocr,
    page_ledger,
    page_not_read,
    pageimage,
    reading_state,
    states,
    stored_paths,
)
from app.config import settings
from tests.fake_tokenizer import install_if_missing

NOW = "2026-11-02T00:00:00Z"
LONG = "shall be hydrostatically tested at one and a half times the design pressure."
HELD_WORDS = page_not_read.FILE_NOT_READ


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "hold.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(settings, "ocr_file_error_hold_enabled", True)
    monkeypatch.setattr(settings, "one_checked_definition_enabled", False)
    install_if_missing(monkeypatch)
    db.reset_connection()
    db.init_db()
    fts_index.ensure_schema()
    yield
    db.reset_connection()


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (600, 800), "white").save(out, "PNG")
    return out.getvalue()


def _pdf(tmp_path, *, text_page: bool = True, name="p.pdf"):
    """A page of text (unless told not to) and a page that is only a picture."""
    doc = pymupdf.open()
    if text_page:
        page = doc.new_page()
        for line in range(30):
            page.insert_text(
                (40, 170 + 18 * line), f"{line} The vessel {LONG}", fontsize=9
            )
    page = doc.new_page()
    page.insert_image(page.rect, stream=_png())
    path = tmp_path / name
    doc.save(path)
    doc.close()
    return path


class _InlinePool:
    """Runs a submitted batch here, and records how the pool was asked to start."""

    seen: ClassVar[list[dict]] = []

    def __init__(self, max_workers=None, **options):
        type(self).seen.append(options)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def submit(self, fn, *args):
        future = cf.Future()
        future.set_result(fn(*args))
        return future

    def shutdown(self, **_kw):
        return None


def _ingest(path, monkeypatch, doc_id="doc1", failure="file") -> str:
    """The production stages up to recognition. `failure`: "file", the real error from a
    stored file the worker cannot find; "engine", a page that raises for another reason; "disk", recognition on
    the real file, with whatever the test made fail."""
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
    assert ocr.pending_pages(doc_id), "the picture page must be routed to recognition"
    real = ocr.recognise_batch

    def worker(_stored, _sha, pages):
        if failure == "file":
            return real("uploads/nowhere.pdf", "0" * 64, pages)
        if failure == "disk":
            return real(_stored, _sha, pages)
        return ocr.failed_rows(pages, "RuntimeError: the engine raised")

    monkeypatch.setattr(ocr, "_build_engine", lambda: lambda _image: None)
    monkeypatch.setattr(ocr, "recognise_batch", worker)
    monkeypatch.setattr(ocr.cf, "ProcessPoolExecutor", _InlinePool)
    ocr.recognise_document(doc_id)
    return doc_id


def _finish(monkeypatch, doc_id: str) -> str:
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
            "INSERT OR IGNORE INTO chunk_vectors"
            " (chunk_id, document_id, dim, vector, model, created_at)"
            " SELECT id, document_id, 1, x'00000000', ?, ? FROM chunks"
            " WHERE document_id = ? AND retrievable = 1",
            (ingest.embedding_tag(), NOW, doc_id),
        )
    worker._finish_if_embedded(doc_id)
    return _status(doc_id)


def _status(doc_id: str) -> str:
    return (
        db.connect()
        .execute("SELECT status FROM documents WHERE id = ?", (doc_id,))
        .fetchone()[0]
    )


def _message(doc_id: str) -> str:
    return (
        db.connect()
        .execute("SELECT error_message FROM documents WHERE id = ?", (doc_id,))
        .fetchone()[0]
    )


# ---------------------------------------------------------------- the workers


def _spawned_read(relative: str, options: dict):
    """A really spawned child: it knows only what it is handed, as on the PC and the Mac."""
    with cf.ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn"), **options
    ) as pool:
        return pool.submit(ocr._native_lines, relative, 1, 1.0).result(timeout=180)


def test_a_spawned_worker_finds_a_relative_stored_path_only_with_the_switch_on(
    tmp_path, monkeypatch
):
    (tmp_path / "uploads").mkdir(exist_ok=True)
    unique = f"uploads/only-here-{tmp_path.name}.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((40, 100), "A line of invented text.")
    doc.save(tmp_path / unique)
    doc.close()

    assert any(
        "invented" in t
        for _, _, t in _spawned_read(unique, stored_paths.pool_options())
    )

    monkeypatch.setattr(settings, "ocr_file_error_hold_enabled", False)
    with pytest.raises(Exception) as off:
        _spawned_read(unique, stored_paths.pool_options())
    assert page_not_read.is_file_error(f"{type(off.value).__name__}: {off.value}")


def test_both_recognition_pools_start_with_the_carried_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(_InlinePool, "seen", [])
    _ingest(_pdf(tmp_path), monkeypatch)
    assert _InlinePool.seen[-1]["initializer"] is stored_paths.carry_data_dir
    assert _InlinePool.seen[-1]["initargs"] == (str(tmp_path.resolve()),)

    _InlinePool.seen.clear()
    monkeypatch.setattr(ocr, "recognise_page_lines", lambda *_a: [])
    ocr.page_lines("uploads/a.pdf", "a" * 64, 1)
    assert _InlinePool.seen == [stored_paths.pool_options()]


def test_with_the_switch_off_the_pools_start_as_before(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ocr_file_error_hold_enabled", False)
    monkeypatch.setattr(_InlinePool, "seen", [])
    _ingest(_pdf(tmp_path), monkeypatch)
    assert _InlinePool.seen == [{}]
    assert stored_paths.pool_options() == {}


def test_the_carried_directory_reaches_the_worker_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "other")
    stored_paths.carry_data_dir(str(tmp_path))
    assert settings.data_dir == tmp_path


# ---------------------------------------------------------------- what counts


@pytest.mark.parametrize(
    "content",
    [None, b"", b"this is not a pdf at all"],
    ids=["missing", "empty", "corrupt"],
)
def test_the_real_error_of_a_file_that_cannot_be_opened_is_a_file_error(
    tmp_path, monkeypatch, content
):
    path = tmp_path / "bad.pdf"
    if content is not None:
        path.write_bytes(content)
    monkeypatch.setattr(ocr, "_build_engine", lambda: lambda _image: None)
    rows = ocr.recognise_batch(str(path), "1" * 64, [1])
    assert page_not_read.is_file_error(rows[0][-1])


@pytest.mark.parametrize(
    "error",
    [
        None,
        "",
        "RuntimeError: the engine raised",
        "OSError: [Errno 28] No space left on device",
        "engine_unavailable: FileNotFoundError: a model file",
        "worker_failed: BrokenProcessPool: a child died",
        "ValueError: FileNotFoundError: named inside a message",
    ],
)
def test_other_failures_are_not_file_errors(error):
    assert not page_not_read.is_file_error(error)


def test_the_ledger_reason_of_a_file_error_is_recognised():
    assert page_not_read.is_file_error("recognition failed: FileDataError: cannot open")


# ---------------------------------------------------------------- the status


def test_a_file_error_holds_the_document_and_says_why(tmp_path, monkeypatch):
    doc = _ingest(_pdf(tmp_path), monkeypatch)
    assert _finish(monkeypatch, doc) == states.PARTIALLY_SEARCHABLE
    told = reading_state.stored(doc)
    assert told["unaccounted"] == 2  # the page, and the same page as holding a picture
    assert told["not_read_listed"] == 0
    assert told["ready"] is False
    assert HELD_WORDS in told["line"]
    assert "page 2" in told["line"]
    readable = reading_state.readable(access.unrestricted_scope())
    assert readable[doc]["line"] == told["line"]
    job = db.connect().execute("SELECT state FROM jobs WHERE document_id = ?", (doc,))
    assert job.fetchone()[0] == "done"
    assert reading_state.hooks_may_run(doc, states.PARTIALLY_SEARCHABLE) is True


def test_the_ledger_and_the_crs_note_name_the_file_error(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "page_read_by_reading_enabled", True)
    doc = _ingest(_pdf(tmp_path), monkeypatch)
    _finish(monkeypatch, doc)
    row = next(r for r in page_ledger.rows(doc) if r["page_no"] == 2)
    assert row["ocr_status"] == "failed"
    assert row["ocr_reason"].startswith("recognition failed: FileNotFoundError")
    coverage = page_ledger.coverage(doc)
    assert coverage["pages_not_read_why"]["2"] == HELD_WORDS
    assert HELD_WORDS in coverage["reading"]["line"]
    notes = crs_mapping.build_review_notes([{"document_id": doc}], [])
    assert any(HELD_WORDS in n["detail"] for n in notes)


def test_a_file_error_holds_with_the_one_meaning_switch_on_too(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    doc = _ingest(_pdf(tmp_path), monkeypatch)
    assert _finish(monkeypatch, doc) == states.PARTIALLY_SEARCHABLE
    assert HELD_WORDS in reading_state.stored(doc)["line"]


def test_with_this_switch_off_the_one_meaning_switch_still_lists_it_as_ready(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "ocr_file_error_hold_enabled", False)
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    doc = _ingest(_pdf(tmp_path), monkeypatch)
    assert _finish(monkeypatch, doc) == states.READY
    assert reading_state.stored(doc)["not_read_listed"] >= 1
    assert HELD_WORDS not in reading_state.stored(doc)["line"]


def test_another_recognition_failure_does_not_hold(tmp_path, monkeypatch):
    doc = _ingest(_pdf(tmp_path), monkeypatch, failure="engine")
    assert _finish(monkeypatch, doc) == states.READY
    assert reading_state.stored(doc) is None
    assert reading_state.decide(doc) is None
    assert (
        not db.connect()
        .execute("SELECT 1 FROM sqlite_master WHERE name = 'document_reading'")
        .fetchone()
    )


def test_a_bare_os_error_on_a_healthy_document_does_not_hold_it(tmp_path, monkeypatch):
    """A full disk while writing the page-image cache: the file is fine, so the words
    "could not open the stored file" would be false. The real error, from the real path."""

    def disk_full(*_args):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(pageimage, "_save_png", disk_full)
    doc = _ingest(_pdf(tmp_path), monkeypatch, failure="disk")
    stored = (
        db.connect()
        .execute("SELECT error FROM page_ocr WHERE document_id = ?", (doc,))
        .fetchone()[0]
    )
    assert stored.startswith("OSError:")
    assert reading_state.file_error_pages(doc) == []
    assert _finish(monkeypatch, doc) == states.READY
    assert reading_state.stored(doc) is None


def test_switches_off_nothing_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ocr_file_error_hold_enabled", False)
    monkeypatch.setattr(settings, "page_read_by_reading_enabled", True)
    doc = _ingest(_pdf(tmp_path), monkeypatch)
    assert _finish(monkeypatch, doc) == states.READY
    assert reading_state.decide(doc) is None
    assert reading_state.stored(doc) is None
    assert reading_state.file_error_pages(doc) == []
    coverage = page_ledger.coverage(doc)
    assert "reading" not in coverage
    assert coverage["pages_not_read_why"]["2"] == page_not_read.IMAGE_NO_READING
    assert crs_mapping.build_review_notes([{"document_id": doc}], []) == []
    assert reading_state.not_found_words(doc, "not found") == "not found"
    assert reading_state.hooks_may_run(doc, states.PARTIALLY_SEARCHABLE) is False


def test_a_re_read_that_succeeds_goes_to_ready_and_the_held_words_go(
    tmp_path, monkeypatch
):
    doc = _ingest(_pdf(tmp_path), monkeypatch)
    assert _finish(monkeypatch, doc) == states.PARTIALLY_SEARCHABLE
    assert ocr.retry_failed(doc) == 1
    assert reading_state.finish_status(doc) == states.READY
    assert reading_state.stored(doc) is None


def test_a_document_of_only_scans_says_the_file_could_not_be_opened(
    tmp_path, monkeypatch
):
    doc = _ingest(_pdf(tmp_path, text_page=False), monkeypatch)
    assert _finish(monkeypatch, doc) == states.NO_SEARCHABLE_CONTENT
    assert "could not open the stored file" in _message(doc)
    assert "found no usable text" not in _message(doc)


def test_with_the_switch_off_only_scans_keep_their_old_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ocr_file_error_hold_enabled", False)
    doc = _ingest(_pdf(tmp_path, text_page=False), monkeypatch)
    _finish(monkeypatch, doc)
    assert "found no usable text" in _message(doc)


def test_not_found_on_a_held_document_is_a_guess_with_the_count(tmp_path, monkeypatch):
    doc = _ingest(_pdf(tmp_path), monkeypatch)
    _finish(monkeypatch, doc)
    said = reading_state.not_found_words(doc, "not found")
    assert said.startswith("not found (a guess: 1 page")


# ---------------------------------------------------------------- rollback


def test_rollback_all_switches_off_a_held_document_goes_to_ready(tmp_path, monkeypatch):
    doc = _ingest(_pdf(tmp_path), monkeypatch)
    _finish(monkeypatch, doc)
    monkeypatch.setattr(settings, "ocr_file_error_hold_enabled", False)
    assert reading_state.release_held() == 1
    assert _status(doc) == states.READY


def test_rollback_with_the_one_meaning_switch_on_redecides_the_document(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    doc = _ingest(_pdf(tmp_path), monkeypatch)
    _finish(monkeypatch, doc)
    monkeypatch.setattr(settings, "ocr_file_error_hold_enabled", False)
    assert reading_state.release_held() == 1
    assert _status(doc) == states.READY
    assert reading_state.stored(doc)["ready"] is True


def test_this_switch_on_keeps_its_hold_when_the_one_meaning_switch_is_off(
    tmp_path, monkeypatch
):
    doc = _ingest(_pdf(tmp_path), monkeypatch)
    _finish(monkeypatch, doc)
    assert reading_state.release_held() == 0
    assert _status(doc) == states.PARTIALLY_SEARCHABLE
    assert reading_state.stored(doc) is not None


def test_a_hold_from_the_one_meaning_switch_is_released_when_only_this_switch_stays(
    tmp_path, monkeypatch
):
    doc = _ingest(_pdf(tmp_path), monkeypatch, failure="engine")
    _finish(monkeypatch, doc)
    conn = db.connect()
    reading_state._ensure_table(conn)
    with conn:
        conn.execute(
            "UPDATE documents SET status = ? WHERE id = ?",
            (states.PARTIALLY_SEARCHABLE, doc),
        )
        conn.execute(
            "INSERT INTO document_reading VALUES (?, ?, ?)",
            (doc, '{"unaccounted": 1, "ready": false}', NOW),
        )
    assert reading_state.release_held() == 1
    assert _status(doc) == states.READY
    assert reading_state.stored(doc) is None


def test_both_switches_on_nothing_is_released_or_decided_again(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "one_checked_definition_enabled", True)
    doc = _ingest(_pdf(tmp_path), monkeypatch)
    _finish(monkeypatch, doc)
    monkeypatch.setattr(reading_state, "finish_status", lambda _doc: pytest.fail("ran"))
    assert reading_state.release_held() == 0
    assert _status(doc) == states.PARTIALLY_SEARCHABLE
