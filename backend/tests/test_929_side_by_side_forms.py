"""#929 (PF2): a four-column table of two forms side by side is read as two pairs per row.

Before: row 0 was taken as the header, so the first row was lost and every other label grew a
column name as a suffix; worse, a label became the VALUE of another field ("Design pressure -
Vacuum service" = "Design temperature"). Invented tables only. The shape rules are general (a
closed list of column-name words, no label or layout named); three or more columns, a four-column
header naming four different columns, and every other width are read as before.
"""

from __future__ import annotations

import pytest

from app import datasheets, table_pairs

FORM = [
    ["Service", "Air receiver", "Vacuum service", "No"],
    ["Design pressure", "10 barg", "Design temperature", "120 C"],
    ["Shell plate material", "SA-285 Grade C", "Radiography", "10 %"],
    ["Hydrostatic test pressure", "15 barg", "Joint efficiency", "0.85"],
]


def _pairs(shape):
    return datasheets.pairs_from_table_shape(shape)


def test_two_forms_side_by_side_give_two_pairs_per_row_including_the_first_row():
    assert _pairs(FORM) == [
        ("Service", "Air receiver"),
        ("Vacuum service", "No"),
        ("Design pressure", "10 barg"),
        ("Design temperature", "120 C"),
        ("Shell plate material", "SA-285 Grade C"),
        ("Radiography", "10 %"),
        ("Hydrostatic test pressure", "15 barg"),
        ("Joint efficiency", "0.85"),
    ]


def test_no_label_becomes_the_value_of_another_field_and_none_grows_a_suffix():
    pairs = _pairs(FORM)
    labels = {label for label, _ in pairs}
    values = {value for _, value in pairs}
    assert not (labels & values)  # "Design temperature" is never a value
    assert all(" - " not in label for label in labels)


def test_a_repeated_header_is_skipped_and_the_rows_are_still_two_pairs():
    shape = [
        ["Parameter", "Value", "Parameter", "Value"],
        ["Design pressure", "10 barg", "Design temperature", "120 C"],
        ["Shell plate material", "SA-285 Grade C", "Radiography", "10 %"],
    ]
    assert _pairs(shape) == [
        ("Design pressure", "10 barg"),
        ("Design temperature", "120 C"),
        ("Shell plate material", "SA-285 Grade C"),
        ("Radiography", "10 %"),
    ]


def test_a_title_row_is_not_an_answer():
    shape = [["Pressure vessel data", "", "", ""], *FORM[1:]]
    assert _pairs(shape)[0] == ("Design pressure", "10 barg")


def test_a_pair_with_an_empty_answer_is_not_emitted():
    shape = [
        *FORM[:3],
        ["Test pressure", "15 barg", "Joint efficiency", "0.85"],
        ["Hydrostatic test pressure", "", "Corrosion allowance", "3 mm"],
    ]
    assert ("Hydrostatic test pressure", "") not in _pairs(shape)
    assert ("Corrosion allowance", "3 mm") in _pairs(shape)


@pytest.mark.parametrize(
    "shape",
    [
        # a four-column header naming FOUR DIFFERENT columns: an ordinary table
        [
            ["Item", "Required", "Offered", "Remarks"],
            ["Casing", "Cast iron", "Cast steel", "Accepted"],
            ["Impeller", "Bronze", "Bronze", "Accepted"],
        ],
        # a unit column and a remarks column
        [
            ["Parameter", "Value", "Unit", "Remarks"],
            ["Design pressure", "10", "barg", "note"],
            ["Design temperature", "120", "C", "note"],
        ],
        # the third column holds codes, not labels
        [
            ["Item", "Required", "Offered", "Remarks"],
            ["Material", "SA-516", "SA-516 Gr70", "OK"],
            ["Flange", "ASME B16.5", "ASME B16.5", "OK"],
        ],
        # three columns
        [
            ["Parameter", "Units", "Value"],
            ["Design pressure", "barg", "10"],
            ["Design temperature", "C", "120"],
        ],
        # two columns and five columns
        [
            ["Gas handled", "Nitrogen"],
            ["Casing design pressure", "14 barg"],
            ["Discharge temperature", "80 C"],
        ],
        # too few rows
        FORM[:2],
    ],
)
def test_every_other_shape_returns_none_and_is_read_as_before(shape):
    assert table_pairs.two_pairs_per_row(shape) is None


def test_the_two_column_table_still_reads_its_first_row_as_an_answer():
    assert _pairs(
        [["Gas handled", "Nitrogen"], ["Casing design pressure", "14 barg"]]
    ) == [
        ("Gas handled", "Nitrogen"),
        ("Casing design pressure", "14 barg"),
    ]


def test_the_column_name_words_are_a_closed_list_not_a_guess():
    assert table_pairs.is_column_names(
        ["Description", "Required", "Offered", "Remarks"]
    )
    assert not table_pairs.is_column_names(
        ["Service", "Air receiver", "Vacuum service", "No"]
    )
    assert not table_pairs.is_column_names(["Design pressure", "Value"])


def test_one_pair_shaped_row_among_others_is_not_enough():
    """A table of which only one row looks like two forms is not that shape."""
    shape = [
        ["Service", "Air receiver", "Vacuum service", "No"],
        ["Material", "SA-516", "SA-516 Gr70", "OK"],
        ["Flange", "ASME B16.5", "ASME B16.5", "OK"],
        ["Bolting", "B7", "B7M", "OK"],
    ]
    assert table_pairs.two_pairs_per_row(shape) is None


def test_two_pair_shaped_rows_among_many_others_are_not_enough():
    pair = ["Design pressure", "10 barg", "Design temperature", "120 C"]
    other = ["Material", "SA-516", "SA-516 Gr70", "OK"]
    assert table_pairs.two_pairs_per_row([pair, pair, other, other, other]) is None
    assert table_pairs.two_pairs_per_row([pair, pair, pair, other, other]) is not None


# the probes of s3's and cloud-3's reviews of the first version: tables of WORDS read as two forms
TEXT_TABLES = {
    "a text matrix": [
        ["Part", "Casing", "Impeller", "Shaft"],
        ["Material", "Cast iron", "Bronze", "Steel"],
        ["Finish", "Smooth", "Rough", "Polished"],
        ["Coating", "Epoxy", "None", "Paint"],
    ],
    "a header with an unlisted word": [
        ["Item", "Value", "Remarks", "Source"],
        ["Fluid", "Water", "Per client", "Datasheet"],
        ["Phase", "Liquid", "As stated", "Datasheet"],
        ["Duty", "Continuous", "Client", "Datasheet"],
    ],
    "components and materials": [
        ["Component", "Material", "Type", "Remarks"],
        ["Casing", "Cast iron", "Welded", "Accepted"],
        ["Impeller", "Bronze", "Cast", "Accepted"],
        ["Shaft", "Steel", "Forged", "Accepted"],
    ],
    "a yes/no compliance table": [
        ["Requirement", "Contractor", "Vendor", "Compliant"],
        ["Painting per spec", "Yes", "Yes", "Yes"],
        ["Coupling guard", "Yes", "No", "No"],
    ],
    "a value in one answer column only": [
        ["Item", "Material", "Type", "Thickness"],
        ["Casing", "Cast iron", "Welded", "10 mm"],
        ["Impeller", "Bronze", "Cast", "5 mm"],
        ["Shaft", "Steel", "Forged", "40 mm"],
    ],
}


@pytest.mark.parametrize("name", sorted(TEXT_TABLES))
def test_a_table_of_words_keeps_its_column_reading(name, monkeypatch):
    """No value (a digit) in BOTH answers, so it is not two forms: the old reading stands, so
    "Bronze = Steel" and "Welded = Accepted" are never invented."""
    shape = TEXT_TABLES[name]
    assert table_pairs.two_pairs_per_row(shape) is None
    got = _pairs(shape)
    monkeypatch.setattr(table_pairs, "two_pairs_per_row", lambda _shape: None)
    assert got == _pairs(
        shape
    )  # identical to the reading with the new rule switched off
    assert all(" - " in label for label, _ in got)  # every fact keeps its column name


def test_a_header_naming_four_different_columns_is_never_two_forms_even_with_pair_shaped_rows():
    """The repeated-header rule: the first row names Item/Required/Offered/Remarks, so the rows are
    columns of one table, whatever they look like. The old reading stands."""
    shape = [
        ["Item", "Required", "Offered", "Remarks"],
        ["Design pressure", "10 barg", "Design temperature", "120 C"],
        ["Shell plate material", "SA-285 Grade C", "Radiography", "10 %"],
        ["Hydrostatic test pressure", "15 barg", "Joint efficiency", "0.85"],
    ]
    assert table_pairs.two_pairs_per_row(shape) is None


def test_a_label_that_carries_a_digit_is_not_read_as_two_forms_a_known_limit():
    """Conservative on purpose: "H2S content" has a digit, so a table of such labels is left to the
    old reading rather than guessed at (said in the PR)."""
    shape = [
        ["H2S content", "5 ppm", "CO2 content", "3 %"],
        ["H2O content", "2 ppm", "O2 content", "1 %"],
        ["N2 content", "9 %", "He content", "0.1 %"],
    ]
    assert table_pairs.two_pairs_per_row(shape) is None
