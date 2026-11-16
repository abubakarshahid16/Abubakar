"""Order 14 (the lead's decision, 16 Nov 2026), lane A: a second opinion whose reply was cut off by its token limit is asked ONCE
more, with twice the limit, for that call only. Answered then, the line is decided on that answer; cut again, it stays cut and counts
as a disagreement (a Query). Every other second opinion is asked once, at the normal limit. An invented model and paper; no network."""

from __future__ import annotations

import json

import pytest
import tests.agent_review_support as s
from app import agent_review_jobs
from app import agent_review_two_reader as two_reader
from app.agent_review_decide import SECOND_RETRY_MAX_TOKENS
from app.agent_review_request import SECOND_MAX_TOKENS
from tests.test_agent_review_job import (  # noqa: F401 - fixture
    lines_of,
    run_job,
    start,
    world,
)


class CutSecond(s.FakeModel):
    """Cuts the first `cuts` second-opinion replies (stop_reason max_tokens, half a JSON text); records each one's max_tokens.
    `then`: how the NEXT second-opinion reply fails instead of answering ("no_json", "error", "refusal"), or None."""

    def __init__(self, cuts=1, then=None, **kw):
        super().__init__(**kw)
        self.cuts, self.then, self.second_limits = cuts, then, []

    def __call__(self, url, *, headers, body, timeout):
        if "independent senior engineer" in json.dumps(body.get("system")):
            with self._lock:
                self.second_limits.append(body.get("max_tokens"))
                cut = len(self.second_limits) <= self.cuts
            if not cut and self.then and len(self.second_limits) == self.cuts + 1:
                self.kinds.append("second")
                if self.then == "error":
                    raise OSError("the line dropped")
                usage = {"input_tokens": 3000, "output_tokens": 10,
                         "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}  # fmt: skip
                reply = self._reply(self.second_name, usage, "I cannot judge this.")
                if self.then == "refusal":
                    reply["stop_reason"] = "refusal"
                return reply
            if cut:
                self.kinds.append("second")
                usage = {"input_tokens": 3000, "output_tokens": body.get("max_tokens") or 0,
                         "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}  # fmt: skip
                reply = self._reply(self.second_name, usage, '{"agree": tr')
                reply["stop_reason"] = "max_tokens"
                return reply
        return super().__call__(url, headers=headers, body=body, timeout=timeout)


def _run(fake, monkeypatch):
    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (fake, s.ENV))
    run_id, job_id = start()
    run_job(job_id)
    return {k: (v, json.loads(v["line_json"])) for k, v in lines_of(run_id).items()}


def test_a_cut_reply_is_asked_once_more_with_twice_the_limit_and_its_answer_counts(
    world, monkeypatch
):  # noqa: F811
    fake = CutSecond(cuts=1)
    lines = _run(fake, monkeypatch)
    assert (
        fake.second_limits[:2]
        == [SECOND_MAX_TOKENS, SECOND_RETRY_MAX_TOKENS]
        == [SECOND_MAX_TOKENS, 2 * SECOND_MAX_TOKENS]
    )
    assert all(
        n == SECOND_MAX_TOKENS for n in fake.second_limits[2:]
    )  # every other call: the normal limit, no retry
    retried = [
        j for _r, j in lines.values() if (j.get("second_opinion") or {}).get("retried")
    ]
    assert (
        len(retried) == 1 and retried[0]["second_opinion"]["agree"] is True
    )  # the retry's answer is the line's


def test_cut_twice_it_stays_cut_and_is_a_query(world, monkeypatch):  # noqa: F811
    fake = CutSecond(cuts=2)
    lines = _run(fake, monkeypatch)
    assert fake.second_limits[:2] == [SECOND_MAX_TOKENS, SECOND_RETRY_MAX_TOKENS]
    cut = [
        (row, j)
        for row, j in lines.values()
        if (j.get("second_opinion") or {}).get("retried")
    ]
    assert len(cut) == 1
    row, j = cut[0]
    assert j["second_opinion"]["agree"] is None and row["word"] != "AI thinks: met"


@pytest.mark.parametrize("then", ["no_json", "error", "refusal"])
def test_a_retry_that_fails_another_way_leaves_the_line_a_disagreement(
    world, monkeypatch, then
):  # noqa: F811
    """R97 M1: the first reply cut, the retry with no JSON, a transport error or a refusal: never "AI thinks: met"."""
    fake = CutSecond(cuts=1, then=then)
    lines = _run(fake, monkeypatch)
    assert fake.second_limits[:2] == [SECOND_MAX_TOKENS, SECOND_RETRY_MAX_TOKENS]
    retried = [
        (row, j)
        for row, j in lines.values()
        if (j.get("second_opinion") or {}).get("retried")
    ]
    assert len(retried) == 1
    row, j = retried[0]
    assert j["second_opinion"]["agree"] is None and two_reader.second_cut_off(j)
    assert row["word"] == "Query" and row["verdict_class"] == "Query for the engineer"
