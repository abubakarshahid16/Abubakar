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
  * the same column holds text in at least `MIN_FILLED_ABOVE` other rows, so it
    is demonstrably the answer column (a table with a single answer is not
    enough);
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
    if value.get("bbox") is None or value["text"]:
        return []
    column = value["column"]
    filled_above = sum(
        1
        for i, data in enumerate(table["rows"])
        if i != index
        and any(c["column"] == column and c["text"] for c in data["cells"])
    )
    if filled_above < MIN_FILLED_ABOVE:
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


def cell_is_bare(page: Any, box: list[float] | None) -> bool:
    """True when the cell holds no word, image or drawn shape, on an upright page."""
    from .geometry_reader import text_rotation

    if not box or int(page.rotation) != 0 or text_rotation(page) != 0:
        return False
    inner = _inside(box)
    if inner[2] <= inner[0] or inner[3] <= inner[1]:
        return False
    try:
        if any(_meets(inner, w[:4]) for w in page.get_text("words")):
            return False
        if any(_meets(inner, i["bbox"]) for i in page.get_image_info()):
            return False
        return not any(_meets(inner, d["rect"]) for d in page.get_drawings())
    except Exception as exc:  # noqa: BLE001 - a page that cannot be inspected proves nothing
        log.info(
            "geometry_blank_cells: page not inspected (%s); no blank",
            type(exc).__name__,
        )
        return False


def keep_bare(page: Any, rows: list[dict]) -> list[dict]:
    """`rows` without the empty-cell candidates the page does not confirm."""
    return [r for r in rows if not r.get("empty_cell") or cell_is_bare(page, r["bbox"])]
