"""Mutations for the visible Claude-to-Local downgrade (2026-10-01, M1870-M1879).
Files: backend/app/chat.py, chat_model.py, chat_claude_first.py and the answer
card. Targets: backend/tests/test_visible_provider_downgrade.py and the
AnswerCard vitest file.
"""

from __future__ import annotations

from ._base import APP, FRONTEND_SRC, Mutation

_T = "tests/test_visible_provider_downgrade.py"
_TAG = ("provider_downgrade",)

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1870", phase=1870,
             description="chat.ask never records that the local model answered a Claude request",
             path=APP / "chat.py",
             anchor="    result.update(chat_model.downgrade_fields(model, result, "
                    "fallback_why[0] if fallback_why else None))\n",
             replacement="",
             target=_T, keyword="named or no_notice or notice", tags=_TAG),
    Mutation(id="M1871", phase=1871,
             description="the notice no longer needs the reader to have chosen Claude",
             path=APP / "chat_model.py",
             anchor='    if preference != CLAUDE or result.get("provider") != rp.OLLAMA:\n        return {}',
             replacement='    if result.get("provider") != rp.OLLAMA:\n        return {}',
             target=_T, keyword="notice or only_a_local_answer", tags=_TAG),
    Mutation(id="M1872", phase=1872,
             description="the notice no longer needs the local model to have answered",
             path=APP / "chat_model.py",
             anchor='    if preference != CLAUDE or result.get("provider") != rp.OLLAMA:\n        return {}',
             replacement='    if preference != CLAUDE:\n        return {}',
             target=_T, keyword="notice or only_a_local_answer", tags=_TAG),
    Mutation(id="M1873", phase=1873,
             description="a spending-cap refusal is reported as a generic failed call",
             path=APP / "chat_model.py",
             anchor='        return "the Claude spending cap would be exceeded"\n    return "the Claude call failed"',
             replacement='        return "the Claude call failed"\n    return "the Claude call failed"',
             target=_T, keyword="cap or fallback or cause", tags=_TAG),
    Mutation(id="M1874", phase=1874,
             description="an unknown cause is written as a made-up one",
             path=APP / "chat_model.py",
             anchor='    lead = f"Claude was not available ({why})" if why else "Claude was not used"',
             replacement='    lead = f"Claude was not available ({why or \'a temporary problem\'})"',
             target=_T, keyword="unknown_cause", tags=_TAG),
    Mutation(id="M1875", phase=1875,
             description="the notice is not stored with the answer",
             path=APP / "chat.py",
             anchor='    # Audit 101: the reader asked for Claude and the local model answered.\n'
                    '    "requested_provider", "provider_note",\n',
             replacement='',
             target=_T, keyword="reopening or persisted or lifted", tags=_TAG),
    Mutation(id="M1876", phase=1876,
             description="the notice is stored but not lifted when a conversation is reopened",
             path=APP / "chat.py",
             anchor='"seconds", "cost_usd",\n           "requested_provider", "provider_note")',
             replacement='"seconds", "cost_usd")',
             target=_T, keyword="reopening or persisted or lifted", tags=_TAG),
    Mutation(id="M1877", phase=1877,
             description="a failed first Claude call's own cause is ignored in favour of the settings",
             path=APP / "chat.py",
             anchor="fallback_why[0] if fallback_why else None))",
             replacement="None))",
             target=_T, keyword="failed_first_claude_call", tags=_TAG),
    Mutation(id="M1878", phase=1878,
             description="the Claude-first loop never reports why it fell back",
             path=APP / "chat_claude_first.py",
             anchor="        if on_fallback_reason is not None:",
             replacement="        if False:",
             target=_T, keyword="why_it_fell_back or classified", tags=_TAG),
    Mutation(id="M1879", phase=1879, runner="vitest",
             description="the answer card never shows the downgrade note",
             path=FRONTEND_SRC / "components" / "chat" / "AnswerCardView.tsx",
             anchor="      <ProviderNotice note={providerNoteFor(view)} />\n",
             replacement="",
             target="src/components/chat/AnswerCard.test.tsx",
             keyword="local model says so", tags=("ui",)),
)
