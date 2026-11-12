# ruff: noqa: C408, E501
"""The calculator of the one reviewer (owner, 12 Nov 2026, STATE section 37): code comparisons as lines of the AI review. Pure; no model, no database.

Each test names the risk of ONE-REVIEWER.md it guards. A "Proven by code" Pass or Fail is unreachable without a compared value with both quotes found by code.
"""

from __future__ import annotations

import itertools

import pytest

from app import agent_review_calculator as calc
from app import agent_review_verdict as V
from app import agent_review_wording as W
from app import comparison, datasheet_checks, hold_reason

PAGE = "Design data. Noise level 85 dB(A). Operating pressure 12 bar. Design pressure 10 bar."
CLAUSE = "Noise level shall not exceed 90 dB(A)."
ITEM = {
    "item_id": "R-1", "source": "rule", "standard": "STD-1", "clause": "4.1", "rule_kind": "limit", "comparator": "<=",
    "value": 90, "unit": "dB(A)", "question": CLAUSE, "rule_version_id": "v1", "standard_document_id": "std1",
    "rule_label": {"tier": "AI approved"}, "field_roles": ["noise"],
}  # fmt: skip


def fact(raw="85", unit="dB(A)", **over):
    base = {
        "id": "f1", "field_label": "Noise level", "raw_value": raw, "raw_unit": unit, "unit": unit, "page": 1,
        "is_blank": False, "source_text": f"Noise level {raw} {unit}", "equipment_tag": "T1",
    }  # fmt: skip
    return {**base, **over}


def line(
    raw="85",
    unit="dB(A)",
    page_text=None,
    clause_text=CLAUSE,
    clause_quote=CLAUSE,
    **over,
):
    f = fact(raw, unit, **over)
    page_text = (
        f"Design data. Noise level {raw} {unit}. Operating pressure 12 bar."
        if page_text is None
        else page_text
    )
    return calc.numeric_line(
        ITEM,
        calc.requirement_from_item(ITEM),
        f,
        submittal_facts=[f],
        page_text=page_text,
        clause_quote=clause_quote,
        clause_text=clause_text,
    )


def exit_of(ln, item=ITEM):
    return W.final_cap(ln, item, None, skill_ids=frozenset())


# ------------------------------------------------------------------------------------------ a compared value, both quotes found: proven


def test_a_met_limit_is_a_proven_pass_and_a_breach_a_proven_fail_through_the_exit():
    ok, bad = exit_of(line("85")), exit_of(line("95"))
    assert (ok["verdict"], ok["verdict_class"]) == ("Pass", "Proven by code")
    assert (bad["verdict"], bad["verdict_class"]) == ("Fail", "Proven by code")
    assert ok["compare"] == {
        "decided": True,
        "verdict": "meets",
        "reason": ok["compare"]["reason"],
    }
    assert (
        bad["decided_by"] == V.BY_CODE
        and bad["item_id"] == "C-R-1-f1"
        and bad["source"] == "code"
    )
    assert (
        ok["quotes_checked"] == {"paper": True, "clause": True}
        and ok["paper_page"] == 1
    )


def test_a_should_rule_is_marked_a_recommendation_by_the_exit():
    advice = {**ITEM, "rule_kind": "advice", "requirement_type": "recommendation"}
    ln = calc.numeric_line(
        advice,
        calc.requirement_from_item(advice),
        fact("95"),
        submittal_facts=[fact("95")],
        page_text="Noise level 95 dB(A)",
        clause_quote=CLAUSE,
        clause_text=CLAUSE,
    )
    ln["rule_kind"] = "advice"
    assert exit_of(ln, advice)["recommendation"] is True


# ------------------------------------------------------------------------------------------ risk: a Pass with a value that was not compared


@pytest.mark.parametrize(
    "ln, code",
    [
        (
            lambda: line("85", "bar"),
            "not_decided",
        ),  # a unit the limit cannot be compared with: never a guess
        (lambda: line("95", "kPa"), "not_decided"),
        (
            lambda: calc.numeric_line(
                ITEM,
                calc.requirement_from_item(ITEM),
                None,
                submittal_facts=[],
                page_text=PAGE,
                clause_quote=CLAUSE,
                clause_text=CLAUSE,
            ),
            "no_fact",
        ),
        (lambda: line("", "dB(A)", is_blank=True, raw_value=None), "blank_value"),
        (lambda: line(page_text="Something else entirely."), "paper_quote_unverified"),
        (lambda: line(clause_text="A different clause."), "clause_quote_unverified"),
        (
            lambda: line(clause_quote="Noise shall never exceed 70 dB(A)."),
            "clause_quote_unverified",
        ),
        (lambda: line(page=None), "paper_quote_unverified"),
    ],
)
def test_anything_short_of_a_compared_value_with_both_quotes_found_is_a_query_with_the_reason(
    ln, code
):
    got = ln()
    assert got["verdict"] == "Query" and got["reason_code"] == code and got["why"]
    assert not calc.can_be_proven(got)
    capped = exit_of(got)
    assert capped["verdict_class"] != "Proven by code" and capped["verdict"] == "Query"


def test_a_hold_on_the_comparison_is_a_query(monkeypatch):
    held = {
        "status": "COMPLIANT",
        "rationale": "held",
        "limit": {"raw_value": "90"},
        "observed": {"raw_value": "85"},
        hold_reason.KEY: "rule_not_proven",
    }
    monkeypatch.setattr(comparison, "compare", lambda *a, **k: held)
    got = line()
    assert got["verdict"] == "Query" and got["reason_code"] == "held"


def test_a_fact_whose_quote_does_not_verify_is_not_compared_into_a_verdict():
    """The lead's decision: a fact whose quote does not verify is a Query with the reason, never a Pass or Fail."""
    got = line("95", page_text="The sheet says nothing about noise.")
    assert got["verdict"] == "Query" and "not found on its page" in got["why"]


# ------------------------------------------------------------------------------------------ the brute force


STATUSES = (
    "COMPLIANT",
    "NON_COMPLIANT",
    "MISSING_INFORMATION",
    "NEEDS_ENGINEER_REVIEW",
    "NOT_APPLICABLE",
    "NOT_IN_DOCUMENT_SCOPE",
    None,
)


def test_brute_force_proven_by_code_is_unreachable_without_a_compared_value_with_both_quotes(
    monkeypatch,
):
    seen = proven = 0
    for status, limit, observed, hold, paper_ok, clause_ok, blank, page in itertools.product(
        STATUSES, (True, False), (True, False), (None, "x"), (True, False), (True, False), (True, False), (1, None, True, "1", 0)
    ):  # fmt: skip
        out = {
            "status": status,
            "rationale": "r",
            "limit": {"raw_value": "90"} if limit else None,
            "observed": {"raw_value": "85"} if observed else None,
        }
        if hold:
            out[hold_reason.KEY] = hold
        monkeypatch.setattr(comparison, "compare", lambda *a, _o=out, **k: _o)
        f = fact(is_blank=blank, page=page)
        ln = calc.numeric_line(
            ITEM, calc.requirement_from_item(ITEM), f, submittal_facts=[f],
            page_text="Noise level 85 dB(A)" if paper_ok else "nope", clause_quote=CLAUSE, clause_text=CLAUSE if clause_ok else "nope",
        )  # fmt: skip
        seen += 1
        capped = exit_of(ln)
        should = (
            status in ("COMPLIANT", "NON_COMPLIANT") and limit and observed and not hold and paper_ok and clause_ok and not blank
            and isinstance(page, int) and not isinstance(page, bool) and page >= 1
        )  # fmt: skip
        if should:
            proven += 1
            assert (
                ln["verdict"] == ("Pass" if status == "COMPLIANT" else "Fail")
                and capped["verdict_class"] == "Proven by code"
            )
            assert calc.can_be_proven(ln)
        else:
            assert (
                ln["verdict"] == "Query" and capped["verdict_class"] != "Proven by code"
            ), (status, limit, observed, hold, paper_ok, clause_ok, blank, page)
            assert capped["verdict"] == "Query" and not calc.can_be_proven(ln)
    assert (
        seen == 7 * 2 * 2 * 2 * 2 * 2 * 2 * 5 and proven == 2 * 1
    )  # one proven case per verdict: every other combination is a Query


# ------------------------------------------------------------------------------------------ the exit asks again (PR 2)


FORGED = [
    dict(compare={"decided": False}),  # no comparison
    dict(quotes_checked={"paper": True, "clause": False}),
    dict(quotes_checked={"paper": False, "clause": True}),
    dict(quotes_checked={}),
    dict(paper_page=None),
    dict(decided_by=V.BY_AI),  # a verdict the model gave
    dict(
        compare={"decided": True, "verdict": "does_not_meet"}
    ),  # a Pass whose comparison says otherwise
]


@pytest.mark.parametrize("change", FORGED)
def test_the_exit_demotes_a_code_line_that_is_pass_without_its_proof(change):
    ln = {**line("85"), **change}
    assert ln["verdict"] == "Pass"
    capped = exit_of(ln)
    assert capped["verdict"] == "Query" and capped["verdict_class"] != "Proven by code"


def test_the_exit_leaves_a_proven_code_line_alone():
    ln = line("95")
    assert (
        exit_of(ln)["verdict_class"] == "Proven by code"
        and exit_of(exit_of(ln))["verdict_class"] == "Proven by code"
    )  # idempotent


def test_a_numeric_code_line_of_an_unapproved_rule_is_capped_like_any_rule_line():
    unapproved = {**ITEM, "rule_tier": V.RULE_NOT_APPROVED}
    capped = exit_of(line("95"), unapproved)
    assert capped["verdict"] == "Query" and capped["verdict_class"] != "Proven by code"


# ------------------------------------------------------------------------------------------ the approved checklist


FACTS = [
    {"id": "f1", "field_name": "Design pressure", "field_label": "Design pressure", "raw_value": "10", "raw_unit": "bar", "unit": "bar", "page": 1, "equipment_tag": "T1", "is_blank": False},
    {"id": "f2", "field_name": "Operating pressure", "field_label": "Operating pressure", "raw_value": "12", "raw_unit": "bar", "unit": "bar", "page": 1, "equipment_tag": "T1", "is_blank": False},
]  # fmt: skip


def test_the_approved_checklist_results_become_lines_through_the_one_evaluator():
    results = datasheet_checks.evaluate(
        FACTS, equipment_type=None, page_texts={1: PAGE}
    )
    lines = calc.checklist_lines(results, page_texts={1: PAGE})
    c1 = next(x for x in lines if x["rule_id"] == "DS-C1")
    assert (
        c1["source"] == "code"
        and c1["approved_checklist"] is True
        and c1["standard"] == "Approved checklist"
    )
    assert (
        c1["verdict"] == "Fail"
        and c1["compare"]["decided"] is True
        and c1["item_id"] == "C-DS-C1-f1"
    )
    capped = exit_of(c1, c1)  # the approved entry stands as its own item: tier owner
    assert (
        capped["verdict_class"] == "Proven by code" and capped["tier"] == V.OWNER_TIER
    )
    assert all(x["verdict"] in ("Pass", "Fail", "Query") for x in lines)


def test_a_checklist_value_that_is_not_on_its_page_next_to_its_label_is_a_query():
    results = datasheet_checks.evaluate(
        FACTS, equipment_type=None, page_texts={1: PAGE}
    )
    lines = calc.checklist_lines(
        results,
        page_texts={
            1: "Design pressure is stated on page 7 of the data book."
            + " filler" * 20
            + " Operating pressure 12 bar. A stray 10 here."
        },
    )
    c1 = next(x for x in lines if x["rule_id"] == "DS-C1")
    assert (
        c1["verdict"] == "Query" and c1["reason_code"] == "paper_quote_unverified"
    )  # "10" is on the page, but not next to the label
    assert calc.value_near_label(
        "Design pressure", "10", "Design pressure 10 bar"
    ) and not calc.value_near_label("Design pressure", "10", "")


def test_a_check_that_does_not_apply_is_no_line_and_a_held_one_is_a_query():
    held = {
        "rule_id": "DS-C1",
        "status": "COMPLIANT",
        "text": "t",
        "detail": "d",
        "value": "10",
        "page": 1,
        "fact_id": "f1",
        "field": "Design pressure",
        hold_reason.KEY: "x",
    }
    na = {"rule_id": "DS-C2", "status": "NOT_APPLICABLE", "text": "t", "detail": "d"}
    lines = calc.checklist_lines([held, na], page_texts={1: PAGE})
    assert [x["rule_id"] for x in lines] == ["DS-C1"] and lines[0]["verdict"] == "Query"


def test_a_forged_approved_marker_with_an_id_the_approved_file_does_not_hold_is_capped():
    forged = {"item_id": "C-X-1", "source": "code", "approved_checklist": True, "rule_id": "DS-NOT-APPROVED", "verdict": "Fail", "decided_by": V.BY_CODE,
              "compare": {"decided": True, "verdict": "does_not_meet"}, "quotes_checked": {"paper": True, "clause": True}, "paper_page": 1}  # fmt: skip
    assert not V.is_approved_code_item(forged)
    capped = exit_of(forged, forged)
    assert capped["verdict"] == "Query" and capped["verdict_class"] != "Proven by code"
    real = {**forged, "rule_id": "DS-C1"}
    assert (
        V.is_approved_code_item(real)
        and exit_of(real, real)["verdict_class"] == "Proven by code"
    )
    assert not V.is_approved_code_item(
        {**real, "source": "rule"}
    ) and not V.is_approved_code_item({**real, "approved_checklist": "yes"})


def test_the_calculator_makes_no_second_number_reader_and_opens_nothing():
    import pathlib

    text = pathlib.Path(calc.__file__).read_text()
    for bad in (
        "numparse",
        "re.compile",
        "socket",
        "requests",
        "httpx",
        "urllib",
        "sqlite3",
        "connect(",
    ):
        assert bad not in text, bad
    assert "comparison.compare" in text  # the one comparison
