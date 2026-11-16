"""Order 14 lane D (proposed with the wiring of `blank_markers.defers_value`): an AI "not met" that rests on silence while the
paper quote code verified itself defers the value ("___*___", "By Contractor") is a Query, never "AI thinks: not met".
Invented lines only."""

from __future__ import annotations

from app import agent_review_verdict as v
from app import agent_review_wording as wording


def _line(**kw):
    base = {
        "source": "skill", "item_id": "S-T-1", "verdict": "Query", "decided_by": "engineer", "ai_verdict": "Fail",
        "reason_code": "absent", "paper_quote": "SEAL CHAMBER PRESSURE  ______*______  barg", "paper_page": 2,
        "quotes_checked": {"paper": True, "clause": True}, "why": "not shown on the sheet; code cannot prove an absence",
    }  # fmt: skip
    return {**base, **kw}


def test_a_silent_not_met_on_a_star_quote_is_a_query():
    got = wording.classify(_line())
    assert got["verdict_class"] == wording.CLASS_QUERY
    assert got["not_proven_reason"].startswith(v.DEFERRED_WHY)


def test_a_silent_not_met_on_a_phrase_quote_is_a_query():
    got = wording.classify(_line(paper_quote="Coupling make  By Contractor"))
    assert got["verdict_class"] == wording.CLASS_QUERY


def test_left_alone_unverified_quote_other_reason_proven_fail_or_no_mark():
    assert wording.not_met_deferred_why(_line(quotes_checked={"paper": False})) is None
    assert wording.not_met_deferred_why(_line(reason_code="not_met")) is None
    assert wording.not_met_deferred_why(_line(verdict="Fail")) is None
    assert (
        wording.not_met_deferred_why(
            _line(paper_quote="SEAL CHAMBER PRESSURE  3.2 barg *")
        )
        is None
    )
    assert (
        wording.classify(_line(paper_quote="SEAL CHAMBER PRESSURE  (blank)"))[
            "verdict_class"
        ]
        == wording.CLASS_OPINION
    )


def test_quote_defers_sees_the_star_blank():
    assert v.quote_defers("FLUSH ___*___ m3/h") is True
    assert v.quote_defers("RATED FLOW 24.8 m3/h *") is False
