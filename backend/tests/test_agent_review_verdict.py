"""The AI reviewer gate: the verdict rule. Invented data only; no model, no network."""

from __future__ import annotations

import itertools

import pytest

from app import agent_review_verdict as V

LEAD = "claude-sonnet-5-5-20261101"
OTHER = "claude-opus-5-5"
PAGES = {1: "ITEM DATA\nNameplate material: aluminium\nCoating thickness: 0.15 mm"}
CLAUSE = "4.1 Nameplates\nNameplates shall be made of stainless steel or aluminium and fixed with corrosion resistant screws."
GOOD = {
    "paper_page": 1,
    "paper_quote": "Nameplate material: aluminium",
    "clause_quote": "Nameplates shall be made of stainless steel or aluminium and fixed with corrosion resistant screws",
}


def test_quote_checks_are_verbatim_on_the_named_page():
    assert V.check_quotes(GOOD, PAGES, CLAUSE).both
    assert V.check_quotes(GOOD, PAGES, CLAUSE).clause_strong
    altered = {**GOOD, "paper_quote": "Nameplate material: aluminum"}
    assert not V.check_quotes(altered, PAGES, CLAUSE).paper
    assert not V.check_quotes(
        {**GOOD, "paper_page": 2}, PAGES, CLAUSE
    ).paper  # a page that was not sent
    assert not V.check_quotes(
        {**GOOD, "clause_quote": "Nameplates shall be brass"}, PAGES, CLAUSE
    ).clause
    assert not V.check_quotes(GOOD, PAGES, None).clause  # no clause text held
    heading = V.check_quotes({**GOOD, "clause_quote": "4.1 Nameplates"}, PAGES, CLAUSE)
    assert (
        heading.clause and not heading.clause_strong
    )  # the heading is in the clause, but never carries a verdict


SECONDS = [
    None,
    {"agree": True, "model": OTHER},
    {"agree": False, "model": OTHER},
    {"agree": None, "model": OTHER},
    {"agree": True, "model": LEAD},  # the same model as the lead
    {"agree": True, "model": "unknown"},  # model not reported
]


@pytest.mark.parametrize(
    "ai,paper,clause,strong,second,error,absent",
    list(
        itertools.product(
            (V.PASS, V.FAIL, V.QUERY, None),
            (True, False),
            (True, False),
            (True, False),
            range(len(SECONDS)),
            (None, "transport_ReadTimeout"),
            (False, True),
        )
    ),
)
def test_textual_pass_or_fail_only_with_both_quotes_and_an_agreeing_second(
    ai, paper, clause, strong, second, error, absent
):
    checks = V.QuoteCheck(
        paper=paper, clause=clause, clause_strong=strong
    )  # even an inconsistent check
    got = V.textual_verdict(
        ai, checks, SECONDS[second], LEAD, error=error, absent=absent
    )
    allowed = (
        ai in (V.PASS, V.FAIL)
        and paper
        and clause
        and strong
        and second == 1
        and error is None
        and not (ai == V.PASS and absent)
    )
    if allowed:
        assert got["verdict"] == ai and got["decided_by"] == V.BY_AI
    else:
        assert got["verdict"] == V.QUERY
    if error:
        assert error in got["why"]  # 3e: the failure is shown, never hidden


def test_lead_model_unknown_can_never_pass():
    checks = V.QuoteCheck(True, True, clause_strong=True)
    assert (
        V.textual_verdict(V.PASS, checks, {"agree": True, "model": OTHER}, None)[
            "verdict"
        ]
        == V.QUERY
    )
    assert (
        V.textual_verdict(V.PASS, checks, {"agree": True, "model": OTHER}, "unknown")[
            "verdict"
        ]
        == V.QUERY
    )


NUM_ANSWER = {
    "paper_page": 1,
    "paper_quote": "Coating thickness: 0.15 mm",
    "clause_quote": "The coating thickness shall be at least 0.2 mm on every outside surface.",
    "paper_figure": "Coating thickness: 0.15 mm",
    "clause_figure": "coating thickness shall be at least 0.2 mm",
}
COMPARES = [
    {"decided": True, "verdict": "meets"},
    {"decided": True, "verdict": "does_not_meet"},
    {"decided": False, "verdict": "cannot decide", "reason": "subject_mismatch"},
    None,
]


@pytest.mark.parametrize(
    "cmp,paper,clause,figs,error",
    list(
        itertools.product(
            range(len(COMPARES)),
            (True, False),
            (True, False),
            (True, False),
            (None, "stop_refusal"),
        )
    ),
)
def test_number_line_is_decided_by_code_only(cmp, paper, clause, figs, error):
    answer = (
        NUM_ANSWER if figs else {**NUM_ANSWER, "paper_figure": "", "clause_figure": ""}
    )
    got = V.number_verdict(
        COMPARES[cmp], V.QuoteCheck(paper, clause), answer, error=error
    )
    if paper and clause and figs and error is None and cmp in (0, 1):
        assert got["verdict"] == (V.PASS if cmp == 0 else V.FAIL)
        assert got["decided_by"] == V.BY_CODE
    else:
        assert got["verdict"] == V.QUERY


def test_number_line_ignores_the_ai_verdict_and_uses_compare_number():
    from app import agent_tools

    box = agent_tools.ToolBox(
        agent_tools.ToolContext(allowed_document_ids={"d"}, document_id="d"),
        page_reader=lambda d, n: PAGES.get(n),
        searcher=lambda q, a: {"hits": []},
        standard_pages=lambda d: [],
    )
    answer = {
        **NUM_ANSWER,
        "verdict": "Pass",
    }  # the AI says Pass; the code says does not meet
    cmp = V.compare_figures(box, answer)
    assert cmp["decided"] is True and cmp["verdict"] == "does_not_meet"
    got = V.number_verdict(cmp, V.QuoteCheck(True, True), answer)
    assert got == {"verdict": V.FAIL, "decided_by": V.BY_CODE, "why": None}


def test_a_figure_outside_its_quote_is_not_compared():
    answer = {**NUM_ANSWER, "paper_figure": "Coating thickness: 0.35 mm"}
    assert not V.figures_inside(answer)
    assert (
        V.number_verdict(
            {"decided": True, "verdict": "meets"}, V.QuoteCheck(True, True), answer
        )["verdict"]
        == V.QUERY
    )


def test_not_mentioned_words_are_seen():
    assert V.says_absent({"reasoning": "The value is not stated on the paper."})
    assert not V.says_absent({"reasoning": "The paper gives aluminium."})


SHORT_RULE = "Nameplates shall be steel."  # a whole rule sentence under 40 characters


def test_short_partial_clause_quote_stays_weak():
    ok, _why, strong = V.check_clause_quote(
        "Nameplates shall be", SHORT_RULE, SHORT_RULE
    )
    assert ok and not strong  # verified, but only part of the short requirement: weak


def test_the_whole_short_requirement_quoted_exactly_is_strong():
    ok, _why, strong = V.check_clause_quote(
        "Nameplates shall be steel.", SHORT_RULE, SHORT_RULE
    )
    assert ok and strong
    ok, _why, strong = V.check_clause_quote(
        "nameplates  shall be\nsteel.", SHORT_RULE, SHORT_RULE
    )
    assert ok and strong  # the existing fold: case and spacing only


def test_whole_text_counts_only_when_it_is_the_requirement():
    ok, _why, strong = V.check_clause_quote(
        "Nameplates shall be steel.", SHORT_RULE
    )  # no requirement given
    assert ok and not strong
    longer = SHORT_RULE + " Screws shall be stainless."
    ok, _why, strong = V.check_clause_quote(
        "Nameplates shall be steel.", longer, longer
    )
    assert ok and not strong  # part of a longer requirement: still weak
    checks = V.check_quotes(
        {
            "paper_page": 1,
            "paper_quote": "Nameplate material: aluminium",
            "clause_quote": SHORT_RULE,
        },
        PAGES,
        SHORT_RULE,
        SHORT_RULE,
    )
    assert checks.both and checks.clause_strong


# ---------------------------------------------------------------- F1: a conditional rule's Fail is never proven

PROVEN_FAIL = {"verdict": V.FAIL, "decided_by": V.BY_AI, "why": None}
PROVEN_PASS = {"verdict": V.PASS, "decided_by": V.BY_AI, "why": None}


def test_markers_are_plain_conditional_words_only():
    for text in (
        "Valves shall be closed when the line is idle.",
        "Only gate valves are allowed",
        "Unless agreed, use steel",
    ):
        assert V.is_conditional(text)
    for text in (
        "Valves shall be steel.",
        "Whenever",
        "",
        None,
    ):  # a word that merely contains a marker is no marker
        assert not V.is_conditional(text)
    assert not V.is_conditional(
        "The nameplate shall be made of aluminium.",
        "Coating thickness at least 0.2 mm.",
    )


def test_f1_a_conditional_rules_fail_becomes_a_query_and_nothing_else_changes():
    held = V.hold_conditional_fail(
        PROVEN_FAIL, "Supports shall be fitted where the span exceeds 3 m.", "x"
    )
    assert (
        held["verdict"] == V.QUERY
        and held["conditional"]
        and held["why"] == V.CONDITIONAL_WHY
    )
    assert held["decided_by"] == V.BY_ENGINEER
    by_requirement = V.hold_conditional_fail(
        PROVEN_FAIL, "Supports shall be fitted.", "Fit them when it is wet."
    )
    assert by_requirement["verdict"] == V.QUERY
    assert (
        V.hold_conditional_fail(PROVEN_PASS, "if wet", "when wet") == PROVEN_PASS
    )  # a Pass is never touched
    assert V.hold_conditional_fail({"verdict": V.QUERY}, "if wet", None) == {
        "verdict": V.QUERY
    }
    assert (
        V.hold_conditional_fail(PROVEN_FAIL, "Supports shall be fitted.", None)
        == PROVEN_FAIL
    )  # not conditional


# ---------------------------------------------------------------- F3: a table row or a note loses its conditions


def test_f3_the_three_signals_of_a_table_row_or_a_note():
    assert V.table_or_note_why({"requirement_type": "table_row"}, "x") == "a"
    assert V.table_or_note_why({"table_row": 3}, "x") == "a"
    assert V.table_or_note_why({"clause_from": "table_caption"}, "x") == "a"
    assert V.table_or_note_why({}, "NOTE 2: use steel") == "b"
    assert V.table_or_note_why({}, "(3) use steel") == "b"
    assert (
        V.table_or_note_why({}, "Valves shall be steel", ["clause_span", "table_page"])
        == "c"
    )
    assert V.table_or_note_why({}, "Valves shall be steel", ["clause_span"]) is None
    assert not V.is_note_start("Notes on steel") and V.is_note_start("Note 1. Steel")


def test_f3_a_table_row_or_note_fail_becomes_a_query_a_pass_is_unchanged():
    held = V.hold_table_note_fail(
        PROVEN_FAIL, {"requirement_type": "table_value"}, "Valves shall be steel."
    )
    assert (
        held["verdict"] == V.QUERY
        and held["why"] == V.TABLE_NOTE_WHY
        and held["table_note"] == "a"
    )
    assert V.hold_table_note_fail(PROVEN_FAIL, {}, "Note 1: steel")["table_note"] == "b"
    assert (
        V.hold_table_note_fail(PROVEN_FAIL, {}, "steel", ["table_page"])["table_note"]
        == "c"
    )
    assert V.hold_table_note_fail(PROVEN_PASS, {"table_row": 1}, "x") == PROVEN_PASS
    assert (
        V.hold_table_note_fail(PROVEN_FAIL, {}, "Valves shall be steel.") == PROVEN_FAIL
    )


# ---------------------------------------------------------------- the cap of a rule that is not AI approved

UNAPPROVED = {
    "source": "rule",
    "rule_tier": V.RULE_NOT_APPROVED,
    "rule_unapproved_why": "values",
}
APPROVED = {"source": "rule", "rule_label": {"tier": "AI approved"}}


def test_the_cap_turns_a_proof_into_a_query_and_nothing_else():
    for proven in (PROVEN_PASS, PROVEN_FAIL):
        capped = V.cap_unapproved(proven, UNAPPROVED)
        assert (
            capped["verdict"] == V.QUERY
            and capped["unapproved_cap"]
            and "not AI approved: values" in capped["why"]
        )
        assert (
            V.cap_unapproved(proven, APPROVED) == proven
        )  # an approved rule is untouched
        assert V.cap_unapproved(proven, None) == proven
    query = {"verdict": V.QUERY, "why": "x"}
    assert V.cap_unapproved(query, UNAPPROVED) == query


def test_the_holds_run_in_the_deciding_order_and_the_cap_is_inside_them():
    """THE cap in the decide path: an unapproved rule's proven Pass or Fail comes out as a Query."""
    for proven in (PROVEN_PASS, PROVEN_FAIL):
        out = V.apply_holds(
            proven,
            UNAPPROVED,
            clause_quote="Valves shall be steel.",
            requirement="Valves shall be steel.",
        )
        assert out["verdict"] == V.QUERY and out["unapproved_cap"]
    clean = V.apply_holds(
        PROVEN_FAIL,
        APPROVED,
        clause_quote="Valves shall be steel.",
        requirement="Valves shall be steel.",
    )
    assert clean == PROVEN_FAIL
    cond = V.apply_holds(
        PROVEN_FAIL,
        APPROVED,
        clause_quote="Valves shall be steel if wet.",
        requirement=None,
    )
    assert cond["verdict"] == V.QUERY and cond["conditional"]
    table = V.apply_holds(
        PROVEN_FAIL,
        {**APPROVED, "table_row": 2},
        clause_quote="Steel.",
        requirement="Steel.",
    )
    assert table["verdict"] == V.QUERY and table["table_note"] == "a"


def test_a_restored_line_is_capped_and_held_again_whatever_the_old_run_said():
    """The redecide path: a stored answer decided again. The cap and F1/F3 hold a line restored as Pass or Fail."""
    line = {
        "item_id": "R-1",
        "verdict": V.PASS,
        "decided_by": V.BY_CODE,
        "why": None,
        "clause_quote": "x",
        "requirement": "y",
    }
    out = V.restore_holds(line, UNAPPROVED)
    assert out["verdict"] == V.QUERY and out["unapproved_cap"]
    assert V.restore_holds(line, APPROVED)["verdict"] == V.PASS
    cond = V.restore_holds(
        {**line, "verdict": V.FAIL, "clause_quote": "if wet"}, APPROVED
    )
    assert cond["verdict"] == V.QUERY and cond["conditional_hold"]
    tab = V.restore_holds(
        {**line, "verdict": V.FAIL}, {**APPROVED, "requirement_type": "table_row"}
    )
    assert tab["verdict"] == V.QUERY and tab["table_note_hold"] == "a"
    assert V.restore_holds({**line, "verdict": V.FAIL}, APPROVED)["verdict"] == V.FAIL


# ---------------------------------------------------------------- the tier of an item and the calls it may buy


def test_the_tier_of_an_item_is_derived_never_assumed():
    assert V.item_tier({"source": "skill"}) == V.NOT_A_RULE
    for tier in ("owner", "engineer", "AI approved"):
        assert V.item_tier({"source": "rule", "rule_label": {"tier": tier}}) == tier
    assert V.item_tier(UNAPPROVED) == V.RULE_NOT_APPROVED
    assert (
        V.item_tier({"source": "rule"}) == V.RULE_NOT_APPROVED
    )  # no tier established: not approved
    assert V.item_tier(None) == V.RULE_NOT_APPROVED
    assert (
        V.item_tier({"source": "rule", "rule_label": {"tier": "not AI approved"}})
        == V.RULE_NOT_APPROVED
    )
    assert (
        V.item_tier({"source": "rule"}, lambda it: "engineer") == "engineer"
    )  # re-derived from the label
    assert V.item_tier({"source": "rule"}, lambda it: None) == V.RULE_NOT_APPROVED
    assert (
        V.item_tier({"source": "rule"}, lambda it: "anything else")
        == V.RULE_NOT_APPROVED
    )
    assert (
        V.item_tier(UNAPPROVED, lambda it: "owner") == V.RULE_NOT_APPROVED
    )  # a lookup never promotes it


def test_no_call_beyond_the_leads_answer_is_allowed_for_a_rule_not_approved():
    assert V.calls_allowed(APPROVED) and V.calls_allowed({"source": "skill"})
    assert not V.calls_allowed(UNAPPROVED)
    assert not V.calls_allowed({"source": "rule"})  # tier not established
    assert not V.calls_allowed(None)
    assert V.calls_allowed({"source": "rule"}, lambda it: "AI approved")


def test_the_current_label_table_overrides_the_tier_the_item_carried():
    carried = {"source": "rule", "rule_label": {"tier": "AI approved"}}
    assert V.item_tier(carried) == "AI approved"
    assert (
        V.item_tier(carried, lambda it: None) == V.RULE_NOT_APPROVED
    )  # the label was revoked since the item was built
    assert V.item_tier(carried, lambda it: "not AI approved") == V.RULE_NOT_APPROVED
    assert not V.calls_allowed(carried, lambda it: None)
