"""Order 228.9 (PR 1316): relief-valve fields are asked with the labels sheets
print, and a reader gap says only that wording for the field appears."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_checklist_text_search.py"
_JSON = APP / "reference" / "datasheet_checks.json"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1316-01",
        phase=1316,
        description="a reader gap says the field is on the sheet (a claim the loose search cannot make)",
        path=APP / "datasheet_checks.py",
        anchor='                        f"{_pretty(field)} was not read as a value; wording for it appears on "\n',
        replacement='                        f"{_pretty(field)} is on the sheet; wording for it appears on "\n',
        target=_T,
        keyword="wording_claims_only",
        tags=("honesty",),
    ),
    Mutation(
        id="M1316-02",
        phase=1316,
        description="the orifice area loses the spelling vendors print for it (actual discharge area)",
        path=_JSON,
        anchor='        "selected area",\n        "actual discharge area"\n',
        replacement='        "selected area"\n',
        target=_T,
        keyword="labels_a_relief_valve_sheet_prints",
        tags=("honesty",),
    ),
    Mutation(
        id="M1316-03",
        phase=1316,
        description="the rated capacity loses its printed spelling, so it is asked as 'Rated capacity' again",
        path=_JSON,
        anchor='        "rated relieving capacity",\n',
        replacement="",
        target=_T,
        keyword="labels_a_relief_valve_sheet_prints",
        tags=("honesty",),
    ),
    Mutation(
        id="M1316-04",
        phase=1316,
        description="the prompt shows fewer spellings, hiding the later ones",
        path=APP / "form_reader_fields.py",
        anchor="MAX_SYNONYMS_SHOWN = 6\n",
        replacement="MAX_SYNONYMS_SHOWN = 3\n",
        target=_T,
        keyword="labels_a_relief_valve_sheet_prints",
        tags=("honesty",),
    ),
    Mutation(
        id="M1316-05",
        phase=1316,
        description="the required area's spelling is offered as the orifice area too (a false Meets)",
        path=_JSON,
        anchor='        "selected area",\n        "actual discharge area"\n',
        replacement='        "selected area",\n        "calculated area",\n        "actual discharge area"\n',
        target=_T,
        keyword="spelling_is_listed_for_two_roles or required_area_is_never_offered",
        tags=("honesty", "critical"),
    ),
)
