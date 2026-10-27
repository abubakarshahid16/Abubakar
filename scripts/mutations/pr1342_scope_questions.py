"""Order 242.2 (PR 1342): a scope reading must be a real sentence, and a Part the
datasheet does not settle is one engineer question."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_242_scope_questions.py"
_Q = APP / "scope_quote.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1342-01",
        phase=1342,
        description="a garbled scope reading holds its Part again",
        path=APP / "ai_applicability.py",
        anchor="    if scope_quote.problems(\n",
        replacement="    if False and scope_quote.problems(\n",
        target=_T,
        keyword="garbled_scope_reading",
        tags=("honesty",),
    ),
    Mutation(
        id="M1342-02",
        phase=1342,
        description="every held requirement becomes its own question",
        path=APP / "ai_applicability.py",
        anchor='            questions.setdefault(key, question)["requirements"] += 1\n',
        replacement='            questions[(key, id(r))] = {**question, "requirements": 1}\n',
        target=_T,
        keyword="one_question_with_its_count",
        tags=("honesty",),
    ),
    Mutation(
        id="M1342-03",
        phase=1342,
        description="a quote that is cut off with an ellipsis still passes",
        path=_Q,
        anchor='    if not quote.endswith(_STOPS) or "..." in quote or "\u2026" in quote:\n',
        replacement="    if False:\n",
        target=_T,
        keyword="fragment_is_not_a_scope_sentence",
        tags=("honesty",),
    ),
    Mutation(
        id="M1342-04",
        phase=1342,
        description="a run of codes passes as a sentence",
        path=_Q,
        anchor="    if _code_share(quote) > MAX_CODE_TOKEN_SHARE:\n",
        replacement="    if False:\n",
        target=_T,
        keyword="fragment_is_not_a_scope_sentence",
        tags=("honesty",),
    ),
    Mutation(
        id="M1342-05",
        phase=1342,
        description="the question line is no longer printed",
        path=APP / "absence.py",
        anchor="    lines += scope_question_lines((split.get(\"division_scope\") or {}).get(\"questions\"))\n",
        replacement="",
        target=_T,
        keyword="one_line_in_the_review_notes",
        tags=("honesty",),
    ),
)
