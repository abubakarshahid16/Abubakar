"""Where a datasheet puts the unit, and which of those the extractor reads.

THESE TESTS RECORD CURRENT BEHAVIOUR, INCLUDING BEHAVIOUR THAT IS WRONG. Two
of the three layouts below lose the unit, and the tests assert that they lose
it. That is deliberate: a defect with a test around it is a defect somebody can
see, and the test is what will go red when it is fixed - at which point the
assertion is updated to the new truth, in the same commit as the fix.

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

def test_layout_a_unit_in_its_own_column_is_lost():
    """THE UNIT BECOMES A SEPARATE PAIR AND IS THEN DISCARDED.

    `split_label_value` pairs cell 1 with cell 2 and then pairs cell 3 with
    nothing, so the unit is not attached to the value - it is briefly a FIELD
    whose name is 'barg' and whose value is empty, and the fact gate drops it
    for having no value.

    So the measured value survives with no unit, and a stray field name is
    manufactured on the way past.
    """
    pairs = split_label_value(["Design pressure", "3.5", "barg"])

    assert ("Design pressure", "3.5") in pairs, "the label-value pair was not found"
    # The unit, orphaned. This is the defect, asserted rather than described.
    assert ("barg", "") in pairs, (
        "expected the unit to be orphaned as its own empty-valued pair - if "
        "this now fails, the extractor has changed and this test should be "
        "updated to whatever it does instead")
    # And the value it belongs to carries no unit.
    assert measure_value("3.5")[1] is None


def test_layout_a_with_a_leading_line_number_behaves_the_same():
    """A numbered form does not change the outcome - the line number is
    correctly discarded and the unit is still orphaned."""
    pairs = split_label_value(["12", "Design pressure", "3.5", "barg"])

    assert ("Design pressure", "3.5") in pairs
    assert ("barg", "") in pairs


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


def test_layout_b_will_read_a_tag_number_as_a_unit():
    """THE COST OF LAYOUT B, and it is being paid on the real corpus.

    Any word after the number is taken as the unit, so a bill-of-materials row
    reading "6 VEFV1101M" stores a unit of 'VEFV1101M' - an equipment tag in a
    unit column. `standards` gained a gate against exactly this (`claims.is_unit`)
    and the datasheet side has not.
    """
    _value, unit, _measure = measure_value("6 VEFV1101M")

    assert unit == "VEFV1101M", "the tag is stored as a unit"
    assert claims.is_unit(unit) is False, (
        "`claims` knows this is not a unit - nothing is asking it here")


# ----------------------------------------- layout C: unit inside the label
#
#   | Design pressure (barg) | 3.5 |

def test_layout_c_unit_inside_the_label_is_lost():
    """The unit is part of the label text and is never looked for there.

    Worse than layout A in one respect: there is no orphaned pair to notice, so
    nothing anywhere records that a unit was present at all.
    """
    pairs = split_label_value(["Design pressure (barg)", "3.5"])
    assert pairs == [("Design pressure (barg)", "3.5")]

    value, unit, _measure = measure_value("3.5")

    assert value == "3.5"
    assert unit is None, "a unit was recovered from the label - behaviour changed"


@pytest.mark.parametrize("label", [
    "Design pressure (barg)",
    "Design pressure, barg",
    "Design pressure [kPa]",
])
def test_layout_c_in_three_spellings_all_lose_the_unit(label):
    """Three ways a form writes it, one outcome. Parameterised so a partial
    fix - brackets but not parentheses - is visible as a partial pass."""
    _pairs = split_label_value([label, "3.5"])

    assert measure_value("3.5")[1] is None


# ------------------------------------------------------------- the summary

def test_only_one_of_three_layouts_yields_a_unit():
    """The three side by side, so the ratio is stated in one place.

    THIS IS THE NUMBER: one layout of three attaches a unit to its value, and
    the two that do not are both common in engineering forms.
    """
    layouts = {
        "unit in its own column": measure_value(
            dict(split_label_value(["Design pressure", "3.5", "barg"]))["Design pressure"]),
        "unit appended to value": measure_value(
            dict(split_label_value(["Design pressure", "3.5 barg"]))["Design pressure"]),
        "unit inside the label": measure_value(
            dict(split_label_value(["Design pressure (barg)", "3.5"]))["Design pressure (barg)"]),
    }
    with_unit = {name for name, (_v, unit, _m) in layouts.items() if unit}

    assert with_unit == {"unit appended to value"}, (
        f"expected exactly one layout to yield a unit, got {with_unit}")
