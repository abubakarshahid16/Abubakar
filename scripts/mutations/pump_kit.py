"""#1478 pump kit preparation: the draft pump cards join the checklist only behind their switch."""

from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1498-01",
        phase=1498,
        description="the draft pump kit cards never reach the pump checklist",
        path=APP / "datasheet_checks.py",
        anchor="    items = kit_core.with_kit(key, ",
        replacement="    items = (lambda _k, x: x)(key, ",
        target="tests/test_1478_pump_kit_prep.py",
        keyword="switch_on",
        tags=("honesty",),
    ),
    Mutation(
        id="M1498-02",
        phase=1498,
        description="a margin rule's text drops its margin again",
        path=APP / "datasheet_checks.py",
        anchor='right_words = right_words if kind == "above_by" else ((',
        replacement="right_words = ((",
        target="tests/test_1478_pump_kit_prep.py",
        keyword="margin",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1498-03",
        phase=1498,
        description="a kit card's result is no longer held for the engineer",
        path=APP / "kit_core.py",
        anchor='    if not item.get("kit"):\n        return result\n',
        replacement="    return result\n",
        target="tests/test_1478_pump_kit_prep.py",
        keyword="held",
        tags=("honesty",),
    ),
)
