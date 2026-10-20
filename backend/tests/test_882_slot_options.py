"""#882 (owner's M-03 CRS): a heading over options that each have a drawn slot.

`MINIMUM FLOW` on one line and `STABLE ____   THERMAL ____` on the next used to
give the heading the value `STABLE` (a value nobody wrote), drop STABLE's own
slot, and leave `THERMAL` as a fragment of its field. Now each option is filed
as "<heading> - <option>". Invented sheets only.
"""

from __future__ import annotations

import pytest

from app import datasheets, slot_options


def pairs(text):
    return datasheets.pairs_from_blocks([(1.0, 1.0, text)])


def test_each_option_is_filed_under_its_heading_and_its_slot_stays_blank():
    assert pairs("MINIMUM FLOW\nSTABLE  ____     THERMAL  ____\n") == [
        ("MINIMUM FLOW - STABLE", "___"),
        ("MINIMUM FLOW - THERMAL", "___"),
    ]


def test_the_heading_is_not_given_an_option_word_as_its_value():
    assert all(
        value not in ("STABLE", "RADIAL")
        for _l, value in pairs("VIBRATION PROBES\nRADIAL  ____    AXIAL  ____\n")
    )


def test_three_options_on_one_line_are_all_kept():
    assert [
        label
        for label, _v in pairs("BEARINGS\nRADIAL  ____   THRUST  ____   OTHER  ____\n")
    ] == ["BEARINGS - RADIAL", "BEARINGS - THRUST", "BEARINGS - OTHER"]


@pytest.mark.parametrize(
    "text, expected",
    [
        # one option only: not a list of options, read as before
        ("BEARINGS\nRADIAL  ____\n", [("BEARINGS", "RADIAL")]),
        (
            "Pumping temperature:   ____   C\nSpecific gravity   ____\n",
            [("Pumping temperature:", "___"), ("Specific gravity", "___")],
        ),
        # two labels on one line, each with its slot
        (
            "RATED POWER   ____*____   kW     EFFICIENCY  ____\n",
            [("RATED POWER", "___*___"), ("EFFICIENCY", "___")],
        ),
        # an answer word that is a value, with no slot after it
        ("Insulation\nNone  ____\n", [("Insulation", "None")]),
    ],
)
def test_other_shapes_are_read_as_before(text, expected):
    assert pairs(text) == expected


def test_the_option_run_counts_only_label_then_slot_pairs():
    parts = ["HEAD", "Radial", "___", "Axial", "___", "Thrust", "next label"]
    slots = [False, False, True, False, True, False, False]
    assert slot_options.count(parts, slots, 1, datasheets.is_field_label) == 2
    assert slot_options.count(parts, slots, 5, datasheets.is_field_label) == 0


def test_a_number_or_a_blank_marker_before_a_slot_is_not_an_option():
    parts = ["HEAD", "Radial", "___", "10", "___", "By vendor", "___"]
    slots = [False, False, True, False, True, False, True]
    assert slot_options.count(parts, slots, 1, datasheets.is_field_label) == 1
    assert slot_options.count(parts, slots, 5, datasheets.is_field_label) == 0
