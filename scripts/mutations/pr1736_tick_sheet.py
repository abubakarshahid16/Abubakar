"""Owner order 11 Nov 2026, step 1 (#805): behind CRS_ROUTING_BY_HOLD_REASON_ENABLED (off), the safety-tick
rows leave the internal CRS sheet for their own sheet, "Passed by a tested rule: engineer to tick"; the
contractor copy never carries them; switch off, the workbook is as on main. `crs_export.py` is in the danger
zone (rule 6). Ids M1736-01.. (named after the PR, rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_E = APP / "crs_export.py"
_T = "tests/test_tick_rows_own_section.py"
_TAGS = ("honesty", "critical")


def _m(n: str, desc: str, anchor: str, repl: str, kw: str) -> Mutation:
    return Mutation(
        id=f"M1736-{n}",
        phase=1736,
        description=desc,
        path=_E,
        anchor=anchor,
        replacement=repl,
        target=_T,
        keyword=kw,
        tags=_TAGS,
    )


_GUARD = (
    '    if view["crs_copy"] != COPY_INTERNAL or not crs_routing.enabled():\n'
    "        return view\n"
)

MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "the tick rows leave the CRS sheet with the switch OFF too (off is no longer main's workbook)",
        _GUARD,
        '    if view["crs_copy"] != COPY_INTERNAL:\n        return view\n',
        "switch_off_the_tick_rows_stay_on_the_crs_sheet",
    ),
    _m(
        "02",
        "a contractor copy is split too (a tick sheet could reach the contractor)",
        _GUARD,
        "    if not crs_routing.enabled():\n        return view\n",
        "never_splits_a_contractor_copy",
    ),
    _m(
        "03",
        "the CRS sheet keeps the tick rows while they are also drawn on their own sheet",
        '        "rows": crs_tick_sheet.renumber(rest),\n',
        '        "rows": crs_tick_sheet.renumber(view["rows"]),\n',
        "leave_the_crs_sheet_for_their_own_section",
    ),
    _m(
        "04",
        "the tick sheet is never drawn on the internal copy (the rows vanish unseen)",
        '    if view.get("tick_rows"):  # owner order 11 Nov: the safety ticks\n',
        '    if view.get("tick_rows") and not internal:\n',
        "own_section or sits_next or permanent_number or same_cells",
    ),
    _m(
        "05",
        "the workbook draws the unsplit view (the switch has no effect on the file)",
        "    view = _tick_section(build_crs_view(findings, meta))\n",
        "    view = build_crs_view(findings, meta)\n",
        "leave_the_crs_sheet_for_their_own_section or numbers_its_own_rows",
    ),
)
