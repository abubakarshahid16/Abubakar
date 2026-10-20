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


def test_fold_rewrites_only_a_heading_over_options_and_keeps_every_other_cell():
    parts = ["Rated flow", "120", "HEAD", "Radial", "___", "Axial", "___", "Last", "x"]
    slots = [False, False, False, False, True, False, True, False, False]
    out, out_slots = slot_options.fold(parts, slots, datasheets.is_field_label)
    assert out == [
        "Rated flow",
        "120",
        "HEAD - Radial",
        "___",
        "HEAD - Axial",
        "___",
        "Last",
        "x",
    ]
    assert out_slots == [False, False, False, True, False, True, False, False]


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "Fluid handled\nWater\nPressure ____   Temperature ____\n",
            [("Fluid handled", "Water"), ("Pressure", "___"), ("Temperature", "___")],
        ),
        (
            "Seal\nAPI Plan 53\nMax ____   Min ____\n",
            [("Seal", "API Plan 53"), ("Max", "___"), ("Min", "___")],
        ),
    ],
)
def test_a_value_after_its_label_is_not_the_heading_of_the_slot_fields_after_it(
    text, expected
):
    assert pairs(text) == expected


def test_fold_leaves_a_label_value_pair_before_slot_fields_alone():
    parts = ["Casing material", "Carbon steel", "Pressure", "___", "Temperature", "___"]
    slots = [False, False, False, True, False, True]
    out, out_slots = slot_options.fold(parts, slots, datasheets.is_field_label)
    assert (out, out_slots) == (parts, slots)


def test_a_heading_after_a_filled_slot_is_still_a_heading():
    parts = ["Material", "GRADE", "HEAD", "Radial", "___", "Axial", "___"]
    slots = [False, True, False, False, True, False, True]
    out, out_slots = slot_options.fold(parts, slots, datasheets.is_field_label)
    assert out == ["Material", "GRADE", "HEAD - Radial", "___", "HEAD - Axial", "___"]
    assert out_slots == [False, True, False, True, False, True]


def test_a_value_in_front_of_two_filled_slot_fields_keeps_its_label():
    # Slot cells that carry an answer written on the drawn line (`80`, `10`).
    parts = ["Fluid", "Water", "Design temperature", "80", "Design pressure", "10"]
    slots = [False, False, False, True, False, True]
    out, out_slots = slot_options.fold(parts, slots, datasheets.is_field_label)
    assert (out, out_slots) == (parts, slots)
