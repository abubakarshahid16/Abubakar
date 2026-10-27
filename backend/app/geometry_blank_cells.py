"""A ruled, empty value cell beside a label is a blank field (order 228.9).

The label/value table path (`geometry_reader._label_value_rows`) used to skip a
row whose only text is its label. On a datasheet that prints a ruled cell for
every answer, a vendor who left the cell empty then looked the same as a row the
reader missed, and the review said "wording appears on page N: engineer to
check" for it. An EMPTY cell alone is still not evidence (a value drawn as an
image, or placed in another cell, looks the same), so a blank is emitted only on
evidence of the geometry:

  * the cell right of the label is a real cell of the table (it has a box) with
    no text;
  * at least `MIN_FILLED_ABOVE` other rows hold text in BOTH the label column
    and the answer column, so the pair is demonstrably label and answer
    (a table with a single answer is not enough), and the cell left of the
    label is filled or empty as it is in most of those rows (a wrapped value
    line or a note under an empty label cell is no label);
  * the page is upright, and no image, no drawn shape and no word lies inside
    the cell (`INSET` inside its rules).

The marker is "empty cell": nothing was drawn, so it is never "______".
Known limit: a section heading drawn as its own ruled label cell with an empty
neighbour looks the same as a blank; it becomes a blank fact for a field no
requirement or checklist item names, so nothing is compared against it.
Pure functions over a table dict and a `pymupdf.Page`; no model, no database.
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

MIN_FILLED_ABOVE = 2
INSET = 1.5
MARKER = "empty cell"


#: A fill darker than this (mean of its colour channels) is a mark on a cell, not a background.
DARK_FILL = 0.35
#: A rectangle at most this many times the cell's own area belongs to ONE cell; a background or a
#: band behind a row or the whole table is larger.
ONE_CELL = 2.5


def _holds(row_cells: list[dict], column: int) -> bool:
    return any(c["column"] == column and c["text"] for c in row_cells)


def _label_sits_where_labels_sit(
    cells: list[dict], at: int, paired: list[list[dict]]
) -> bool:
    """The cell to the left of the lone text is filled exactly as it is in the
    table's own label/value rows. A wrapped value line or a note in a row whose
    label cell is empty has an empty left neighbour where real labels have a
    filled one, and is then no label."""
    if at == 0:
        return True
    left = cells[at - 1]["column"]
    same = sum(
        1
        for row_cells in paired
        if _holds(row_cells, left) == bool(cells[at - 1]["text"])
    )
    return same * 2 > len(paired)


def _ends_in_a_bare_unit(text: str) -> bool:
    """A label of two or more words whose last word is a unit the table knows (two letters or more), NOT in brackets
    ("Design pressure barg"): the number may have been lost from a value pushed into the label cell,
    so the empty neighbour is not proof of a blank. A bracketed unit ("Design pressure (barg)") is
    an ordinary label qualifier and stays a label."""
    from . import claims

    words = text.split()
    last = words[-1].strip(",.;:") if words else ""
    if len(words) < 2 or last[:1] in "([" or last[-1:] in ")]":
        return False
    return len(last) >= 2 and claims.is_unit(last)


def rows(
    table: dict[str, Any], index: int, cells: list[dict], filled: list[int]
) -> list[dict]:
    """The blank row (as a one-item list, else []) for table row `index`
    (`cells` sorted by column, `filled` the indexes holding text). A candidate
    is confirmed against the page by `keep_bare`."""
    if len(filled) != 1 or filled[0] + 1 >= len(cells):
        return []
    label, value = cells[filled[0]], cells[filled[0] + 1]
    text = label["text"]
    if not text or not re.search(r"[^\W_\d]", text) or label.get("cut_word", False):
        return []
    # A value pushed into the label cell ("Design pressure 10 barg") is not a
    # label with an empty answer: a number in its last two words says so.
    if any(ch.isdigit() for word in text.split()[-2:] for ch in word):
        return []
    if _ends_in_a_bare_unit(text):
        return []
    if value.get("bbox") is None or value["text"]:
        return []
    column = value["column"]
    paired = [
        data["cells"]
        for i, data in enumerate(table["rows"])
        if i != index
        and _holds(data["cells"], label["column"])
        and _holds(data["cells"], column)
    ]
    if len(paired) < MIN_FILLED_ABOVE or not _label_sits_where_labels_sit(
        cells, filled[0], paired
    ):
        return []
    return [
        {
            "source": "table",
            "page": value["page"],
            "label": text,
            "label_text": "",
            "value_text": "",
            "value": None,
            "unit": None,
            "is_blank": True,
            "blank_marker": MARKER,
            "condition": None,
            "note": None,
            "bbox": value["bbox"],
            "label_bbox": label.get("bbox"),
            "position": None,
            "table_id": value["table_id"],
            "row": value["row"],
            "column": column,
            "column_label": "",
            "empty_cell": True,
        }
    ]


def _inside(box: list[float]) -> tuple[float, float, float, float]:
    return box[0] + INSET, box[1] + INSET, box[2] - INSET, box[3] - INSET


def _meets(a: tuple[float, float, float, float], b: Any) -> bool:
    return not (b[2] <= a[0] or b[0] >= a[2] or b[3] <= a[1] or b[1] >= a[3])


def _bounds(item: tuple) -> tuple[float, float, float, float] | None:
    """The box of one segment of a drawn path ("l" line, "re" rectangle, "qu"
    quad, "c" curve), or None for a kind this does not know."""
    kind, *points = item
    if kind == "re" or kind == "qu":
        r = points[0]
        r = r.rect if kind == "qu" else r
        return r.x0, r.y0, r.x1, r.y1
    if kind in ("l", "c"):
        xs, ys = [p.x for p in points], [p.y for p in points]
        return min(xs), min(ys), max(xs), max(ys)
    return None


def _area(box: tuple[float, float, float, float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _dark_over_one_cell(
    inner: tuple[float, float, float, float],
    box: tuple[float, float, float, float],
    drawing: dict,
) -> bool:
    """A SOLID DARK fill about the size of this one cell is a mark (a blacked-out or hatched-out cell
    reads "not applicable"), not the background behind a table. A light or mid fill stays a
    background: a shaded input cell is a cell to be filled."""
    fill = drawing.get("fill")
    if not fill or sum(fill) / len(fill) >= DARK_FILL:
        return False
    return _area(box) <= ONE_CELL * _area(inner)


def _marks_the_cell(inner: tuple[float, float, float, float], drawing: dict) -> bool:
    """A drawn path puts something IN the cell only through a SEGMENT that meets
    it. The bounding box of a whole path would not do: a table grid drawn as one
    path, or a fill behind the table, has a box that meets every cell. A segment
    that covers the whole cell and more is a background, not a mark; a segment
    of an unknown kind counts as a mark (the safe side)."""
    for item in drawing.get("items") or []:
        box = _bounds(item)
        if box is None:
            return True
        if not _meets(inner, box):
            continue
        covers = (
            box[0] <= inner[0]
            and box[1] <= inner[1]
            and box[2] >= inner[2]
            and box[3] >= inner[3]
        )
        if item[0] == "re" and covers and not _dark_over_one_cell(inner, box, drawing):
            continue
        return True
    return not drawing.get("items") and _meets(inner, drawing["rect"])


def _page_marks(page: Any) -> tuple[list, list, list] | None:
    """The page's words, images and drawings, read once; None when it cannot be
    inspected (a page that cannot be inspected proves nothing)."""
    try:
        return page.get_text("words"), page.get_image_info(), page.get_drawings()
    except Exception as exc:  # noqa: BLE001 - a page that cannot be inspected proves nothing
        log.info(
            "geometry_blank_cells: page not inspected (%s); no blank",
            type(exc).__name__,
        )
        return None


def _bare(marks: tuple[list, list, list], box: list[float] | None) -> bool:
    words, images, drawings = marks
    if not box:
        return False
    inner = _inside(box)
    if inner[2] <= inner[0] or inner[3] <= inner[1]:
        return False
    return not (
        any(_meets(inner, w[:4]) for w in words)
        or any(_meets(inner, i["bbox"]) for i in images)
        or any(_marks_the_cell(inner, d) for d in drawings)
    )


def cell_is_bare(page: Any, box: list[float] | None) -> bool:
    """True when the cell holds no word, image or drawn mark, on an upright page."""
    from .geometry_reader import text_rotation

    if int(page.rotation) != 0 or text_rotation(page) != 0:
        return False
    marks = _page_marks(page)
    return marks is not None and _bare(marks, box)


def keep_bare(page: Any, rows: list[dict]) -> list[dict]:
    """`rows` without the empty-cell candidates the page does not confirm. The
    page is inspected once, and only when there is a candidate."""
    from .geometry_reader import text_rotation

    if not any(r.get("empty_cell") for r in rows):
        return rows
    marks = None
    if int(page.rotation) == 0 and text_rotation(page) == 0:
        marks = _page_marks(page)
    return [
        r
        for r in rows
        if not r.get("empty_cell") or (marks is not None and _bare(marks, r["bbox"]))
    ]
