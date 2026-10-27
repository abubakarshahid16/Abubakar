"""The set-pressure label pattern had an unbracketed alternation: `...psig|barg\\)?$` made ANY label
ending in "barg" read as the set pressure, so "Design pressure (barg)" and "Operating pressure
(barg)" on a relief-valve sheet falsely satisfied "the set pressure is stated"."""

from __future__ import annotations

import pytest

from app import datasheet_checks as dc

RULES = dc.load_rules()


@pytest.mark.parametrize(
    "label",
    [
        "design pressure (barg)",
        "operating pressure (barg)",
        "maximum allowable working pressure (barg)",
        "back pressure (barg)",
        "test pressure (barg)",
        "design pressure barg",
    ],
)
def test_a_label_that_only_ends_in_a_pressure_unit_is_not_the_set_pressure(label):
    assert dc.role_of(label, RULES) != "set_pressure"


@pytest.mark.parametrize(
    "label",
    [
        "set pressure",
        "set press.",
        "set pressure (barg)",
        "set pressure (psig)",
        "set pressure at inlet psig",
        "set pressure barg",
    ],
)
def test_the_set_pressure_labels_still_read_as_the_set_pressure(label):
    assert dc.role_of(label, RULES) == "set_pressure"
