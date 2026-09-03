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

from pathlib import Path

import fitz

from .config import settings


class PageOutOfRange(ValueError):
    pass


def cache_dir() -> Path:
    d = settings.data_dir / "page_images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_path(sha256: str, page_no: int, dpi: int) -> Path:
    return cache_dir() / f"{sha256[:16]}_p{page_no:05d}_{dpi}.png"


def render_page(document: dict, page_no: int, dpi: int = 150) -> Path:
    """Render one 1-based page to PNG, returning the cached path."""
    if page_no < 1:
        raise PageOutOfRange(f"page {page_no} is out of range")

    out = cache_path(document["sha256"], page_no, dpi)
    if out.exists() and out.stat().st_size > 0:
        return out

    pdf_path = document["stored_path"]
    with fitz.open(pdf_path) as doc:
        if page_no > doc.page_count:
            raise PageOutOfRange(
                f"page {page_no} is out of range (document has {doc.page_count})"
            )
        page = doc.load_page(page_no - 1)
        # 72 dpi is PDF user space; scale from there.
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72))
        pix.save(str(out))
    return out
