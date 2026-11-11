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
        "Seat tightness | later",
        "Lift | hold",
        "Tag\t-",
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
        assert V.quote_defers(f"Value | {word}") or V.quote_defers(f"10 bar {word}"), (
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


def test_line_wraps_and_note_references_are_not_deferrals():
    for text in (
        "Set pressure 10 barg is determined\nby calculation per API 520\nand shown on the drawing",
        "By design the body is cast steel",
        "Set pressure 10 bar\nNote 3",
        "Seat tightness\nlater",
    ):
        assert not V.quote_defers(text), text
        assert exit_of(met(paper_quote=text))["verdict_label"] == W.THINKS_MET
    assert (
        exit_of(met(paper_quote="Set pressure 340 psig (By Contractor)"))[
            "verdict_label"
        ]
        == W.WORD_QUERY
    )


def test_a_met_with_no_clause_quote_recorded_is_a_query_by_design():
    out = exit_of(
        met(
            clause_quote=None,
            quotes_checked={
                "paper": True,
                "clause": False,
                "clause_why": "no clause quote",
            },
        )
    )
    assert (
        out["verdict_label"] == W.WORD_QUERY
        and out["not_proven_reason"] == V.UNVERIFIED_CLAUSE_WHY
    )


@pytest.mark.parametrize("quote", ["340 psig (By Contractor)", "plain steel value"])
@pytest.mark.parametrize("checks", [None, {"paper": False, "clause": False}, dict(OK)])
def test_a_proven_fail_with_ai_met_is_never_touched(quote, checks):
    out = exit_of(
        met(
            verdict="Fail",
            decided_by="decided by code",
            paper_quote=quote,
            quotes_checked=checks,
            second_opinion={"agree": False},
        )
    )
    assert (out["verdict_label"], out["verdict_class"]) == ("Fail", W.CLASS_PROVEN)


def test_the_only_change_the_guard_can_make_is_met_to_query():
    """Every verdict x ai_verdict x (deferring quote, quote check, second opinion): compare the exit with the same line
    given plain verified quotes and no disagreement. The guard may only turn 'AI thinks: met' into Query."""
    for verdict in ("Pass", "Fail", "Query"):
        for ai in ("Pass", "Fail", "Query", None):
            for quote in ("Value TBA", "carbon steel"):
                for checks in (
                    None,
                    {"paper": False, "clause": True},
                    {"paper": True, "clause": False},
                    dict(OK),
                ):
                    for second in (
                        None,
                        {"agree": False},
                        {"agree": None},
                        {"agree": True},
                    ):
                        line = met(
                            verdict=verdict,
                            ai_verdict=ai,
                            paper_quote=quote,
                            quotes_checked=checks,
                            second_opinion=second,
                        )
                        base = {
                            **line,
                            "paper_quote": "carbon steel",
                            "quotes_checked": dict(OK),
                            "second_opinion": None,
                        }
                        got, ref = W.classify(line), W.classify(base)
                        if got["verdict_label"] != ref["verdict_label"]:
                            assert (ref["verdict_label"], got["verdict_label"]) == (
                                W.THINKS_MET,
                                W.WORD_QUERY,
                            ), (verdict, ai, quote, checks, second)


def test_a_guarded_line_is_on_the_query_side_of_the_workbook_with_its_new_reason(
    tmp_path,
):
    import openpyxl

    from app import agent_review_crs as C

    ok = {"source": "rule", "rule_label": {"tier": "AI approved"}}

    def mk(iid, **kw):
        base = {
            "item_id": iid,
            "source": "rule",
            "standard": "STD-1",
            "clause": "4.1",
            "verdict": "Query",
            "decided_by": "engineer",
            "ai_verdict": "Pass",
            "why": "no second opinion",
            "paper_page": 2,
            "paper_quote": "Nameplate: steel",
            "clause_quote": "Nameplates shall be steel and fixed",
            "quotes_checked": dict(OK),
            "model": "m",
            "field_roles": ["nameplate_material"],
        }
        return W.final_cap({**base, **kw}, ok)

    held, moved = mk("R-4"), mk("R-9", paper_quote="Value TBA")
    assert (
        held["verdict_label"] == W.THINKS_MET and moved["verdict_label"] == W.WORD_QUERY
    )
    meta = {
        "paper": "P",
        "run_id": "r",
        "date": "2026-11-12",
        "lead_models": [],
        "second_models": [],
    }
    path = C.write_internal([held, moved], tmp_path / "i.xlsx", meta)
    wb = openpyxl.load_workbook(path)

    def ids(title):
        return [
            r[0]
            for r in wb[title].iter_rows(values_only=True)
            if r[0] in ("R-4", "R-9")
        ]

    assert ids(C.HELD_PASS_SHEET) == ["R-4"] and ids("CRS") == ["R-9"]
    text = "\n".join(
        str(c) for r in wb["CRS"].iter_rows(values_only=True) for c in r if c
    )
    assert V.DEFERRED_WHY in text
    counts = C.run_counts([held, moved])
    assert counts["held_ai_pass"] == 1 and counts["query"] == 2
