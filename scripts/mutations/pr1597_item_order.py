"""#1592 item c / PR 1597, the internal copy's Item No is the sheet order (crs_export is
danger zone): each entry undoes one decision; the test file must notice."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_crs_item_sheet_order.py"
_TAG = ("pr1597", "crs_item_order")
_E = APP / "crs_export.py"


def _m(n, desc, anchor, repl, kw):
    return Mutation(
        id=f"M1597-{n:02d}",
        phase=1597,
        description=desc,
        path=_E,
        anchor=anchor,
        replacement=repl,
        target=_T,
        keyword=kw,
        tags=_TAG,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "the issue copy prints a position, so a contractor can no longer quote the number",
        "        and copy == COPY_INTERNAL\n        and settings.crs_item_sheet_order_enabled\n",
        "        and settings.crs_item_sheet_order_enabled\n",
        "issue_copy_keeps",
    ),
    _m(
        2,
        "the switch is ignored: the sheet order prints with it off",
        "        and settings.crs_item_sheet_order_enabled\n    ):\n",
        "    ):\n",
        "switch_off",
    ),
    _m(
        3,
        "a numbered row keeps its jumping number with the switch on",
        '        return f"{n:03d}"\n',
        '        return crs_ref or f"{n:03d}"\n',
        "numbers_rows_in_sheet_order",
    ),
    _m(
        4,
        "the position prints with no Internal sheet to say the number",
        "        export_quality\n        and copy == COPY_INTERNAL\n",
        "        copy == COPY_INTERNAL\n",
        "without_the_quality_export",
    ),
    _m(
        5,
        "the view ignores the switch's function",
        '            "item_no": _item_no(crs_ref, n, copy, qon),\n',
        '            "item_no": crs_ref or n,\n',
        "numbers_rows_in_sheet_order",
    ),
)
