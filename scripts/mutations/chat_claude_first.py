"""Claude-first chat (owner order 2026-09-27): tools, verification, budget,
the tool-call cap, and the web tool's consent gate."""
from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1107", phase=90,
             description="a tool returns a document outside the caller's grants",
             path=APP / "chat_tools.py",
             anchor="    if document_id not in allowed_document_ids:\n        return None\n",
             replacement="    if False:\n        return None\n",
             target="tests/test_chat_claude_first.py",
             keyword="never_returns_a_document_outside_the_callers_grants",
             tags=("privacy", "critical")),
    Mutation(id="M1108", phase=90,
             description="a document claim is shown even when its quote does not verify",
             path=APP / "chat_claude_first.py",
             anchor='        text, verification, claims, removed = answer_mod.verify_claims(\n'
                    '            text, sources, narration_from_line=first_last_line, dropped=dropped_points)\n',
             replacement='        verification, claims, removed = {"verified": 1, "total": 1, '
                        '"method": "quote found on the page"}, [], 0\n',
             target="tests/test_chat_pr2_router.py",
             keyword="on_the_claude_lane_a_claim_whose_quote_is_not_on_the_page_is_removed",
             tags=("honesty", "critical")),
    Mutation(id="M1109", phase=90,
             description="the tool-call cap never stops the loop offering more tools",
             path=APP / "chat_claude_first.py",
             anchor='            tool_choice = ({"type": "none"}\n                           if tool_calls_made >= settings.chat_tool_max_calls else None)\n',
             replacement="            tool_choice = None\n",
             target="tests/test_chat_claude_first.py",
             keyword="the_tool_call_cap_stops_the_loop_rather_than_running_forever",
             tags=("cost", "critical")),
    Mutation(id="M1110", phase=90,
             description="a budget refusal mid-loop is swallowed into a silent empty answer "
                        "rather than told to the reader",
             path=APP / "chat_claude_first.py",
             anchor="                if tool_calls_made == 0 and not sources:\n"
                   "                    raise _Fallback(str(exc)) from exc\n"
                   "                return _budget_or_provider_failure(exc, sources, steps, started, turn_cost)\n",
             replacement="                raise _Fallback(str(exc)) from exc\n",
             target="tests/test_chat_claude_first.py",
             keyword="a_budget_refusal_mid_loop_is_answered_honestly_not_swallowed",
             tags=("honesty", "cost", "critical")),
    Mutation(id="M1111", phase=90,
             description="the web tool searches immediately instead of asking first",
             path=APP / "chat_tools.py",
             anchor='    if name == "web_search":\n        raise ConsentRequired(str(input.get("query") or ""))\n',
             replacement='    if name == "web_search":\n        return ToolRun("web_search", input, '
                        '"Searched the web", True), None\n',
             target="tests/test_chat_claude_first.py",
             keyword="web_tool_asks_first_and_the_sanitiser_still_applies",
             tags=("privacy", "critical")),
)
