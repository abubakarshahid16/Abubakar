"""Step a, fail closed: code verifies NUMBERS and QUOTES, never meaning; the engineer's confirmed figures carry the meaning
(Lane 1). Every text here is INVENTED."""

# ruff: noqa: RUF001  (fullwidth digits and thin spaces are the point of these tests)
from __future__ import annotations

import json

import pytest

from app import rule_finish as rf
from app import rule_finish_figures as ff
from tests.test_rule_finish_kit import marker_key, rule  # noqa: F401

Q = "The wall shall be at least 10 mm thick."


def eng(figures, accounted=(), result="pass"):
    """What `rule_of` lays on a rule when an engineer check is bound to this version, quote and content."""
    return {
        "result": result,
        "confirmed_figures": list(figures),
        "accounted_numbers": list(accounted),
    }


def limit(value=10, unit="mm", comparator=">="):
    return {"value": value, "unit": unit, "comparator": comparator}


def stored(quote=Q, check=None, **kw):
    base = {
        "quote": quote,
        "kind": "limit",
        "value": 10,
        "unit": "mm",
        "comparator": ">=",
    }
    if check is not None:
        base["engineer_check"] = check
    return rule(**{**base, **kw})


# ------------------------------------------------------------------------------------------------ no English decides anything


def test_the_module_has_no_polarity_negation_or_shape_machinery_left():
    for name in (
        "POLARITY_TABLE",
        "_NEGATION",
        "_closed_range",
        "_TRAILING",
        "read",
        "implied_comparator",
        "SAFE_CASE_UNITS",
    ):
        assert not hasattr(ff, name), name
    assert not hasattr(rf, "proposal_of") and not hasattr(rf, "run_steps")


@pytest.mark.parametrize(
    "quote",
    [
        "The wall shall be at least 10 mm thick.",
        "The wall shall not be less than 10 mm thick.",
        "The wall shall be not more than 10 mm thick.",
        "not between 10 and 40 C",
        "outside 10 to 40 C",
        "10 to 40 mm is not allowed",
        "it isn't more than 10 mm",
        "prohibited from exceeding 10 mm",
        "unacceptable above 10 mm",
        "forbidden over 10 mm",
        "unless 10 mm is used",
        "other than 10 mm",
        "if less than 10 mm",
        "at least 10 mm and 20 mm or less",
    ],
)
def test_the_same_numbers_never_pass_on_the_strength_of_the_english_around_them(quote):
    """Code reads no English: whatever the words say, no engineer check means no pass, and a stored figure meets its
    quote only by number and unit."""
    first = ff.figures(quote)[0]
    r = stored(quote, value=first.value, unit=first.unit)
    assert rf.limit_and_unit(r)[0] in (rf.INCOMPLETE, rf.FAIL)
    assert rf.limit_and_unit(rule(quote=quote))[0] in (rf.INCOMPLETE, rf.FAIL)
    for comparator in (
        ">=",
        "<=",
        "<",
        ">",
        "=",
    ):  # an engineer check that differs from the stored comparator never passes
        wrong = dict(
            r,
            comparator=">=",
            engineer_check=eng([limit(first.value, first.unit, comparator)]),
        )
        got = rf.limit_and_unit(wrong)[:2]
        assert (
            got != (rf.PASS, "comparator_confirmed_by_engineer") or comparator == ">="
        )


# ------------------------------------------------------------------------------------------------ number tokens, fail closed


@pytest.mark.parametrize(
    "quote",
    [
        "Use 10 liters of oil",
        "Use 10 kilopascals",
        "Use 10 millimetres",
        "Use 10 degrees Celsius",
        "Use 10 °C",
        "Use 10 ºC",
        "Use 10 ℃",
        "Use 10 in²",
        "Use 10 MMSCFD",
        "Use １０ mm",
        "Use ١٠ mm",
        "Use ten bar",
        "Use 10 /min",
        "Use 2 NPT",
        "Use 10 ㎜",
        "Use 10 ㎏",
        "Use ½ inch",
        "Use 三 bolts",
        "Use 1e3 mm",
        "Use 5.3.2 mm",
        "Use 1/2/3 mm",
        "Use 10 mm Hg",
        "Use 10 in. H2O",
        "Use 10 US gpm",
        'Use 12"',
        "Use 5 tons",
        "Use 10 mm/m",
        "Use 10 psi/ft",
        "Use 100 ºF",
        "Use twenty-five mm",
        "Use hundreds of bolts",
        "Use 2nd and 3rd",
        "Use 1 000 mm",
    ],
)
def test_a_number_the_figure_reader_does_not_know_is_never_no_figure_and_never_a_pass(
    quote,
):
    result, reason, _ = rf.limit_and_unit(rule(quote=quote))
    assert result in (rf.INCOMPLETE, rf.FAIL), (quote, result, reason)
    assert ff.number_tokens(quote), quote


@pytest.mark.parametrize(
    "quote",
    [
        "Widgets shall be painted.",
        "Use NPT threads and MMSCFD units.",
        "Use liters and kilopascals only.",
        "see clause 4.1.2 and table 7 of API 610 and note 2 on page 5, section 3, para 4.1, figure 3",
        "per ISO 15156-3 and NACE MR0175",
        "",
    ][:-1],
)
def test_not_applicable_only_where_the_quote_has_no_number_token_at_all(quote):
    assert rf.limit_and_unit(rule(quote=quote))[:2] == (
        rf.NOT_APPLICABLE,
        "no_number_in_quote",
    )


def test_the_references_the_repo_strips_are_stripped_and_everything_else_counts():
    assert (
        ff.number_tokens(
            "see clause 4.1.2, table 7, figure 3, note 2, page 5, section 3 and para 4.1"
        )
        == []
    )
    raw = [t for t, _ in ff.number_tokens("API 610 requires 12 bolts per clause 4.2")]
    assert raw == ["12"]
    assert [t for t, _ in ff.number_tokens("Use 3/4 inch and 1 1/2 inch")] == [
        "3/4",
        "1 1/2",
    ]


@pytest.mark.parametrize(
    "word",
    [
        "one",
        "two",
        "three",
        "ten",
        "twenty",
        "thirty",
        "forty",
        "fifty",
        "hundred",
        "thousand",
        "million",
        "half",
        "dozen",
        "ninety",
    ],
)
def test_every_number_word_and_its_plural_or_ordinal_is_a_token(word):
    for form in (word, word + "s", word + "th"):
        assert [t for t, _ in ff.number_tokens(f"Use {form} bolts")] == [form], form
    assert (
        ff.number_tokens("someone, tone, wonder, often, stone") == []
    )  # not inside other words


def test_a_token_from_a_non_ascii_digit_or_numeral_has_no_value_and_is_never_a_figure():
    for quote in ("１０", "١٠", "²", "½", "三", "①"):
        tokens = ff.number_tokens(f"Use {quote} mm")
        assert tokens and tokens[0][1] is None, quote
    assert ff.figures("Use １０ mm") == ()


# ------------------------------------------------------------------------------------------------ step a, stored figures


def test_step_a_is_pending_until_an_engineer_check_is_bound_to_this_version_and_content():
    assert rf.limit_and_unit(stored())[:2] == (
        rf.INCOMPLETE,
        "engineer_confirmation_pending",
    )
    assert rf.limit_and_unit(stored(check=eng([limit()])))[:2] == (
        rf.PASS,
        "comparator_confirmed_by_engineer",
    )
    assert rf.limit_and_unit(stored(check=eng([limit()], result="fail")))[:2] == (
        rf.INCOMPLETE,
        "engineer_not_ok",
    )


def test_the_engineers_figures_must_equal_the_stored_ones_exactly():
    base = stored()
    for bad in (
        [limit(comparator="<=")],
        [limit(value=11)],
        [limit(unit="kPa")],
        [],
        [limit(), limit(value=20)],
        [{"low": 10, "high": 10, "unit": "mm", "kind": "range"}],
        [{"value": 10, "unit": "mm"}],
        ["x"],
        [None],
        [1],
        [{"kind": "range"}],
        [{"value": "x", "unit": "mm", "comparator": ">="}],
    ):
        assert rf.limit_and_unit(dict(base, engineer_check=eng(bad)))[:2] == (
            rf.INCOMPLETE,
            "engineer_figures_differ",
        ), bad
    assert (
        rf.same_figures(rf._stored_figures(base), [limit(unit="MM")]) is False
    )  # a difference of case only
    assert (
        rf.same_figures([("limit", 0.75, "inch", ">=")], [limit(0.75, "inch")]) is True
    )


def test_a_unit_the_repo_reads_as_the_same_unit_is_the_same():
    assert (
        ff.same_unit("mm", "mm") and ff.same_unit("kPa", "kpa") is False
    )  # a case difference is no match
    assert (
        not ff.same_unit(None, "mm")
        and not ff.same_unit("mm", "")
        and not ff.same_unit("mm", "kPa")
    )


def test_a_stored_range_is_confirmed_as_a_range_with_its_two_ends_and_a_unit():
    q = "Ambient shall be between 10 and 40 C."
    r = rule(quote=q, kind="range", value_low=10, value_high=40, unit="C")
    good = {"low": 10, "high": 40, "unit": "C", "kind": "range"}
    assert rf.limit_and_unit(dict(r, engineer_check=eng([good])))[:2] == (
        rf.PASS,
        "comparator_confirmed_by_engineer",
    )
    for bad in (
        {**good, "low": 11},
        {**good, "high": 41},
        {**good, "unit": "F"},
        {"value": 10, "unit": "C", "comparator": ">="},
    ):
        assert rf.limit_and_unit(dict(r, engineer_check=eng([bad])))[0] == rf.INCOMPLETE
    assert rf.limit_and_unit(dict(r, value_low=40, value_high=10))[:2] == (
        rf.FAIL,
        "range_order",
    )
    assert rf.limit_and_unit(dict(r, value_high=45))[:2] == (
        rf.FAIL,
        "value_not_in_quote",
    )
    assert rf.limit_and_unit(dict(r, unit="F"))[:2] == (rf.FAIL, "unit_not_in_quote")
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


def test_a_stored_figure_must_stand_in_the_quote_with_its_number_and_unit():
    assert rf.limit_and_unit(stored(value=11))[:2] == (rf.FAIL, "value_not_in_quote")
    assert rf.limit_and_unit(stored(unit="kPa"))[:2] == (rf.FAIL, "unit_not_in_quote")
    assert rf.limit_and_unit(stored(unit="MM"))[:2] == (rf.FAIL, "unit_not_in_quote")
    assert rf.limit_and_unit(stored(unit=None))[:2] == (rf.FAIL, "unit_not_filled")
    assert rf.limit_and_unit(stored(unit="none"))[:2] == (rf.FAIL, "unit_not_filled")
    assert rf.limit_and_unit(stored("Widgets shall be painted."))[:2] == (
        rf.FAIL,
        "value_not_in_quote",
    )
    other = stored("The wall shall be 10 mm and 10 kPa thick.")
    assert rf.limit_and_unit(other)[:2] == (
        rf.FAIL,
        "unit_not_in_quote",
    )  # the same number printed with another unit


def test_every_number_token_of_the_quote_is_a_stored_figure_or_accounted_by_the_engineer():
    q = "At least 4 bolts of 12 mm shall be fitted."
    r = stored(q, value=12)
    only = eng([limit(12)])
    assert rf.limit_and_unit(dict(r, engineer_check=only))[:2] == (
        rf.INCOMPLETE,
        "unaccounted_numbers",
    )
    assert rf.limit_and_unit(dict(r, engineer_check=only))[2]["unaccounted"] == ["4"]
    counted = eng([limit(12)], [{"token": "4", "reason": "count"}])
    assert rf.limit_and_unit(dict(r, engineer_check=counted))[:2] == (
        rf.PASS,
        "comparator_confirmed_by_engineer",
    )
    for noise in (
        [{"token": "5", "reason": "count"}],
        ["4"],
        [None],
        [{"reason": "count"}],
    ):
        assert (
            rf.limit_and_unit(dict(r, engineer_check=eng([limit(12)], noise)))[0]
            == rf.INCOMPLETE
        )
    words = stored("Provide ten bolts of at least 12 mm.", value=12)
    assert rf.limit_and_unit(dict(words, engineer_check=eng([limit(12)])))[2][
        "unaccounted"
    ] == ["ten"]


def test_a_rule_with_no_figure_is_failed_when_the_quote_prints_one_and_proposes_value_and_unit_only():
    r = rule(quote="The pump casing shall have a wall of at least 6 mm.")
    result, reason, ev = rf.limit_and_unit(r)
    assert (result, reason) == (rf.FAIL, "figure_not_filled") and ev[
        "engineer_required"
    ] is True
    assert ev["proposed"] == [
        {"value": 6.0, "unit": "mm", "comparator": "?", "applied": False}
    ]
    assert r["value"] is None and r["unit"] is None  # never applied silently
    assert rf.limit_and_unit(rule(quote="Provide ten bolts."))[:2] == (
        rf.INCOMPLETE,
        "engineer_confirmation_pending",
    )


def test_a_quote_with_numbers_all_accounted_and_no_figure_passes_on_the_engineers_word():
    r = rule(
        quote="Provide at least ten bolts.",
        engineer_check=eng([], [{"token": "ten", "reason": "count"}]),
    )
    assert rf.limit_and_unit(r)[:2] == (rf.PASS, "comparator_confirmed_by_engineer")
    assert rf.limit_and_unit(dict(r, engineer_check=eng([])))[:2] == (
        rf.INCOMPLETE,
        "unaccounted_numbers",
    )


def test_a_stored_figure_with_no_number_in_the_quote_fails():
    assert rf.limit_and_unit(
        rule(quote="Widgets shall be painted.", value=3, unit="mm")
    )[:2] == (rf.FAIL, "value_not_in_quote")


def test_a_fraction_is_one_token_and_one_figure_read_whole_by_numparse():
    r = rule(
        quote="at least 3/4 inch",
        kind="limit",
        value=0.75,
        unit="inch",
        comparator=">=",
    )
    ok = dict(r, engineer_check=eng([limit(0.75, "inch")]))
    assert rf.limit_and_unit(ok)[:2] == (rf.PASS, "comparator_confirmed_by_engineer")
    assert rf.limit_and_unit(dict(r, value=4.0))[:2] == (
        rf.FAIL,
        "value_not_in_quote",
    )  # never its denominator
    assert rf.limit_and_unit(dict(r, value=3.0))[:2] == (rf.FAIL, "value_not_in_quote")
    assert [f.value for f in ff.figures("at least 1 1/2 inch")] == [1.5]


@pytest.mark.parametrize("sep", [" ", " ", " ", " "])
def test_a_grouped_number_is_two_tokens_never_one_figure_and_zero_does_not_stand_for_them(
    sep,
):
    quote = f"at least 1{sep}000 mm"
    r = rule(quote=quote, kind="limit", value=1000, unit="mm", comparator=">=")
    assert rf.limit_and_unit(r)[0] == rf.FAIL  # 1000 is not printed
    zero = rule(quote=quote, kind="limit", value=0, unit="mm", comparator=">=")
    assert rf.limit_and_unit(zero)[:2] == (rf.FAIL, "value_not_in_quote")


def test_a_zero_value_stands_only_where_a_zero_is_printed():
    assert (
        ff.stands(0, "a gap of 0 mm")
        and not ff.stands(0, "a gap of 000 mm")
        and not ff.stands(0, "a gap of 5 mm")
    )
    r = rule(
        quote="The gap shall be 0 mm.", kind="limit", value=0, unit="mm", comparator="="
    )
    assert (
        rf.limit_and_unit(dict(r, engineer_check=eng([limit(0, "mm", "=")])))[0]
        == rf.PASS
    )


def test_figures_are_the_numbers_directly_before_a_unit_of_the_table_and_nothing_else():
    assert [
        (f.value, f.unit)
        for f in ff.figures("at least 10 mm and 2 cm, 15 m from, 3/4 inch")
    ] == [
        (10.0, "mm"),
        (2.0, "cm"),
        (15.0, "m"),
        (0.75, "inch"),
    ]
    assert ff.figures("Provide 3 stages, 12 March 2025, item 5") == ()


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


def test_an_empty_quote_fails_and_the_article_a_is_not_the_unit_ampere():
    assert rf.limit_and_unit(rule(quote=""))[:2] == (rf.FAIL, "no_quote")
    assert rf.limit_and_unit(rule(quote=None))[:2] == (rf.FAIL, "no_quote")
    assert ff.figures("Give it 3 a coat") == () and [
        f.unit for f in ff.figures("Draw 3 A")
    ] == ["A"]


def test_a_stored_figure_with_no_printed_unit_beside_its_number_is_a_unit_not_in_the_quote():
    r = stored("Provide at least 10 stages.")
    assert rf.limit_and_unit(r)[:2] == (rf.FAIL, "unit_not_in_quote")
    other = stored("Provide 10 stages of 10 mm and 10 kPa.")
    assert rf.limit_and_unit(other)[:2] == (
        rf.FAIL,
        "unit_not_in_quote",
    )  # one printing of the number has another unit


def test_the_engineers_figures_are_matched_one_for_one():
    twin = [("limit", 10.0, "mm", ">="), ("limit", 10.0, "mm", ">=")]
    assert (
        rf.same_figures(twin, [limit(10), limit(20)]) is False
    )  # one confirmed figure cannot account for two stored
    assert rf.same_figures(twin, [limit(10), limit(10)]) is True
    assert (
        rf.same_figures(
            [("limit", 10.0, "mm", ">=")],
            [{"value": 10, "unit": "mm", "comparator": ">=", "kind": "x"}],
        )
        is True
    )
    assert (
        rf.same_figures(
            [("limit", 10.0, "mm", ">=")],
            [{"low": 10, "high": 10, "unit": "mm", "kind": "range"}],
        )
        is False
    )
    assert rf.same_figures([("range", 1.0, 2.0, "C")], [limit(1, "C")]) is False
    assert (
        rf.figure_key("x") is None
        and rf.figure_key({"kind": "range", "low": 1}) is None
    )


def test_the_content_hash_covers_everything_the_engineer_is_shown():
    from app import rule_finish_record as rec

    base = rule(
        field="inlet size",
        kind="limit",
        strength="shall",
        clause="4.1",
        page=3,
        quote="The inlet shall be at least 5 mm.",
    )
    h = rec.content_sha256(base)
    for change in (
        {"field": "colour"},
        {"field": "outlet size"},
        {"kind": "range"},
        {"strength": "should"},
        {"clause": "4.2"},
        {"page": 4},
    ):
        assert rec.content_sha256(dict(base, **change)) != h, change
    shown = dict(
        base, quote="The inlet size shall be shown on the data sheet at least 5 mm."
    )
    assert rf.evidence_source(shown)[1] != rf.evidence_source(base)[1]
    assert (
        rec.content_sha256(shown) != h
    )  # the evidence-source decision alone differs: same field, figures and page
    assert rec.content_sha256(dict(base)) == h
