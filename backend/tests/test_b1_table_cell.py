"""ONE REVIEWER: the one cell of a field label on stored table rows, the slash-compound split, the per-tag groups and the settling of a held reading.
General tables only: invented labels and tags; nothing of one sheet. Pure."""

from __future__ import annotations

import json

import pytest

from app import agent_review_calculator_cells as cells
from app import table_cell as T


def tbl(*rows):
    return [list(r) for r in rows]


# ---------------------------------------------------------------------------------------- the cell of a label in its own row


def test_a_label_and_the_value_to_its_right_with_only_empty_cells_between_is_one_cell():
    rows = tbl(
        ["1", "Fluid", "", "Water", "", "42", "Cap", "Bolted"],
        ["2", "Rate", "", "5 kg/h", "", "43", "Lift", "Plain"],
    )
    got, why = T.locate([rows], page=1, label="Fluid", value_text="Water")
    assert (
        got
        and (got.label_col, got.value_col, got.row) == (1, 3, 0)
        and got.quote == "Fluid Water"
        and why == ""
    )
    right, _ = T.locate([rows], page=1, label="Cap", value_text="Bolted")
    assert right and (right.label_col, right.value_col) == (
        6,
        7,
    )  # the other half of the row


def test_a_non_empty_cell_between_the_label_and_the_value_is_no_cell():
    rows = tbl(["Rate", "10", "12"])
    got, why = T.locate([rows], page=1, label="Rate", value_text="12")
    assert got is None and "no cell holds the value next to the label" in why


def test_a_label_on_two_rows_with_the_same_value_is_ambiguous_never_a_guess():
    rows = tbl(["Rate", "5 kg/h"], ["Rate", "5 kg/h"])
    got, why = T.locate([rows], page=1, label="Rate", value_text="5 kg/h")
    assert got is None and "more than one place" in why


def test_an_unknown_label_and_empty_inputs_say_why():
    assert (
        T.locate([tbl(["A", "1"])], page=1, label="B", value_text="1")[1]
        == "the label is not a cell of any table on this page"
    )
    assert T.locate([], page=1, label="", value_text="1")[0] is None


# ---------------------------------------------------------------------------------------- a column per case or tag (2, 3 and 5 columns)


@pytest.mark.parametrize("n", [2, 3, 5])
def test_the_cell_is_where_the_labels_row_crosses_the_headers_column(n):
    heads = [f"Case {chr(65 + k)}" for k in range(n)]
    rows = tbl(
        ["", *heads],
        ["Set pressure", *[str(10 + k) for k in range(n)]],
        ["Rate", *[str(100 + k) for k in range(n)]],
    )
    for k in range(n):
        got, why = T.locate_column(
            [rows], page=1, label="Set pressure", header=heads[k]
        )
        assert (
            got and got.value_text == str(10 + k) and got.label_text == "Set pressure"
        ), why


def test_a_header_that_matches_two_columns_or_a_label_on_two_rows_or_an_empty_crossing_is_a_refusal():
    two = tbl(["", "Case A", "Case A"], ["Rate", "1", "2"])
    assert T.locate_column([two], page=1, label="Rate", header="Case A")[0] is None
    rows = tbl(["", "Case A", "Case B"], ["Rate", "1", "2"], ["Rate", "3", "4"])
    assert T.locate_column([rows], page=1, label="Rate", header="Case A")[0] is None
    empty = tbl(["", "Case A", "Case B"], ["Rate", "1", ""])
    assert T.locate_column([empty], page=1, label="Rate", header="Case B")[0] is None
    assert (
        T.locate_column([tbl(["Rate", "1"])], page=1, label="Rate", header="Case Z")[1]
        == T.NO_HEADER
    )


def test_a_note_column_is_never_the_value_of_a_case():
    rows = tbl(["", "Case A", "Case B", "Notes"], ["Rate", "1", "2", "see note 3"])
    assert (
        T.locate_column([rows], page=1, label="Rate", header="Case B")[0].value_text
        == "2"
    )
    assert (
        T.locate_column([rows], page=1, label="Rate", header="Notes")[0].value_text
        == "see note 3"
    )  # asked for the note column, it is the note


# ---------------------------------------------------------------------------------------- slash-compound rows


def test_a_two_part_compound_splits_by_position_and_says_so_in_plain_words():
    k, figure, unit, words = T.split_compound(
        "Inlet/Outlet pressure",
        "7.5 / 3.25 barg (Note - 9)",
        "Outlet pressure",
    )
    assert (k, figure, unit) == (
        1,
        "3.25",
        "barg",
    ) and words == "read as the second of two values in 'Inlet/Outlet pressure'"
    first = T.split_compound(
        "Inlet/Outlet pressure", "7.5 / 3.25 barg", "Inlet pressure"
    )
    assert first[:3] == (0, "7.5", "barg") and "first of two values" in first[3]


def test_a_three_part_compound_and_a_unit_repeated_on_each_part():
    assert T.split_compound(
        "Min/Nor/Max temperature", "1 / 2 / 3 C", "Nor temperature"
    )[:3] == (1, "2", "C")
    assert T.split_compound("Min/Max temperature", "1 C / 3 C", "Max temperature")[
        :3
    ] == (1, "3", "C")


@pytest.mark.parametrize(
    "label, cell, wanted",
    [
        (
            "Inlet/Outlet pressure",
            "7.5 / 3.25 / 9 barg",
            "Inlet pressure",
        ),  # unequal counts
        (
            "Inlet/Outlet pressure",
            "7.5 barg / 3.25",
            "Inlet pressure",
        ),  # the unit on the first part only
        (
            "Inlet/Outlet pressure",
            "7.5 bar / 3.25 psi",
            "Inlet pressure",
        ),  # two different units
        (
            "Inlet/Outlet pressure",
            "7.5 / 3.25 barg",
            "Set pressure",
        ),  # not one of the label's parts
        (
            "Inlet/Outlet pressure",
            "see note / 3.25 barg",
            "Inlet pressure",
        ),  # a part with no number
        ("Pressure", "7.5 / 3.25 barg", "Pressure"),  # not a compound label
    ],
)
def test_a_compound_that_does_not_split_cleanly_is_not_split(label, cell, wanted):
    assert T.split_compound(label, cell, wanted) is None


def test_a_compound_row_is_found_only_once_on_a_page():
    row = ["5", "Inlet/Outlet pressure", "", "7.5 / 3.25 barg", "", "", "", ""]
    got, figure, unit = T.locate_compound([tbl(row)], page=1, label="Inlet pressure")
    assert (
        got
        and (figure, unit) == ("7.5", "barg")
        and got.split
        and got.quote.endswith("barg")
    )
    twice = T.locate_compound([tbl(row, row)], page=1, label="Inlet pressure")
    assert twice[0] is None and "more than one" in twice[1]


def test_the_cells_words_must_stand_on_the_page_text():
    cell = T.Cell(1, 0, 0, 0, 1, "Rate", "5 kg/h")
    assert T.in_page(cell, "x Rate\n5 kg/h y") and not T.in_page(cell, "Rate 6 kg/h")
    assert not T.in_page(cell, "")


def test_tables_of_reads_the_stored_shape_and_is_empty_on_garbage():
    assert T.tables_of(json.dumps({"v": 1, "tables": [{"rows": [["a", None]]}]})) == [
        [["a", ""]]
    ]
    assert T.tables_of("not json") == [] and T.tables_of(None) == []


# ---------------------------------------------------------------------------------------- per-tag groups


def f(page, label, raw, tag=None, **over):
    return {
        "id": f"f{page}{label}",
        "page": page,
        "field_label": label,
        "raw_value": raw,
        "source_text": f"{raw} bar",
        "equipment_tag": tag,
        **over,
    }


def test_facts_are_grouped_by_tag_and_a_tagless_fact_by_its_page():
    facts = [
        f(1, "A", "1", "T1"),
        f(2, "A", "2", "T2"),
        f(3, "A", "3"),
        f(4, "B", "4"),
        f(1, "B", "5", "T1"),
    ]
    got = cells.groups(facts)
    assert sorted(got) == ["T1", "T2", "page 3", "page 4"] and len(got["T1"]) == 2
    assert cells.page_tag_counts(facts) == {1: 1, 2: 1, 3: 1, 4: 1}
    two = [f(1, "A", "1", "T1"), f(1, "A", "2", "T2")]
    assert cells.page_tag_counts(two) == {1: 2} and sorted(cells.groups(two)) == [
        "T1",
        "T2",
    ]


# ---------------------------------------------------------------------------------------- settling a held reading


def held(page, label, raw, tag, **box):
    return f(page, label, raw, tag, validation_state="conflict", bbox=json.dumps(box))


def test_a_hold_that_is_only_other_tags_values_is_lifted_and_says_why():
    facts = [held(1, "Rate", "5", "T1", conflict_pages=[1, 2]), f(2, "Rate", "6", "T2")]
    got, words = cells.settle(facts[0], facts, {})
    assert (
        got["validation_state"] is None
        and "other tags" in words
        and got["settled_note"] == words
    )


def test_the_lift_needs_every_rival_under_another_KNOWN_tag():
    mine = held(1, "Rate", "5", "T1", conflict_pages=[1, 2])
    for rivals, why in (
        ([f(2, "Rate", "6")], "a tag-less continuation page"),
        ([f(2, "Rate", "6", "T1")], "the same tag"),
        ([f(2, "Rate", "6", "T1 and T2")], "a header that names the same tag"),
        (
            [f(2, "Rate", "6", "T2"), f(3, "Rate", "7")],
            "one rival under another tag and one tag-less",
        ),
        ([], "no rival to compare with"),
    ):
        mine = held(1, "Rate", "5", "T1", conflict_pages=[1, 2, 3])
        got, words = cells.settle(mine, [mine, *rivals], {})
        assert got["validation_state"] == "conflict" and words is None, why
    untagged = held(1, "Rate", "5", None, conflict_pages=[1, 2])
    other = f(2, "Rate", "6", "T2")
    assert (
        cells.settle(untagged, [untagged, other], {})[0]["validation_state"]
        == "conflict"
    )  # my own fact has no tag
    two = held(1, "Rate", "5", "T1", conflict_pages=[1, 2])
    assert (
        cells.settle(two, [two, f(2, "Rate", "6", "T2 and T3")], {})[0][
            "validation_state"
        ]
        is None
    )  # another tag's own header naming two tags is still another tag


def test_two_tags_of_one_header_overlap_but_two_headers_without_a_shared_identifier_do_not():
    a = {"equipment_tag": "XV-101 A/B & XV-201 A/B"}
    assert not cells.other_tags(a, {"equipment_tag": "XV-201 A/B"})
    assert cells.other_tags(a, {"equipment_tag": "XV-103 A/B & XV-203 A/B"})
    assert not cells.other_tags(a, {"equipment_tag": None}) and not cells.other_tags(
        {}, a
    )


def test_a_hold_with_a_rival_in_its_own_group_is_not_lifted_without_a_cell():
    a = held(1, "Rate", "5", "T1", conflicts_with=["rival"])
    rival = {**f(1, "Rate", "6", "T1"), "id": "rival", "extraction_method": "model"}
    got, words = cells.settle(a, [a, rival], {})
    assert (
        got["validation_state"] == "conflict"
        and words is None
        and "reading_conflict" not in got
    )


def test_two_readings_in_one_tag_are_never_settled_into_a_value_at_most_a_question_names_both():
    a = held(1, "Rate", "5", "T1", conflicts_with=["rival"])
    rival = {**f(1, "Rate", "6", "T1"), "id": "rival", "extraction_method": "model"}
    got, words = cells.settle(a, [a, rival], {1: [tbl(["Rate", "", "5 bar"])]})
    assert (
        words is None
        and got["validation_state"] == "conflict"
        and got["raw_value"] == "5"
    )  # the hold stays, the value is not chosen
    assert (
        got["reading_conflict"]
        == "two readings: 5 and 6; the table cell beside the label holds 5; confirm"
    )
    other, _ = cells.settle(a, [a, rival], {1: [tbl(["Rate", "", "6 bar"])]})
    assert (
        other["reading_conflict"]
        == "two readings: 6 and 5; the table cell beside the label holds 6; confirm"
        and other["raw_value"] == "5"
    )
    for rows in (
        [tbl(["Rate", "", "9 bar"])],
        [tbl(["Rate", "", "5 bar"], ["Rate", "", "6 bar"])],
        [tbl(["Rate", "", "5 / 6 bar"])],
    ):
        assert "reading_conflict" not in cells.settle(a, [a, rival], {1: rows})[0]


def test_an_engineer_confirmed_fact_and_other_states_are_left_alone():
    a = {**held(1, "Rate", "5", "T1", conflict_pages=[1, 2]), "confirmed_by": "eng"}
    assert cells.settle(a, [a], {}) == (a, None)
    other = f(1, "Rate", "5", "T1", validation_state="needs_engineer_review")
    assert cells.settle(other, [other], {})[1] is None


# ---------------------------------------------------------------------------------------- which cell is a fact's value


def test_a_single_tag_page_takes_the_cell_next_to_its_label():
    rows = {1: [tbl(["1", "Rate", "", "5 bar", "", "9", "Other", "x"])]}
    got = cells.cell_of(f(1, "Rate", "5", "T1"), rows)
    assert got and got.value_text == "5 bar"


def test_with_several_tags_on_a_page_the_cell_is_the_tags_own_column_and_never_another():
    rows = {1: [tbl(["", "T1", "T2"], ["Rate", "5 bar", "6 bar"])]}
    one, two = f(1, "Rate", "5", "T1"), f(1, "Rate", "6", "T2")
    assert (
        cells.cell_of(one, rows, 2).value_text == "5 bar"
        and cells.cell_of(two, rows, 2).value_text == "6 bar"
    )
    wrong = f(1, "Rate", "5", "T2")  # the fact says 5 for T2, the table says 6
    assert cells.cell_of(wrong, rows, 2) is None


def test_a_compound_row_gives_the_part_whose_figure_is_the_facts_number():
    rows = {1: [tbl(["5", "Inlet/Outlet pressure", "", "7.5 / 3.25 barg"])]}
    first = cells.cell_of(f(1, "Inlet pressure", "7.5", "T1"), rows)
    assert first and "first of two" in first.split
    assert cells.cell_of(f(1, "Inlet pressure", "99", "T1"), rows) is None


def test_a_blank_fact_or_a_page_with_no_table_has_no_cell():
    assert (
        cells.cell_of(
            f(1, "Rate", "5", "T1", is_blank=True), {1: [tbl(["Rate", "5 bar"])]}
        )
        is None
    )
    assert cells.cell_of(f(1, "Rate", "5", "T1"), {}) is None


# ---------------------------------------------------------------------------------------- the column header of a value cell (R48m 5)


def test_the_header_over_a_value_cell_is_the_nearest_text_above_in_its_own_column():
    rows = tbl(["", "Normal", "Design"], ["Pressure", "10", "12"])
    assert T.header_of(rows, 1, 2) == "Design" and T.header_of(rows, 1, 1) == "Normal"
    assert T.header_of(tbl(["Pressure", "10"]), 0, 1) is None  # nothing above
    assert (
        T.header_of(tbl(["", "12"], ["Pressure", "10"]), 1, 1) is None
    )  # only a number above: not a header


def test_the_cell_carries_its_header_in_its_reference():
    rows = tbl(["", "Normal", "Design"], ["Pressure", "", "12"])
    got, _ = T.locate([rows], page=1, label="Pressure", value_text="12")
    assert got.header == "Design" and got.ref()["header"] == "Design"
    crossed, _ = T.locate_column(
        [tbl(["", "T1", "T2"], ["Rate", "5", "6"])], page=1, label="Rate", header="T2"
    )
    assert crossed.header == "T2"
