"""N9: an "AI thinks: met" the code cannot stand behind is a Query. Invented data only; no model, no network."""

from __future__ import annotations

import pytest

from app import agent_review_verdict as V
from app import agent_review_wording as W

CHECKLIST = {"item_id": "S-1", "source": "skill", "rule_version_id": None}
RULE_OK = {"item_id": "R-1", "source": "rule", "rule_label": {"tier": "AI approved"}}
OK = {"paper": True, "clause": True, "both": True}


def met(**kw):
    base = {
        "item_id": "S-1",
        "verdict": "Query",
        "decided_by": "engineer",
        "ai_verdict": "Pass",
        "why": "second opinion disagreed",
        "paper_quote": "Body material: carbon steel",
        "quotes_checked": dict(OK),
    }
    return {**base, **kw}


def exit_of(line, item=CHECKLIST):
    return W.final_cap(line, item, None, {"S-1"}, "datasheet")


@pytest.mark.parametrize("item", [CHECKLIST, RULE_OK])
@pytest.mark.parametrize(
    "quote",
    [
        "340 psig (By Contractor, as per Code)",
        "Set pressure: to be confirmed",
        "Capacity TBA",
        "Orifice: vendor to advise",
        "Seat tightness\nlater",
        "Lift\nhold",
        "Tag\n-",
    ],
)
def test_met_with_a_deferring_paper_quote_is_a_query(item, quote):
    out = exit_of(met(item_id=item["item_id"], paper_quote=quote), item)
    assert out["verdict_label"] == W.WORD_QUERY
    assert out["verdict_class"] == W.CLASS_QUERY
    assert out["not_proven_reason"] == V.DEFERRED_WHY
    assert quote not in out["not_proven_reason"]


@pytest.mark.parametrize(
    ("checks", "why"),
    [
        ({"paper": True, "clause": False}, V.UNVERIFIED_CLAUSE_WHY),
        ({"paper": False, "clause": True}, V.UNVERIFIED_PAPER_WHY),
        (None, V.UNVERIFIED_PAPER_WHY),
    ],
)
def test_met_with_an_unverified_quote_is_a_query(checks, why):
    out = exit_of(met(quotes_checked=checks))
    assert (out["verdict_label"], out["verdict_class"]) == (W.WORD_QUERY, W.CLASS_QUERY)
    assert out["not_proven_reason"] == why


def test_met_with_verified_plain_quotes_stays_met():
    out = exit_of(met())
    assert out["verdict_label"] == W.THINKS_MET
    assert out["verdict_class"] == W.CLASS_OPINION


def test_a_proven_pass_is_not_touched_even_with_odd_quote_fields():
    out = exit_of(
        met(
            verdict="Pass",
            decided_by="AI verdict",
            paper_quote="By Contractor",
            quotes_checked={},
        )
    )
    assert (out["verdict_label"], out["verdict_class"]) == ("Pass", W.CLASS_PROVEN)


def test_not_met_is_not_touched():
    out = exit_of(
        met(
            ai_verdict="Fail",
            paper_quote="By Contractor",
            quotes_checked={"paper": False},
        )
    )
    assert out["verdict_label"] == W.THINKS_NOT_MET


def test_the_guard_never_makes_a_line_more_confident():
    for ai in ("Pass", "Fail", "Query", None):
        for verdict in ("Pass", "Fail", "Query"):
            for quote in ("340 psig By Contractor", "carbon steel body"):
                for checks in (dict(OK), {"paper": False}, None):
                    line = met(
                        ai_verdict=ai,
                        verdict=verdict,
                        paper_quote=quote,
                        quotes_checked=checks,
                    )
                    before = W.classify(
                        {**line, "quotes_checked": dict(OK), "paper_quote": "x" * 30}
                    )
                    after = W.classify(line)
                    rank = {
                        "Query for the engineer": 0,
                        W.THINKS_NOT_MET: 1,
                        W.THINKS_MET: 1,
                        "Fail": 2,
                        "Pass": 2,
                    }
                    assert (
                        rank[after["verdict_label"]] <= rank[before["verdict_label"]]
                        or ai != "Pass"
                    )


def test_the_deferral_word_list_is_the_one_in_blank_markers():
    """The guard has no word list of its own; these phrases are what it reacts to today (a change here is a reviewed change)."""
    deferring = [
        "by contractor",
        "by vendor",
        "by supplier",
        "by manufacturer",
        "by bidder",
        "to be advised",
        "to be confirmed",
        "to be determined",
        "to be specified",
        "to be provided",
        "vendor to advise",
        "contractor to confirm",
        "supplier to provide",
        "tba",
        "tbc",
        "tbd",
        "later",
        "hold",
        "-",
        "*",
    ]
    for word in deferring:
        assert V.quote_defers(f"Value\n{word}") or V.quote_defers(f"10 bar {word}"), (
            word
        )
    for plain in ("carbon steel", "N/A", "not required", "Required", "340 psig", ""):
        assert not V.quote_defers(plain), plain


@pytest.mark.parametrize("item", [CHECKLIST, RULE_OK])
def test_met_with_a_disagreeing_second_opinion_is_a_query(item):
    out = exit_of(
        met(item_id=item["item_id"], second_opinion={"agree": False, "model": "m"}),
        item,
    )
    assert (out["verdict_label"], out["verdict_class"]) == (W.WORD_QUERY, W.CLASS_QUERY)
    assert out["not_proven_reason"] == V.DISAGREE_WHY


def test_met_with_an_agreeing_second_opinion_stays_met():
    out = exit_of(met(second_opinion={"agree": True, "model": "m"}))
    assert out["verdict_label"] == W.THINKS_MET


def test_met_with_no_second_opinion_asked_stays_met_but_other_clauses_apply():
    assert exit_of(met(second_opinion=None))["verdict_label"] == W.THINKS_MET
    out = exit_of(
        met(second_opinion=None, quotes_checked={"paper": True, "clause": False})
    )
    assert out["not_proven_reason"] == V.UNVERIFIED_CLAUSE_WHY


def test_met_with_a_failed_second_opinion_is_neither_agreement_nor_disagreement():
    failed = {"agree": None, "model": "unknown"}
    assert exit_of(met(second_opinion=failed))["verdict_label"] == W.THINKS_MET
    out = exit_of(met(second_opinion=failed, paper_quote="Value TBA"))
    assert out["not_proven_reason"] == V.DEFERRED_WHY


def test_a_disagreeing_second_opinion_does_not_move_a_proven_pass_or_not_met():
    d = {"agree": False, "model": "m"}
    assert (
        exit_of(met(verdict="Pass", decided_by="AI verdict", second_opinion=d))[
            "verdict_label"
        ]
        == "Pass"
    )
    assert (
        exit_of(met(ai_verdict="Fail", second_opinion=d))["verdict_label"]
        == W.THINKS_NOT_MET
    )
