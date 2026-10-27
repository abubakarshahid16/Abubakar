"""#1309 backlog 243.4b: "24.8 m3/h (30 gpm)" was read with the first number unchecked, because
`gpm` is recognised but not converted by the unit table. The trailing form now checks a bare
`gpm` bracket as the US gallon per minute (cross-check only): a gross mismatch is refused like
"(30 USGPM)", a nominal one reads as before. The interleaved form and the unit table are
untouched. Invented values only.
"""

from __future__ import annotations

import re

import pytest

from app import claims, datasheets, dual_unit_form


def _read(raw: str):
    value, unit, _m = datasheets.measure_value(raw)
    return value, unit


@pytest.mark.parametrize(
    "cell",
    [
        "24.8 m3/h (30 gpm)",
        "24.8 m3/h (30 GPM)",
        "24.8 m3/h (30  gpm)",
        "24.8 m3/h (200 gpm)",
        "10 m3/h (1 gpm)",
    ],
)
def test_a_gross_gpm_mismatch_is_refused_like_usgpm(cell):
    assert _read(cell) == _read(re.sub("(?i)gpm", "USGPM", cell))
    assert _read(cell) == (None, None)


@pytest.mark.parametrize(
    "cell, value",
    [
        ("24.8 m3/h (109 gpm)", "24.8"),  # 109 US gpm = 24.76 m3/h
        (
            "24.8 m3/h (91 gpm)",
            "24.8",
        ),  # 91 imperial gpm = 24.8 m3/h, 16% from the US reading
        ("24.8 m3/h (100 gpm)", "24.8"),
    ],
)
def test_a_nominal_gpm_bracket_reads_as_before(cell, value):
    assert _read(cell) == (value, "m3/h")


def test_the_unit_table_and_the_interleaved_form_are_untouched():
    assert claims.unit_dimension("gpm") is None
    assert dual_unit_form.first_system("24.8 (30) m3/h (gpm)", lambda *a: True) is None
    assert _read("24.8 (109) m3/h (gpm)") == ("24.8", None)


def test_other_second_units_are_not_renamed():
    assert dual_unit_form._CHECKED_AS == {"gpm": "usgpm"}
    # An unknown bracket unit is not a unit: the cell reads as before (first number, with its unit).
    assert _read("24.8 m3/h (30 foo)") == ("24.8", "m3/h")
