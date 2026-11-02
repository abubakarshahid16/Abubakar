"""A Word file's pictures, read by the local OCR engine (WORD_PAGE_MARKERS_ENABLED).

`docx_reader` reads text and tables; a picture holds neither. The project's only
local picture path is the OCR engine (`ocr._build_engine`: RapidOCR with vendored
models, in a child process). `ocr.recognise_batch` renders pages of a PDF, so it
cannot be handed a Word file; this gives the SAME engine the images themselves.

LOCAL ONLY. No Claude lane, no vision reader, no reader model, no socket. A read is
stored per file and picture number, so a repeat read costs nothing and asks nothing.

HONEST. A picture is read only when text came back (rule 4). No text, a format the
engine cannot open, a failure: no reading, and the reason is kept (never document
text). One picture failing is one picture, and a dead engine fails the pictures,
never the document. Text goes in the database and the local pages only; it is never logged.
"""

from __future__ import annotations

import concurrent.futures as cf
import functools
import hashlib
import os
import posixpath
import tempfile
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from . import docx_reader, errors
from .config import settings
from .db import connect
from .docx_pages import PICTURE_IMAGE, PictureReading

STATUS_READ = "read"
STATUS_NO_TEXT = "no_text"
STATUS_NOT_READABLE = "not_readable"
STATUS_FAILED = "failed"

#: Not asked again: the answer would be the same. A failure is asked again.
_FINAL = (STATUS_READ, STATUS_NO_TEXT, STATUS_NOT_READABLE)

WHY_TOO_BIG = "the image is over the recogniser's size limit"
WHY_OUTSIDE = "the picture points outside the file's media folder, so it is refused"
WHY_MISSING = "the picture's image is missing from the file"
WHY_NO_TEXT = "the recogniser found no text in it (a photo or a drawing with no words)"
#: One child process runs the batch, one picture at a time.
BATCH_TIMEOUT_S = 600
#: Past these a picture is not read, and says so (`intake` has the same pixel limit).
MAX_PICTURES = 200
MAX_IMAGE_PIXELS = 100_000_000


@functools.lru_cache(maxsize=32)
def _hash_of(path: str, _mtime_ns: int, _size: int) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256(path: str | os.PathLike) -> str:
    state = Path(path).stat()
    return _hash_of(str(path), state.st_mtime_ns, state.st_size)


def _ensure_table(conn) -> None:
    """Made on the first read: with the switch off, nothing here exists at all."""
    with conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS word_picture_readings (
                   file_sha256 TEXT NOT NULL,
                   picture_no  INTEGER NOT NULL,
                   status      TEXT NOT NULL,
                   text        TEXT NOT NULL DEFAULT '',
                   mean_conf   REAL,
                   seconds     REAL,
                   reason      TEXT,
                   engine      TEXT,
                   created_at  TEXT NOT NULL,
                   PRIMARY KEY (file_sha256, picture_no)
               )"""
        )


def stored_readings(path: str | os.PathLike) -> dict[int, PictureReading]:
    """What is stored for this file, by picture number. Nothing stored: nothing read."""
    conn = connect()
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'word_picture_readings'"
    ).fetchone():
        return {}
    rows = conn.execute(
        "SELECT picture_no, status, text, reason FROM word_picture_readings"
        " WHERE file_sha256 = ?",
        (_sha256(path),),
    ).fetchall()
    return {
        r["picture_no"]: PictureReading(
            (r["text"] or "") if r["status"] == STATUS_READ else "", r["reason"]
        )
        for r in rows
    }


def _readable(data: bytes) -> str | None:
    """Why the engine cannot be given these bytes, or None. Opens the header
    only, so a huge image costs nothing here."""
    import io

    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            kind = image.format or "unknown"
    except Image.DecompressionBombError:
        return WHY_TOO_BIG
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        return "its image format cannot be opened by the local recogniser"
    if kind in ("WMF", "EMF"):  # Pillow names them, on Windows only it can draw them
        return f"its image format ({kind}) cannot be opened by the local recogniser"
    if width * height > MAX_IMAGE_PIXELS:
        return WHY_TOO_BIG
    return None


def recognise_images(items: list[tuple[int, str]]) -> list[tuple]:
    """(picture number, image path) -> (number, text, mean confidence, seconds, error).
    Runs in a WORKER PROCESS, like `ocr.recognise_batch`, with the same engine."""
    from . import ocr

    try:
        engine = ocr._build_engine()
    except Exception as exc:  # noqa: BLE001 - recorded per picture: a missing model fails the pictures, not the document
        why = errors.fell_back(
            "word_pictures: no engine",
            exc,
            f"the recogniser could not start: {type(exc).__name__}",
        )
        return [(no, "", None, 0.0, why) for no, _ in items]
    out = []
    for no, image in items:
        started = time.perf_counter()
        try:
            result = engine(image)
            lines = list(result.txts) if result.txts else []
            scores = (
                [float(s) for s in result.scores] if result.scores is not None else []
            )
            mean = round(sum(scores) / len(scores), 4) if scores else None
            out.append(
                (
                    no,
                    "\n".join(lines),
                    mean,
                    round(time.perf_counter() - started, 3),
                    None,
                )
            )
        except Exception as exc:  # noqa: BLE001 - recorded per picture: one bad picture must not stop the others
            why = errors.fell_back(
                "word_pictures: one picture failed",
                exc,
                f"the recogniser failed on it: {type(exc).__name__}",
            )
            out.append((no, "", None, round(time.perf_counter() - started, 3), why))
    return out


def _recognise(items: list[tuple[int, str]]) -> list[tuple]:
    """`recognise_images` in a child: its memory goes back when it exits (see `ocr`)."""
    pool = None
    try:
        pool = cf.ProcessPoolExecutor(max_workers=1)
        return pool.submit(recognise_images, items).result(timeout=BATCH_TIMEOUT_S)
    except cf.TimeoutError:
        for proc in list(getattr(pool, "_processes", {}).values()):
            proc.kill()
        return [(no, "", None, 0.0, "the recogniser took too long") for no, _ in items]
    except Exception as exc:  # noqa: BLE001 - recorded per picture: a dead worker fails the pictures, not the document
        why = errors.fell_back(
            "word_pictures: no worker",
            exc,
            f"the recogniser could not run: {type(exc).__name__}",
        )
        return [(no, "", None, 0.0, why) for no, _ in items]
    finally:
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)


def _store(
    conn, sha: str, no: int, status: str, text: str, mean, seconds, reason
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO word_picture_readings"
        " (file_sha256, picture_no, status, text, mean_conf, seconds, reason, engine, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (
            sha,
            no,
            status,
            text,
            mean,
            seconds,
            reason,
            settings.ocr_rec_model,
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )


def _image_bytes(zf: zipfile.ZipFile, target: str) -> tuple[bytes | None, str | None]:
    """(image, why not). Only an entry of the media folder is ever read."""
    entry = posixpath.normpath(target)
    if not entry.startswith("word/media/"):
        return None, WHY_OUTSIDE
    try:
        return zf.read(entry), None
    except KeyError:
        return None, WHY_MISSING
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError) as exc:
        return (
            None,
            f"the picture's image could not be taken from the file: {type(exc).__name__}",
        )


def read_document(path: str | os.PathLike) -> dict:
    """Give this Word file's unread pictures to the local engine and store the
    answers. Counts only come back. Does nothing when the switch is off. Never
    fails the document: a picture not read is said, and reading carries on."""
    if not settings.word_page_markers_enabled:
        return {"asked": 0}
    try:
        return _read_pictures(path)
    except Exception as exc:  # noqa: BLE001 - logged; the pictures then read as not sent, and say so
        return errors.fell_back("word_pictures: pictures not read", exc, {"asked": 0})


def _read_pictures(path: str | os.PathLike) -> dict:
    sha = _sha256(path)
    conn = connect()
    _ensure_table(conn)
    done = {
        r["picture_no"]
        for r in conn.execute(
            "SELECT picture_no, status FROM word_picture_readings WHERE file_sha256 = ?",
            (sha,),
        )
        if r["status"] in _FINAL
    }
    pictures = docx_reader.read_structure(path, picture_readings={}).pictures
    todo = [p for p in pictures if p.kind == PICTURE_IMAGE and p.no not in done]
    over = todo[MAX_PICTURES:]
    todo = todo[:MAX_PICTURES]
    with conn:
        for pic in over:
            _store(
                conn,
                sha,
                pic.no,
                STATUS_FAILED,
                "",
                None,
                None,
                f"past the limit of {MAX_PICTURES} pictures read from one file",
            )
    if not todo:
        return {"asked": 0}
    with (
        tempfile.TemporaryDirectory(prefix="word-pictures-") as folder,
        zipfile.ZipFile(path) as zf,
    ):
        items: list[tuple[int, str]] = []
        refused: dict[int, str] = {}
        for pic in todo:
            data, why = _image_bytes(zf, pic.targets[0])
            why = why or _readable(data)
            if why:
                refused[pic.no] = why
                continue
            image = Path(folder) / f"{pic.no}{Path(pic.targets[0]).suffix.lower()}"
            image.write_bytes(data)
            items.append((pic.no, str(image)))
        rows = _recognise(items) if items else []
    with conn:
        for no, why in refused.items():
            _store(conn, sha, no, STATUS_NOT_READABLE, "", None, None, why)
        for no, text, mean, seconds, error in rows:
            text = (text or "").strip()
            if error:
                _store(conn, sha, no, STATUS_FAILED, "", mean, seconds, error)
            elif text:
                _store(conn, sha, no, STATUS_READ, text, mean, seconds, None)
            else:
                _store(conn, sha, no, STATUS_NO_TEXT, "", mean, seconds, WHY_NO_TEXT)
    return {"asked": len(items), "not_readable": len(refused)}
