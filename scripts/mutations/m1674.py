"""#1674: a requirement pairs with a datasheet field only if its subject is the same quantity."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_subject_pairing.py"
_TAGS = ("honesty", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1674-01",
        phase=1674,
        description="the rule never refuses a different quantity, so a coating thickness pairs with the corrosion allowance",
        path=APP / "subject_pairing.py",
        anchor="    return None if subject == field else SUBJECT_DIFFERS\n",
        replacement="    return None\n",
        target=_T,
        keyword="coating_thickness_is_not_the_corrosion_allowance",
        tags=_TAGS,
    ),
    Mutation(
        id="M1674-02",
        phase=1674,
        description="a requirement with no subject is paired by the words of its sentence again",
        path=APP / "subject_pairing.py",
        anchor="        return SUBJECT_UNKNOWN\n",
        replacement="        return None\n",
        target=_T,
        keyword="no_subject_is_refused",
        tags=_TAGS,
    ),
    Mutation(
        id="M1674-03",
        phase=1674,
        description="the pairing check no longer asks the subject rule, so the AI matcher's pair stands",
        path=APP / "match_rules.py",
        anchor="    if subject_pairing.conflict(requirement, fact, sheet):\n",
        replacement="    if False:\n",
        target=_T,
        keyword="ai_matchers_pair_of_a_coating_thickness",
        tags=_TAGS,
    ),
)
