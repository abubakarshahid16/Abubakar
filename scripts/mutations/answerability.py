"""Mutations of `backend/app/answerability.py` and its wiring - B8."""

from __future__ import annotations

from ._base import APP, Mutation

_A = APP / "answerability.py"
_T = "tests/test_b8_answerability.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M818", phase=71, description="B8: a refused answer is no longer reported insufficient",
             path=_A, anchor='    if result.get("answer_type") == "insufficient_evidence" or not shown:\n',
             replacement='    if False:\n', target=_T, keyword="insufficient_not_answered", tags=("honesty",)),
    Mutation(id="M819", phase=71, description="B8: a compliance judgement is answered instead of routed to an engineer",
             path=_A, anchor="    if _JUDGEMENT.search(question):\n", replacement="    if False:\n",
             target=_T, keyword="routed_to_an_engineer", tags=("honesty",)),
    Mutation(id="M820", phase=71, description="B8: a clause deferring to a standard not held reads as an answer",
             path=_A, anchor="    if _DEFERS.search(sentence) and not _quantities(sentence):\n",
             replacement="    if False:\n",
             target=_T, keyword="defers_to_a_standard"),
    Mutation(id="M821", phase=71, description="B8: search's dropped near-copies are not compared - a conflict vanishes",
             path=_A, anchor="    others += _dropped_copies(result, top, allowed_document_ids)\n", replacement="",
             target=_T, keyword="different_values", tags=("honesty",)),
    Mutation(id="M822", phase=71, description="B8: text found in several documents is reported supported",
             path=_A, anchor='    if result.get("scope_ambiguity") or understood.get("ambiguous_documents"):\n',
             replacement="    if False:\n", target=_T, keyword="several_documents_is_ambiguous"),
    Mutation(id="M823", phase=71, description="B8: the judge accepts a model 'yes' without verifying its quote",
             path=_A, anchor='    if not (1 <= n <= len(passages)) or not quote_verified(out["quote"], passages[n - 1].get("text")):\n',
             replacement="    if not (1 <= n <= len(passages)):\n", target=_T, keyword="invented_quote", tags=("honesty",)),
    Mutation(id="M824", phase=71, description="B8: the judge may turn a refusal into an answer",
             path=_A, anchor='    if current["verdict"] != SUPPORTED or provider is None:\n',
             replacement="    if provider is None:\n", target=_T, keyword="never_turn_a_refusal", tags=("honesty",)),
    Mutation(id="M825", phase=71, description="B8: answers no longer carry a verdict",
             path=APP / "answer.py",
             anchor='    result["answerability"] = answerability.judge(\n        question, result, verdict, answerability.judge_provider())\n',
             replacement="", target=_T, keyword="supported_and_cites or insufficient_not_answered"),
    Mutation(id="M826", phase=71, description="B8: the HTTP response drops the verdict",
             path=APP / "schemas.py",
             anchor='    answerability: Answerability | None = Field(\n        None, description="B8: whether the evidence answers the question, and why")\n',
             replacement="", target=_T, keyword="http_response"),
    Mutation(id="M827", phase=71, description="B8: a clause that states its own value is flagged as a deferral",
             path=_A, anchor="    if _DEFERS.search(sentence) and not _quantities(sentence):\n",
             replacement="    if _DEFERS.search(sentence):\n", target=_T, keyword="stating_its_own_value"),
    Mutation(id="M828", phase=71, description="B8: a standard the question itself names is reported missing",
             path=_A, anchor="                   and re.sub(r\"[^A-Z0-9]\", \"\", ref.upper()) not in asked]\n",
             replacement="                   ]\n", target=_T, keyword="question_names"),
)
