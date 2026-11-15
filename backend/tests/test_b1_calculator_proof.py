"""R48e on #1804: the proof behind "Proven by code" is recomputed from the line's own texts and values, never taken from a flag.
One test group per finding of the review. Invented data only."""

from __future__ import annotations

import copy
import itertools

import pytest

from app import agent_review_calculator as calc
from app import agent_review_code_proof as proof
from app import agent_review_verdict as V
from tests import b1_pages
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
    assert proven(good)
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


def test_8_the_page_is_read_again_so_a_forged_flag_quote_and_context_together_prove_nothing(
    _pages,
):
    good = line("85")
    assert proven(good)
    _pages[("doc1", 1)] = (
        "Noise level 70 dB(A)\nOperating pressure 85 dB(A)\n"  # what the store really holds
    )
    other = {
        **good,
        "paper_quote": "Operating pressure 85 dB(A)",
        "paper_context": "Noise level 85 dB(A)",
    }  # a real line of the page, another field
    assert (
        other["quotes_checked"]["paper"] is True
        and exit_of(other)["verdict_class"] != "Proven by code"
    )
    off_page = {
        **good,
        "paper_quote": "Noise level 85 dB(A)",
        "paper_context": "Noise level 85 dB(A)",
    }  # a quote the page does not hold
    assert exit_of(off_page)["verdict_class"] != "Proven by code"


@pytest.mark.parametrize(
    "change",
    [
        {"paper_document_id": None},
        {"paper_document_id": ""},
        {"paper_document_id": "other"},
        {"paper_page": 2},
        {"paper_page": True},
        {"paper_page": None},
    ],
)
def test_8_a_line_that_names_no_readable_page_is_not_proven(change):
    assert exit_of({**line("85"), **change})["verdict_class"] != "Proven by code"


def test_8_a_page_that_cannot_be_read_again_proves_nothing(monkeypatch):
    def boom(doc, page):
        raise RuntimeError("down")

    monkeypatch.setattr(proof, "PAGE_SOURCE", [boom])
    assert exit_of(line("85"))["verdict_class"] != "Proven by code"


def test_8_the_label_line_directly_above_still_proves_through_the_stored_lines():
    ok = line(
        "85",
        page_text="Noise level\n85 dB(A)\nOperating pressure 12 bar",
        source_text="85 dB(A)",
    )
    assert proven(ok)


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


# ---------------------------------------------------------------------------------------- 10 (valve trial): the clause must be ABOUT the rule's field


def test_10_a_limit_stated_for_another_subject_is_not_applied_to_this_field():
    clause = "Liquid service valves, certified in accordance with the code, are required to reach full capacity at 90 dB(A) or less noise."
    ln = _dir_line(clause, item={"comparator": "<="})
    assert (
        query(ln, "clause_subject_not_the_field")
        and "subject of the limit" in ln["why"]
    )


@pytest.mark.parametrize(
    "clause", ["The noise level shall not exceed 90 dB(A).", "Noise: maximum 90 dB(A)."]
)
def test_10_a_clause_about_the_field_still_proves(clause):
    assert proven(_dir_line(clause))


@pytest.mark.parametrize("field", [None, "", "pressure", "liquid"])
def test_10_the_exit_asks_again_a_line_whose_rule_field_is_not_in_the_clause_is_demoted(
    field,
):
    ln = _dir_line("Noise level shall not exceed 90 dB(A).")
    assert proven(ln) and ln["rule_field"] == "noise"
    assert exit_of({**ln, "rule_field": field})["verdict"] == "Query"


# ---------------------------------------------------------------------------------------- 11 (planted trial): a check that only asks a field be STATED compares no value


def _result(rule_id, status="COMPLIANT"):
    return {
        "rule_id": rule_id,
        "status": status,
        "fact_id": "f9",
        "value": "21",
        "page": 1,
        "field": "Over pressure %",
        "equipment_tag": "T1",
        "text": "The allowable overpressure is stated.",
        "detail": "stated",
    }


def test_11_a_presence_check_that_passes_makes_no_proven_line():
    from app import agent_review_approved_code as ac

    assert "PSV-06" in ac.presence_only_ids() and "PSV-16" not in ac.presence_only_ids()
    lines = calc.checklist_lines(
        [_result("PSV-06")], page_texts={1: "Over pressure % 21"}
    )
    assert lines == []  # stated is not compared: no Pass, and nothing to ask
    kept = calc.checklist_lines(
        [_result("PSV-06", "MISSING_INFORMATION")], page_texts={1: "x"}
    )
    assert (
        len(kept) == 1 and kept[0]["verdict"] == "Query"
    )  # a field that is NOT stated is still a question


def test_11_a_compared_check_still_proves_and_the_exit_demotes_a_forged_presence_pass():
    lines = calc.checklist_lines(
        [_result("PSV-16")], page_texts={1: "Over pressure % 21", 2: "x"}
    )
    assert (
        lines
        and lines[0]["verdict"] == "Pass"
        and exit_of(lines[0], lines[0])["verdict_class"] == "Proven by code"
    )
    forged = {**lines[0], "rule_id": "PSV-06"}
    out = exit_of(forged, forged)
    assert out["verdict"] == "Query" and out["verdict_class"] != "Proven by code"


@pytest.fixture(autouse=True)
def _pages(monkeypatch):
    return b1_pages.install(monkeypatch)


def test_8_a_checklist_line_is_asked_again_from_the_page_too(_pages):
    lines = calc.checklist_lines(
        [_result("PSV-16")], page_texts={1: "Over pressure % 21", 2: "x"}
    )
    assert (
        lines[0]["verdict"] == "Pass"
        and exit_of(lines[0], lines[0])["verdict_class"] == "Proven by code"
    )
    _pages[("doc1", 1)] = (
        "Something else 21"  # the stored page does not hold the value next to its label
    )
    assert lines[0]["quotes_checked"]["paper"] is True
    assert exit_of(lines[0], lines[0])["verdict_class"] != "Proven by code"


# ---------------------------------------------------------------------------------------- 12 (R48i 2): the field is the subject of the SAME sentence, as a whole phrase


def _subject_line(clause, field):
    return _dir_line(
        clause, item={"field_roles": [field], "rule_label": {"tier": "AI approved"}}
    )


def test_12_the_field_in_another_sentence_is_not_the_subject_of_the_limit():
    clause = "Noise level is reported separately. Valve body shall not exceed 90 dB(A)."
    ln = _subject_line(clause, "noise")
    assert query(ln, "clause_subject_not_the_field")
    assert proven(
        _subject_line(
            "Valve body is reported separately. Noise level shall not exceed 90 dB(A).",
            "noise",
        )
    )


def test_12_a_table_line_is_its_own_sentence():
    assert query(
        _subject_line("Noise level\nValve body maximum 90 dB(A)", "noise"),
        "clause_subject_not_the_field",
    )
    assert proven(_subject_line("Valve body\nNoise level maximum 90 dB(A)", "noise"))


@pytest.mark.parametrize(
    "clause",
    [
        "The test pressure shall not exceed 90 dB(A).",
        "The relief valve pressure shall not exceed 90 dB(A).",
        "Design pressure shall not exceed 90 dB(A).",
    ],
)
def test_12_a_lone_common_word_does_not_accept_a_longer_name_that_ends_in_it(clause):
    assert query(_subject_line(clause, "pressure"), "clause_subject_not_the_field")


@pytest.mark.parametrize(
    "clause",
    [
        "The pressure shall not exceed 90 dB(A).",
        "Pressure shall not exceed 90 dB(A).",
        "Pressure: maximum 90 dB(A).",
    ],
)
def test_12_the_lone_word_as_the_subject_itself_proves(clause):
    assert proven(_subject_line(clause, "pressure"))


def test_12_a_more_specific_field_of_the_approved_list_in_the_sentence_is_a_query():
    assert proven(
        _subject_line("The set pressure shall not exceed 90 dB(A).", "set_pressure")
    )
    assert query(
        _subject_line("The design pressure shall not exceed 90 dB(A).", "set_pressure"),
        "clause_subject_not_the_field",
    )
    assert query(
        _subject_line(
            "The set pressure and the design pressure shall not exceed 90 dB(A).",
            "set_pressure",
        ),
        "clause_subject_not_the_field",
    )


def test_12_a_field_that_stands_only_after_the_figure_is_not_the_subject():
    assert query(
        _subject_line(
            "Valves shall not exceed 90 dB(A) with the design pressure.",
            "design_pressure",
        ),
        "clause_subject_not_the_field",
    )
    assert proven(
        _subject_line(
            "The design pressure shall not exceed 90 dB(A).", "design_pressure"
        )
    )


def test_11_the_presence_counts_say_how_many_were_stated_and_how_many_are_missing():
    results = [
        _result("PSV-06"),
        _result("PSV-06"),
        _result("PSV-06", "MISSING_INFORMATION"),
        _result("PSV-06", "NOT_APPLICABLE"),
        _result("PSV-16"),
    ]  # PSV-16 is a compared check
    assert calc.presence_counts(results) == {
        "presence_checked": 3,
        "presence_stated": 2,
        "presence_missing": 1,
    }
    assert calc.presence_counts([]) == {
        "presence_checked": 0,
        "presence_stated": 0,
        "presence_missing": 0,
    }


# ---------------------------------------------------------------------------------------- 13 (lead B): a deferred value may be a proven FAIL by its stated figure, never a proven Pass


def _deferred(raw, note="By Contractor, as per Code"):
    text = f"Noise level {raw} dB(A) {note}"
    return line(raw, page_text=text, source_text=text, value_note=note)


def test_13_a_stated_figure_that_breaches_its_limit_is_a_proven_fail_in_plain_words():
    ln = _deferred("95")
    out = exit_of(ln)
    assert (out["verdict"], out["verdict_class"]) == ("Fail", "Proven by code") and ln[
        "deferred_note"
    ].startswith("By Contractor")
    words = ln["compare"]["reason"]
    assert (
        "the sheet marks this value as by the contractor" in words
        and "the figure stated is 95 dB(A)" in words
        and "which breaches <= 90 dB(A)" in words
    )


def test_13_a_deferred_figure_within_its_limit_is_a_question_never_a_pass():
    ln = _deferred("85")
    assert ln["verdict"] == "Query" and ln["reason_code"] == "deferred_value"
    assert (
        "defers Noise level to the contractor: confirm the value" in ln["why"]
        and exit_of(ln)["verdict_class"] != "Proven by code"
    )


def test_13_a_plain_value_is_unchanged_and_a_deferred_pass_is_demoted_at_the_exit():
    assert proven(line("85")) and proven(line("95"))
    fail = _deferred("95")
    forged = {
        **fail,
        "verdict": "Pass",
        "compare": {"decided": True, "verdict": "meets", "reason": ""},
    }
    assert exit_of(forged)["verdict"] == "Query"  # the line says it is deferred
    no_note = {k: v for k, v in forged.items() if k != "deferred_note"}
    assert exit_of(no_note)["verdict"] == "Query"  # and so does the page the line names


def test_13_a_deferral_phrase_beside_the_figure_on_the_page_demotes_a_forged_pass(
    _pages,
):
    good = line("85")
    assert proven(good)
    _pages[("doc1", 1)] = (
        "Noise level 85 dB(A) TBA vendor to advise"  # what the store holds now
    )
    assert exit_of(good)["verdict_class"] != "Proven by code"
