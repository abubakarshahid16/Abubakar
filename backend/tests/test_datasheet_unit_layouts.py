"""Where a datasheet puts the unit, and which of those the extractor reads.

THESE TESTS RECORD CURRENT BEHAVIOUR. They were written when two of the three
layouts LOST the unit and asserted that they lost it - a defect with a test
around it is a defect somebody can see - on the stated contract that the
assertion would be rewritten in the same commit as the fix. That has now
happened twice: all three layouts attach a unit, and the tag-as-unit case is
refused.

Do not "repair" a failing assertion here by loosening it. If one of these
starts failing, the extractor changed and the question is whether it changed
for the better.

WHY IT MATTERS. `comparison.compare` refuses to compare two measurements whose
units are not the same dimension - deliberately, because that refusal is what
stops a 300 mm cover being read as 300 m. A fact with NO unit is therefore not
a fact that compares loosely; it is a fact that cannot be compared at all, and
every requirement touching it returns NEEDS_ENGINEER_REVIEW.

THE FIXTURES ARE SYNTHETIC AND GENERIC. They are three ways any engineering
form writes a unit, not a transcription of any particular sheet - nothing here
is shaped around one vendor's layout, and a fix validated only against these
three is not yet validated.
"""

from __future__ import annotations

import pytest

from app import claims
from app.datasheets import measure_value, split_label_value


# ------------------------------------------- layout A: unit in its own column
#
#   | Design pressure | 3.5 | barg |
#
# The common shape in a numbered three-column form.

def test_layout_a_unit_in_its_own_column_is_attached_to_the_value():
    """FIXED. The unit cell is absorbed into the value beside it.

    It used to become a separate pair - a FIELD named 'barg' with an empty
    value, dropped later for having no value, taking the unit with it. Every
    engineering row on the real submittal lost its unit that way.
    """
    pairs = split_label_value(["Design pressure", "3.5", "barg"])

    assert pairs == [("Design pressure", "3.5 barg")]
    assert not any(label == "barg" for label, _v in pairs), (
        "a field named after a unit was manufactured")
    assert measure_value("3.5 barg")[1] == "barg"


def test_a_trailing_word_that_is_not_a_unit_is_not_absorbed():
    """THE GUARD on the rule above, and the reason it is safe.

    `| Shell material | SA 516 | Gr 70N |` is a three-column row whose third
    cell is not a unit. Absorbing it would corrupt the value, so it is left
    alone - which also proves the absorption is driven by the unit table and
    not by column position.
    """
    pairs = split_label_value(["Shell material", "SA 516", "Gr 70N"])

    assert ("Shell material", "SA 516") in pairs
    assert ("Shell material", "SA 516 Gr 70N") not in pairs


def test_layout_a_with_a_leading_line_number_behaves_the_same():
    """A numbered form does not change the outcome: the sheet's own line
    number is discarded and the unit is still attached."""
    pairs = split_label_value(["12", "Design pressure", "3.5", "barg"])

    assert pairs == [("Design pressure", "3.5 barg")]


# ------------------------------------ layout B: unit appended to the value
#
#   | Design pressure | 3.5 barg |

def test_layout_b_unit_appended_to_the_value_is_read():
    """THE ONE LAYOUT THAT WORKS. `measure_value` splits the cell."""
    pairs = split_label_value(["Design pressure", "3.5 barg"])
    assert pairs == [("Design pressure", "3.5 barg")]

    value, unit, _measure = measure_value("3.5 barg")

    assert (value, unit) == ("3.5", "barg")


def test_layout_b_reads_a_unit_it_cannot_convert():
    """Read and converted are different questions.

    `barg` is recognised as a pressure but has no conversion factor, so the
    raw unit is kept and the normalised value stays NULL. That is the honest
    outcome: the sheet said barg, and nothing here invents a conversion.
    """
    _value, unit, measure = measure_value("3.5 barg")

    assert unit == "barg"
    assert claims.unit_dimension("barg") == "pressure"
    assert measure.normalized_value is None


def test_layout_b_no_longer_reads_a_tag_number_as_a_unit():
    """FIXED, and this test is the record of what it used to do.

    A bill-of-materials row reads "6 VEFV1101M" in ONE cell - a row index and
    an equipment tag - so the column rule never saw a unit column and any word
    after the number became the unit. Ten of the twenty numeric facts on the
    real submittal were that.

    THE TEST IS SHAPE, NOT MEMBERSHIP, and that distinction is the whole fix.
    This module cannot simply demand a recognised unit the way
    `requirements_3b.unit_token` does: its own docstring protects "9970 Kg/hr",
    a real value whose compound unit is not in the table.

    The shape is a SOLIDUS and a digit/letter mix, not length. An earlier
    version used length and discarded `kg/cm2`, `kg/cm2g` and `lb/ft3` - see
    the compound-unit tests at the end of this file.
    """
    assert measure_value("6 VEFV1101M")[:2] == (None, None), (
        "the tag is still being stored as a unit")
    assert claims.is_unit("VEFV1101M") is False

    # THE GUARD, on the same call. An unrecognised unit that is SHORT is still
    # a unit and its number must survive - without this the test would pass
    # against a rule that rejected every unit the table does not know.
    assert measure_value("9970 Kg/hr")[:2] == ("9970", "Kg/hr")


# ----------------------------------------- layout C: unit inside the label
#
#   | Design pressure (barg) | 3.5 |

def test_layout_c_unit_inside_the_label_is_moved_to_the_value():
    """FIXED. A parenthesised unit is stripped from the label and attached.

    This was the worst of the three: there was no orphaned pair to notice, so
    nothing anywhere recorded that a unit had been present at all.

    The label loses the parenthetical, which is correct - `Design pressure
    (barg)` and `Design pressure` are one field asked once.
    """
    pairs = split_label_value(["Design pressure (barg)", "3.5"])

    assert pairs == [("Design pressure", "3.5 barg")]
    assert measure_value("3.5 barg")[1] == "barg"


def test_a_parenthetical_that_is_not_a_unit_stays_in_the_label():
    """THE GUARD, and it matters more than the rule it guards.

    Datasheets end labels with "(Note - 3)" far more often than with a unit.
    Stripping those would rename the field, and two labels collapsing into one
    field name is how a value ends up filed under another requirement.
    """
    pairs = split_label_value(["Design pressure (Note - 3)", "3.5"])

    assert pairs == [("Design pressure (Note - 3)", "3.5")]


@pytest.mark.parametrize("label,expected", [
    ("Design pressure (barg)", "barg"),
    ("Design pressure [kPa]", "kPa"),
])
def test_layout_c_handles_both_bracket_spellings(label, expected):
    """Parameterised so a partial fix - parentheses but not square brackets -
    shows up as a partial pass rather than a green tick."""
    pairs = split_label_value([label, "3.5"])

    assert pairs == [("Design pressure", "3.5 " + expected)]


# ------------------------------------------------------------- the summary

def test_all_three_layouts_now_yield_a_unit():
    """The three side by side, so the ratio is stated in one place.

    THIS IS THE NUMBER, and it was one of three when this file was written.
    All three now attach a unit, each for a different reason - which is why
    each keeps its own test and its own negative guard above rather than being
    folded into this one.
    """
    layouts = {
        "unit in its own column": ["Design pressure", "3.5", "barg"],
        "unit appended to value": ["Design pressure", "3.5 barg"],
        "unit inside the label": ["Design pressure (barg)", "3.5"],
    }
    units = {name: measure_value(split_label_value(cells)[0][1])[1]
             for name, cells in layouts.items()}

    assert units == {
        "unit in its own column": "barg",
        "unit appended to value": "barg",
        "unit inside the label": "barg",
    }, units


# ------------------------------------------------ compound engineering units

@pytest.mark.parametrize("unit", [
    "kg/cm2", "kg/cm2g", "N/mm2", "kN/m2", "kg/m3", "lb/ft3", "W/m2K", "kJ/kgK",
])
def test_a_compound_engineering_unit_is_recognised(unit):
    """THE IDENTIFIER RULE MUST NOT EAT REAL UNITS.

    The first version of that rule discarded anything unrecognised longer than
    five characters carrying a digit. That is `kg/cm2`, `kg/cm2g` and `lb/ft3` -
    a pressure, a gauge pressure and a density - and the five that survived did
    so only by being short enough, not by being understood.

    All eight are now in `claims`, so the rule cannot reach them at all.
    """
    from app import claims
    base, _reference = claims.split_reference(unit)

    assert claims.is_unit(base) is True
    assert measure_value(f"5 {unit}")[:2] == ("5", unit)


@pytest.mark.parametrize("unit,dimension", [
    ("kg/cm2", "pressure"), ("N/mm2", "pressure"), ("kN/m2", "pressure"),
    ("kg/m3", "density"), ("lb/ft3", "density"),
    ("W/m2K", "heat_transfer"), ("kJ/kgK", "specific_heat"),
])
def test_each_compound_unit_lands_in_the_right_dimension(unit, dimension):
    """A dimension is what stops a density being compared against a pressure,
    so a unit filed under the wrong one is worse than an unrecognised one."""
    from app import claims
    assert claims.unit_dimension(unit) == dimension


def test_a_gauge_compound_pressure_splits_like_barg_does():
    """`kg/cm2g` differs from `kg/cm2` by an atmosphere, exactly as barg does,
    and the reference has to survive the same way."""
    from app import claims
    assert claims.split_reference("kg/cm2g") == ("kg/cm2", "gauge")


def test_an_equipment_tag_is_still_refused():
    """THE GUARD ON THE RULE ABOVE. Widening the unit table must not widen what
    counts as a unit: a tag has no solidus and mixes several digits with
    several letters, and no engineering unit here does."""
    assert measure_value("6 VEFV1101M")[:2] == (None, None)
    assert measure_value("12 VEFV1107M")[:2] == (None, None)
