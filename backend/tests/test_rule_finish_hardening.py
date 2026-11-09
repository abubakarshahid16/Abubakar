"""Step a, simple and closed: figures, units, the closed polarity table, the simple shape, engineer-confirmed figures (Lane 1).
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
def test_every_phrase_of_the_closed_table_gives_its_comparator_in_the_simple_shape(
    phrase, sym
):
    r = ff.read(f"The wall shall be {phrase} 10 mm thick.")
    assert (r.shape, r.comparator, [f.value for f in r.figures]) == (
        "simple",
        sym,
        [10.0],
    )


@pytest.mark.parametrize(
    "quote, comparator",
    [
        ("shall not be less than 10 mm", ">="),
        ("not exceeding 10 mm", "<="),
        ("no greater than 10 mm", "<="),
        ("shall not be more than 10 mm", "<="),
        ("not smaller than 10 mm", ">="),
        ("less than 10 mm", "<"),
        ("more than 10 mm", ">"),
        ("10 mm minimum", ">="),
        ("10 mm maximum", "<="),
        ("10 mm or more", ">="),
        ("10 mm or less", "<="),
        ("10 mm or below", "<="),
        ("10 mm or lower", "<="),
        ("10 mm or fewer", "<="),
        ("10 mm at the most", "<="),
    ],
)
def test_the_simple_shape_reads_a_phrase_directly_before_or_a_trailing_word_directly_after(
    quote, comparator
):
    r = ff.read(f"The wall is {quote} thick.")
    assert (r.shape, r.comparator) == ("simple", comparator)


@pytest.mark.parametrize(
    "quote",
    [
        "At least 10 mm and 20 mm or less",
        "Not more than 10 mm and 5 mm or more",
        "Wall is 5 mm (minimum) for 40 bar",
        "The design pressure shall be 40 bar, minimum wall 5 mm",
        "10 mm minimum, 20 mm maximum",
        "at least 10 mm and at most 20 mm",
        "at least 10 mm but not more than 20 mm",
        "at least 10 mm except 20 mm",
        "at least 10 mm. 20 mm for valves",
        "at least 3/4 inch for threaded valves and 1 inch for flanged valves",  # no inheritance, ever
        "at least 10 mm and 20 mm",
        "A minimum of 4 bolts of 12 mm shall be fitted.",  # a polarity phrase that governs a bare count
        "At least 2 pumps with a 50 mm suction shall be provided.",
        "At most 3 gaskets of 2 mm shall be used.",
        "The wall is 5 mm (minimum).",  # a parenthetical polarity
        "Minimum wall thickness shall be 5 mm.",  # the phrase is not directly before the figure
        "Class 150 flanges shall be at least 10 mm.",  # a bare number elsewhere
        "at least 10 mm minimum",  # two phrases
        "not at least 10 mm",  # a negation the table does not use
        "neither less than 5 mm",
        "shall be 6 mm",  # no phrase
        "10-40 C",  # a range in no closed form
        "10 mm to 20 mm",
        "at least 1 in 50 mm",
    ],
)
def test_every_other_shape_is_complex_and_gets_no_comparator_from_code(quote):
    r = ff.read(quote)
    assert (r.shape, r.comparator) == ("complex", None), quote
    q = rule(quote=quote)
    result, reason, ev = rf.limit_and_unit(q)
    assert (result, reason) == (rf.FAIL, "figure_not_filled") and ev[
        "engineer_required"
    ] is True
    assert ev["proposed"] == []  # never a proposal outside the simple shape


@pytest.mark.parametrize(
    "quote",
    [
        "between 10 and 40 C",
        "Between 10 and 40 C",
        "from 10 to 40 C",
        "10 to 40 C",
        "Range: between -10 and 40 C",
    ],
)
def test_a_closed_range_form_has_its_two_ends_and_a_proposal_of_both(quote):
    r = ff.read(quote)
    assert r.shape == "range" and r.figures[0].value <= r.figures[1].value
    _, _, ev = rf.limit_and_unit(rule(quote=quote))
    assert [(p["comparator"], p["applied"]) for p in ev["proposed"]] == [
        (">=", False),
        ("<=", False),
    ]
    assert ev["engineer_required"] is False


def test_other_range_shapes_are_not_closed_forms():
    for quote in (
        "between 10 and 40 C and 50 C",
        "10 to 40 C or 50 C",
        "between 10 and 40",
        "and 10 to 40 C",
    ):
        assert ff.read(quote).shape != "range", quote


# ------------------------------------------------------------------------------------------------ units


@pytest.mark.parametrize(
    "quote",
    [
        "a gap of 10 mm/m",
        "a gap of 10 psi/ft",
        "a gap of 10 deg C",
        "a gap of 10 \u00b0 C",
        "a gap of 100 \u00baC",
        "a gap of 10 in wc",
        'a gap of 12"',
        "a gap of 12''",
        "a gap of 5 tons",
        "a gap of 10 US gpm",
        "a gap of 1e3 mm",
        "a gap of 10 MM",
        "a gap of 10 Mm",
        "a gap of 10 M",
        "a gap of 10 x 20 mm",
    ],
)
def test_a_number_with_a_unit_shape_the_table_does_not_read_is_incomplete_never_not_applicable(
    quote,
):
    result, reason, _ = rf.limit_and_unit(rule(quote=quote))
    assert result == rf.INCOMPLETE, (quote, reason)
    filled = rule(quote=quote, kind="limit", value=10, unit="mm", comparator="=")
    assert rf.limit_and_unit(filled)[0] == rf.INCOMPLETE


@pytest.mark.parametrize(
    "quote",
    [
        "Widgets shall be painted.",
        "Provide 3 stages.",
        "issued 12 March 2025",
        "see clause 4.1.2 and table 7",
        "5 widgets per bay",
    ],
)
def test_not_applicable_only_where_the_quote_has_no_number_and_unit_shape_at_all(quote):
    assert rf.limit_and_unit(rule(quote=quote))[:2] == (
        rf.NOT_APPLICABLE,
        "no_figure_in_quote",
    )


def test_a_unit_whose_capital_is_not_its_meaning_is_refused_and_the_safe_spellings_read():
    for unit in ("MM", "Mm", "M", "S", "G"):
        assert ff.read(f"at least 10 {unit}").incomplete == "unit_case_ambiguous"
    for unit in ("kPa", "MPa", "C", "mm", "bar"):
        assert ff.read(f"at least 10 {unit} thick").incomplete is None
    (f,) = ff.figures("at least 10 mm")
    assert ff.unit_matches("mm", f) and not ff.unit_matches("MM", f)
    assert not ff.unit_matches(None, f) and not ff.unit_matches("", f)
    assert not ff.unit_matches("mm", ff.Figure(1.0, "", 0, 1, 1, "1"))


# ------------------------------------------------------------------------------------------------ step a: stored figures


Q = "The wall shall be at least 10 mm thick."


def stored(**kw):
    base = {"quote": Q, "kind": "limit", "value": 10, "unit": "mm", "comparator": ">="}
    return rule(**{**base, **kw})


def test_a_simple_shape_passes_when_value_unit_and_comparator_are_the_quotes():
    assert rf.limit_and_unit(stored())[:2] == (rf.PASS, "value_and_unit_stand_in_quote")
    assert rf.limit_and_unit(stored(comparator="<="))[:2] == (
        rf.FAIL,
        "comparator_mismatch",
    )
    assert rf.limit_and_unit(stored(comparator=None))[:2] == (
        rf.FAIL,
        "comparator_mismatch",
    )
    assert rf.limit_and_unit(stored(value=11))[:2] == (rf.FAIL, "value_not_in_quote")
    assert rf.limit_and_unit(stored(unit="kPa"))[:2] == (rf.FAIL, "unit_not_in_quote")
    assert rf.limit_and_unit(stored(unit=None))[:2] == (rf.FAIL, "unit_not_filled")


def test_every_figure_of_the_quote_must_be_stored_or_confirmed():
    q = "at least 10 mm and 20 mm"
    r = rule(quote=q, kind="limit", value=10, unit="mm", comparator=">=")
    assert rf.limit_and_unit(r)[:2] == (rf.INCOMPLETE, "unaccounted_figures")
    conf = [{"value": 20, "unit": "mm", "comparator": ">="}]
    assert rf.limit_and_unit(dict(r, confirmed_figures=conf))[:2] == (
        rf.INCOMPLETE,
        "comparator_needs_engineer",
    )
    both = [
        {"value": 10, "unit": "mm", "comparator": ">="},
        {"value": 20, "unit": "mm", "comparator": ">="},
    ]
    two = rule(
        quote=q,
        figures=[{"value": 10}, {"value": 20}],
        unit="mm",
        comparator=">=",
        confirmed_figures=both,
    )
    assert rf.limit_and_unit(two)[:2] == (rf.PASS, "comparator_confirmed_by_engineer")


def test_in_every_complex_shape_step_a_passes_only_on_the_engineers_confirmed_figures_exactly():
    q = "at least 3/4 inch for threaded valves and at least 1 inch for flanged valves"
    base = rule(
        quote=q, figures=[{"value": 0.75}, {"value": 1.0}], unit="inch", comparator=">="
    )
    assert rf.limit_and_unit(base)[:2] == (rf.INCOMPLETE, "comparator_needs_engineer")
    good = [
        {"value": 0.75, "unit": "inch", "comparator": ">="},
        {"value": 1.0, "unit": "inch", "comparator": ">="},
    ]
    assert rf.limit_and_unit(dict(base, confirmed_figures=good))[:2] == (
        rf.PASS,
        "comparator_confirmed_by_engineer",
    )
    for bad in (
        good[:1],  # one figure missing
        [*good, {"value": 2.0, "unit": "inch", "comparator": ">="}],  # one more
        [dict(good[0], comparator="<="), good[1]],  # another comparator
        [dict(good[0], value=0.8), good[1]],  # another value
        [dict(good[0], unit="mm"), good[1]],  # another unit
        [],
    ):
        assert rf.limit_and_unit(dict(base, confirmed_figures=bad))[0] == rf.INCOMPLETE
    assert (
        rf.limit_and_unit(dict(base, comparator="<=", confirmed_figures=good))[0]
        == rf.INCOMPLETE
    )


def test_a_closed_range_passes_with_both_ends_in_order_and_needs_no_engineer():
    q = "Ambient shall be between 10 and 40 C."
    ok = rule(quote=q, kind="range", value_low=10, value_high=40, unit="C")
    assert rf.limit_and_unit(ok)[:2] == (rf.PASS, "value_and_unit_stand_in_quote")
    assert rf.limit_and_unit(dict(ok, value_low=40, value_high=10))[0] in (
        rf.FAIL,
        rf.INCOMPLETE,
    )
    assert rf.limit_and_unit(dict(ok, value_high=45))[:2] == (
        rf.FAIL,
        "value_not_in_quote",
    )
    assert rf.limit_and_unit(dict(ok, unit="F"))[0] == rf.FAIL
    unordered = rule(
        quote="between 40 and 10 C", kind="range", value_low=40, value_high=10, unit="C"
    )
    assert rf.limit_and_unit(unordered)[:2] == (rf.FAIL, "range_order")


def test_a_bare_number_limit_needs_the_engineers_confirmation_too():
    r = rule(
        quote="Provide at least 3 stages.",
        kind="limit",
        value=3,
        comparator=">=",
        unit=None,
    )
    assert rf.limit_and_unit(r)[:2] == (rf.INCOMPLETE, "comparator_needs_engineer")
    conf = [{"value": 3, "unit": "none", "comparator": ">="}]
    assert rf.limit_and_unit(dict(r, unit="none", confirmed_figures=conf))[:2] == (
        rf.PASS,
        "comparator_confirmed_by_engineer",
    )
    assert rf.limit_and_unit(dict(r, value=4))[:2] == (rf.FAIL, "value_not_in_quote")


# ------------------------------------------------------------------------------------------------ fractions, groups, compounds


@pytest.mark.parametrize(
    "quote, value",
    [
        ("size at least \u00bd inch", 0.5),
        ("size at least 1\u00bd inch", 1.5),
        ("size at least \u00be inch", 0.75),
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
    assert ff.normalise("size 3.\u00bd inch")[1] == "fraction_character_unreadable"
    assert ff.read("size 3.\u00bd inch").incomplete in (
        "fraction_character_unreadable",
        "figure_ambiguous",
    )


@pytest.mark.parametrize("sep", [" ", "\u2009", "\u00a0", "\u202f"])
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
    assert [f.value for f in ff.figures("at least 1 000,5 mm")] == [1000.5]
    assert ff.normalise("a gap of 1 000,5,1 mm")[1] == "grouped_number_unreadable"
    assert rf.limit_and_unit(rule(quote="a gap of 1 000,5,1 mm"))[0] == rf.INCOMPLETE


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
    assert rf.limit_and_unit(rule(quote=quote))[0] == rf.INCOMPLETE


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


def test_percent_minus_and_signed_figures_are_read_through_numparse():
    r = ff.read("at least 50 percent")
    assert (r.figures[0].value, r.figures[0].unit, r.comparator) == (50.0, "%", ">=")
    assert ff.figures("at least 50 per cent")[0].unit == "%"
    assert [f.value for f in ff.figures("not less than minus 10 C")] == [-10.0]
    assert [f.value for f in ff.read("between -10 and 40 C").figures] == [-10.0, 40.0]


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
    monkeypatch.setattr(rf, "_list_after", lambda text, start: (start - 5, 2))
    assert rf.rejoin(r, pages) == (None, {"reason": "join_not_contiguous"})
    monkeypatch.undo()
    monkeypatch.setattr(rf, "quote_verified", lambda joined, text: False)
    assert rf.rejoin(r, pages) == (None, {"reason": "join_not_contiguous"})


def test_a_trailing_phrase_not_directly_after_the_unit_makes_the_shape_complex():
    assert ff.read("The wall shall be at least 10 mm thick or less.").shape == "complex"
    assert ff.read("The wall shall be at least 10 mm thick.").shape == "simple"


def test_a_pair_of_numbers_joined_by_and_is_a_range_only_after_between():
    assert ff.read("Use 10 and 40 C").shape == "complex"
    assert ff.read("Use between 10 and 40 C").shape == "range"
    assert ff.read("Use 10 to 40 C").shape == "range"
    assert ff.read("Use and 10 to 40 C").shape == "complex"
    assert ff.read("Use between 10 to 40 C").shape == "complex"


def test_a_zero_value_stands_only_where_a_zero_is_printed():
    r = rule(
        quote="The gap shall be at least 000 mm.",
        kind="limit",
        value=0,
        unit="mm",
        comparator=">=",
    )
    assert rf.limit_and_unit(r)[:2] == (rf.FAIL, "value_not_in_quote")
    assert (
        ff.stands(0, "a gap of 0 mm")
        and not ff.stands(0, "a gap of 000 mm")
        and not ff.stands(0, "a gap of 5 mm")
    )


def test_a_polar_phrase_a_unit_symbol_token_or_a_stop_word_after_a_number_is_read_closed():
    assert rf.limit_and_unit(rule(quote="a gap of 12 °CELSIUS"))[0] == rf.INCOMPLETE
    assert rf.limit_and_unit(rule(quote="a gap of 12 °C"))[0] in (
        rf.FAIL,
        rf.INCOMPLETE,
    )


def test_a_polar_phrase_anywhere_else_in_the_quote_makes_the_shape_complex():
    assert (
        ff.read(
            "The wall shall be at least 10 mm thick and greater than the flange."
        ).shape
        == "complex"
    )
    assert (
        ff.read("The wall shall be at least 10 mm thick and not welded.").shape
        == "complex"
    )
