"""#456 (C-H5): an answer-judge reply the token cap cut off is named as cut off.

WHAT WAS WRONG. `answerability.judge` never checked `Response.truncated`. A
reply ended by `num_predict` was reported as "output rejected: not valid JSON"
- a model fault - when the fix is a larger cap; and a cut reply whose
arrived part happened to parse could be accepted.

Calls `judge` directly with a scripted provider, so no corpus or model is
needed (the structural verdict it receives is built by hand).
"""
from __future__ import annotations

from app import answerability
from app.reasoning_provider import Response

PASSAGE = {"chunk_id": "c1", "document_id": "d1", "page_start": 4, "page_end": 4,
           "section": "5.2", "text": "Blast cleaning shall give a profile of 50 to 75 micrometres."}
STRUCTURAL = {"verdict": answerability.SUPPORTED, "reason": "stated", "evidence": []}


class Scripted:
    def __init__(self, text: str, finish: str):
        self.text, self.finish = text, finish

    def reason(self, packet):
        return Response(text=self.text, provider="ollama", model_tag="fake", digest="d",
                        finish_reason=self.finish, prompt_sha256=packet.sha256)


def _judge(text: str, finish: str) -> dict:
    return answerability.judge("what profile is required?", {"passage": PASSAGE},
                               dict(STRUCTURAL), Scripted(text, finish))


def test_a_cut_off_reply_is_named_and_never_accepted_even_when_it_parses():
    whole = '{"answers": true, "passage": 1, "quote": "a profile of 50 to 75 micrometres"}'
    assert _judge(whole, "stop")["judge"]["accepted"] is True      # the control
    cut = _judge(whole, "length")
    assert cut["judge"] == {"accepted": False, "why": "output cut off at the token limit"}
    assert cut["verdict"] == answerability.SUPPORTED               # the structural verdict stands


def test_a_half_reply_says_cut_off_not_malformed():
    out = _judge('{"answers": true, "passa', "length")
    assert out["judge"]["why"] == "output cut off at the token limit"
    # and a complete reply that is simply bad is still called malformed
    assert _judge("I think so.", "stop")["judge"]["why"].startswith("output rejected")
