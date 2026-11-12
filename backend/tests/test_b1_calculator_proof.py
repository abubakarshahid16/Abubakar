"""R48e on #1804: the proof behind "Proven by code" is recomputed from the line's own texts and values, never taken from a flag.
One test group per finding of the review. Invented data only."""

from __future__ import annotations

import copy
import itertools

import pytest

from app import agent_review_calculator as calc
from app import agent_review_code_proof as proof
from app import agent_review_verdict as V
from tests.test_b1_calculator import ITEM, exit_of, fact, line


def proven(ln) -> bool:
    return exit_of(ln)["verdict_class"] == "Proven by code"


def query(ln, code) -> bool:
    out = exit_of(ln)
    return (
        out["verdict"] == "Query"
        and ln["reason_code"] == code
        and out["verdict_class"] != "Proven by code"
    )


# ---------------------------------------------------------------------------------------- 1: the paper quote must CONTAIN the compared value


def test_1_a_quote_with_another_number_is_a_query_not_a_pass():
    ln = line(
        "85", page_text="Noise level 95 dB(A).", source_text="Noise level 95 dB(A)"
    )  # the reviewer's case
    assert ln["verdict"] == "Query" and query(ln, "paper_value_not_in_quote")


def test_1_the_unit_must_be_in_the_quote_too():
    ln = line("85", page_text="Noise level 85 bar.", source_text="Noise level 85 bar")
    assert query(ln, "paper_value_not_in_quote")


def test_1_the_quote_must_sit_with_the_fields_label_on_its_line_or_the_line_above():
    ok = line(
        "85",
        page_text="Noise level\n85 dB(A)\nOperating pressure 12 bar",
        source_text="85 dB(A)",
    )
    assert proven(ok)  # the label line directly above, no digit on it
    far = line(
        "85",
        page_text="Noise level\nOperating pressure 12 bar\n85 dB(A)",
        source_text="85 dB(A)",
    )
    assert query(far, "field_not_with_quote")
    other = line(
        "85", page_text="Operating pressure 12 bar\n85 dB(A)", source_text="85 dB(A)"
    )
    assert query(other, "field_not_with_quote")


# ---------------------------------------------------------------------------------------- 2: the clause quote must CONTAIN the limit


def test_2_another_sentence_of_the_clause_is_a_query():
    clause = "Operating pressure shall not exceed 5 bar. Noise level shall be reported."
    ln = line(
        "85",
        clause_text=clause,
        clause_quote="Operating pressure shall not exceed 5 bar.",
    )
    assert query(ln, "clause_limit_not_in_quote")


def test_2_the_limit_unit_must_be_in_the_clause_quote():
    ln = line(
        "85",
        clause_text="Noise level shall not exceed 90 bar.",
        clause_quote="Noise level shall not exceed 90 bar.",
    )
    assert query(ln, "clause_limit_not_in_quote")


# ---------------------------------------------------------------------------------------- 3: the exit re-derives


def good():
    return line("85")


def _forged_shapes():
    base = good()
    out = {}

    def mk(name, fn):
        ln = copy.deepcopy(base)
        fn(ln)
        out[name] = ln

    mk(
        "empty quotes, flags true",
        lambda ln: ln.update(paper_quote="", clause_quote=""),
    )
    mk(
        "no limit and no value",
        lambda ln: ln.update(proof_requirement=None, proof_fact=None),
    )
    mk(
        "limit missing",
        lambda ln: ln.update(
            proof_requirement={**ln["proof_requirement"], "raw_value": None}
        ),
    )
    mk(
        "observed missing",
        lambda ln: ln.update(proof_fact={"raw_value": None, "raw_unit": "dB(A)"}),
    )
    mk("page 99", lambda ln: ln.update(paper_page=99))
    mk("page not recorded", lambda ln: ln.update(paper_page_count=None))
    mk("source model", lambda ln: ln.update(source="model"))
    mk("source missing", lambda ln: ln.pop("source"))
    mk("source rule", lambda ln: ln.update(source="rule"))
    mk(
        "quote of another number",
        lambda ln: ln.update(paper_quote="Noise level 95 dB(A)"),
    )
    mk(
        "clause of another number",
        lambda ln: ln.update(clause_quote="Pressure shall not exceed 5 bar"),
    )
    mk(
        "verdict flipped",
        lambda ln: ln.update(
            verdict="Fail",
            compare={"decided": True, "verdict": "does_not_meet", "reason": ""},
        ),
    )
    mk(
        "observed changed after the compare",
        lambda ln: ln.update(proof_fact={"raw_value": "95", "raw_unit": "dB(A)"}),
    )
    mk(
        "qualified value",
        lambda ln: ln.update(proof_fact={"raw_value": "min 85", "raw_unit": "dB(A)"}),
    )
    mk(
        "flags only",
        lambda ln: ln.update(quotes_checked={"paper": False, "clause": True}),
    )
    return out


@pytest.mark.parametrize("name", list(_forged_shapes()))
def test_3_every_forged_shape_is_demoted_at_the_exit(name):
    ln = _forged_shapes()[name]
    assert ln["verdict"] in ("Pass", "Fail")  # the forgery claims a verdict
    out = exit_of(ln)
    assert out["verdict"] == "Query" and out["verdict_class"] != "Proven by code", name


def test_3_the_source_is_read_without_case_and_a_marked_line_with_another_source_is_demoted():
    assert proven(
        {**good(), "source": " CODE "}
    )  # same proof, another spelling: still the code's line
    for src in ("Model", "MODEL", "", None, "rule"):
        forged = {**good(), "source": src}
        assert exit_of(forged)["verdict"] == "Query"
    marked = {k: v for k, v in good().items() if k not in ("source", "code_kind")}
    marked["item_id"] = "c-R-1-f1"  # the id alone marks it
    assert exit_of(marked)["verdict"] == "Query"


def test_3_brute_force_nothing_short_of_the_whole_proof_is_proven():
    base = good()
    keys = [
        "paper_quote",
        "clause_quote",
        "paper_page",
        "paper_page_count",
        "quotes_checked",
        "compare",
        "decided_by",
        "code_kind",
        "proof_requirement",
        "proof_fact",
        "verdict",
    ]
    variants = [None, "", 0, False, True, {}, [], "x", -1]
    seen = 0
    for key in keys:
        for bad in variants:
            ln = {**copy.deepcopy(base), key: bad}
            if ln == base:
                continue
            seen += 1
            out = exit_of(ln)
            assert not (
                out["verdict"] in ("Pass", "Fail")
                and out["verdict_class"] == "Proven by code"
            ), (key, bad)
    for key in keys:
        ln = copy.deepcopy(base)
        ln.pop(key)
        assert exit_of(ln)["verdict_class"] != "Proven by code", key
        seen += 1
    for a, b in itertools.product((True, False), repeat=2):
        ln = {**copy.deepcopy(base), "quotes_checked": {"paper": a, "clause": b}}
        assert (exit_of(ln)["verdict_class"] == "Proven by code") == (a and b)
    assert seen > 100 and proven(base)


def test_3_the_comparison_is_made_again_and_must_equal_the_stored_verdict():
    ln = {
        **good(),
        "proof_fact": {"raw_value": "95", "raw_unit": "dB(A)"},
        "paper_quote": "Noise level 95 dB(A)",
    }
    assert (
        ln["verdict"] == "Pass" and exit_of(ln)["verdict"] == "Query"
    )  # a breach cannot stand as a Pass
    assert (
        proof.recompute(good()["proof_requirement"], good()["proof_fact"])
        == "COMPLIANT"
    )


def test_3_the_two_names_of_the_code_agree():
    assert proof.BY_CODE == V.BY_CODE


# ---------------------------------------------------------------------------------------- 4: a qualified value is never compared as a bare number


@pytest.mark.parametrize(
    "raw",
    [
        "min 85",
        "max 85",
        "approx. 85",
        "typ. 85",
        ">= 85",
        "≥ 85",
        "85 typ.",
        "~85",
        "5-10",
    ],
)
def test_4_a_qualified_value_in_the_datasheet_is_a_query_with_the_reason(raw):
    ln = line(raw)
    assert ln["verdict"] == "Query" and ln["reason_code"] in (
        "paper_value_not_in_quote",
        "not_decided",
        "held",
        "field_not_with_quote",
    ), raw
    assert exit_of(ln)["verdict_class"] != "Proven by code"


@pytest.mark.parametrize(
    "quote",
    [
        "Noise level min 85 dB(A)",
        "Noise level max 85 dB(A)",
        "Noise level approx. 85 dB(A)",
        "Noise level typ. 85 dB(A)",
        "Noise level ≥ 85 dB(A)",
        "Noise level 85 dB(A) typ.",
    ],
)
def test_4_a_bound_word_next_to_the_number_in_the_quote_is_a_query(quote):
    ln = line("85", page_text=quote, source_text=quote)
    assert query(ln, "paper_value_not_in_quote")


def test_4_a_plain_quote_still_proves():
    assert proven(line("85"))


# ---------------------------------------------------------------------------------------- 5: the limit is the stored number


@pytest.mark.parametrize(
    "stored, text",
    [
        (10000.55, "10000.55"),
        (1234567, "1234567"),
        (90, "90"),
        (0.125, "0.125"),
        (2.5, "2.5"),
    ],
)
def test_5_the_limit_is_passed_as_stored_not_reformatted(stored, text):
    req = calc.requirement_from_item({**ITEM, "value": stored})
    assert req["raw_value"] == text
    assert proof.limit_numbers(req) == [text]


def test_5_a_big_limit_proves_against_its_own_clause():
    item = {**ITEM, "value": 10000.55, "unit": "dB(A)"}
    f = fact("9999")
    ln = calc.numeric_line(item, calc.requirement_from_item(item), f, submittal_facts=[f], page_text="Noise level 9999 dB(A)",
                           clause_quote="Noise level shall not exceed 10000.55 dB(A)", clause_text="Noise level shall not exceed 10000.55 dB(A)", page_count=2)  # fmt: skip
    assert proven(ln) and ln["limit"]["raw_value"] == "10000.55"


# ---------------------------------------------------------------------------------------- 6: the value belongs to the label's own cell


@pytest.mark.parametrize(
    "label, value, text, expect",
    [
        (
            "Design pressure",
            "5",
            "Design pressure 15 bar",
            False,
        ),  # a substring is not a token
        ("Design pressure", "15", "Design pressure 15 bar", True),
        (
            "Design pressure",
            "5",
            "Operating pressure 5 bar\nDesign pressure 10 bar",
            False,
        ),  # the neighbour's value
        (
            "Design pressure",
            "10",
            "Design pressure case A 10 bar case B 12 bar",
            False,
        ),  # two values follow
        (
            "Design pressure",
            "10",
            "Design pressure 10 bar\nDesign pressure 12 bar",
            False,
        ),  # the label repeats
        (
            "Design pressure",
            "10",
            "Design pressure 10 bar\nOperating pressure 12 bar",
            True,
        ),
        ("Material", "316L", "Material 316L", True),
        ("Material", "316", "Material 316L", False),
        ("Design pressure", "10", "", False),
    ],
)
def test_6_value_near_label_is_a_token_match_and_one_cell(label, value, text, expect):
    assert calc.value_near_label(label, value, text) is expect


# ---------------------------------------------------------------------------------------- 7 (R48f ask): the clause must show the DIRECTION of the limit


def _dir_line(clause, *, item=None, raw="85"):
    it = {**ITEM, **(item or {}), "question": clause}
    f = fact(raw)
    return calc.numeric_line(
        it, calc.requirement_from_item(it), f, submittal_facts=[f], page_text=f"Noise level {raw} dB(A)",
        clause_quote=clause, clause_text=clause, page_count=3,
    )  # fmt: skip


@pytest.mark.parametrize(
    "clause",
    [
        "Noise level shall not exceed 90 dB(A).",
        "Noise level: maximum 90 dB(A).",
        "Noise level shall be at most 90 dB(A).",
        "Noise level shall be not more than 90 dB(A).",
        "Noise level of 90 dB(A) maximum.",
        "Noise level of 90 dB(A) or less.",
    ],
)
def test_7_an_upper_limit_is_proven_only_by_an_upper_word(clause):
    assert proven(_dir_line(clause))


@pytest.mark.parametrize(
    "clause",
    [
        "Noise level shall be at least 90 dB(A).",  # the opposite word: the reviewer's case
        "Noise level: minimum 90 dB(A).",
        "Noise level of 90 dB(A) or more.",
        "The noise level is 90 dB(A).",  # no direction word
        "Noise level 90 dB(A).",
    ],
)
def test_7_the_opposite_word_or_no_word_is_a_query_with_the_reason(clause):
    ln = _dir_line(clause)
    assert (
        query(ln, "clause_direction_not_shown")
        and "direction of the limit" in ln["why"]
    )


def test_7_a_lower_limit_needs_a_lower_word_and_strict_or_not_is_one_sense():
    low = {"comparator": ">=", "value": 80}
    assert proven(_dir_line("Noise level shall be at least 80 dB(A).", item=low))
    assert proven(
        _dir_line(
            "Noise level shall be more than 80 dB(A).",
            item={"comparator": ">", "value": 80},
        )
    )
    assert query(
        _dir_line("Noise level shall not exceed 80 dB(A).", item=low),
        "clause_direction_not_shown",
    )


def test_7_equality_needs_an_equality_word():
    eq = {"comparator": "=", "value": 85}
    assert proven(_dir_line("Noise level = 85 dB(A).", item=eq))
    assert query(
        _dir_line("Noise level shall not exceed 85 dB(A).", item=eq),
        "clause_direction_not_shown",
    )


def test_7_a_range_needs_between_and_or_a_join():
    rng = {
        "rule_kind": "range",
        "requirement_type": "range_limit",
        "comparator": None,
        "value": None,
        "value_low": 80,
        "value_high": 90,
    }
    assert proven(_dir_line("Noise level shall be between 80 and 90 dB(A).", item=rng))
    assert proven(_dir_line("Noise level shall be 80 to 90 dB(A).", item=rng))


def test_7_the_exit_asks_again_a_flipped_comparator_on_a_stored_line_is_demoted():
    ln = _dir_line("Noise level shall not exceed 90 dB(A).")
    assert proven(ln)
    flipped = {**ln, "proof_requirement": {**ln["proof_requirement"], "operator": ">="}}
    assert exit_of(flipped)["verdict"] == "Query"
    assert (
        exit_of({**ln, "clause_quote": "Noise level 90 dB(A)."})["verdict"] == "Query"
    )


# ---------------------------------------------------------------------------------------- 8 (R48f): no flag is trusted: the label test is asked again at the exit


def test_8_a_quote_of_another_field_with_the_flag_true_is_demoted_at_the_exit():
    good = line("85")
    assert proven(good) and "noise level" in good["paper_context"]
    forged = {
        **good,
        "paper_quote": "Operating pressure 85 dB(A)",
        "paper_context": "Operating pressure 85 dB(A)",
    }  # the reviewer's case
    assert forged["quotes_checked"]["paper"] is True
    assert (
        exit_of(forged)["verdict"] == "Query"
        and exit_of(forged)["verdict_class"] != "Proven by code"
    )


@pytest.mark.parametrize(
    "context", [None, "", 5, ["Noise level"], "Design pressure 85 dB(A)"]
)
def test_8_without_the_fields_own_lines_nothing_is_proven(context):
    forged = {**line("85"), "paper_context": context}
    assert exit_of(forged)["verdict_class"] != "Proven by code"


def test_8_the_label_line_directly_above_still_proves_through_the_stored_lines():
    ok = line(
        "85",
        page_text="Noise level\n85 dB(A)\nOperating pressure 12 bar",
        source_text="85 dB(A)",
    )
    assert proven(ok) and ok["paper_context"].splitlines()[0].startswith("noise level")


# ---------------------------------------------------------------------------------------- 9 (R48f low): tokens, on both sides, and the basis of a unit


@pytest.mark.parametrize(
    "quote",
    [
        "Noise level x85 dB(A)",
        "Noise level PN85 dB(A)",
        "Noise level 85x dB(A)",
        "Noise level A85 dB(A)",
        "Noise level 85dB(A)",
    ],
)
def test_9_a_number_glued_to_a_letter_is_not_the_value(quote):
    ln = line("85", page_text=quote, source_text=quote)
    assert query(ln, "paper_value_not_in_quote")


def test_9_the_number_helpers_use_token_boundaries():
    assert (
        proof.number_stated("85", "Noise level 85 dB(A)")
        and proof.number_stated("85", "Noise level 85.")
        and proof.number_stated("85", "(85)")
    )
    assert (
        not proof.number_stated("85", "x85")
        and not proof.number_stated("5", "15 bar")
        and not proof.number_stated("85", "85.5")
    )


@pytest.mark.parametrize(
    "quote",
    [
        "Design pressure 10 bar(g)",
        "Design pressure 10 barg",
        "Design pressure 10 bar/h",
    ],
)
def test_9_a_unit_that_is_the_start_of_a_longer_unit_or_basis_is_a_query(quote):
    ln = line(
        "10",
        unit="bar",
        page_text=quote,
        source_text=quote,
        field_label="Design pressure",
    )
    assert ln["verdict"] == "Query"
    assert not proof.unit_stated("bar", quote)


def test_9_a_unit_as_its_own_token_is_stated_and_case_is_kept():
    assert (
        proof.unit_stated("bar", "Design pressure 10 bar.")
        and proof.unit_stated("dB(A)", "85 dB(A)")
        and proof.unit_stated("", "x")
    )
    assert not proof.unit_stated("MPa", "5 mPa") and not proof.unit_stated(
        "bar", "10 barg"
    )
