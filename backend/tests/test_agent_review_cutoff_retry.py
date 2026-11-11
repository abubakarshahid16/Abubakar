"""An answer cut off at its token limit is asked ONCE more with a larger limit (invented paper, rule book and model).

The fake lane cuts chosen lead calls off (stop_reason max_tokens, half a JSON text) and records each call's limit."""

from __future__ import annotations

import json

from app import agent_review_request as request_mod
from app import agent_review_run as run_mod
from tests import agent_review_support as s
from tests.test_agent_review_guards import run_review, w  # noqa: F401
from tests.test_agent_review_job import lines_of


class CutLane(s.FakeModel):
    """Lead call n (0-based) is cut off when n is in `cut`; `limits` holds the max_tokens of every lead call."""

    def __init__(self, cut, **kw):
        super().__init__(**kw)
        self.cut, self.limits = set(cut), []

    def __call__(self, url, *, headers, body, timeout):
        system = json.dumps(body.get("system"))
        lead = "CONTEXT CHECK" not in system and "independent senior engineer" not in system
        if not lead:
            return super().__call__(url, headers=headers, body=body, timeout=timeout)
        n = len(self.lead_asked)
        self.limits.append(body["max_tokens"])
        if n in self.cut:
            self.lead_asked.append(self._ids(body))
            self.kinds.append("lead")
            usage = {"input_tokens": 3000, "output_tokens": body["max_tokens"]}
            reply = self._reply(self.LEAD, usage, '{"answers": [{"item_id": "R-co')
            reply["stop_reason"] = "max_tokens"
            return reply
        return super().__call__(url, headers=headers, body=body, timeout=timeout)

    @staticmethod
    def _ids(body):
        last = body["messages"][0]["content"][-1]["text"]
        return [q["item_id"] for q in json.loads(last.split("\n\n")[0])["items"]]


def use(w, monkeypatch, cut, ids=("R-coat",)):
    from app import agent_review_jobs

    lane = CutLane(cut)
    w["fake"] = lane
    w["doc"], w["cache"] = s.item_doc(ids)
    monkeypatch.setattr(agent_review_jobs, "lane", lambda: (lane, s.ENV))
    return lane


def test_cut_off_then_complete_the_line_is_decided_from_the_second_answer_only(w, monkeypatch):
    lane = use(w, monkeypatch, {0})
    line = lines_of(run_review())["R-coat"]
    assert line["word"] == "Pass"
    assert len(lane.limits) == 2
    assert lane.limits[1] == min(request_mod.RETRY_MAX_TOKENS, 2 * lane.limits[0]) > lane.limits[0]


def test_cut_off_twice_is_not_reviewed_and_says_twice_and_no_verdict_is_guessed(w, monkeypatch):
    lane = use(w, monkeypatch, {0, 1})
    line = lines_of(run_review())["R-coat"]
    assert line["word"] == "Not reviewed" and line["verdict_class"] == "Not reviewed"
    assert "cut off twice" in line["reason"]
    assert len(lane.limits) == 2  # asked once more, not a third time
    assert "second" not in lane.kinds and "context" not in lane.kinds


def test_a_complete_first_answer_makes_exactly_one_lead_call(w, monkeypatch):
    lane = use(w, monkeypatch, set())
    assert lines_of(run_review())["R-coat"]["word"] == "Pass"
    assert len(lane.limits) == 1 and lane.kinds.count("lead") == 1


def test_a_batch_cut_off_is_still_split_first_then_a_half_gets_the_larger_retry(w, monkeypatch):
    lane = use(w, monkeypatch, {0, 1}, ids=("R-coat", "R-frame", "R-mark", "R-colour"))
    lines = lines_of(run_review())
    first, half1, retry = lane.limits[0], lane.limits[1], lane.limits[2]
    assert len(lane.lead_asked[0]) == 4 and len(lane.lead_asked[1]) == 2 == len(lane.lead_asked[2])
    assert lane.lead_asked[1] == lane.lead_asked[2]  # the same half, asked again with more room
    assert retry == 2 * half1 and half1 < first
    assert lines["R-coat"]["word"] == "Pass" and lines["R-mark"]["word"] == "Fail"


def test_the_retry_reserves_its_larger_worst_case_and_a_low_cap_refuses_it(w, monkeypatch):
    # a per-item budget above the 4,096 floor the spend module reserves for models that think, so the worst case can differ
    monkeypatch.setattr(run_mod, "TOKENS_PER_ITEM", 3000)
    lane = use(w, monkeypatch, {0})
    seen = []
    real = run_mod.Runner.call

    def call(self, model, parts, max_tokens):
        seen.append((model == self.model, max_tokens, request_mod.app_worst_usd(model, parts, max_tokens)))
        return real(self, model, parts, max_tokens)

    monkeypatch.setattr(run_mod.Runner, "call", call)
    run_review()
    leads = [x for x in seen if x[0] and x[1] > 400 and x[1] != request_mod.FINAL_MAX_TOKENS]
    assert len(leads) == 2 and leads[1][2] > leads[0][2]  # the larger limit costs more in the worst case
    # now a cap that admits the first call but not the retry
    cap = leads[0][2] + leads[1][2] - 0.0001
    monkeypatch.setattr(run_mod, "app_cap", lambda: cap)
    lane2 = use(w, monkeypatch, {0})
    run_id = run_review()
    line = lines_of(run_id)["R-coat"]
    assert len(lane2.limits) == 1  # the retry was never sent
    assert line["word"] == "Not reviewed"
