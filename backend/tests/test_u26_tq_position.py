# ruff: noqa: F811 - pytest fixtures imported from the ready-query tests are used as parameters
"""COMPANY's usual cost / schedule position in a system draft: a set sentence added by code, never by the model, and marked for the
engineer (lead-4's decision, 27 Nov 2026). Invented values; no model."""

from __future__ import annotations

from app import technical_queries as tq
from app import technical_query_auto as auto
from app import technical_query_jobs as J
from app import technical_query_position as P
from tests.test_tq_g_feature_off import (
    storage,  # noqa: F401 - the autouse database fixture
)
from tests.test_u16_tq_ready import _run, query  # noqa: F401 - the ready-query fixture


def test_the_set_sentence_closes_a_plain_technical_reply():
    out = P.with_position(
        "1. Class 300 applies [S1].", "1. Which flange class applies?\n2. Which gasket?"
    )
    assert out == f"1. Class 300 applies [S1].\n\n{P.POSITION_LINE}"
    assert P.position_mark(out, "Which flange class applies?", True) == P.POSITION_MARK
    assert P.with_position(out, "Which flange class applies?") == out  # never twice


def test_nothing_is_added_when_the_request_raises_cost_or_schedule_and_the_page_says_it_is_the_engineers_call():
    for ask in (
        "Please confirm the cost impact of the revised routing.",
        "CONTRACTOR requests an extension of time for item 2.",
        "Will a variation order be issued for the added valves?",
        "CONTRACTOR seeks compensation for the re-work.",
    ):
        assert P.raises_cost(ask), ask
        assert (
            P.with_position("Class 300 applies [S1].", ask) == "Class 300 applies [S1]."
        )
        assert P.position_mark("Class 300 applies [S1].", ask, True) == P.RAISED_MARK


RAISES = (
    # builder H's second gate of #1963: these got the sentence before the rule was flipped
    "Contractor claims a 2-week extension for the pipe rack.",
    "This change will increase the contract price.",
    "We cannot meet the milestone date without this information.",
    "Additional manhours are required for this scope.",
    "The rework is at COMPANY's expense.",
    "This will push the mechanical completion date.",
    # builder H's first gate, and earlier cases
    "Please confirm who bears the cost of the extra valves.",
    "The late drawings delay our work by 3 weeks; please confirm.",
    "We request schedule relief for the tie-in.",
    "Who will pay for the re-test?",
    "The supply is delayed; please advise.",
    "The fabrication will slip unless the datasheet is approved.",
    "The work is now behind schedule.",
    "Please confirm the extra time needed for the hydrotest.",
    "The delivery is 2 weeks late.",
)
TECHNICAL = (
    "What is the time delay setting of the trip relay?",
    "Is pipe schedule 80 acceptable for this line?",
    "Per Schedule B, which standard applies?",
    "Is the scheduled maintenance interval stated?",
    "Which revision of the datasheet is the latest?",
    "What is the design pressure of the vessel?",
    "Is a slip-on flange acceptable?",
    "What flow rate is required?",
    "Is a push button required at the panel?",
    "Which seismic acceleration applies?",
    "Is the drain behind the column acceptable?",
)


def test_the_flipped_rule_any_money_or_time_word_means_no_sentence():
    for ask in RAISES:
        assert P.raises_cost(ask), ask
        assert (
            P.with_position("Class 300 applies [S1].", ask) == "Class 300 applies [S1]."
        ), ask
        assert P.position_mark("Class 300 applies [S1].", ask, True) == P.RAISED_MARK


def test_technical_words_that_only_look_like_money_or_time_still_get_the_sentence():
    for ask in TECHNICAL:
        assert not P.raises_cost(ask), ask
        assert P.with_position("Class 300 applies [S1].", ask).endswith(
            P.POSITION_LINE
        ), ask


def test_the_set_sentence_is_independent_wording():
    # invented to stand apart from any approved reply (the gate found the first wording followed one too closely)
    assert (
        P.POSITION_LINE
        == "On the information given, COMPANY finds no basis for a change to cost or schedule from this item."
    )
    for older in (
        "Based on the information provided",
        "does not see grounds",
        "to support a schedule or cost impact",
    ):
        assert older not in P.POSITION_LINE
    # a draft that already speaks of cost and schedule gets nothing more
    said = "Class 300 applies [S1]. There is no change to cost or schedule."
    assert P.with_position(said, "Which class applies?") == said


def test_nothing_is_added_when_the_draft_already_speaks_of_an_impact_and_a_typed_reply_gets_no_mark():
    deferring = "Class 300 applies [S1]. COMPANY to confirm any schedule impact."
    assert P.with_position(deferring, "Which class applies?") == deferring
    assert P.position_mark(deferring, "Which class applies?", True) is None
    assert (
        P.position_mark(f"Typed.\n\n{P.POSITION_LINE}", "Which class applies?", False)
        is None
    )
    # technical words that only look like money or time are not a cost request
    assert not P.raises_cost(
        "What is the time delay of the trip relay? Is the scheduled maintenance interval stated?"
    )


def test_the_system_draft_carries_the_sentence_and_the_page_marks_it(
    query, monkeypatch
):
    item, scope, _asked = query
    monkeypatch.setattr("app.answer.answer", lambda q, **k: {
        "answer_type": "generated", "answer": "1. Class 300 applies [S1].", "cited": [1], "model": "synthetic-local",
        "passages": [{"document_id": "d1", "page_start": 3, "page_end": 3, "text": "Invented clause 7.1: the flange rating shall be class 300."}]})  # fmt: skip
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    got = tq.get(item["id"], "u1", False, False)
    draft = got["drafts"][-1]
    assert draft["answer"].endswith(P.POSITION_LINE)
    assert (
        draft["prompt_version"] == auto.SYSTEM_DRAFT == "system-draft-2"
    )  # unchanged: no backlog redo for this line
    assert P.POSITION_MARK in got["ready"]["marks"]
