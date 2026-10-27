"""#525: a standalone PNG or JPEG is accepted at upload and becomes a one-page PDF with no text
layer, so everything after intake (extraction, OCR routing, page images, citations) sees a PDF.

Invented pictures only (drawn with PyMuPDF); no model, no OCR run."""

from __future__ import annotations

import hashlib
import io
import struct

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import extract, image_intake
from app.config import settings
from app.db import connect
from app.main import app
from app.upload import UploadError, ingest
from tests.test_upload import temp_storage  # noqa: F401 - autouse


def _picture(
    kind: str = "png", w: int = 300, h: int = 200, colour=(250, 250, 250)
) -> bytes:
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), False)
    pix.set_rect(pix.irect, colour)
    return pix.tobytes(kind)


def _post(data: bytes, name: str):
    return TestClient(app).post(
        "/api/documents",
        files={"file": (name, io.BytesIO(data), "application/octet-stream")},
    )


@pytest.mark.parametrize(("kind", "name"), [("png", "scan.png"), ("jpeg", "scan.jpg")])
def test_a_picture_is_stored_as_a_one_page_pdf_with_its_hash(kind, name):
    r = _post(_picture(kind), name)
    assert r.status_code == 200, r.text
    doc = r.json()["document"]
    assert doc["filename"] == "scan.pdf"
    stored = next(settings.upload_dir.glob("*.pdf")).read_bytes()
    assert stored.startswith(b"%PDF-")
    assert doc["sha256"] == hashlib.sha256(stored).hexdigest()
    assert doc["size_bytes"] == len(stored)
    with pymupdf.open("pdf", stored) as pdf:
        assert len(pdf) == 1 and pdf[0].get_text().strip() == ""


def test_the_same_picture_twice_is_one_document():
    data = _picture()
    first = _post(data, "a.png").json()
    second = _post(data, "b.png").json()
    assert second["duplicate_of"] == first["document"]["id"]
    assert len(list(settings.upload_dir.glob("*.pdf"))) == 1


def test_the_page_renders_at_the_pictures_own_pixels():
    pdf = pymupdf.open("pdf", image_intake.to_pdf_bytes(_picture(w=300, h=200)))
    pix = pdf[0].get_pixmap(dpi=int(settings.ocr_dpi))
    assert (pix.width, pix.height) == (300, 200)


def test_a_picture_page_has_no_text_so_it_goes_to_recognition(tmp_path):
    row, _job, _dup = ingest(io.BytesIO(_picture()), "scan.png")
    extract.extract_document(row["id"])
    page = (
        connect()
        .execute(
            "SELECT needs_ocr, char_count FROM pages WHERE document_id = ? AND page_no = 1",
            (row["id"],),
        )
        .fetchone()
    )
    assert page["needs_ocr"] == 1 and page["char_count"] == 0


def _png_claiming(w: int, h: int) -> bytes:
    real = bytearray(_picture())
    real[16:24] = struct.pack(">II", w, h)
    return bytes(real)


def test_a_picture_claiming_a_huge_canvas_is_refused_before_it_is_decoded():
    r = _post(_png_claiming(60_000, 60_000), "bomb.png")
    assert r.status_code == 400 and r.json()["code"] == "bad_image"
    assert list(settings.upload_dir.glob("*")) == []


def test_a_picture_claiming_no_size_is_refused():
    r = _post(_png_claiming(0, 0), "empty.png")
    assert r.status_code == 400 and r.json()["code"] == "bad_image"


def test_a_cut_off_picture_is_refused_by_name_and_nothing_is_stored():
    with pytest.raises(UploadError) as err:
        ingest(io.BytesIO(image_intake.PNG_MAGIC + b"\x00\x00"), "cut.png")
    assert err.value.code == "bad_image"
    assert list(settings.upload_dir.glob("*")) == []


def test_other_files_are_still_refused_as_not_a_pdf():
    r = _post(b"GIF89a....", "x.gif")
    assert r.status_code == 400 and r.json()["code"] == "not_pdf"


def test_the_header_size_reads_both_formats():
    assert image_intake.size_of(_picture("png", 123, 45)) == (123, 45)
    assert image_intake.size_of(_picture("jpeg", 123, 45)) == (123, 45)


@pytest.mark.parametrize(
    "cut",
    [
        b"\xff\xd8\xff\xc0\x00\x11\x08\x00",
        b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x10",
    ],
)
def test_a_jpeg_cut_inside_its_frame_header_is_refused_by_name(cut):
    with pytest.raises(image_intake.ImageRefused):
        image_intake.size_of(cut)
    with pytest.raises(UploadError) as err:
        ingest(io.BytesIO(cut), "cut.jpg")
    assert err.value.code == "bad_image"
    assert list(settings.upload_dir.glob("*")) == []


def _with_orientation(jpeg: bytes, orientation: int) -> bytes:
    tiff = b"MM\x00\x2a\x00\x00\x00\x08\x00\x01" + struct.pack(
        ">HHIHH", 0x0112, 3, 1, orientation, 0
    )
    body = b"Exif\x00\x00" + tiff + b"\x00\x00\x00\x00"
    return jpeg[:2] + b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body + jpeg[2:]


@pytest.mark.parametrize("share", [0.5, 0.99])
def test_a_jpeg_cut_off_short_of_its_end_is_refused_not_wrapped(share):
    data = _picture("jpeg", 400, 300)
    cut = data[: int(len(data) * share)]
    with pytest.raises(UploadError) as err:
        ingest(io.BytesIO(cut), "cut.jpg")
    assert err.value.code == "bad_image" and "cut off" in err.value.detail
    assert list(settings.upload_dir.glob("*")) == []


def test_a_png_cut_off_is_refused_too():
    data = _picture("png", 400, 300)
    with pytest.raises(UploadError) as err:
        ingest(io.BytesIO(data[: int(len(data) * 0.99)]), "cut.png")
    assert err.value.code == "bad_image"


def test_a_jpeg_with_zero_padding_after_its_end_is_taken():
    pdf = pymupdf.open("pdf", image_intake.to_pdf_bytes(_picture("jpeg") + b"\x00" * 8))
    assert len(pdf) == 1


@pytest.mark.parametrize(("orientation", "turn"), [(1, 0), (3, 180), (6, 90), (8, 270)])
def test_a_phone_photo_is_shown_upright_by_its_exif_turn(orientation, turn):
    photo = _with_orientation(_picture("jpeg", 300, 200), orientation)
    pdf = pymupdf.open("pdf", image_intake.to_pdf_bytes(photo))
    assert pdf[0].rotation == turn


def test_a_mirrored_photo_is_refused_by_name():
    photo = _with_orientation(_picture("jpeg"), 2)
    with pytest.raises(image_intake.ImageRefused, match="mirrored"):
        image_intake.to_pdf_bytes(photo)


def test_an_unreadable_exif_block_states_nothing():
    jpeg = _picture("jpeg")
    junk = b"Exif\x00\x00MM\x00\x2a\xff\xff\xff\xff"
    data = jpeg[:2] + b"\xff\xe1" + struct.pack(">H", len(junk) + 2) + junk + jpeg[2:]
    assert len(pymupdf.open("pdf", image_intake.to_pdf_bytes(data))) == 1
