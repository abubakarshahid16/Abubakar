"""Page images for the AI reviewer: open_page also gives the page IMAGE when the lead can see images (ported from the
experiment's exp11/page_image.py).

  page_image(ref, page)      one page of a stored PDF as PNG bytes, long side <= MAX_LONG_SIDE px and at most MAX_PNG_BYTES,
                             cached on disk under the app's data folder (LOCAL). Renders with pymupdf through the app's own
                             `pdf_guard.open_pdf` lock, the same path `pageimage.render_page` uses.
  ImageToolBox(toolbox, lead_sees_images=...)
                             a thin wrapper: `run("open_page", ...)` returns open_page's own result unchanged plus, ONLY when
                             the flag is on, the PNG under the top-level key IMAGE_KEY (raw bytes, so the trace's string
                             walkers and JSON logs never see base64). Every other tool passes through.
  to_api_messages(messages)  `agent_claude.to_api_messages` with the image put back as a real image block inside the tool_result.
  image_tokens(images)       the app's own image rule (`claude_image_tokens.image_tokens`), never the base64 text length.

Rules kept: rule 5 (an image is attached only for a document in the toolbox's `allowed_document_ids`); the image is a VIEW
only - quotes are still verified by code against the stored page text, so an image never makes a verdict more confident; no
document text, filename or path in any return value or error (ids and page numbers only); rule 13 (no per-layout code).
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

#: Claude's image guidance: images over ~1568 px on the long side are scaled down server side, and one image may be
#: at most 5 MB (base64). We stay under both with margin.
MAX_LONG_SIDE = 1500
MAX_PNG_BYTES = 3_000_000
#: The render is never sharper than this, so a small page is not blown up into a huge PNG.
MAX_DPI = 200
#: Shrink step when a PNG is still too large.
SHRINK = 0.8
#: Top-level key on a tool result that holds the image (beside ok / result / cites; never inside 'result').
IMAGE_KEY = "page_image"
MEDIA_TYPE = "image/png"

#: Which leads can see an image. Unknown leads are text-only (the safer default: nothing extra is sent).
LEADS_THAT_SEE_IMAGES = ("claude",)


class PageImageUnavailable(Exception):
    """No image for this page. `.reason` is a fixed code word, never document text or a path."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def lead_sees_images(lead: str | None) -> bool:
    """True for a Claude lead, False for a local text-only model or anything unknown."""
    name = (lead or "").strip().lower()
    return any(
        name == k or name.startswith(k + "-") or name.startswith(k + ":")
        for k in LEADS_THAT_SEE_IMAGES
    )


# ------------------------------------------------------------------ finding the stored PDF


def document_ref(conn: sqlite3.Connection, document_id: str) -> dict:
    """The row fields needed to find a document's PDF: id, sha256, stored_path, pagination. Read only."""
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    row = cursor.execute(
        "SELECT id, sha256, stored_path, pagination FROM documents WHERE id = ?",
        (document_id,),
    ).fetchone()
    if row is None:
        raise PageImageUnavailable("document_not_found")
    return dict(row)


def default_cache_dir() -> Path:
    """Where rendered pages are cached: under the app's data folder, never git."""
    from .config import settings

    return Path(settings.data_dir) / "agent_reviews" / "page-cache"


def pdf_path(ref: Mapping, data_dir: str | os.PathLike) -> Path:
    """This machine's file for a stored_path, by the same rule as `stored_paths.local` but against `data_dir`
    (a DB copy's paths may be relative or written on another machine)."""
    from . import stored_paths

    value = ref.get("stored_path")
    if not value:
        raise PageImageUnavailable("no_stored_file")
    base = Path(data_dir)
    absolute, parts = stored_paths._parts(str(value))
    if not absolute:
        candidate = base.joinpath(*parts)
        if candidate.is_file():
            return candidate
        raise PageImageUnavailable("stored_file_missing")
    if Path(str(value)).is_file():
        return Path(str(value))
    for start in range(
        len(parts)
    ):  # written on another machine: the longest tail that exists under data_dir
        candidate = base.joinpath(*parts[start:])
        if candidate.is_file():
            return candidate
    raise PageImageUnavailable("stored_file_missing")


# ------------------------------------------------------------------ rendering


def _cache_file(cache_dir: Path, key: str, page: int, long_side: int) -> Path:
    return cache_dir / f"{key[:16]}_p{page:05d}_L{long_side}.png"


def _write_atomic(out: Path, data: bytes) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _render(path: Path, page: int, long_side: int, max_bytes: int) -> bytes:
    import pymupdf

    from .pdf_guard import open_pdf

    try:
        with open_pdf(str(path)) as doc:
            if page > doc.page_count:
                raise PageImageUnavailable("page_out_of_range")
            pg = doc.load_page(page - 1)
            rect = pg.rect
            longest = max(rect.width, rect.height)
            if longest <= 0:
                raise PageImageUnavailable("page_has_no_size")
            scale = min(MAX_DPI / 72.0, long_side / longest)
            while True:
                pix = pg.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                data = pix.tobytes("png")
                if len(data) <= max_bytes:
                    return data
                if (
                    max(pix.width, pix.height) < 400
                ):  # never shrink into an unreadable thumbnail
                    raise PageImageUnavailable("page_image_too_large")
                scale *= SHRINK
    except PageImageUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001  a broken file is "no image", never a crash; only the class is kept
        raise PageImageUnavailable(f"render_failed:{type(exc).__name__}") from None


def page_image(
    ref: Mapping,
    page: int,
    *,
    data_dir: str | os.PathLike | None = None,
    cache_dir: str | os.PathLike | None = None,
    long_side: int = MAX_LONG_SIDE,
    max_bytes: int = MAX_PNG_BYTES,
) -> bytes:
    """One 1-based page as PNG bytes, long side <= `long_side`, size <= `max_bytes`, cached on disk.

    `ref` is a document row (`document_ref`: needs `stored_path`; `sha256` and `pagination` used when present). `data_dir` is where relative stored paths live (default: the app's `settings.data_dir`).
    Raises PageImageUnavailable with a code word when there is no image to give.
    """
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise PageImageUnavailable("page_number_invalid")
    if (
        ref.get("pagination") or ""
    ) == "flow":  # a Word document has no printed pages (as the page-image route)
        raise PageImageUnavailable("no_printed_pages")
    if data_dir is None:
        from .config import settings

        data_dir = settings.data_dir
    path = pdf_path(ref, data_dir)
    key = ref.get("sha256") or hashlib.sha256(path.read_bytes()).hexdigest()
    cache = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    out = _cache_file(cache, str(key), page, int(long_side))
    if out.is_file() and 0 < out.stat().st_size <= max_bytes:
        return out.read_bytes()
    data = _render(path, page, int(long_side), int(max_bytes))
    _write_atomic(out, data)
    return data


def image_source(
    open_conn: Callable[[], sqlite3.Connection] | None = None,
    data_dir: str | os.PathLike | None = None,
    cache_dir: str | os.PathLike | None = None,
) -> Callable[[str, int], bytes]:
    """A (doc id, page) -> PNG function; the document rows are looked up once each, through `open_conn()` (default: the
    app's own `db.connect`, thread-local, never closed here)."""
    refs: dict[str, dict] = {}

    def source(doc: str, page: int) -> bytes:
        if doc not in refs:
            if open_conn is None:
                from . import db

                refs[doc] = document_ref(db.connect(), doc)
            else:
                refs[doc] = document_ref(open_conn(), doc)
        return page_image(refs[doc], page, data_dir=data_dir, cache_dir=cache_dir)

    return source


# ------------------------------------------------------------------ the open_page wrapper


def png_size(data: bytes) -> tuple[int, int]:
    """(width, height) from the PNG header."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a png")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def open_page_with_image(
    toolbox: Any,
    doc: object = None,
    page: object = None,
    *,
    lead_sees_images: bool,
    image_for: Callable[[str, int], bytes],
) -> dict:
    """`toolbox.open_page(doc, page)` unchanged, plus the page image under IMAGE_KEY when the lead can see images.

    The image is attached only when open_page itself named an in-scope document and page (also when the page has
    no readable text: that is when the image helps most). A refusal never gets an image. `result['image']` says
    'attached' or 'not_available:<code>' so the lead knows; with the flag off nothing is added at all.
    """
    res = (
        toolbox.run("open_page", {"doc": doc, "page": page})
        if hasattr(toolbox, "run")
        else toolbox.open_page(doc, page)
    )
    return _add_image(
        toolbox, res, lead_sees_images=lead_sees_images, image_for=image_for
    )


def _add_image(
    toolbox: Any,
    res: Any,
    *,
    lead_sees_images: bool,
    image_for: Callable[[str, int], bytes],
) -> Any:
    if not lead_sees_images or not isinstance(res, dict):
        return res
    inner = res.get("result")
    if not isinstance(inner, dict) or "refused" in inner:
        return res
    doc, number = inner.get("doc"), inner.get("page")
    allowed = getattr(
        getattr(toolbox, "ctx", None), "allowed_document_ids", frozenset()
    )
    if not isinstance(doc, str) or doc not in allowed or not isinstance(number, int):
        return res  # rule 5: never an image of a document outside the scope
    out = {**res, "result": dict(inner)}
    try:
        data = image_for(doc, number)
        png_size(data)
    except PageImageUnavailable as exc:
        out["result"]["image"] = f"not_available:{exc.reason}"
        return out
    except Exception as exc:  # noqa: BLE001  the text result still stands
        recorded = type(exc).__name__  # only the class is recorded
        out["result"]["image"] = f"not_available:error_{recorded}"
        return out
    out["result"]["image"] = "attached"
    out[IMAGE_KEY] = {"media_type": MEDIA_TYPE, "png": data, "doc": doc, "page": number}
    return out


class ImageToolBox:
    """Wraps an `agent_tools.ToolBox`: open_page gains the image when `lead_sees_images`; everything else delegates."""

    def __init__(
        self,
        toolbox: Any,
        *,
        lead_sees_images: bool,
        image_for: Callable[[str, int], bytes],
    ) -> None:
        self._inner = toolbox
        self.lead_sees_images = bool(lead_sees_images)
        self._image_for = image_for
        self.images_attached = 0

    def __getattr__(
        self, name: str
    ) -> Any:  # ctx, TOOL_SPECS, set_item, compare_failures, ...
        return getattr(self._inner, name)

    def run(self, name: str, args: object) -> dict:
        res = self._inner.run(name, args)
        if name != "open_page":
            return res
        out = _add_image(
            self._inner,
            res,
            lead_sees_images=self.lead_sees_images,
            image_for=self._image_for,
        )
        if isinstance(out, dict) and IMAGE_KEY in out:
            self.images_attached += 1
        return out

    def open_page(self, doc: object = None, page: object = None) -> dict:
        return open_page_with_image(
            self._inner,
            doc,
            page,
            lead_sees_images=self.lead_sees_images,
            image_for=self._image_for,
        )


# ------------------------------------------------------------------ to the Claude API


def image_tokens(images: Mapping[int, bytes]) -> int:
    """Input tokens of page images by the app's own image rule (`claude_image_tokens`: size read from the PNG header, scaled to
    the long-edge limit, width x height / 750, never the base64 text length, never 0)."""
    from .claude_image_tokens import image_tokens as rule

    total = 0
    for data in images.values():
        try:
            w, h = png_size(data)
        except ValueError:
            w = h = 0  # the rule counts an unreadable size as the maximum
        total += rule(w, h)
    return total


def image_block(image: Mapping) -> dict:
    import base64

    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": image.get("media_type") or MEDIA_TYPE,
            "data": base64.b64encode(image["png"]).decode("ascii"),
        },
    }


def strip_images(messages: list[dict]) -> list[dict]:
    """The loop messages with every IMAGE_KEY removed (for logs, checkpoints or a text-only lead)."""
    out = []
    for m in messages or []:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, dict) and IMAGE_KEY in content:
            m = {**m, "content": {k: v for k, v in content.items() if k != IMAGE_KEY}}
        out.append(m)
    return out


def to_api_messages(
    messages: list[dict], *, keep_last: int | None = None
) -> tuple[list[dict], list[str]]:
    """`agent_claude.to_api_messages`, with each tool result's image put in its tool_result as an image block.

    `keep_last`: only the last N images are sent (older ones become the text note 'image shown earlier'), so a long
    item does not resend every page it opened; None sends all.
    """
    from . import agent_claude

    api, system = agent_claude.to_api_messages(strip_images(messages))
    # agent_claude.to_api_messages emits exactly one message per non-system loop message, in order.
    plain = [
        m
        for m in (messages or [])
        if not (isinstance(m, dict) and m.get("role") == "system")
    ]
    if len(plain) != len(
        api
    ):  # the shape changed under us: send no images rather than misplace one
        return api, system
    with_image = [
        i
        for i, m in enumerate(plain)
        if m.get("role") == "tool"
        and isinstance(m.get("content"), dict)
        and IMAGE_KEY in m["content"]
    ]
    send = set(
        with_image
        if keep_last is None
        else with_image[len(with_image) - keep_last :]
        if keep_last > 0
        else []
    )
    for i in with_image:
        blocks = api[i]["content"]
        if not blocks or blocks[0].get("type") != "tool_result":
            continue
        first = dict(blocks[0])
        text = first.get("content")
        parts = [
            {"type": "text", "text": text if isinstance(text, str) and text else "."}
        ]
        if i in send:
            parts.append(image_block(plain[i]["content"][IMAGE_KEY]))
        else:
            parts.append({"type": "text", "text": "image shown earlier"})
        first["content"] = parts
        api[i] = {**api[i], "content": [first, *blocks[1:]]}
    return api, system


__all__ = [
    "IMAGE_KEY",
    "MAX_LONG_SIDE",
    "MAX_PNG_BYTES",
    "ImageToolBox",
    "PageImageUnavailable",
    "document_ref",
    "image_source",
    "image_tokens",
    "lead_sees_images",
    "open_page_with_image",
    "page_image",
    "pdf_path",
    "png_size",
    "strip_images",
    "to_api_messages",
]
