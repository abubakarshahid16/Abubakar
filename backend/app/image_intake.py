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
#: The last bytes of a whole PNG (the IEND chunk with its checksum).
PNG_END = b"IEND\xaeB`\x82"
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


def _exif_orientation(data: bytes) -> int | None:
    """The EXIF orientation (1 to 8) of a JPEG, or None when it states none."""
    i = 2
    while i + 4 <= len(data) and data[i] == 0xFF:
        marker = data[i + 1]
        if marker == 0xDA:  # start of scan: no more header segments
            return None
        length = struct.unpack(">H", data[i + 2 : i + 4])[0]
        body = data[i + 4 : i + 2 + length]
        if marker == 0xE1 and body.startswith(b"Exif\x00\x00"):
            tiff = body[6:]
            end = "<" if tiff[:2] == b"II" else ">"
            first = struct.unpack(end + "I", tiff[4:8])[0]
            (count,) = struct.unpack(end + "H", tiff[first : first + 2])
            for n in range(count):
                at = first + 2 + 12 * n
                tag, _kind, _n = struct.unpack(end + "HHI", tiff[at : at + 8])
                if tag == 0x0112:
                    return struct.unpack(end + "H", tiff[at + 8 : at + 10])[0]
            return None
        i += 2 + length
    return None


#: EXIF orientation to the clockwise turn that shows the picture upright. 2, 4, 5 and 7 are
#: mirror images, which a scan never is: refused rather than read the wrong way round.
_TURN = {None: 0, 1: 0, 3: 180, 6: 90, 8: 270}


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
    turn = 0
    if data.startswith(PNG_MAGIC) and not data.rstrip(b"\x00").endswith(PNG_END):
        raise ImageRefused("the PNG ends early: the file looks cut off")
    if data.startswith(JPEG_MAGIC):
        if not data.rstrip(b"\x00").endswith(b"\xff\xd9"):
            raise ImageRefused("the JPEG ends early: the file looks cut off")
        try:
            orientation = _exif_orientation(data)
        except struct.error:
            orientation = None  # an unreadable tag states nothing
        if orientation not in _TURN:
            raise ImageRefused(
                "the picture is mirrored by its EXIF tag; it is not accepted"
            )
        turn = _TURN[orientation]
    scale = 72.0 / max(1, int(settings.ocr_dpi))
    try:
        doc = pymupdf.open()
        page = doc.new_page(width=width * scale, height=height * scale)
        page.insert_image(page.rect, stream=data)
        if turn:
            page.set_rotation(
                turn
            )  # a rotated phone photo shows upright, as the camera saw it
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
