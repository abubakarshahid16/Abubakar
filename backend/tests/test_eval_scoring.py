"""The eval harness must not count a length-limit refusal as a refusal.

A generation that exhausts its budget inside its only citation gets the marker
stripped, is left unsupported, and is refused. That is correct - but the CAUSE
is the token cap, not the corpus, and folding the two together corrupts the
metric in both directions:

  * on an UNANSWERABLE question it scores a correct refusal for the wrong
    reason, so refusal accuracy would IMPROVE the more often generation ran out
    of room. A truncation bug would make the system look better.
  * on an ANSWERABLE question it is recorded as a false refusal, blaming
    retrieval for something that happened after retrieval succeeded.

`length_limited` is currently 0 on the real eval, which is expected with a cap
of 250 against a worst observed case of 108 tokens. These tests exist because a
category that has never been seen to fire is indistinguishable from one that
cannot.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "eval"))

from run_eval import score_one, summarise  # noqa: E402


def _q(qid="Q1", answerable=True):
    return {"id": qid, "question": "what is the warranty period",
            "answerable": answerable, "expected_pages": None,
            "expected_clauses": None, "required_tokens": None}


def _refusal(truncated: bool):
    return {"answer_type": "insufficient_evidence", "seconds": 1.0,
            "truncated": truncated,
            "reason": ("the generated answer was cut off at its length limit "
                       "before it cited a source") if truncated else
                      "the model reported the sources do not contain the answer",
            "passage": None, "answer_passages": []}


# ------------------------------------------------ the inflation this prevents

def test_a_length_limit_refusal_is_not_counted_as_a_correct_refusal():
    """THE metric-corrupting case. An unanswerable question refused because the
    generator ran out of room did not demonstrate anything about the corpus."""
    row = score_one(_q(answerable=False), _refusal(truncated=True))
    assert row["length_limited"] is True
    assert row["refusal_correct"] is None, (
        "a length-limit refusal was scored as a refusal about the documents - "
        "refusal accuracy can now be inflated by a truncation bug")


def test_a_genuine_evidence_refusal_is_still_counted():
    """The other half. Narrowing the category must not empty it."""
    row = score_one(_q(answerable=False), _refusal(truncated=False))
    assert row["length_limited"] is False
    assert row["refusal_correct"] is True


def test_a_length_limit_refusal_is_not_counted_as_a_false_refusal():
    """On an ANSWERABLE question it must not be blamed on retrieval, which
    succeeded - the failure happened after it."""
    row = score_one(_q(answerable=True), _refusal(truncated=True))
    assert row["length_limited"] is True
    assert row["false_refusal"] is False, (
        "a length-limit refusal was recorded as a false refusal, blaming "
        "retrieval for a generation-stage failure")


def test_a_genuine_false_refusal_is_still_counted():
    row = score_one(_q(answerable=True), _refusal(truncated=False))
    assert row["false_refusal"] is True


# ------------------------------------------------------------- aggregation

def test_the_summary_reports_length_limited_separately_and_excludes_it():
    rows = [
        score_one(_q("Q1", answerable=False), _refusal(truncated=False)),
        score_one(_q("Q2", answerable=False), _refusal(truncated=True)),
        score_one(_q("Q3", answerable=True), _refusal(truncated=True)),
    ]
    s = summarise(rows)
    assert s["length_limited"] == 2
    # Q2 is excluded from refusal accuracy, so it is 1/1 and not 2/2.
    assert s["refusal"] == (1, 1), (
        f"refusal accuracy is {s['refusal']} - a length-limited row was "
        "folded into it")
    # Q3 is excluded from false refusals.
    assert s["false_refusals"][0] == 0


def test_a_scored_run_with_no_truncation_is_unaffected():
    """The change must be invisible when nothing was truncated, which is the
    normal case and what the current eval reports."""
    rows = [
        score_one(_q("Q1", answerable=False), _refusal(truncated=False)),
        score_one(_q("Q2", answerable=True), _refusal(truncated=False)),
    ]
    s = summarise(rows)
    assert s["length_limited"] == 0
    assert s["refusal"] == (1, 1)
    assert s["false_refusals"][0] == 1
