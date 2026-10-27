"""Order 235.2: the centrifugal-pump review checklist. `reference/datasheet_checks.json` and
`datasheet_checks.py` are in the danger zone (rule 6). Ids M2352-01 onwards, phase 2352."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_235_2_pump_checklist.py"
_JSON = APP / "reference" / "datasheet_checks.json"
_PY = APP / "datasheet_checks.py"
_TAGS = ("honesty", "o235")


def _m(n, description, path, anchor, replacement, keyword=None):
    return Mutation(
        id=f"M2352-{n}",
        phase=2352,
        description=description,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "the pump checklist replaces API 610's library requirements (it governs) although it only asks that fields are stated",
        _JSON,
        '    "Centrifugal Pump": {\n      "sign_off": {\n        "status": "draft",\n        "by": null,\n        "date": null\n      },\n      "clauses_verified": false,\n      "governs": false,',
        '    "Centrifugal Pump": {\n      "sign_off": {\n        "status": "draft",\n        "by": null,\n        "date": null\n      },\n      "clauses_verified": false,\n      "governs": true,',
    ),
    _m(
        "02",
        "the pump checklist claims its clause numbers are verified",
        _JSON,
        '    "Centrifugal Pump": {\n      "sign_off": {\n        "status": "draft",\n        "by": null,\n        "date": null\n      },\n      "clauses_verified": false,',
        '    "Centrifugal Pump": {\n      "sign_off": {\n        "status": "draft",\n        "by": null,\n        "date": null\n      },\n      "clauses_verified": true,',
    ),
    _m(
        "03",
        "NPSH required is no longer read from the pump sheet's own label",
        _JSON,
        '"^npsh ?(r|3|required|\\\\(required\\\\))( at rated (flow|capacity))?$"',
        '"^npsh ?(r|3|required|\\\\(required\\\\))( at rated (flow|capacity))?$x"',
    ),
    _m(
        "04",
        "a bare 'plan' is read as the seal flush plan (any 'plan' on a page)",
        _JSON,
        '"^(api |seal )(seal )?(flush |piping )?plan( no\\\\.?| number)?$"',
        '"^(api |seal )?(seal )?(flush |piping )?plan( no\\\\.?| number)?$"',
    ),
    _m(
        "05",
        "the engine ignores a checklist's own 'does not govern' and governs its standards anyway",
        _PY,
        '    return {"key": key, "items": items, "draft": draft, **governs(entry)}\n',
        '    return {"key": key, "items": items, "draft": draft}\n',
    ),
)
