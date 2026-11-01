"""#1478 pump kit preparation: the draft pump cards join the checklist only behind their switch."""

from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1498-01",
        phase=1498,
        description="the draft pump kit cards never reach the pump checklist",
        path=APP / "datasheet_checks.py",
        anchor=" + pump_kit.loader_items(key, b)\n",
        replacement="\n",
        target="tests/test_1478_pump_kit_prep.py",
        keyword="switch_on",
        tags=("honesty",),
    ),
)
