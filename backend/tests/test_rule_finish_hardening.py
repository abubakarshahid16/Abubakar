# ruff: noqa: RUF001  (thin and no-break spaces in digit groups are the point of these tests)
"""Reading figures for step a, polarity as a closed table, comparators, ranges, unreadable figures (Lane 1).
Every text here is INVENTED."""

from __future__ import annotations

import json

import pytest

from app import rule_finish as rf
from app import rule_finish_figures as ff
from tests.test_rule_finish_kit import marker_key, rule  # noqa: F401

# ------------------------------------------------------------------------------------------------ H1 polarity table

#: The closed table written out here, independently of the module, so a phrase dropped or changed there is caught.
_GE = (
    "at least",
    "minimum",
    "min.",
    "min",
    "not less than",
    "no less than",
    "not smaller than",
    "not lower than",
    "not fewer than",
    "shall not be less than",
    "shall not be smaller than",
    "shall not be lower than",
    "greater than or equal to",
    ">=",
    "\u2265",
)
_LE = (
    "at most",
    "maximum",
    "max.",
    "max",
    "not more than",
    "no more than",
    "not greater than",
    "no greater than",
    "not higher than",
    "no higher than",
    "not exceeding",
    "shall not exceed",
    "not to exceed",
    "shall not be more than",
    "shall not be greater than",
    "shall not be higher than",
    "nor more than",
    "nor greater than",
    "nor exceeding",
    "up to",
    "less than or equal to",
    "<=",
    "\u2264",
)
TABLE = [
    *((p, ">=") for p in _GE),
    *((p, "<=") for p in _LE),
    *((p, "=") for p in ("exactly", "equal to", "equals")),
    *((p, ">") for p in ("more than", "greater than", "exceeding", "higher than")),
    *((p, "<") for p in ("less than", "smaller than", "lower than", "fewer than")),
]


def test_the_table_is_exactly_the_closed_table():
    assert sorted(TABLE) == sorted(
        (p, s) for s, ps in ff.POLARITY_TABLE.items() for p in ps
    )


@pytest.mark.parametrize("phrase, sym", TABLE)
def test_every_phrase_of_the_closed_table_gives_its_comparator(phrase, sym):
    (f,) = ff.figures(f"The wall shall be {phrase} 10 mm thick.")
    assert (f.value, f.comparator) == (10.0, sym)


@pytest.mark.parametrize(
    "quote, expected",
    [
        ("shall not be less than 10 mm", ">="),  # was read '<'
        ("not exceeding 10 mm", "<="),  # was read '>'
        ("no greater than 10 mm", "<="),
        ("shall not be more than 10 mm", "<="),
        ("not smaller than 10 mm", ">="),  # was read '<'
        ("not lower than 10 mm", ">="),
        ("not higher than 10 mm", "<="),
        ("less than 10 mm", "<"),
        ("more than 10 mm", ">"),
    ],
)
def test_a_negated_comparative_gives_the_right_polarity(quote, expected):
    assert [f.comparator for f in ff.figures(quote)] == [expected]


@pytest.mark.parametrize(
    "quote, expected",
    [
        (
            "not less than 10 mm nor more than 20 mm",
            [(10.0, ">="), (20.0, "<=")],
        ),  # the 20 was read '>'
        ("not less than 10 mm and not more than 20 mm", [(10.0, ">="), (20.0, "<=")]),
        ("not less than 10 mm and at most 20 mm", [(10.0, ">="), (20.0, "<=")]),
        (
            "10 mm minimum, 20 mm maximum",
            [(10.0, ">="), (20.0, "<=")],
        ),  # the 20 took '>=' from the 10's trailing word
        ("20 mm maximum and 10 mm minimum", [(20.0, "<="), (10.0, ">=")]),
        ("at least 10 mm and at most 20 mm", [(10.0, ">="), (20.0, "<=")]),
        (
            "at least 3/4 inch for threaded and 1 inch for flanged",
            [(0.75, ">="), (1.0, None)],
        ),  # never inherited
    ],
)
def test_every_figure_takes_the_phrase_immediately_governing_it_and_never_one_from_another_figure(
    quote, expected
):
    assert [(f.value, f.comparator) for f in ff.figures(quote)] == expected


@pytest.mark.parametrize(
    "quote",
    [
        "neither less than 5 mm",  # a negation the table does not use
        "shall not be roughly 5 mm",
        "at least or at most 5 mm",  # two polarities
        "5 mm",  # none
        "at least 5 mm maximum",  # leading and trailing disagree
    ],
)
def test_an_unknown_or_conflicting_phrase_is_no_comparator(quote):
    (f,) = ff.figures(quote)
    assert f.comparator is None
    r = rule(quote=quote, kind="limit", value=5, unit="mm", comparator=">=")
    assert rf.limit_and_unit(r)[:2] == (rf.INCOMPLETE, "comparator_unreadable")
    assert (
        rf.limit_and_unit(rule(quote=quote))[0] == rf.FAIL
    )  # proposals list it with comparator None
    _, _, ev = rf.limit_and_unit(rule(quote=quote))
    assert ev["proposed"][0]["comparator"] is None


def test_implied_comparator_needs_exactly_one_reading_of_the_figure():
    assert ff.implied_comparator("at least 10 mm", 10, "mm") == ">="
    assert (
        ff.implied_comparator("at least 10 mm and at most 10 mm", 10, "mm") is None
    )  # two printings disagree
    assert ff.implied_comparator("at least 10 mm", 11, "mm") is None
    assert ff.implied_comparator("at least 10 mm", 10, "kPa") is None
    assert (
        ff.implied_comparator("at least 10 mm and again at least 10 mm", 10, "mm")
        == ">="
    )


def test_unit_matches_needs_both_units_and_the_same_case_where_case_is_meaning():
    (f,) = ff.figures("at least 10 mm")
    assert ff.unit_matches("mm", f) and ff.unit_matches("MM", f)
    assert not ff.unit_matches(None, f) and not ff.unit_matches("", f)
    assert not ff.unit_matches("mm", ff.Figure(1.0, "", 0, 1, 1, "1"))
    assert not ff.unit_matches("M", ff.Figure(1.0, "m", 0, 1, 1, "1"))


# ------------------------------------------------------------------------------------------------ ranges (H3)


@pytest.mark.parametrize(
    "quote",
    ["between 10 and 40 C", "from 10 to 40 C", "10 to 40 C", "10-40 C", "10 C - 40 C"],
)
def test_a_range_is_two_figures_low_then_high(quote):
    assert [(f.value, f.comparator) for f in ff.figures(quote)] == [
        (10.0, ">="),
        (40.0, "<="),
    ]


def test_a_signed_low_end_is_read_whole():
    assert [(f.value, f.comparator) for f in ff.figures("-10 to 40 C")] == [
        (-10.0, ">="),
        (40.0, "<="),
    ]
    assert [f.value for f in ff.figures("minus 10 C")] == [-10.0]


def test_a_range_proposal_is_two_figures_never_one_without_a_comparator():
    _, _, ev = rf.limit_and_unit(rule(quote="Ambient shall be between 10 and 40 C."))
    assert [(p["value"], p["comparator"]) for p in ev["proposed"]] == [
        (10.0, ">="),
        (40.0, "<="),
    ]


def test_a_stored_range_needs_both_ends_in_the_unit_in_order():
    q = "Ambient shall be between 10 and 40 C."
    ok = rule(quote=q, kind="range", value_low=10, value_high=40, unit="C")
    assert rf.limit_and_unit(ok)[:2] == (rf.PASS, "value_and_unit_stand_in_quote")
    assert rf.limit_and_unit(dict(ok, value_low=40, value_high=10))[:2] == (
        rf.FAIL,
        "range_order",
    )
    mixed = rule(
        quote="Use 10 mm and 20 cm.",
        kind="range",
        value_low=10,
        value_high=20,
        unit="mm",
    )
    assert rf.limit_and_unit(mixed)[:2] == (
        rf.FAIL,
        "unit_not_in_quote",
    )  # the unit fits one end only
    other = rule(
        quote="at least 10 mm, then 20 mm",
        kind="range",
        value_low=10,
        value_high=20,
        unit="mm",
    )
    assert rf.limit_and_unit(other)[:2] == (
        rf.FAIL,
        "comparator_mismatch",
    )  # the ends are not low and high


# ------------------------------------------------------------------------------------------------ H2 stored comparator


def test_a_stored_comparator_must_be_the_figures_own():
    q = "The wall shall be at least 10 mm thick."
    ok = rule(quote=q, kind="limit", value=10, unit="mm", comparator=">=")
    assert rf.limit_and_unit(ok)[:2] == (rf.PASS, "value_and_unit_stand_in_quote")
    assert rf.limit_and_unit(dict(ok, comparator="<="))[:2] == (
        rf.FAIL,
        "comparator_mismatch",
    )
    assert rf.limit_and_unit(dict(ok, comparator=">"))[:2] == (
        rf.FAIL,
        "comparator_mismatch",
    )
    assert rf.limit_and_unit(dict(ok, comparator=None))[:2] == (
        rf.FAIL,
        "comparator_missing",
    )
    both = rule(
        quote="at least 10 mm and at most 10 mm",
        kind="limit",
        value=10,
        unit="mm",
        comparator=">=",
    )
    assert rf.limit_and_unit(both)[:2] == (
        rf.INCOMPLETE,
        "comparator_unreadable",
    )  # two readings of the figure


def test_a_bare_number_has_its_comparator_checked_too():
    ok = rule(
        quote="Provide at least 3 stages.",
        kind="limit",
        value=3,
        comparator=">=",
        unit=None,
    )
    assert rf.limit_and_unit(ok)[:2] == (rf.PASS, "value_stands_no_unit_in_quote")
    assert rf.limit_and_unit(dict(ok, comparator="<="))[:2] == (
        rf.FAIL,
        "comparator_mismatch",
    )
    assert (
        rf.limit_and_unit(
            rule(
                quote="Provide 3 stages.",
                kind="limit",
                value=3,
                comparator=">=",
                unit=None,
            )
        )[0]
        == rf.INCOMPLETE
    )
    assert rf.limit_and_unit(dict(ok, unit="mm"))[:2] == (rf.FAIL, "unit_not_in_quote")


# ------------------------------------------------------------------------------------------------ fractions, groups


@pytest.mark.parametrize(
    "quote, value",
    [
        ("size at least ½ inch", 0.5),
        ("size at least 1½ inch", 1.5),
        ("size at least ¾ inch", 0.75),
    ],
)
def test_a_vulgar_fraction_character_is_read_through_numparse(quote, value):
    result, reason, ev = rf.limit_and_unit(rule(quote=quote))
    assert (result, reason) == (rf.FAIL, "figure_not_filled") and ev["proposed"][0][
        "value"
    ] == value
    filled = rule(quote=quote, kind="limit", value=value, unit="inch", comparator=">=")
    assert rf.limit_and_unit(filled)[0] == rf.PASS


def test_a_fraction_character_numparse_cannot_read_is_incomplete_never_not_applicable():
    assert ff.normalise("size 3.½ inch")[1] == "fraction_character_unreadable"
    assert rf.limit_and_unit(rule(quote="size 3.½ inch"))[0] in (rf.INCOMPLETE, rf.FAIL)
    assert ff.read("size 3.½ inch").incomplete in (
        "fraction_character_unreadable",
        "figure_ambiguous",
    )


@pytest.mark.parametrize("sep", [" ", " ", " ", " "])
def test_grouped_thousands_are_one_number_and_zero_never_stands_for_them(sep):
    quote = f"at least 1{sep}000 mm"
    assert [f.value for f in ff.figures(quote)] == [1000.0]
    assert rf.limit_and_unit(
        rule(quote=quote, kind="limit", value=0, unit="mm", comparator=">=")
    )[:2] == (rf.FAIL, "value_not_in_quote")
    assert (
        rf.limit_and_unit(
            rule(quote=quote, kind="limit", value=1000, unit="mm", comparator=">=")
        )[0]
        == rf.PASS
    )
    assert (
        rf.limit_and_unit(
            rule(quote="exactly 0 mm", kind="limit", value=0, unit="mm", comparator="=")
        )[0]
        == rf.PASS
    )


def test_grouped_digits_with_a_decimal_comma_are_read_whole_by_numparse_or_not_at_all():
    assert [f.value for f in ff.figures("at least 1 000,5 mm")] == [1000.5]  # was 0.5
    assert ff.normalise("a gap of 1 000,5,1 mm")[1] == "grouped_number_unreadable"
    assert rf.limit_and_unit(rule(quote="a gap of 1 000,5,1 mm"))[0] == rf.INCOMPLETE


# ------------------------------------------------------------------------------------------------ misreads (M9, H4)


@pytest.mark.parametrize(
    "quote",
    [
        "a head of 10 mm Hg",
        "a head of 5 mm H2O",
        "a rate of 5 mm per side",
        "5 mm w.c.",
        "10 in. H2O",
        "10 in. w.c.",
        "10 IN. W.C.",
        "10 in H2O",
    ],
)
def test_a_unit_followed_by_a_second_unit_word_is_incomplete(quote):
    assert rf.limit_and_unit(rule(quote=quote))[:2] == (rf.INCOMPLETE, "compound_unit")
    filled = rule(quote=quote, kind="limit", value=5, unit="mm", comparator="=")
    assert rf.limit_and_unit(filled)[0] == rf.INCOMPLETE


def test_a_compound_unit_the_unit_table_reads_is_a_figure():
    assert rf.limit_and_unit(rule(quote="a rate of at least 10 mm/s"))[:2] == (
        rf.FAIL,
        "figure_not_filled",
    )


@pytest.mark.parametrize("quote", ["a gap of 1.5.0 mm", "section 1.5.0 mm"])
def test_a_compound_number_beside_a_unit_is_incomplete_not_no_figure(quote):
    assert rf.limit_and_unit(rule(quote=quote))[:2] == (
        rf.INCOMPLETE,
        "number_unreadable",
    )


def test_percent_is_read_as_a_figure_through_the_unit_table():
    (f,) = ff.figures("at least 50 percent")
    assert (f.value, f.unit, f.comparator) == (50.0, "%", ">=")
    assert (
        rf.limit_and_unit(
            rule(
                quote="at least 50 percent",
                kind="limit",
                value=50,
                unit="%",
                comparator=">=",
            )
        )[0]
        == rf.PASS
    )
    assert ff.figures("at least 50 per cent")[0].unit == "%"


def test_a_unit_whose_case_is_its_meaning_is_not_read_loosely():
    assert rf.limit_and_unit(rule(quote="a span of 10 M"))[:2] == (
        rf.INCOMPLETE,
        "unit_case_ambiguous",
    )
    r = rule(quote="at least 10 m", kind="limit", value=10, unit="M", comparator=">=")
    assert rf.limit_and_unit(r)[0] == rf.FAIL  # a rule unit M is not the quote's m
    assert rf.limit_and_unit(dict(r, unit="m"))[0] == rf.PASS


# ------------------------------------------------------------------------------------------------ M5, M6


def test_an_equipment_type_row_outside_the_vocabulary_is_incomplete_and_leaves_no_raw_text():
    r = rule(applicability=[("equipment_type", "banana widget")])
    result, reason, ev = rf.conditions_of(r)
    assert (result, reason) == (rf.INCOMPLETE, "equipment_type_not_in_vocabulary")
    assert "banana" not in json.dumps(ev)
    assert (
        rf.conditions_of(rule(applicability=[("equipment_type", "centrifugal pump")]))[
            0
        ]
        == rf.PASS
    )


ALL = {
    "a": "pass",
    "b": "pass",
    "c": "pass",
    "d": "pass",
    "e": "pass",
    "f": "pass",
    "g": "pass",
}


def test_an_engineer_check_that_is_pending_or_stale_does_not_finish_a_rule():
    for bad in ("incomplete", "not_applicable", "fail", "stale"):
        assert rf.may_decide(dict(ALL, e=bad)) is False
    assert rf.finish_status(dict(ALL, e="stale")) == (rf.NOT_FINISHED, "e", "e_stale")
    assert rf.finish_status(dict(ALL, f="stale")) == (rf.NOT_FINISHED, "f", "f_stale")
    assert rf.may_decide(dict(ALL, f="not_applicable")) is False
    assert (
        rf.may_decide(dict(ALL, b="not_applicable")) is True
        and rf.may_decide(dict(ALL, a="not_applicable")) is True
    )


def test_a_fragment_needs_every_pointer_to_hold_its_list():
    q = "The vendor shall state the following: (a) the tag; (b) the service; (c) the date; as listed below"
    assert rf.fragments(rule(quote=q), {})[0] == rf.INCOMPLETE


def test_a_condition_the_reader_cannot_read_whole_is_incomplete():
    r = rule(
        applicability=[
            ("subject", "pumps"),
            ("condition", "above 100 kPa and when the moon is full"),
        ]
    )
    assert rf.conditions_of(r)[0] == rf.INCOMPLETE


def test_a_join_must_start_with_the_quote_and_be_contiguous_in_the_pages(monkeypatch):
    long = "The vendor shall state the following data about each relief valve it supplies to the site"
    r = rule(quote=long, page=2)
    pages = {2: f"Intro.\n{long}\n(a) the tag;\n(b) the service;\n"}
    assert rf.rejoin(r, pages)[0] is not None
    monkeypatch.setattr(
        rf, "_list_after", lambda text, start: (start - 5, 2)
    )  # a join that stops before the quote ends
    assert rf.rejoin(r, pages) == (None, {"reason": "join_not_contiguous"})
    monkeypatch.undo()
    monkeypatch.setattr(
        rf, "quote_verified", lambda joined, text: False
    )  # a join the pages do not hold
    assert rf.rejoin(r, pages) == (None, {"reason": "join_not_contiguous"})
