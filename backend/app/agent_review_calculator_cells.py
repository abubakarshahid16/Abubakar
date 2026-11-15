"""What the calculator step does with a sheet's structure (owner, 12 Nov 2026; `redesign/TABLE-VALUE.md`; general: any sheet, no label or layout of one sheet).

  * `group_key` / `groups`: a sheet of several items (one tag per page, or two tags on one page) is checked PER TAG: facts are grouped by their tag, and where no
    tag can be told by the page, one group is one page. A check and a numeric pair run inside one group, so "two different values of the same field" can
    only be raised inside one group, and the line names its tag and page.
  * `settle`: a value held as "conflict" (`validation_state`) is looked at again by code. (1) Every other reading of the field stands under ANOTHER KNOWN tag (both tagged,
    the identifiers they name do not overlap): inside its own tag there is no conflict, so the hold is lifted and the line says why. A fact with no tag, or under a
    header that overlaps, never lifts a hold. (2) Two readings disagree inside one tag: they are NEVER settled into a value (the first value cell after a label reads no
    column header); at most the fact carries `reading_conflict`, the words naming both readings and the table cell beside the label, and the line is a question.
  * `cells_of`: the one cell of each fact's value on its page's stored tables, or the part of a compound row, with the plain words of the split.
Pure but for the facts and stored table rows it is given: no database, no model, no network. No document text is logged.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence

from . import numparse, table_cell

HELD = "conflict"


def group_key(fact: Mapping) -> str:
    tag = str(fact.get("equipment_tag") or "").strip()
    return tag if tag else f"page {fact.get('page')}"


def groups(facts: Sequence[Mapping]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for f in facts:
        out.setdefault(group_key(f), []).append(dict(f))
    return out


def _box(fact: Mapping) -> dict:
    try:
        got = json.loads(fact.get("bbox") or "{}")
    except (TypeError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _same_text(a: object, b: object) -> bool:
    return str(a or "").strip() == str(b or "").strip()


_TAG_ID = re.compile(r"[A-Za-z0-9]*\d[A-Za-z0-9\-/]*")


def _tag_ids(fact: Mapping) -> frozenset[str]:
    """The identifiers a tag names (tokens with a digit: "XV-101"), else the folded tag itself; empty when the fact has no tag."""
    tag = str(fact.get("equipment_tag") or "").strip()
    if not tag:
        return frozenset()
    ids = {t.lower() for t in _TAG_ID.findall(tag)}
    return frozenset(ids or {numparse.fold(tag)})


def other_tags(a: Mapping, b: Mapping) -> bool:
    """The two facts stand under DIFFERENT tags, both known: each has a tag and the identifiers they name do not overlap. A fact with no tag, or a header that
    names a tag the other also names, is never "another tag": a reading conflict with it stays a conflict."""
    ta, tb = _tag_ids(a), _tag_ids(b)
    if not (ta and tb) or ta & tb:
        return False
    # "V1" and "V1A": one identifier is the start of the other
    return not any(x.startswith(y) or y.startswith(x) for x in ta for y in tb)


def settle(
    fact: Mapping, facts: Sequence[Mapping], tables: Mapping[int, list]
) -> tuple[dict, str | None]:
    """(the fact the step uses, the plain words of a LIFT or None). A fact not held, or confirmed by an engineer, is returned as it is.
    A hold is LIFTED only when every other reading of the field stands under another KNOWN tag (`other_tags`: both tagged, different identifiers), and there is at
    least one; a tag-less fact, or one under a header that overlaps, never lifts it. Two readings inside one group are never settled into a value: at most the
    fact carries `reading_conflict`, the words naming both readings and the table cell beside the label (`_by_cell`), and the hold stays."""
    if str(fact.get("validation_state") or "").lower() != HELD or fact.get(
        "confirmed_by"
    ):
        return dict(fact), None
    box = _box(fact)
    by_id = {f.get("id"): f for f in facts}
    label = numparse.fold(str(fact.get("field_label") or ""))
    rivals = [by_id[i] for i in box.get("conflicts_with") or [] if i in by_id]
    other_pages = {p for p in box.get("conflict_pages") or [] if p != fact.get("page")}
    rivals += [
        f
        for f in facts
        if f.get("page") in other_pages
        and numparse.fold(str(f.get("field_label") or "")) == label
        and f.get("id") not in {r.get("id") for r in rivals}
    ]
    if rivals and all(other_tags(fact, r) for r in rivals):
        words = "the other readings of this field stand under other tags, so it is not a conflict within this tag"
        return {**fact, "validation_state": None, "settled_note": words}, words
    return _by_cell(fact, [r for r in rivals if not other_tags(fact, r)], tables), None


def _figure_in(cell: table_cell.Cell, raw: object) -> bool:
    """The cell holds exactly one number and it is the fact's value."""
    want = numparse.as_number(raw)
    nums = [
        n.value
        for n in numparse.find_numbers(numparse.fold(cell.value_text))
        if n.value is not None and not n.joined
    ]
    return want is not None and nums == [want]


def _by_cell(fact: Mapping, rivals: list[Mapping], tables: Mapping[int, list]) -> dict:
    """Two readings of one value: the fact WITH, when exactly one reading is a cell of the label's row, the words naming both readings and that cell. The hold
    stays: the cell is the first value cell after the label, with no column header read, so it settles nothing by itself (no Pass and no Fail from it)."""
    readings = [fact, *rivals]
    located = []
    for r in readings:
        cell, _why = table_cell.locate(
            tables.get(r.get("page")) or [],
            page=r.get("page") or 0,
            label=str(r.get("field_label") or ""),
            value_text=str(r.get("source_text") or ""),
        )
        if cell is not None and _figure_in(cell, r.get("raw_value")):
            located.append(r)
    if len(located) != 1 or not rivals:
        return dict(fact)
    kept = located[0]
    others = " and ".join(str(r.get("raw_value")) for r in readings if r is not kept)
    words = f"two readings: {kept.get('raw_value')} and {others}; the table cell beside the label holds {kept.get('raw_value')}; confirm"
    return {**fact, "reading_conflict": words}


def cell_of(
    fact: Mapping, tables: Mapping[int, list], page_tags: int = 1
) -> table_cell.Cell | None:
    """The one cell that is this fact's value, else None. A fact with a tag, on a page that holds several tags, on a table that has a column for it takes the cell where the label's row crosses that
    column, and only that; otherwise the label's own row (the value cell to its right), else the part of a compound row whose figure is the fact's number."""
    page, label, tag = (
        fact.get("page"),
        str(fact.get("field_label") or ""),
        str(fact.get("equipment_tag") or "").strip(),
    )
    if not isinstance(page, int) or fact.get("is_blank"):
        return None
    rows = tables.get(page) or []
    if (
        tag and page_tags >= 2
    ):  # several tags on this page: a column per tag is possible
        crossed, why = table_cell.locate_column(
            rows, page=page, label=label, header=tag
        )
        if crossed is not None or not why.startswith(table_cell.NO_HEADER):
            return (
                crossed
                if crossed is not None and _figure_in(crossed, fact.get("raw_value"))
                else None
            )
    cell, _why = table_cell.locate(
        rows, page=page, label=label, value_text=str(fact.get("source_text") or "")
    )
    if cell is not None:
        return cell
    comp, figure, _unit = table_cell.locate_compound(rows, page=page, label=label)
    if (
        comp is not None
        and numparse.as_number(figure) is not None
        and numparse.as_number(figure) == numparse.as_number(fact.get("raw_value"))
    ):
        return comp
    return None


def page_tag_counts(facts: Sequence[Mapping]) -> dict[object, int]:
    """page -> how many distinct tag groups have facts on it (several: a table may have a column per tag)."""
    tags: dict[object, set[str]] = {}
    for f in facts:
        tags.setdefault(f.get("page"), set()).add(group_key(f))
    return {p: len(t) for p, t in tags.items()}


def cells_of(
    facts: Sequence[Mapping], tables: Mapping[int, list], counts: Mapping[object, int]
) -> dict[str, table_cell.Cell]:
    """fact id -> its cell, for the facts that have exactly one (`counts` from `page_tag_counts` over ALL the paper's facts)."""
    return {
        str(f["id"]): c
        for f in facts
        if f.get("id")
        and (c := cell_of(f, tables, counts.get(f.get("page"), 1))) is not None
    }
