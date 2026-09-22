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
from pathlib import Path

import pymupdf

from .config import settings


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


def render_page(document: dict, page_no: int, dpi: int = 150) -> Path:
    """Render one 1-based page to PNG, returning the cached path."""
    if page_no < 1:
        raise PageOutOfRange(f"page {page_no} is out of range")

    out = cache_path(document["sha256"], page_no, dpi)
    if out.exists() and out.stat().st_size > 0:
        return out

    pdf_path = document["stored_path"]
    with pymupdf.open(pdf_path) as doc:
        if page_no > doc.page_count:
            raise PageOutOfRange(
                f"page {page_no} is out of range (document has {doc.page_count})"
            )
        page = doc.load_page(page_no - 1)
        # 72 dpi is PDF user space; scale from there.
        pix = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72))
        pix.save(str(out))
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

    with pymupdf.open(document["stored_path"]) as doc:
        if not 1 <= page_no <= doc.page_count:
            raise PageOutOfRange(
                f"page {page_no} is out of range (document has {doc.page_count})"
            )
        page = doc.load_page(page_no - 1)
        shape = page.new_shape()
        for x0, y0, x1, y1 in rects:
            box = pymupdf.Rect(x0, y0, x1, y1) + (
                -HIGHLIGHT_PADDING, -HIGHLIGHT_PADDING,
                HIGHLIGHT_PADDING, HIGHLIGHT_PADDING,
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
        pix.save(str(out))
    return out
