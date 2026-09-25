"""A field name that is the tail of a field name.

THE DEFECT, MEASURED. The drum sheet writes a corrosion allowance over two
lines inside one cell:

    Figure 1
    Design corrosion allowance for removable internal parts
    (material 2)
    0
    mm

The text-block path reads each line as a cell and pairs strictly left to
right, so `Figure 1` became the label, the real label became its value, and
`(material 2)` - a continuation of the line above it - became a label of its
own paired with the `0` beneath. `normalise_field_name` then dropped the
brackets, and the sheet acquired a field called `material 2` whose value was
0 mm.

That field is what the model tier paired with SAES-W-010 11.3.1's "at least
25 mm of adjacent base metal", producing a NON_COMPLIANT verdict against the
contractor with both citations resolving. A corrosion allowance of zero is a
perfectly ordinary thing for a duplex-steel vessel to state.

TWO CAUSES, BOTH GENERIC, and each is a rule about the SHAPE of a row rather
than about this sheet:

  * a cell that is only a bracketed qualifier continues the cell before it;
  * a cross-reference cell - "Figure 1", "Table 3", "Note 5" - introduces the
    pair that follows it, exactly as a bare line number already did.

The negative fixtures are the guard: `Insulation | None` must survive, because
the obvious wider rule ("the value looks like a label, so re-anchor") deletes
it - `None` is a real answer that happens to read like a word.

Mutations: M167-M170, `python scripts/mutation_check.py --phase 12`.
"""

from __future__ import annotations

import pytest

from app import datasheets


# ----------------------------------------- a bracket-only cell continues

def test_a_bracket_only_line_is_part_of_the_label_above_it():
    """THE PRODUCTION ROW, as the text-block path delivers it."""
    pairs = datasheets.split_label_value([
        "Figure 1",
        "Design corrosion allowance for removable internal parts",
        "(material 2)", "0", "mm"])

    assert pairs == [
        ("Design corrosion allowance for removable internal parts "
         "(material 2)", "0 mm")]
    # AND THE NAME A READER SEES CARRIES THE WHOLE THING.
    assert datasheets.normalise_field_name(pairs[0][0]) == (
        "design corrosion allowance for removable internal parts material 2")


def test_the_same_row_from_the_grid_path_gives_the_same_pair():
    """BOTH PATHS RUN, and a fix in one of them is a fix in one of two homes.
    The grid path delivers the cell already joined, with the line number and
    the trailing note beside it."""
    pairs = datasheets.split_label_value([
        "36", "Figure 1",
        "Design corrosion allowance for removable internal parts (material 2)",
        "0", "mm", "For 25 % Cr SDSS", "", ""])

    assert ("Design corrosion allowance for removable internal parts "
            "(material 2)", "0 mm") in pairs


def test_a_bracket_only_cell_never_becomes_a_field_of_its_own():
    """The symptom, stated as the rule: no field on a datasheet is called
    `material 2`."""
    pairs = datasheets.split_label_value(
        ["Shell thickness", "(corroded)", "12", "mm"])

    assert [label for label, _ in pairs] == ["Shell thickness (corroded)"]


def test_a_parenthetical_with_nothing_before_it_is_left_alone():
    """There is nothing to attach it to, and inventing an attachment would be
    worse than leaving it."""
    assert datasheets._join_continuations(["(material 2)", "0", "mm"]) == [
        "(material 2)", "0", "mm"]


def test_a_unit_parenthetical_still_reaches_the_value():
    """The guard on the continuation rule: `Design pressure (barg) | 3.5` is
    layout C, and merging brackets must not break the path that moves a
    bracketed UNIT onto the value."""
    assert datasheets.split_label_value(["Design pressure (barg)", "3.5"]) == [
        ("Design pressure", "3.5 barg")]


# ------------------------------------------ a cross-reference introduces

@pytest.mark.parametrize("reference", [
    "Figure 1", "Fig. 2", "Table 3", "Note 5", "Detail A", "Sheet 2 of 4",
    "Drawing B", "Item 7",
])
def test_a_cross_reference_cell_is_skipped_like_a_line_number(reference):
    pairs = datasheets.split_label_value(
        [reference, "Design pressure", "3.5", "bar"])

    assert pairs == [("Design pressure", "3.5 bar")]


def test_a_dotted_clause_reference_is_skipped_like_a_line_number():
    """THE SAME DEFECT IN A DIFFERENT SPELLING, and it cost three weights.

    The drum sheet's weight rows read `19 | 4.2.1 | Fabricated weight (L1) : |
    4410 | kg`. The bare line number was already dropped; the clause reference
    behind it then took the label position and the real label became its
    value, so the fabricated, empty and operating weights were all lost.
    """
    assert datasheets.split_label_value(
        ["19", "4.2.1", "Fabricated weight (L1) :", "4410", "kg", "00"]) == [
        ("Fabricated weight (L1) :", "4410 kg")]


def test_a_single_dot_number_is_a_value_and_not_a_clause():
    """THE GUARD, and why the rule needs two dots. `1.6` is a corrosion
    allowance in millimetres and `4.2.1` is a clause; a rule that could not
    tell them apart would throw away values."""
    assert datasheets.split_label_value(
        ["Design corrosion allowance", "1.6", "mm"]) == [
        ("Design corrosion allowance", "1.6 mm")]


@pytest.mark.parametrize("cells,expected", [
    # THE ANSWER THAT READS LIKE A LABEL. The wider rule this one was chosen
    # over deletes this row.
    (["Insulation", "None"], [("Insulation", "None")]),
    (["Boot material", "N/A"], [("Boot material", "N/A")]),
    # Two forms side by side, with their line numbers. The client layout.
    (["5", "Design pressure", "23.5 barg", "46", "Bonnet material", "CS"],
     [("Design pressure", "23.5 barg"), ("Bonnet material", "CS")]),
    # A unit in its own column.
    (["Concrete bearing stress", "8300", "kPa"],
     [("Concrete bearing stress", "8300 kPa")]),
])
def test_the_layouts_that_already_worked_still_do(cells, expected):
    assert datasheets.split_label_value(cells) == expected


def test_a_field_whose_name_merely_contains_a_reference_word_survives():
    """The guard on the cross-reference rule. "Figure 1" is a pointer;
    "Figure of merit" and "Notes on installation" are not, and a rule that
    swallowed them would silently drop real fields."""
    for label in ("Figure of merit", "Table support material",
                  "Note on nozzle orientation"):
        assert datasheets.split_label_value([label, "42 mm"]) == [
            (label, "42 mm")], f"{label!r} was read as a cross-reference"
