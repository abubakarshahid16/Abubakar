"""PR #1274: a requirement whose quantity is named at the end of the sentence is
paired with the sheet's row (#913). backend/tests/test_913_closing_noun.py must notice."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_913_closing_noun.py"
_NOUN = APP / "closing_noun.py"
_CMP = APP / "comparison.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1274-01",
        phase=1274,
        description="a label that is only the closing phrase may pair (a reference becomes the quantity)",
        path=_NOUN,
        anchor="found.start() < len(closing) and found.end() > len(closing)",
        replacement="found.start() < len(closing)",
        target=_T,
        keyword="does_not_straddle",
        tags=("pr1274", "closing_noun"),
    ),
    Mutation(
        id="M1274-02",
        phase=1274,
        description="the closing phrase is read as one word only",
        path=_NOUN,
        anchor="(?:\\s+[a-z][a-z\\-]*){0,2})",
        replacement="(?:\\s+[a-z][a-z\\-]*){0,0})",
        target=_T,
        keyword="closing_phrase",
        tags=("pr1274", "closing_noun"),
    ),
    Mutation(
        id="M1274-03",
        phase=1274,
        description="the closing-noun pass is never run: the planted defect is unpaired again",
        path=_CMP,
        anchor="    for eligible in (fact_has_number, is_blank) if composed else ():",
        replacement="    for eligible in (fact_has_number, is_blank) if False else ():",
        target=_T,
        keyword="planted_defect or another_equipment_type",
        tags=("pr1274", "comparison"),
    ),
    Mutation(
        id="M1274-04",
        phase=1274,
        description="the closing-noun pass replaces the plain pairing instead of waiting for it to find nothing",
        path=_CMP,
        anchor="        hits = hits or closing_noun.straddling(found, composed, closing)",
        replacement="        hits = closing_noun.straddling(found, composed, closing)",
        target=_T,
        keyword="plain_pairing_is_left_alone",
        tags=("pr1274", "comparison"),
    ),
)
