"""Mutations of plan step 4 (which clause applies): backend/app/condition_choice.py
and its use in backend/app/answer.py and backend/app/chat.py.
Target: backend/tests/test_condition_choice.py.
"""

from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_T = "tests/test_condition_choice.py"
_CC = APP / "condition_choice.py"
_A = APP / "answer.py"
_CHAT = FRONTEND_SRC / "components" / "chat"
_V = "src/components/chat/conditionChoice.test.tsx"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1407", phase=1407,
             description="the clause a named condition chose is not quoted: the "
                         "top-ranked clause for another size answers anyway",
             path=_A,
             anchor='        if choice is not None and choice["mode"] == "matched":\n'
                    "            # the clause that ranked first stays visible, as supporting",
             replacement="        if False:\n"
                         "            # the clause that ranked first stays visible, as supporting",
             target=_T, keyword="quotes_the_clause_the_condition_chose", tags=("honesty",)),
    Mutation(id="M1408", phase=1408,
             description="an options answer quotes only the top clause; the rival "
                         "conditions are not part of the answer",
             path=_A,
             anchor='            answers += [_passage_payload(h, question) for h in choice.pop("hits")[1:]]',
             replacement='            choice.pop("hits")',
             target=_T, keyword="unsized_question_shows_both_clauses", tags=("honesty",)),
    Mutation(id="M1409", phase=1409,
             description="a bare value in a passage ('shall be 5 mm') is read as a condition",
             path=_CC,
             anchor="            elif question or (kind == \"size\" and _NOMINAL_AFTER.match(text[m.end():])",
             replacement="            elif True or (kind == \"size\" and _NOMINAL_AFTER.match(text[m.end():])",
             target=_T, keyword="bare_value_in_a_passage", tags=("honesty",)),
    Mutation(id="M1410", phase=1410,
             description="'larger than 2 inch' includes 2 inch",
             path=_CC,
             anchor="                add(m, low=v, low_open=True)",
             replacement="                add(m, low=v)",
             target=_T, keyword="falls_inside_or_outside", tags=("correctness",)),
    Mutation(id="M1411", phase=1411,
             description="a rival stating the same values (a duplicate clause) is shown as an option",
             path=_A,
             anchor="        if not values or not lead_values or values == lead_values:",
             replacement="        if not values or not lead_values:",
             target=_T, keyword="same_values_is_a_duplicate", tags=("correctness",)),
    Mutation(id="M1412", phase=1412,
             description="a rival far below the top competes as an option",
             path=_A,
             anchor="        if not _close_enough(hit, lead):\n            continue",
             replacement="        if False:\n            continue",
             target=_T, keyword="far_below_the_top", tags=("correctness",)),
    Mutation(id="M1413", phase=1413,
             description="a reopened conversation loses which clause applied",
             path=APP / "chat.py",
             anchor='    "condition_choice",\n',
             replacement="",
             target=_T, keyword="kept_when_a_conversation_is_reopened", tags=("reliability",)),
    Mutation(id="M1414", phase=1414,
             description="a rival the lexical gate rejects competes as an option",
             path=_A,
             anchor="        if not lexical.assess(question, _searchable_text(hit), document_id,\n"
                    "                              allowed_document_ids=allowed_document_ids)[\"ok\"]:\n"
                    "            continue",
             replacement="        pass",
             target=_T, keyword="lexical_gate_rejects", tags=("honesty",)),
    Mutation(id="M1415", phase=1415,
             description="Fahrenheit is compared as if it were Celsius",
             path=_CC,
             anchor="            return (value - 32) * 5 / 9",
             replacement="            return value",
             target=_T, keyword="fahrenheit", tags=("correctness",)),
    Mutation(id="M1416", phase=1416, runner="vitest",
             description="the options warning is never rendered on the answer card",
             path=_CHAT / "AnswerCardView.tsx",
             anchor="      <ConditionNotice choice={view.condition_choice} />\n",
             replacement="",
             target=_V, keyword="asks which condition applies", tags=("honesty", "ui")),
    Mutation(id="M1417", phase=1417, runner="vitest",
             description="a reopened conversation loses the condition choice",
             path=_CHAT / "AnswerCardContent.tsx",
             anchor="    condition_choice: p.condition_choice ?? null,\n",
             replacement="    condition_choice: null,\n",
             target=_V, keyword="reopened", tags=("honesty", "ui")),
    Mutation(id="M1418", phase=1418, runner="vitest",
             description="the options list drops each clause's condition",
             path=_CHAT / "AnswerVerdict.tsx",
             anchor='            <span className="font-medium">{o.conditions.join(", ")}</span>',
             replacement='            <span className="font-medium">{o.section}</span>',
             target=_V, keyword="asks which condition applies", tags=("honesty", "ui")),
)
