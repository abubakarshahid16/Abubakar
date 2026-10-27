"""On-demand page rendering.

PyMuPDF text extraction loses `=` and `+` from equations and flattens table
column pairing. Neither is fixable in text mode, and re-implementing a PDF
layout engine is out of scope. The durable answer is to show the reader the
real page next to the quoted text: whatever the extraction lost, the page
image still has it.

Renders are cached on disk under the document's content hash, so the same
page is only rasterised once.
"""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

import pymupdf

from . import stored_paths
from .config import settings
from .pdf_guard import open_pdf


class PageOutOfRange(ValueError):
    pass


def cache_dir() -> Path:
    d = settings.data_dir / "page_images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_path(sha256: str, page_no: int, dpi: int, mark: str = "") -> Path:
    """`mark` distinguishes a highlighted render from a plain one.

    It is a hash of the rectangles, so the same answer on the same page reuses
    its render and a different answer on that page gets its own - the cache
    key has to include what was drawn, or the second question would be served
    the first question's box.
    """
    suffix = f"_{mark}" if mark else ""
    return cache_dir() / f"{sha256[:16]}_p{page_no:05d}_{dpi}{suffix}.png"


def _save_png(pix, out: Path) -> None:
    """Write the PNG to a private temp file, then move it into place in one step: two requests
    rendering the same page must never serve a half-written file (order 252)."""
    tmp = out.with_name(f".{out.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_bytes(pix.tobytes("png"))
        tmp.replace(out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def render_page(document: dict, page_no: int, dpi: int = 150) -> Path:
    """Render one 1-based page to PNG, returning the cached path."""
    if page_no < 1:
        raise PageOutOfRange(f"page {page_no} is out of range")

    out = cache_path(document["sha256"], page_no, dpi)
    if out.exists() and out.stat().st_size > 0:
        return out

    pdf_path = stored_paths.local(document["stored_path"])
    with open_pdf(pdf_path) as doc:
        if (
            out.exists() and out.stat().st_size > 0
        ):  # another request rendered it while we waited
            return out
        if page_no > doc.page_count:
            raise PageOutOfRange(
                f"page {page_no} is out of range (document has {doc.page_count})"
            )
        page = doc.load_page(page_no - 1)
        # 72 dpi is PDF user space; scale from there.
        pix = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72))
        _save_png(pix, out)
        del pix, page  # freed while the lock is still held
    return out


#: Drawn as an outline with a light wash rather than a solid fill, so the text
#: underneath stays readable - the point is to show the reader the words, not
#: to cover them.
HIGHLIGHT_STROKE = (0.18, 0.62, 0.56)
HIGHLIGHT_FILL = (0.18, 0.62, 0.56)
HIGHLIGHT_FILL_OPACITY = 0.18
HIGHLIGHT_WIDTH = 1.4
#: Grown slightly so the box sits around the text rather than clipping it.
HIGHLIGHT_PADDING = 1.5


def render_page_with_highlight(
    document: dict,
    page_no: int,
    rects: list[tuple[float, float, float, float]],
    dpi: int = 150,
) -> Path:
    """Render a page with the answer boxed on the image itself.

    Boxing on the RENDER rather than overlaying in the browser keeps the
    geometry in PDF user space, where the rectangles were measured. Overlaying
    in CSS would mean reproducing the page-to-image transform in a second
    place, and any drift between the two would draw the box slightly off - on
    a dense specification table, slightly off is the wrong row.
    """
    if not rects:
        return render_page(document, page_no, dpi=dpi)

    mark = hashlib.sha256(
        repr([tuple(round(v, 2) for v in r) for r in rects]).encode()
    ).hexdigest()[:12]
    out = cache_path(document["sha256"], page_no, dpi, mark=mark)
    if out.exists() and out.stat().st_size > 0:
        return out

    with open_pdf(stored_paths.local(document["stored_path"])) as doc:
        if (
            out.exists() and out.stat().st_size > 0
        ):  # another request rendered it while we waited
            return out
        if not 1 <= page_no <= doc.page_count:
            raise PageOutOfRange(
                f"page {page_no} is out of range (document has {doc.page_count})"
            )
        page = doc.load_page(page_no - 1)
        shape = page.new_shape()
        for x0, y0, x1, y1 in rects:
            box = pymupdf.Rect(x0, y0, x1, y1) + (
                -HIGHLIGHT_PADDING,
                -HIGHLIGHT_PADDING,
                HIGHLIGHT_PADDING,
                HIGHLIGHT_PADDING,
            )
            shape.draw_rect(box)
        shape.finish(
            color=HIGHLIGHT_STROKE,
            fill=HIGHLIGHT_FILL,
            fill_opacity=HIGHLIGHT_FILL_OPACITY,
            width=HIGHLIGHT_WIDTH,
        )
        shape.commit()
        pix = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72))
        _save_png(pix, out)
        del pix, page  # freed while the lock is still held
    return out


#: #967: the Sheet's underline colours, by the card's state - amber needs
#: you, grey is answered - the same two the list under the page uses.
MARK_COLOURS = {
    "open": (0.96, 0.62, 0.04),
    # #1003: a safety tick's value, green like its card; checked by eye, not a comment.
    "tick": (0.13, 0.77, 0.37),
    "answered": (0.55, 0.58, 0.62),
}
MARK_WIDTH = 2.2
#: The underline sits just under the text's baseline box.
MARK_DROP = 1.5


def render_page_with_marks(
    document: dict,
    page_no: int,
    marks: list[tuple[list[tuple[float, float, float, float]], str]],
    dpi: int = 150,
) -> Path:
    """#967: render a page with EVERY card's value underlined on it, each in
    the colour of its card's state (`MARK_COLOURS`).

    Same rule as `render_page_with_highlight`: the marks are drawn on the
    render, in PDF user space where the rectangles were measured, never
    overlaid in the browser. The cache key hashes the rectangles AND the
    states, so answering a card re-renders the page with its mark grey.
    A page with no placeable mark is the plain render.
    """
    drawn = [(rects, state) for rects, state in marks if rects]
    if not drawn:
        return render_page(document, page_no, dpi=dpi)
    unknown = {state for _, state in drawn} - set(MARK_COLOURS)
    if unknown:
        raise ValueError(f"unknown mark state(s): {sorted(unknown)}")
    mark = hashlib.sha256(
        repr(
            [
                ([tuple(round(v, 2) for v in r) for r in rects], state)
                for rects, state in drawn
            ]
        ).encode()
    ).hexdigest()[:12]
    out = cache_path(document["sha256"], page_no, dpi, mark=f"m{mark}")
    if out.exists() and out.stat().st_size > 0:
        return out
    with open_pdf(stored_paths.local(document["stored_path"])) as doc:
        if (
            out.exists() and out.stat().st_size > 0
        ):  # another request rendered it while we waited
            return out
        if not 1 <= page_no <= doc.page_count:
            raise PageOutOfRange(
                f"page {page_no} is out of range (document has {doc.page_count})"
            )
        page = doc.load_page(page_no - 1)
        for state, colour in MARK_COLOURS.items():
            shape = page.new_shape()
            for rects, mark_state in drawn:
                if mark_state != state:
                    continue
                for x0, _y0, x1, y1 in rects:
                    shape.draw_line((x0, y1 + MARK_DROP), (x1, y1 + MARK_DROP))
            shape.finish(color=colour, width=MARK_WIDTH)
            shape.commit()
        pix = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72))
        _save_png(pix, out)
        del pix, page  # freed while the lock is still held
    return out
