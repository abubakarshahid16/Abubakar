"""Code audit 26 Oct, items K1 and K2: an issued number carries the engineer's tick
only for the words they confirmed, and the program's note to the engineer never goes
to the contractor. `crs_mapping.py` and `crs_numbers`-adjacent code are in the danger
zone (rule 6). PR #1287: ids M1287-01 onwards, phase 1287."""

from __future__ import annotations

from ._base import APP, Mutation

_K1 = "tests/test_k1_changed_words_need_a_fresh_tick.py"
_TAGS = ("honesty", "k1k2")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1287-01",
        phase=1287,
        description="other words under an issued number keep the engineer's tick",
        path=APP / "crs_carry.py",
        anchor="    if not own and words_changed_since_issue(row, record):\n",
        replacement="    if False:\n",
        target=_K1,
        keyword="other_words_under",
        tags=_TAGS,
    ),
    Mutation(
        id="M1287-02",
        phase=1287,
        description="a row confirmed only by its number rewrites the words the number keeps",
        path=APP / "main.py",
        anchor='            and not row.get("confirmed_by_number")\n',
        replacement="",
        target=_K1,
        keyword="carried_tick_does_not_refresh",
        tags=_TAGS,
    ),
    Mutation(
        id="M1287-03",
        phase=1287,
        description="the 'Replaces earlier ...' line counts as words, so a replaced number looks changed",
        path=APP / "crs_carry.py",
        anchor='    while lines and _fold(lines[-1]).startswith(\n        ("replaces earlier ", "earlier issued ")\n    ):\n',
        replacement="    while False:\n",
        target=_K1,
        keyword="line_added_for_replaced",
        tags=_TAGS,
    ),
    Mutation(
        id="M1287-04",
        phase=1287,
        description="'Engineer to check' is no longer an internal phrase the issue gate blocks",
        path=APP / "crs_machine_words.py",
        anchor='    "engineer to check",\n',
        replacement="",
        target="tests/test_152_crs_machine_words.py",
        keyword="machine_words_are_found",
        tags=_TAGS,
    ),
    Mutation(
        id="M1287-05",
        phase=1287,
        description="a requirement no field was paired with is worded for the engineer again",
        path=APP / "crs_mapping.py",
        anchor='        return (f"Clarification requested: no field read from the datasheet was paired with "\n',
        replacement='        return (f"Engineer to check: no field this system read was paired with "\n',
        target="tests/test_f7_735_clean_crs.py",
        keyword="no_field_was_paired",
        tags=_TAGS,
    ),
)
