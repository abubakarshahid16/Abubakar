"""A standalone PNG or JPEG becomes a one-page PDF at intake (#525).

Everything after upload reads a PDF: extraction, the page ledger, OCR routing,
citations, page images. A scan sent as a picture file used to be refused as "not a
PDF". Wrapping it as a one-page PDF with no text layer sends it down the path every
scanned page already takes (the page has no text, so it is routed to recognition),
and nothing after intake depends on the file type.

NO LAYOUT, NO MODEL, NO NETWORK. The picture is embedded as it is; nothing is read
from it here. The stored file is the PDF, and its SHA-256 is the document's hash, so
the content-addressed store keeps its rule (a file's name is the hash of its bytes).
The PDF is written without a creation date or random id, so the same picture always
gives the same bytes and the same hash (a second upload is a duplicate).

BOUNDED. The pixel count is read from the file header and refused above `MAX_PIXELS`
BEFORE anything is decoded: a small file can claim a huge canvas. A file whose header
cannot be read, or that claims no size, is refused by name; nothing is stored.
"""

from __future__ import annotations

import struct
from pathlib import Path

from .config import settings

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
IMAGE_MAGICS = (PNG_MAGIC, JPEG_MAGIC)

#: A page of a scan at 600 dpi on A3 is about 70 million pixels; a picture larger than
#: this is refused rather than decoded.
MAX_PIXELS = 100_000_000

#: The largest picture file taken (read whole, unlike a PDF, which is streamed).
MAX_IMAGE_BYTES = 100 * 1024 * 1024

_JPEG_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


class ImageRefused(Exception):
    """The picture cannot be wrapped; `str(exc)` says why in plain words."""


def is_image(head: bytes) -> bool:
    return head.startswith(IMAGE_MAGICS)


def _png_size(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[12:16] != b"IHDR":
        raise ImageRefused("the PNG header could not be read")
    return struct.unpack(">II", data[16:24])


def _jpeg_size(data: bytes) -> tuple[int, int]:
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
        elif marker in _JPEG_SOF:
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return width, height
        elif marker == 0x01 or 0xD0 <= marker <= 0xD9:  # no length field
            i += 2
        else:
            i += 2 + struct.unpack(">H", data[i + 2 : i + 4])[0]
    raise ImageRefused("the JPEG header could not be read")


def size_of(data: bytes) -> tuple[int, int]:
    """(width, height) in pixels from the file header; decodes nothing."""
    try:
        return _png_size(data) if data.startswith(PNG_MAGIC) else _jpeg_size(data)
    except struct.error as exc:  # a header cut short inside a field
        raise ImageRefused("the picture header is cut short") from exc


def to_pdf_bytes(data: bytes) -> bytes:
    """The picture as a one-page PDF with no text layer, page sized so that rendering at the
    project's OCR dpi gives the picture's own pixels."""
    import pymupdf

    width, height = size_of(data)
    if width < 1 or height < 1:
        raise ImageRefused("the picture claims no size")
    if width * height > MAX_PIXELS:
        raise ImageRefused(
            f"the picture is {width} x {height} pixels; the limit is {MAX_PIXELS} in all"
        )
    scale = 72.0 / max(1, int(settings.ocr_dpi))
    try:
        doc = pymupdf.open()
        page = doc.new_page(width=width * scale, height=height * scale)
        page.insert_image(page.rect, stream=data)
        doc.set_metadata({})
        return doc.tobytes(deflate=True, garbage=4, no_new_id=True)
    except Exception as exc:  # any decoder failure is one named refusal
        raise ImageRefused("the picture could not be read as an image") from exc


def convert_file(path: Path) -> None:
    """Replace the picture at `path` by its one-page PDF, in place."""
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ImageRefused(
            f"the picture file is over {MAX_IMAGE_BYTES // (1024 * 1024)} MB"
        )
    path.write_bytes(to_pdf_bytes(path.read_bytes()))
