"""Order 260.3 (PR 1390): the pressure-vessel and heat-exchanger review checklists.
`reference/datasheet_checks.json` is in the danger zone (rule 6). Ids M1390-01 onwards, phase 1390."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_260_3_vessel_hx_checklists.py"
_JSON = APP / "reference" / "datasheet_checks.json"
_TAGS = ("honesty", "o260")


def _m(n, description, anchor, replacement, keyword=None):
    return Mutation(
        id=f"M1390-{n}",
        phase=1390,
        description=description,
        path=_JSON,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAGS,
    )


_HEAD = '    "{key}": {{\n      "sign_off": {{\n        "status": "draft",\n        "by": null,\n        "date": null\n      }},\n      "clauses_verified": false,\n      "governs": false,'

MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "the vessel checklist replaces the standards' library requirements (it governs)",
        _HEAD.format(key="Pressure Vessel"),
        _HEAD.format(key="Pressure Vessel").replace(
            '"governs": false', '"governs": true'
        ),
        "does_not_govern",
    ),
    _m(
        "02",
        "the heat-exchanger checklist replaces the standards' library requirements (it governs)",
        _HEAD.format(key="Heat Exchanger"),
        _HEAD.format(key="Heat Exchanger").replace(
            '"governs": false', '"governs": true'
        ),
        "does_not_govern",
    ),
    _m(
        "03",
        "the heat-exchanger checklist claims its clauses are verified",
        _HEAD.format(key="Heat Exchanger"),
        _HEAD.format(key="Heat Exchanger").replace(
            '"clauses_verified": false', '"clauses_verified": true'
        ),
        "does_not_govern",
    ),
    _m(
        "04",
        "a bare 'passes' is read as the number of tube passes",
        '"^(number of|no\\\\.? of) (tube[- ]side )?passes$"',
        '"^((number of|no\\\\.? of) (tube[- ]side )?)?passes$"',
        "loose_label",
    ),
    _m(
        "05",
        "tube material is no longer read from the exchanger sheet's own label",
        '"^tube (bundle )?material$"',
        '"^tube (bundle )?material$x"',
        "every_field_a_sheet_prints",
    ),
)
