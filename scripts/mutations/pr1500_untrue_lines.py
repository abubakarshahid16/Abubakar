"""#1472 (PR #1500): the datasheet checks read one value where a range is printed twice, and a combined
label answers the text attribute it names (same_value.py, datasheet_checks.py, datasheet_roles.py; danger
zone). Ids M1500-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_c1_1472_untrue_lines.py"
_TAG = ("checklist", "honesty")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1500-01",
        phase=1500,
        description="a range printed twice with a plain note is two values again",
        path=APP / "same_value.py",
        anchor='    if base[0] == "t" and settings.datasheet_one_value_enabled:\n',
        replacement="    if False:\n",
        target=_T,
        keyword="noted_range_and_a_bare_range_are_one_value",
        tags=_TAG,
    ),
    Mutation(
        id="M1500-02",
        phase=1500,
        description="anything around a range counts as a plain note (a bound, a condition, a side)",
        path=APP / "same_value.py",
        anchor='    if not _plain_note("", rest):\n        return None\n',
        replacement="",
        target=_T,
        keyword="anything_else_around_a_range",
        tags=_TAG,
    ),
    Mutation(
        id="M1500-03",
        phase=1500,
        description="a value inside a combined line is decided (can be COMPLIANT) instead of asked",
        path=APP / "datasheet_checks.py",
        anchor='    if fact.get("combined_label"):\n',
        replacement="    if False:\n",
        target=_T,
        keyword="never_compliant",
        tags=_TAG,
    ),
    Mutation(
        id="M1500-05",
        phase=1500,
        description="a combined line is added even where the tag has its own value for the role",
        path=APP / "datasheet_roles.py",
        anchor="            if not mine.get(role) and not shared.get(role):\n",
        replacement="            if True:\n",
        target=_T,
        keyword="under_the_rating_label_itself",
        tags=_TAG,
    ),
    Mutation(
        id="M1500-06",
        phase=1500,
        description="merged readings keep the first reading, so a deferral note is kept or lost by order",
        path=APP / "datasheet_checks.py",
        anchor="        return next((f for f in found if note_of(f)), found[0]), None\n",
        replacement="        return found[0], None\n",
        target=_T,
        keyword="merged_noted_range_is_a_query",
        tags=_TAG,
    ),
    Mutation(
        id="M1500-07",
        phase=1500,
        description="an unqualified part answers a qualified role whatever the other parts name",
        path=APP / "datasheet_roles.py",
        anchor="        if qualifier and not _agrees(qualifier, others, pair_words):\n",
        replacement="        if False:\n",
        target=_T,
        keyword="qualifier_must_agree",
        tags=_TAG,
    ),
)
