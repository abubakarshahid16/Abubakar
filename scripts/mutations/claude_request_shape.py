"""Mutations for the Claude chat request shape (2026-09-30, M1820-M1824).
Files: backend/app/chat_claude_first.py, backend/app/reasoning_provider.py.
Target: backend/tests/test_claude_request_shape.py (and the cap test in
test_chat_claude_first.py).
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_claude_request_shape.py"
_CF = APP / "chat_claude_first.py"
_RP = APP / "reasoning_provider.py"
_TAG = ("claude_request_shape",)

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1820", phase=1820,
             description="after the tool cap the tools are no longer defined",
             path=_CF,
             anchor="            offer_tools = tools\n",
             replacement="            offer_tools = tools if tool_choice is None else ()\n",
             target=_T, keyword="tool_cap_still_defines_tools", tags=_TAG),
    Mutation(id="M1821", phase=1821,
             description="thinking is switched off after the first round again",
             path=_CF,
             anchor="thinking_budget = settings.chat_thinking_budget_tokens if used_thinking else None\n",
             replacement="thinking_budget = (settings.chat_thinking_budget_tokens\n                              if used_thinking and tool_calls_made == 0 else None)\n",
             target=_T, keyword="thinking_turn_with_a_tool_call", tags=_TAG),
    Mutation(id="M1822",  phase=1822,
             description="the streamed thinking signature is dropped again",
             path=_RP,
             anchor="                        block[\"signature\"] = str(delta.get(\"signature\") or \"\")\n",
             replacement="                        pass\n",
             target=_T, keyword="thinking_turn_with_a_tool_call", tags=_TAG),
    Mutation(id="M1823", phase=1823,
             description="tool_choice is never sent",
             path=_RP,
             anchor="            if packet.tool_choice:\n                body[\"tool_choice\"] = dict(packet.tool_choice)\n",
             replacement="",
             target="tests/test_chat_claude_first.py", keyword="tool_call_cap_stops_the_loop", tags=_TAG),
    Mutation(id="M1824", phase=1824,
             description="the cap no longer forces a text-only answer",
             path=_CF,
             anchor="                           if tool_calls_made >= settings.chat_tool_max_calls else None)\n",
             replacement="                           if tool_calls_made >= settings.chat_tool_max_calls + 99 else None)\n",
             target="tests/test_chat_claude_first.py", keyword="tool_call_cap_stops_the_loop", tags=_TAG),
)
