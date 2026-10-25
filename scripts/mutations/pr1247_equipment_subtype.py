"""Orders 180.1 item 5: a standard for another equipment sub-type is not asked of this
equipment; an unstated sub-type asks the engineer. `crs_mapping.py` is in the danger
zone (rule 6). PR #1247: ids M1247-01 onwards, phase 1247."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_180_equipment_subtype.py"
_TAGS = ("honesty", "180")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1247-01",
        phase=1247,
        description="an unsure standard is worded as a missing reference again",
        path=APP / "crs_mapping.py",
        anchor='            "comment": equipment_subtype.not_cited_words(r),\n',
        replacement='            "comment": f"Contractor did not reference {ident}; confirm compliance.",\n',
        target=_T,
        keyword="engineer_questions",
        tags=_TAGS,
    ),
    Mutation(
        id="M1247-02",
        phase=1247,
        description="a sheet that states no sub-type has every typed standard required again",
        path=APP / "equipment_subtype.py",
        anchor='        return "unsure", list(governed)\n',
        replacement='        return "required", list(governed)\n',
        target=_T,
        keyword="states_no_pump_type",
        tags=_TAGS,
    ),
    Mutation(
        id="M1247-03",
        phase=1247,
        description="a standard for another sub-type is still required",
        path=APP / "equipment_subtype.py",
        anchor='    return ("required" if stated & set(governed) else "other"), list(governed)\n',
        replacement='    return "required", list(governed)\n',
        target=_T,
        keyword="not_required_of_a_centrifugal",
        tags=_TAGS,
    ),
)
