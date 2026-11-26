"""WHAT OF A DRAWING WAS READ (update 13, lead-4, 26 Nov 2026; builder H). A drawing PDF exported from CAD usually carries a text layer: its
title block, notes, tags and line numbers. The review reads that text; it does NOT read the drawing itself (lines, symbols, connections).
So, page by page, for a paper an ENGINEER CONFIRMED as a drawing (`document_kinds`, state confirmed; never a suggestion, a guess made
from page shapes, or the AI's naming inside the review):

  - a page with 20 to 49 characters of text is PICTURE ONLY: named as not read, waiting for the picture reading (J3, its switch off);
    (a page under 20 characters is named already by `unread`, as for every kind);
  - a page with 50 or more characters and a title block (3 or more title-block fields) or a drawn share of 25% or more of the page is
    reviewed on its text and title block and named "picture part not read".

THE PAGE TEST (upload only: it SUGGESTS "drawing" for an engineer to confirm, `doc_router`; it marks nothing in a review; update 13
review B2: a ruled table counts as drawn, so drawn share alone would call a form a drawing): a page is a DRAWING SHEET when its bottom
quarter (the sheet's title-block band) holds 3+ title-block fields, one of them a drawing number, AND the page is drawn over a quarter
of its area. A paper is suggested when more than half of its pages of 50+ characters are drawing sheets. A form's header sits at the
top and its revision footer names no drawing number.

Any other paper is untouched (its unread list is exactly as before: the Claude review of the scored kinds stays byte-identical). The
record is codes and page numbers only ("page 3: picture_part_not_read"), never text. Reads the stored file through pdf_guard; no model,
no network.
"""

from __future__ import annotations

import itertools
import logging
import re

log = logging.getLogger(__name__)

DRAWING_KIND = "drawing"
MIN_DRAWING_CHARS = 50
MIN_TITLE_FIELDS = 3
MIN_DRAWN_SHARE = 0.25
PICTURE_ONLY, PICTURE_PART = "drawing_picture_only", "picture_part_not_read"
#: The title-block field labels code looks for (whole words, any case).
TITLE_FIELDS = (
    r"\btitle\b",
    r"\b(?:drawing|dwg)\.?\s*(?:no|number)\b",
    r"\brev(?:ision)?\b",
    r"\bscale\b",
    r"\bdate\b",
    r"\bdrawn\b",
    r"\bchecked\b",
    r"\bapproved\b",
    r"\bsheet\b",
    r"\bproject\b",
)
_GRID = 40


def title_fields(text: str) -> int:
    low = str(text or "").lower()
    return sum(1 for rx in TITLE_FIELDS if re.search(rx, low))


#: The drawing number label of a title block (the field a form's revision footer does not carry).
DRAWING_NUMBER = TITLE_FIELDS[1]
SHEET_BAND = 0.25  # the bottom quarter of the page, as it is shown
LABEL_RIGHT = 0.5  # the drawing-number label sits in the right half of that band (the title-block corner)
MAX_GRID = 8.0  # body segments per position above which the body is a cell-by-cell table (real sheets 1.8-4.2; ruled forms ~15)


def is_drawing(conn, paper_id: str) -> bool:
    """An engineer confirmed the paper's kind as drawing (`document_kinds`, state confirmed). A suggestion never counts."""
    held = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'document_kinds'"
    ).fetchone()
    if held is None:
        return False
    row = conn.execute(
        "SELECT kind, state FROM document_kinds WHERE document_id = ?", (str(paper_id),)
    ).fetchone()
    return (
        row is not None
        and row[1] == "confirmed"
        and str(row[0] or "").lower() == DRAWING_KIND
    )


def is_sheet(page) -> bool:
    """A drawing sheet: the bottom quarter (as shown) holds 3+ title-block fields, its drawing-number label sits in the RIGHT half (the
    sheet's title-block corner; update 14 R3: a form's footer label sits anywhere), the page is drawn, and its body is not a regular
    cell-by-cell table (`grid_regularity`)."""
    import pymupdf

    r = page.rect

    def shown(
        rect,
    ):  # a band of the page as it is shown, in the page's own (unrotated) coordinates
        return rect * page.derotation_matrix if page.rotation else rect

    band = shown(pymupdf.Rect(r.x0, r.y1 - SHEET_BAND * r.height, r.x1, r.y1))
    low = str(page.get_text("text", clip=band) or "").lower()
    if not re.search(DRAWING_NUMBER, low) or title_fields(low) < MIN_TITLE_FIELDS:
        return False
    corner = shown(
        pymupdf.Rect(
            r.x0 + LABEL_RIGHT * r.width, r.y1 - SHEET_BAND * r.height, r.x1, r.y1
        )
    )
    if not re.search(
        DRAWING_NUMBER, str(page.get_text("text", clip=corner) or "").lower()
    ):
        return False
    return drawn_share(page) >= MIN_DRAWN_SHARE and grid_regularity(page) <= MAX_GRID


def grid_regularity(page) -> float:
    """Axis-aligned segments (lines and rectangle edges) of the page's BODY (15% to 75% of its height) per distinct position they sit
    on (2 pt). A table ruled cell by cell puts many segments on few grid positions (about 15); a drawing's lines sit at
    many positions (1.8 to 4.2 on the real set measured). 0 when the body holds no segment."""
    m = page.rotation_matrix if page.rotation else None
    r = page.rect
    y0, y1 = r.y0 + 0.15 * r.height, r.y1 - SHEET_BAND * r.height
    segs = []
    for path in page.get_drawings():
        for it in path.get("items", []):
            if it[0] == "l":
                segs.append((it[1], it[2]))
            elif it[0] == "re":
                q = it[1]
                a, b, c, d = q.tl, q.tr, q.br, q.bl
                segs += [(a, b), (b, c), (c, d), (d, a)]
    pos: set[tuple[str, int]] = set()
    n = 0
    for a, b in segs:
        if m is not None:
            a, b = a * m, b * m
        if not y0 <= (a.y + b.y) / 2 <= y1:
            continue
        if abs(a.y - b.y) < 0.5 and abs(a.x - b.x) > 1:
            pos.add(("h", round(a.y / 2)))
            n += 1
        elif abs(a.x - b.x) < 0.5 and abs(a.y - b.y) > 1:
            pos.add(("v", round(a.x / 2)))
            n += 1
    return n / len(pos) if pos else 0.0


def page_test(pages: dict, path) -> tuple[int, int]:
    """(drawing sheets, pages of 50+ characters). No file: no page is measured, so none passes."""
    texts = [
        n
        for n in sorted(pages)
        if len(str(pages.get(n) or "").strip()) >= MIN_DRAWING_CHARS
    ]
    if not texts or path is None:
        return 0, len(texts)
    from app import pdf_guard

    passed = 0
    with pdf_guard.opened(str(path)) as pdf:
        for n in texts:
            if 1 <= n <= pdf.page_count:
                with pdf_guard.held():
                    passed += is_sheet(pdf.load_page(n - 1))
    return passed, len(texts)


def looks_drawn(pages: dict, path) -> bool:
    """The page test: more than half of the pages of 50+ characters are drawing sheets."""
    passed, of = page_test(pages, path)
    return of > 0 and 2 * passed > of


def drawn_share(page) -> float:
    """The share of a 40 x 40 grid of the page that images or drawn vectors touch (a frame round the page marks only its edge cells)."""
    W, H = page.rect.width or 1, page.rect.height or 1
    cells: set[tuple[int, int]] = set()

    def seg(x0, y0, x1, y1):
        n = max(2, int(max(abs(x1 - x0) / W, abs(y1 - y0) / H) * _GRID * 2))
        for s in range(n + 1):
            x, y = x0 + (x1 - x0) * s / n, y0 + (y1 - y0) * s / n
            if 0 <= x <= W and 0 <= y <= H:
                cells.add(
                    (
                        min(_GRID - 1, int(x / W * _GRID)),
                        min(_GRID - 1, int(y / H * _GRID)),
                    )
                )

    def area(r):
        for i in range(
            max(0, int(r.x0 / W * _GRID)), min(_GRID, int(r.x1 / W * _GRID) + 1)
        ):
            for j in range(
                max(0, int(r.y0 / H * _GRID)), min(_GRID, int(r.y1 / H * _GRID) + 1)
            ):
                cells.add((i, j))

    for img in page.get_images(full=True):
        for r in page.get_image_rects(img[0]):
            r = r & page.rect
            if not r.is_empty:
                area(r)
    for path in page.get_drawings():
        filled = path.get("fill") is not None
        for it in path.get("items", []):
            if it[0] == "l":
                seg(it[1].x, it[1].y, it[2].x, it[2].y)
            elif it[0] == "c":
                for a, b in itertools.pairwise(it[1:5]):
                    seg(a.x, a.y, b.x, b.y)
            elif it[0] == "re":
                r = it[1]
                if filled and r.width * r.height < 0.9 * W * H:
                    area(r)
                elif not filled:
                    for (a, b), (c, d) in (
                        ((r.x0, r.y0), (r.x1, r.y0)),
                        ((r.x1, r.y0), (r.x1, r.y1)),
                        ((r.x1, r.y1), (r.x0, r.y1)),
                        ((r.x0, r.y1), (r.x0, r.y0)),
                    ):
                        seg(a, b, c, d)
    return len(cells) / (_GRID * _GRID)


def marks(conn, paper_id: str, paper, path, min_chars: int) -> list[dict]:
    """The drawing pages' entries for the unread list (pages of `min_chars` characters or more only; shorter ones are `unread`'s)."""
    if not is_drawing(conn, paper_id):
        return []
    import contextlib

    from app import pdf_guard

    out: list[dict] = []
    with contextlib.ExitStack() as stack:
        pdf = None  # opened once, only when a page has no title block, and closed under the guard's lock
        for n in sorted(paper.pages):
            text = str(paper.pages.get(n) or "").strip()
            if len(text) < min_chars:
                continue
            if len(text) < MIN_DRAWING_CHARS:
                out.append({"where": f"page {n}", "why": PICTURE_ONLY})
                continue
            drawn = title_fields(text) >= MIN_TITLE_FIELDS
            if not drawn and path is not None:
                if pdf is None:
                    pdf = stack.enter_context(pdf_guard.opened(str(path)))
                if n <= pdf.page_count:
                    with pdf_guard.held():
                        drawn = drawn_share(pdf.load_page(n - 1)) >= MIN_DRAWN_SHARE
            if drawn:
                out.append({"where": f"page {n}", "why": PICTURE_PART})
    return out
