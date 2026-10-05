"""Mutations of the answer text left after claims are removed: hollow leftovers
(a lead-in with nothing after it, bare citation markers, filler narration) and
the unscoped refusal wording. Ids M2030-M2049.
Target: backend/tests/test_answer_hollow_leftovers.py.
"""

from __future__ import annotations

from ._base import APP, Mutation

_ANSWER = APP / "answer.py"
_T = "tests/test_answer_hollow_leftovers.py"


def _m(num: int, description: str, anchor: str, replacement: str, keyword: str) -> Mutation:
    return Mutation(id=f"M{num}", phase=num, description=description, path=_ANSWER,
                    anchor=anchor, replacement=replacement, target=_T,
                    keyword=keyword, tags=("render",))


MUTATIONS: tuple[Mutation, ...] = (
    _m(2030, "a sentence of only citation markers is kept again",
       "            if _hollow_markers(segment):\n", "            if False:\n",
       "only_citation_numbers"),
    _m(2031, "filler narration ('Let me confirm directly.') is kept again",
       "                if _is_filler_narration(segment):\n", "                if False:\n",
       "narration_that_promises"),
    _m(2032, "a lead-in with nothing after it is kept again",
       "    if final:\n        # From the bottom up", "    if False:\n        # From the bottom up",
       "dangling or e_g or bare_marker"),
    _m(2033, "a lead-in is dropped even when its bullets survive",
       "            content_gone = entry[\"lost_tail\"] or nxt is None or not nxt[\"segments\"] or nxt[\"drop\"]\n",
       "            content_gone = True\n",
       "surviving_bullets"),
    _m(2034, "a dropped verified point is still counted in 'N of M'",
       "        if seg[1] == \"verified\":\n            total -= 1\n            verified -= 1\n",
       "        if seg[1] == \"verified\":\n            pass\n",
       "bare_marker"),
    _m(2035, "the unscoped refusal goes back to 'none of the indexed documents'",
       "if document_id else _nothing_matched(len(allowed_document_ids)))",
       "if True else _nothing_matched(len(allowed_document_ids)))",
       "unscoped_refusal"),
    _m(2036, "the streaming call (final=False) drops a lone lead-in sentence",
       "    if final:\n        # From the bottom up", "    if True:\n        # From the bottom up",
       "streaming_call_keeps"),
    _m(2037, "'Let me know ...' (an offer) is treated as narration",
       'r"(?:check|confirm|verify|', 'r"(?:know|check|confirm|verify|',
       "let_me_know"),
    _m(2038, "a quote mark is ignored when deciding that a sentence ends in a colon",
       "_MARKERS.sub(\"\", plain).rstrip()", "_MARKERS.sub(\"\", plain).rstrip(' \"')",
       "quoted_text_with_a_colon"),
)
