"""F4: the page-context check before a Fail is proven. Invented data; the model is a fake callable; no network."""

from __future__ import annotations

import json

import pytest

from app import agent_review_context as X

LEAD, OTHER = "claude-sonnet-5-5-20261101", "claude-opus-5-5"
RULE = "Nameplates shall be made of stainless steel."
STD_PAGE = f"4 Marking\n{RULE}\nScrews shall be stainless. This page is otherwise empty for the invented standard."
PAPER = {3: "Item data\nNameplate material: aluminium\nCoating thickness: 0.15 mm"}
PAPER_QUOTE = "Nameplate material: aluminium"
FAIL = {"verdict": "Fail", "decided_by": "AI verdict", "why": None}


class Fake:
    """The injected model call. `reply` is the dict ask returns, or an exception to raise."""

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, parts):
        self.calls.append(parts)
        if isinstance(self.reply, BaseException):
            raise self.reply
        return self.reply


def answer(obj, model=OTHER):
    return {"obj": obj, "model": model, "usd": 0.01}


def run(
    ask,
    *,
    decision=FAIL,
    rule_text=RULE,
    std=STD_PAGE,
    stored=None,
    in_scope=True,
    lead=LEAD,
    fatal=(),
    **kw,
):
    return X.check_fail(
        decision,
        rule_text=rule_text,
        paper_quotes=[PAPER_QUOTE],
        paper_pages=PAPER,
        rule_doc="std1",
        rule_page=7,
        clause="4.1",
        std_pages=lambda doc, n: std if n == 7 else None,
        ask=ask,
        lead_model=lead,
        stored=stored,
        in_scope=in_scope,
        fatal=fatal,
        **kw,
    )


def proven(res):
    return res.decision["verdict"] == "Fail" and res.info["context_check"] == X.PROVEN


def held(res, why=None):
    ok = (
        res.decision["verdict"] == "Query"
        and res.decision["context_hold"]
        and res.info["context_check"] != X.PROVEN
    )
    return ok and (why is None or res.decision["why"] == why)


def test_limits_false_keeps_the_fail_proven_and_the_exchange_is_kept():
    ask = Fake(answer({"limits": False, "reason": "no limit"}))
    res = run(ask)
    assert proven(res) and len(ask.calls) == 1
    assert (
        res.info["context_limits"] is False
        and res.exchange["answer"]["limits"] is False
    )
    assert (
        "stainless steel" in res.exchange["request"]
    )  # the request carries the rule and the page


@pytest.mark.parametrize("limits", ["false", 0, 1, "true", None, [], {}, "no"])
def test_limits_must_be_the_boolean_false_or_the_fail_is_held(limits):
    res = run(Fake(answer({"limits": limits})))
    assert held(res)
    assert res.info["context_check"] in (X.NOT_COMPLETED, X.HELD)


def test_a_missing_limits_key_malformed_json_or_a_list_holds_the_fail():
    for obj in ({}, {"reason": "x"}, None, ["limits"], "limits"):
        assert held(run(Fake(answer(obj)))), obj
    assert held(
        run(Fake({"text": "this is not json", "model": OTHER}))
    )  # unparseable text
    assert proven(
        run(Fake({"text": '```json\n{"limits": false}\n```', "model": OTHER}))
    )  # a fenced boolean is read


CONDITION = "Screws shall be stainless."


def met(**over):
    return {
        "limits": True,
        "condition_quote": CONDITION,
        "condition_met": "yes",
        "paper_quote_for_condition": "Nameplate material: aluminium",
        **over,
    }


def test_the_fully_verified_yes_path_proves_the_fail_and_every_other_exit_holds():
    assert proven(run(Fake(answer(met()))))
    assert proven(
        run(Fake(answer(met(condition_met=" YES "))))
    )  # normalised; both quotes are still verified by code
    for bad in (
        met(
            condition_quote="Screws shall be brass and chrome."
        ),  # the condition quote is not on the rule-book page
        met(
            paper_quote_for_condition="Nameplate material: copper"
        ),  # the paper quote is not on the paper
        met(condition_quote="short"),  # under 12 characters
        met(paper_quote_for_condition=""),
        met(condition_met="no"),
        met(condition_met="not_shown"),
        met(condition_met=None),
        met(condition_met="maybe"),
    ):
        res = run(Fake(answer(bad)))
        assert held(res, X.WHY_LIMITS), bad
        assert res.info["context_check"] == X.HELD


def test_an_unverified_quote_never_leaves_the_fail_proven(monkeypatch):
    """F4 unverified quote: if code did not find the quote, the Fail is held, whatever the model said."""
    assert held(
        run(Fake(answer(met(condition_quote="Screws shall be brass and chrome."))))
    )
    monkeypatch.setattr(
        X, "_found", lambda quote, texts: True
    )  # break the verification
    assert proven(
        run(Fake(answer(met(condition_quote="Screws shall be brass and chrome."))))
    )  # the guard is what held it


@pytest.mark.parametrize("exc", [ValueError("bad"), TimeoutError(), RuntimeError("x")])
def test_a_model_error_holds_the_fail(exc):
    ask = Fake(exc)
    res = run(ask)
    assert held(res, X.WHY_NOT_DONE) and res.info["context_check"] == X.NOT_COMPLETED
    assert res.exchange["error"] == type(exc).__name__ and len(ask.calls) == 1


def test_a_fatal_stop_holds_the_fail_and_is_handed_back_to_halt_the_run():
    class Stop(Exception):
        pass

    res = run(Fake(Stop("cap")), fatal=(Stop,))
    assert held(res) and isinstance(res.fatal, Stop)
    assert run(Fake(ValueError("not fatal")), fatal=(Stop,)).fatal is None


@pytest.mark.parametrize(
    "model", [LEAD, "claude-sonnet-5-5-20250101", "", None, "unknown"]
)
def test_a_model_of_the_leads_family_or_an_unnamed_one_cannot_check_it(model):
    assert held(run(Fake(answer({"limits": False}, model=model))))


def test_the_rule_quote_not_on_its_own_page_is_held_without_a_call():
    ask = Fake(answer({"limits": False}))
    res = run(ask, std="A page that does not hold the sentence at all, invented.")
    assert held(res, X.WHY_NOT_DONE) and ask.calls == []
    assert held(run(ask, std=""))  # no page
    assert held(run(ask, rule_text=None))
    assert ask.calls == []


def test_no_call_possible_holds_the_fail_never_proves_it():
    assert held(run(None))  # no model injected
    ask = Fake(answer({"limits": False}))
    assert (
        held(run(ask, in_scope=False)) and ask.calls == []
    )  # a free redecide makes no call and proves nothing


def test_only_a_fail_is_checked():
    ask = Fake(answer({"limits": True}))
    for verdict in ("Pass", "Query"):
        res = run(ask, decision={"verdict": verdict})
        assert res.decision == {"verdict": verdict} and res.info == {}
    assert ask.calls == []


def stored(check, **over):
    fp = X.fingerprint(RULE, [PAPER_QUOTE])
    return {
        "context_check": check,
        "context_hash": fp,
        "context_limits": False,
        "context_condition_met": None,
        **over,
    }


def test_a_stored_proven_check_carries_over_only_for_the_same_quotes():
    ask = Fake(answer({"limits": True}))
    same = run(ask, stored=stored(X.PROVEN), in_scope=False)
    assert proven(same) and ask.calls == []  # carried over, no new call
    for bad in (
        {
            **stored(X.PROVEN),
            "context_hash": X.fingerprint(
                "Another rule sentence entirely.", [PAPER_QUOTE]
            ),
        },
        {**stored(X.PROVEN), "context_hash": None},
        {**stored(X.PROVEN), "context_hash": 12},
        {**stored(X.PROVEN), "context_hash": X.fingerprint(RULE, [PAPER_QUOTE])[:8]},
        {**stored(X.PROVEN), "context_hash": [X.fingerprint(RULE, [PAPER_QUOTE])]},
        stored(X.NOT_COMPLETED),
        stored(None),
    ):
        assert held(run(None, stored=bad)), bad
    changed = run(
        None,
        stored={
            **stored(X.PROVEN),
            "context_hash": X.fingerprint(RULE, ["Nameplate material: copper"]),
        },
    )
    assert held(changed)


def test_a_line_held_before_stays_held_with_no_new_call():
    ask = Fake(answer({"limits": False}))
    res = run(ask, stored=stored(X.HELD, context_limits=True))
    assert held(res, X.WHY_LIMITS) and ask.calls == []


def test_the_neighbour_page_is_sent_only_when_the_quote_is_near_a_page_edge():
    middle = ("filler word " * 60) + RULE + (" filler word" * 60)
    assert X.neighbour_pages(7, middle, RULE) == [7]
    assert X.neighbour_pages(7, RULE + (" tail word" * 80), RULE) == [
        6,
        7,
    ]  # at the top: the previous page
    assert X.neighbour_pages(7, ("head word " * 80) + RULE, RULE) == [
        7,
        8,
    ]  # at the bottom: the next page
    assert X.neighbour_pages(7, "no quote here", RULE) == [
        6,
        7,
        8,
    ]  # quote not found: both neighbours
    assert X.neighbour_pages(1, RULE + (" tail word" * 80), RULE) == [1]
    assert X.neighbour_pages(1, "no quote", RULE) == [1, 2]


def test_the_request_holds_the_rule_both_page_sets_and_no_equipment_word():
    parts = X.build_parts(RULE, "4.1", {7: STD_PAGE}, [PAPER_QUOTE], PAPER)
    claim = json.loads(parts["messages"][0]["content"][0]["text"])
    assert claim["rule_quote"] == RULE and claim["standard_pages"] == {"7": STD_PAGE}
    assert claim["paper_pages"] == {"3": PAPER[3]} and claim[
        "paper_quotes_the_fail_rests_on"
    ] == [PAPER_QUOTE]
    assert "limits" in X.ANSWER_SHAPE and "true or false" in X.ANSWER_SHAPE


def test_the_fingerprint_changes_with_either_quote_and_ignores_spacing_and_order():
    a = X.fingerprint(RULE, ["b one", "a two"])
    assert a == X.fingerprint("  " + RULE.upper() + " ", ["A  TWO", "B one"])
    assert a != X.fingerprint(RULE + "!", ["b one", "a two"]) and a != X.fingerprint(
        RULE, ["b one"]
    )
    assert len(a) == 16
