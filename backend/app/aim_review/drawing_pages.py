"""WHAT OF A DRAWING WAS READ (update 13, lead-4, 26 Nov 2026; builder H). A drawing PDF exported from CAD usually carries a text layer: its
title block, notes, tags and line numbers. The review reads that text; it does NOT read the drawing itself (lines, symbols, connections).
So, page by page, for a paper the app recorded as a DRAWING before the review (`agent_review_kind.read_kind`: the engineer's confirmed
kind, else the code's reading of the cover and title; never the AI's naming inside the review):

  - a page with 20 to 49 characters of text is PICTURE ONLY: named as not read, waiting for the picture reading (J3, its switch off);
    (a page under 20 characters is named already by `unread`, as for every kind);
  - a page with 50 or more characters and a title block (3 or more title-block fields) or a drawn share of 25% or more of the page is
    reviewed on its text and title block and named "picture part not read".

Any other kind is untouched (its unread list is exactly as before: the Claude review of the scored kinds stays byte-identical). The record is
codes and page numbers only ("page 3: picture_part_not_read"), never text. Reads the stored file through pdf_guard; no model, no network.
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


def is_drawing(conn, paper_id: str) -> bool:
    """The kind the app recorded for the paper BEFORE the review: drawing, and known (never a guess made inside the review)."""
    from app import agent_review_kind

    got = agent_review_kind.read_kind(conn, str(paper_id)) or {}
    return bool(got.get("known")) and got.get("kind") == DRAWING_KIND


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
