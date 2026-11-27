# ruff: noqa: F811 - pytest fixtures imported from the ready-query tests are used as parameters
"""COMPANY's usual cost / schedule sentence: OFFERED to the engineer beside the draft, never put in by code; the money / time word check
is only a hint (lead-4's final design, 27 Nov 2026, after builder H's three gates). Invented values; no model."""

from __future__ import annotations

import inspect

import pytest

from app import technical_queries as tq
from app import technical_query_auto as auto
from app import technical_query_jobs as J
from app import technical_query_position as P
from tests.test_tq_g_feature_off import (
    storage,  # noqa: F401 - the autouse database fixture
)
from tests.test_u16_tq_ready import _run, query  # noqa: F401 - the ready-query fixture

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
# builder H's third gate: money / time requests no word list caught. The sentence is never put in, so they are safe by construction.
H_FRESH = (
    "The contractor seeks a revised quotation for the extra pumps.",
    "This affects our lump sum.",
    "We will need overtime to recover.",
    "Please approve the change in scope for the flare tie-in.",
    "This deviation requires a variation.",
    "Our float is consumed by this redesign.",
    "Will COMPANY fund the redesign?",
    "Liquidated damages may apply if this is not resolved.",
    "The redesign requires an extra week.",
    "Please confirm whether this is extra work.",
    "Can the shutdown window be extended?",
    "Who is responsible for the additional scope?",
    "The vendor quoted a higher figure for the alloy.",
)


def test_code_never_writes_the_sentence_into_a_draft():
    # nothing in the draft pipeline can add it: the old helpers are gone and the pipeline does not name the sentence
    assert not hasattr(P, "with_position") and not hasattr(P, "position_mark")
    pipeline = inspect.getsource(auto)
    assert "POSITION_LINE" not in pipeline and "with_position" not in pipeline


@pytest.mark.parametrize(
    "ask", ["1. What flange rating applies?", *RAISES[:3], *H_FRESH[:3], *TECHNICAL[:2]]
)
def test_a_system_draft_is_the_models_own_text_for_any_request(query, monkeypatch, ask):
    item, scope, _asked = query
    with tq.connect() as conn:
        conn.execute(
            "UPDATE technical_queries SET confirmed_question=? WHERE id=?",
            (ask, item["id"]),
        )
    monkeypatch.setattr("app.answer.answer", lambda q, **k: {
        "answer_type": "generated", "answer": "1. Class 300 applies [S1].", "cited": [1], "model": "synthetic-local",
        "passages": [{"document_id": "d1", "page_start": 3, "page_end": 3, "text": "Invented clause 7.1: the flange rating shall be class 300."}]})  # fmt: skip
    J.enqueue(item["id"], scope.readable_with_attachments, "u1", False, False)
    _run(item["id"])
    got = tq.get(item["id"], "u1", False, False)
    assert got["drafts"][-1]["question"] == ask  # the draft answers this very request
    assert (
        got["drafts"][-1]["answer"] == "1. Class 300 applies [S1]."
    )  # exactly the model's text
    assert P.POSITION_LINE not in got["drafts"][-1]["answer"]
    assert got["ready"]["position"]["line"] == P.POSITION_LINE  # offered beside it


def test_the_hint_shows_for_money_or_time_words_and_not_for_plain_technical_requests():
    for ask in RAISES:
        assert P.offer(ask) == {"line": P.POSITION_LINE, "hint": P.HINT, "reply_speaks": False}, ask
    for ask in TECHNICAL:
        assert P.offer(ask) == {"line": P.POSITION_LINE, "hint": None, "reply_speaks": False}, ask
    # the hint is only a hint: a request it misses is still offered the sentence, and nothing is ever added without the engineer
    for ask in H_FRESH:
        assert P.offer(ask)["line"] == P.POSITION_LINE


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
