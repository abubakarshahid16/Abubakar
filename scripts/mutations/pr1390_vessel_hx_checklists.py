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
        '"^(number of|no\\\\.? of) tube([- ]side)? passes$"',
        '"^(number of|no\\\\.? of) (tube([- ]side)? )?passes$"',
        "passes_label",
    ),
    _m(
        "05",
        "tube material is no longer read from the exchanger sheet's own label",
        '"^tube (bundle )?material$"',
        '"^tube (bundle )?material$x"',
        "every_field_a_sheet_prints",
    ),
    _m(
        "06",
        "the vessel checklist claims its clauses are verified",
        _HEAD.format(key="Pressure Vessel"),
        _HEAD.format(key="Pressure Vessel").replace(
            '"clauses_verified": false', '"clauses_verified": true'
        ),
        "does_not_govern",
    ),
    _m(
        "07",
        "the exchanger flow item no longer says one side is enough",
        "The flow is stated for the shell side or the tube side (one side is enough to pass).",
        "The flow is stated for the shell side or the tube side.",
        "one_side_is_enough",
    ),
    _m(
        "08",
        "a bare 'volume' is read as the vessel volume",
        '"^(vessel |total |internal |design )volume$"',
        '"^(vessel |total |internal |design )?volume$"',
        "loose_label",
    ),
    _m(
        "09",
        "'MDMT exemption' is read as the minimum design metal temperature",
        '"^(minimum design metal temperature|mdmt)( \\\\(mdmt\\\\))?$"',
        '"^(minimum design metal temperature|mdmt)( .*)?$"',
        "loose_label",
    ),
    Mutation(
        id="M1390-10",
        phase=1390,
        description="a placeholder word such as 'fields' is looked up as a clause and linked to a standard page",
        path=APP / "standard_clause_page.py",
        anchor='    if not label or not (re.search(r"\\d", clause) or re.fullmatch(r"[A-Za-z]", clause)):',
        replacement="    if not label or not clause:",
        target="tests/test_225_standard_clause_page.py",
        keyword="placeholder_word",
        tags=_TAGS,
    ),
    Mutation(
        id="M1390-11",
        phase=1390,
        description="the review chooses the vessel / exchanger checklist from a body mention of the type again",
        path=APP / "checklist_scope.py",
        anchor='    if review_type(classification) is None:\n        rules = {**rules, "checklists": {}}\n',
        replacement="",
        target="tests/test_264_checklist_type_evidence.py",
        keyword="asks_no_exchanger_question",
        tags=_TAGS,
    ),
    Mutation(
        id="M1390-12",
        phase=1390,
        description="a type read from the body (body_phrase_match) still chooses the title-only checklists",
        path=APP / "checklist_scope.py",
        anchor='    weak = evidence.get("method") == "body_phrase_match" and not classification.get(\n        "confirmed"\n    )\n',
        replacement="    weak = False\n",
        target="tests/test_264_checklist_type_evidence.py",
        keyword="chosen_from_a_title",
        tags=_TAGS,
    ),
    Mutation(
        id="M1390-13",
        phase=1390,
        description="a type a person confirmed is treated as weak (the checklist is refused)",
        path=APP / "checklist_scope.py",
        anchor='    weak = evidence.get("method") == "body_phrase_match" and not classification.get(\n        "confirmed"\n    )\n',
        replacement='    weak = evidence.get("method") == "body_phrase_match"\n',
        target="tests/test_264_checklist_type_evidence.py",
        keyword="chosen_from_a_title",
        tags=_TAGS,
    ),
    Mutation(
        id="M1390-14",
        phase=1390,
        description="the revision-block check is given the withheld checklist type, so it stops running and the run still says it ran",
        path=APP / "checklist_scope.py",
        anchor='        equipment_type=classification.get("equipment_type"),\n',
        replacement="        equipment_type=review_type(classification),\n",
        target="tests/test_264_checklist_type_evidence.py",
        keyword="still_gets_the_revision_check",
        tags=_TAGS,
    ),
)
