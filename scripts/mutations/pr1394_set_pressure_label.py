"""PR 1394: the set-pressure label pattern. `reference/datasheet_checks.json` is in the danger
zone (rule 6). Ids M1394-01 onwards, phase 1394."""

from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1394-01",
        phase=1394,
        description="the set-pressure pattern's unit alternation is unbracketed again: any label ending in barg is the set pressure",
        path=APP / "reference" / "datasheet_checks.json",
        anchor='"^set press(ure|\\\\.)? (at inlet )?\\\\(?(psig|barg)\\\\)?$"',
        replacement='"^set press(ure|\\\\.)? (at inlet )?\\\\(?psig|barg\\\\)?$"',
        target="tests/test_set_pressure_label.py",
        keyword="only_ends_in_a_pressure_unit",
        tags=("honesty",),
    ),
    Mutation(
        id="M1394-02",
        phase=1394,
        description="the set pressure in a unit bracket is no longer read",
        path=APP / "reference" / "datasheet_checks.json",
        anchor='"^set press(ure|\\\\.)? (at inlet )?\\\\(?(psig|barg)\\\\)?$"',
        replacement='"^set press(ure|\\\\.)? (at inlet )?\\\\(?(psig)\\\\)?$"',
        target="tests/test_set_pressure_label.py",
        keyword="still_read",
        tags=("honesty",),
    ),
)
