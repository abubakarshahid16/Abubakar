"""Order 14, lane A: the AI said "met" on a value whose own verified quote carries a deferral mark ("By Contractor"), and a pass
guard already made it a Query with another reason (the field is not quoted). The line takes the reason value_deferred, so the
engineer reads why it is open; it stays a Query. Code and two-reader Queries, AI not-met opinions and unverified quotes are never
touched. Invented values only."""

from __future__ import annotations

from app import agent_review_verdict as V
from app.agent_review_decide import DecideMixin

QUOTE = "Back pressure variable 12 psig By Contractor"


def fix(
    quote=QUOTE,
    *,
    ai="Pass",
    by="engineer",
    dec="Query",
    checked=True,
    code="pass_field_not_quoted",
):
    decision = {"verdict": dec, "decided_by": by, "why": "the field is not quoted"}
    ev = {"checks": V.QuoteCheck(checked, True), "reason_code": code}
    return DecideMixin().deferred_quote(
        {"paper_page": 3, "verdict": ai, "paper_quote": quote}, ev, decision, None
    )


def test_a_guarded_ai_pass_on_a_marked_value_takes_value_deferred_and_stays_a_query():
    got = fix()
    assert got is not None
    decision, code, page = got
    assert (decision["verdict"], decision["decided_by"], code, page) == (
        "Query",
        "engineer",
        "value_deferred",
        3,
    )
    assert "not final on page 3" in decision["why"]


def test_nothing_else_is_touched():
    assert (
        fix("Back pressure variable 12 psig") is None
    )  # no mark on the line's own quote
    assert fix(checked=False) is None  # the quote is not verified on its page
    assert fix(by="decided by code") is None  # a code decision
    assert fix(by="AI verdict") is None  # a two-reader decision
    assert fix(ai="Fail") is None  # an AI not-met opinion stays as it is
    assert fix(code="not_applicable") is None
