"""#754 F5b: the CRS rows of the required-vs-cited standards check
(crs_mapping, danger zone). Ids M758-01..M758-04 (CLAUDE.md rule 12)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_754_required_vs_cited.py"
_P = APP / "crs_mapping.py"
_TAG = ("w5b", "crs")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M758-01", phase=758, description="a required standard the contractor did not cite gets no CRS row",
             path=_P, anchor='    for r in (check or {}).get("required_not_cited") or []:\n',
             replacement='    for r in []:\n',
             target=_T, keyword="exactly_one_crs_row or carries_the_missed", tags=_TAG),
    Mutation(id="M758-02", phase=758, description="a cited standard that does not apply gets no note",
             path=_P, anchor='    for r in (check or {}).get("cited_not_applicable") or []:\n',
             replacement='    for r in []:\n',
             target=_T, keyword="another_equipment_type_gives_a_note", tags=_TAG),
    Mutation(id="M758-03", phase=758, description="build_crs_rows drops the standards check rows",
             path=_P, anchor="    rows.extend(standards_check_rows(standards_check, submittal_name))\n",
             replacement="",
             target=_T, keyword="exactly_one_crs_row", tags=_TAG),
    Mutation(id="M758-04", phase=758, description="a missed-standard row is issued as engineer-confirmed",
             path=_P, anchor='            "row_kind": ROW_KIND_STANDARD_NOT_CITED, "severity": "",\n            "engineer_confirmed": False,\n',
             replacement='            "row_kind": ROW_KIND_STANDARD_NOT_CITED, "severity": "",\n            "engineer_confirmed": True,\n',
             target=_T, keyword="exactly_one_crs_row", tags=_TAG),
)
