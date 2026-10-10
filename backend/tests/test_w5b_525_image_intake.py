"""#525 (W5b-01): a scan sent as an image file takes the PDF path unchanged.

PNG, JPEG and TIFF are opened by PyMuPDF as documents (one page per frame),
so after upload nothing depends on the file type: the same pages, the same
recognition stage, the same chunks, the same page citations as a PDF with the
same content. INVENTED content only.

The OCR models are not in the cloud test environment, so recognition is a
FAKE engine here (it returns the invented sentence); everything around it -
rendering the image page, routing, storing, chunking - is the real code.

Mutations: M5701-M5711 (scripts/mutations/w5b_525_image_intake.py).
"""
from __future__ import annotations

import io
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import access, chunker, db, extract, keyword, ocr, upload
from app.config import settings
from app.main import app

SENTENCE = "The relief valve set pressure shall be 10 bar gauge at the inlet flange."


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "w5b525.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(settings, "image_input_enabled", True)
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    yield
    db.reset_connection()


class _Done:
    def __init__(self, value):
        self._value = value

    def result(self):
        return self._value


class _InlinePool:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def submit(self, fn, *args, **kwargs):
        return _Done(fn(*args, **kwargs))


class _FakeResult:
    def __init__(self, text):
        self.txts = [text]
        self.scores = [0.95]
        self.boxes = [[[0, 0], [10, 0], [10, 10], [0, 10]]]


@pytest.fixture
def pipeline(monkeypatch):
    """Extraction and recognition inline, with a fake engine that 'reads'
    SENTENCE off any rendered page image it is given."""
    seen: list[str] = []

    def engine(image_path):
        assert Path(image_path).exists(), "the image page was not rendered"
        seen.append(image_path)
        return _FakeResult(SENTENCE)

    monkeypatch.setattr(extract.cf, "ProcessPoolExecutor", _InlinePool)
    monkeypatch.setattr(ocr.cf, "ProcessPoolExecutor", _InlinePool)
    monkeypatch.setattr(ocr, "_build_engine", lambda: engine)
    return seen


def _text_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=300)
    page.insert_text((40, 80), SENTENCE, fontsize=11)
    out = doc.tobytes()
    doc.close()
    return out


def _scan(fmt: str, frames: int = 1, size=(800, 400)) -> bytes:
    images = [Image.new("L", size, color=255) for _ in range(frames)]
    buf = io.BytesIO()
    if frames > 1:
        images[0].save(buf, format=fmt, save_all=True, append_images=images[1:])
    else:
        images[0].save(buf, format=fmt)
    return buf.getvalue()


def _upload(data: bytes, name: str):
    return upload.ingest(io.BytesIO(data), name)


def _ingest(data: bytes, name: str) -> str:
    row, _job, _dup = _upload(data, name)
    extract.extract_document(row["id"])
    if db.connect().execute("SELECT 1 FROM pages WHERE document_id = ? AND needs_ocr = 1",
                            (row["id"],)).fetchone():
        ocr.recognise_document(row["id"])
    chunker.chunk_document(row["id"])
    return row["id"]


def _chunks(doc_id: str) -> list[tuple]:
    rows = db.connect().execute(
        "SELECT page_start, page_end, text FROM chunks WHERE document_id = ? AND retrievable = 1"
        " ORDER BY ordinal", (doc_id,)).fetchall()
    return [(r["page_start"], r["page_end"], " ".join(r["text"].split())) for r in rows]


# ------------------------------------------------------------------ upload


@pytest.mark.parametrize("fmt, kind, suffix", [
    ("PNG", upload.KIND_PNG, ".png"), ("JPEG", upload.KIND_JPEG, ".jpg"),
    ("TIFF", upload.KIND_TIFF, ".tif")])
def test_an_image_scan_is_accepted_and_queued_for_the_pdf_pipeline(fmt, kind, suffix):
    """THE MUTATION TARGET: before #525 every image was refused as not_pdf."""
    row, job, dup = _upload(_scan(fmt), f"scan.{fmt.lower()}")
    assert job is not None and dup is None, "an image scan was not queued"
    assert row["status"] == "queued"
    assert row["stored_path"].endswith(suffix)
    assert row["filename"].endswith(suffix)
    assert upload.detect_kind(Path(row["stored_path"])) == kind


def test_an_image_is_refused_when_image_input_is_off(monkeypatch):
    monkeypatch.setattr(settings, "image_input_enabled", False)
    with pytest.raises(upload.UploadError) as err:
        _upload(_scan("PNG"), "scan.png")
    assert err.value.code == "not_pdf"


def test_a_file_that_only_starts_like_an_image_is_refused_and_not_stored():
    with pytest.raises(upload.UploadError) as err:
        _upload(b"\x89PNG\r\n\x1a\n" + b"not an image at all" * 20, "fake.png")
    assert err.value.code == "not_image"
    assert not any(settings.upload_dir.glob("*.png"))


def test_an_image_larger_than_the_pixel_limit_is_refused_before_decoding(monkeypatch):
    monkeypatch.setattr(upload, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(upload.UploadError) as err:
        _upload(_scan("PNG", size=(20, 20)), "big.png")
    assert err.value.code == "not_image" and "400" not in err.value.message
    assert "pixels" in err.value.detail


def test_an_image_with_too_many_pages_is_refused(monkeypatch):
    monkeypatch.setattr(upload, "MAX_IMAGE_FRAMES", 1)
    with pytest.raises(upload.UploadError) as err:
        _upload(_scan("TIFF", frames=2), "two.tif")
    assert err.value.code == "not_image"


def test_every_frame_of_a_tiff_is_checked_against_the_pixel_limit(monkeypatch):
    small, large = Image.new("L", (5, 5), 255), Image.new("L", (30, 30), 255)
    buf = io.BytesIO()
    small.save(buf, format="TIFF", save_all=True, append_images=[large])
    monkeypatch.setattr(upload, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(upload.UploadError) as err:
        _upload(buf.getvalue(), "mixed.tif")
    assert "frame 2" in err.value.detail


def test_the_refusal_hint_names_images():
    assert "PNG, JPEG, TIFF" in upload.UNSUPPORTED_OFFICE_HINT


# ------------------------------------------------------------------ same pipeline


def test_an_image_page_has_no_text_layer_and_is_routed_to_recognition(pipeline):
    row, _job, _dup = _upload(_scan("PNG"), "scan.png")
    extract.extract_document(row["id"])
    pages = db.connect().execute(
        "SELECT page_no, needs_ocr, ocr_route FROM pages WHERE document_id = ?", (row["id"],)).fetchall()
    assert [(p["page_no"], p["needs_ocr"]) for p in pages] == [(1, 1)]
    assert "no_text_layer" in pages[0]["ocr_route"]


def test_a_multi_page_tiff_becomes_one_page_per_frame(pipeline):
    row, _job, _dup = _upload(_scan("TIFF", frames=3), "three.tif")
    extract.extract_document(row["id"])
    assert db.connect().execute("SELECT COUNT(*) FROM pages WHERE document_id = ?",
                                (row["id"],)).fetchone()[0] == 3


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "TIFF"])
def test_a_scan_and_a_pdf_with_the_same_content_yield_the_same_chunks_and_citations(fmt, pipeline):
    """The acceptance criterion: same blocks, same page citations."""
    pdf_id = _ingest(_text_pdf(), "same.pdf")
    scan_id = _ingest(_scan(fmt), f"same.{fmt.lower()}")
    assert pipeline, "the scan's page was never rendered for recognition"
    assert _chunks(pdf_id), "the text PDF produced no chunks"
    assert _chunks(scan_id) == _chunks(pdf_id)


def test_the_original_scan_is_served_as_an_image():
    row, _job, _dup = _upload(_scan("PNG"), "scan.png")
    res = TestClient(app).get(f"/api/documents/{row['id']}/original")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
