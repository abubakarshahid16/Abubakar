"""A placeholder value ("*", "TBA", "by vendor") is never "stated" (planner,
28 Oct, audit of the live M-03 run): "MIN FLOW THERMAL * m3/h" passed "the
minimum flow is stated". Invented values only."""

from __future__ import annotations

import pytest

from app import blank_markers
from tests.test_746_relief_valve_checklist import fact, results

SET = "set pressure"


def _set_pressure_status(f):
    rows = [
        r
        for r in results([f]).values()
        if "set pressure is stated" in r["text"].lower()
    ]
    assert rows
    return rows[0]["status"]


@pytest.mark.parametrize("value", ["*", "TBA", "by vendor", "later"])
def test_a_placeholder_with_a_unit_is_missing_not_stated(value):
    assert _set_pressure_status(fact(SET, value, "barg")) == "MISSING_INFORMATION"


def test_a_real_value_is_still_stated():
    assert _set_pressure_status(fact(SET, "10", "barg")) == "COMPLIANT"


def test_a_mandatory_field_with_a_unit_and_a_placeholder_value_is_missing():
    """The mandatory-field check (DS-M2) judges the bare value too."""
    from tests.test_datasheet_checks import fact as dfact
    from tests.test_datasheet_checks import full_vessel, run

    results = run(
        full_vessel(**{"hydrotest pressure": dfact("hydrotest pressure", "*", "barg")})
    )
    assert results["DS-M2"]["status"] == "MISSING_INFORMATION"
    assert results["DS-M2"]["detail"].startswith(
        "Hydrotest pressure is marked '* barg'"
    )


# 2p gate (s2, 28 Oct, I-06): "10 barg By Contractor" states 10 barg (#725 F3: the phrase is a note on
# the figure). The placeholder test must not turn a read figure into "the contractor is to provide it".


def _named(name, printed, raw, unit="barg"):
    f = fact(name, raw, unit)
    f["field_value"] = printed
    return f


@pytest.mark.parametrize(
    ("printed", "raw"),
    [
        ("10 barg By Contractor", "10"),  # the reader parsed the figure
        ("10 barg (By Contractor, as per Code)", "10"),
        ("10 barg By Contractor", None),  # only the printed cell is left
        ("10 barg TBC", None),
        ("<85 dBA By Contractor", None),  # a comparator first is still a figure first
        ("-5 degC TBC", None),
        ("0.5 bar (by vendor)", None),
    ],
)
def test_a_figure_with_a_note_beside_it_is_stated(printed, raw):
    assert _set_pressure_status(_named(SET, printed, raw)) == "COMPLIANT"


@pytest.mark.parametrize(
    ("printed", "raw"),
    [
        (
            "By Contractor 10 barg",
            None,
        ),  # the phrase first: nothing says which is the value
        (
            "(By Contractor) 10 barg",
            "10",
        ),  # the phrase first, even when a figure was parsed
        ("TBC 10 barg", None),
        ("TBA 2025", "TBA 2025"),  # a digit after the phrase is not its figure
        ("TBA", "TBA"),
        ("m3/h TBA", None),  # a digit inside a unit is not a figure
        ("* m3/h", "*"),
        ("By Contractor", "By Contractor"),
    ],
)
def test_a_phrase_with_no_figure_first_is_still_missing(printed, raw):
    assert _set_pressure_status(_named(SET, printed, raw)) == "MISSING_INFORMATION"


@pytest.mark.parametrize(
    "printed",
    [
        "See note 3 - vendor to advise",
        "Note 3: by contractor",
        "Per API 520, by contractor",
        "ASME Class 300, TBC",
        "Item 2 TBA",
        "3. By contractor",  # a list number
        "3: vendor to advise",
        "10. By contractor",
    ],
)
def test_a_reference_number_before_a_phrase_is_not_a_figure(printed):
    """cloud-2 on #1399 (28 Oct): a note, code, class or item number ahead of the phrase is not the value."""
    assert _set_pressure_status(_named(SET, printed, "3")) == "MISSING_INFORMATION"
    assert _set_pressure_status(_named(SET, printed, None)) == "MISSING_INFORMATION"


def test_the_mandatory_field_path_keeps_a_figure_with_a_note_as_missing():
    """DS-M2 is unchanged by the checklist fix: '340 psig By Contractor' is a provisional figure the
    vendor must confirm (the `blank_markers` module note), exactly as on 2o."""
    from tests.test_datasheet_checks import fact as sheet_fact
    from tests.test_datasheet_checks import full_vessel, run

    f = sheet_fact("hydrotest pressure", "340", "psig")
    f["field_value"] = "340 psig By Contractor"
    results = run(full_vessel(**{"hydrotest pressure": f}))
    assert results["DS-M2"]["status"] == "MISSING_INFORMATION"
    assert (
        "Hydrotest pressure is marked '340 psig By Contractor'"
        in results["DS-M2"]["detail"]
    )


# 2p gate, M-03 (s2 21:04): the geometry reader stores the cell as a label word, a lone "*" and a unit with a
# digit, with no parsed value and no blank flag. `classify` sees a star only when it is the whole cell.


@pytest.mark.parametrize(
    "printed",
    [
        "THERMAL * m3/h",
        "Min flow * m3/h",
        "THERMAL ___*___ m3/h",
        "THERMAL ___ m3/h",
        "m3/h *",
        "Rated flow * see note 3",
        "Rated flow * Item 2 TBA",
        "Set pressure * per API 526",
        "Rated flow * Class 300",
    ],
)
def test_a_lone_star_between_a_label_and_a_unit_is_a_placeholder(printed):
    assert _set_pressure_status(_named(SET, printed, None)) == "MISSING_INFORMATION"
    f = _named(SET, printed, None)
    f.update(is_blank=0, blank_marker=None, raw_unit=None)
    assert blank_markers.fact_is_placeholder(f) and blank_markers.fact_is_placeholder(
        f, figure_wins=True
    )


@pytest.mark.parametrize(
    "printed",
    [
        "10 barg *",
        "Pump 2*4 inline",
        "5* stage",
        "RATED FLOW * 24.8 m3/h",
        "Set pressure * 10 barg",
        "Head 78 m *",
    ],
)
def test_a_star_that_is_not_standing_alone_or_follows_a_figure_is_not_a_placeholder(
    printed,
):
    assert _set_pressure_status(_named(SET, printed, None)) == "COMPLIANT"
    # and on the path that does not let a figure win (the mandatory-field check)
    assert not blank_markers.fact_is_placeholder(_named(SET, printed, None))
