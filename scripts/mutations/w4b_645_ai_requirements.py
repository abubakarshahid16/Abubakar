"""#645: AI requirement extraction - every field the model states is checked in
code. M4301 onward (M40xx are #653's, M41xx and M42xx the cloud session's)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w4b_645_ai_requirements.py"
_M = APP / "ai_requirements.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M4301", phase=4301, description="a quote the passage does not contain is kept",
             path=_M,
             anchor="    if not quote.strip() or _squash(quote) not in _squash(passage):\n",
             replacement="    if not quote.strip():\n",
             target=_T, keyword="quote_not_in_the_passage", tags=("honesty", "critical")),
    Mutation(id="M4302", phase=4302, description="a figure is not held to its quote",
             path=_M,
             anchor="        problem = answer.figure_check(stated, claimed, quote)\n",
             replacement="        problem = None\n",
             target=_T, keyword="figure_not_in_its_quote or psi_read_as_percent or gauge_read",
             tags=("honesty", "critical")),
    Mutation(id="M4303", phase=4303, description="a unit mismatch is reported as a missing figure",
             path=_M,
             anchor="            return UNIT_NOT_IN_QUOTE if problem[1] == answer.UNIT_MISMATCH else FIGURE_NOT_IN_QUOTE\n",
             replacement="            return FIGURE_NOT_IN_QUOTE\n",
             target=_T, keyword="psi_read_as_percent or gauge_read", tags=("honesty",)),
    Mutation(id="M4304", phase=4304, description="a standard name that does not parse is kept",
             path=_M,
             anchor="        if standard_ids.parse(named) is None:\n",
             replacement="        if False:\n",
             target=_T, keyword="named_standard", tags=("honesty",)),
    Mutation(id="M4305", phase=4305, description="a named standard need not be the one quoted",
             path=_M,
             anchor="        if not any(standard_ids.same_standard(named, raw)\n",
             replacement="        if False and not any(standard_ids.same_standard(named, raw)\n",
             target=_T, keyword="named_standard", tags=("honesty", "critical")),
    Mutation(id="M4306", phase=4306, description="items are kept without any check",
             path=_M,
             anchor="            reason = check_item(item, passage)\n",
             replacement="            reason = None\n",
             target=_T, keyword="quote_not_in_the_passage or psi_read_as_percent", tags=("honesty", "critical")),
    Mutation(id="M4307", phase=4307, description="duplicates are not merged",
             path=_M,
             anchor="            if key in seen:\n",
             replacement="            if False:\n",
             target=_T, keyword="read_twice", tags=("honesty",)),
    Mutation(id="M4308", phase=4308, description="a passage may exceed the word limit",
             path=_M,
             anchor="        if count + len(words) > max_words and current:\n",
             replacement="        if False:\n",
             target=_T, keyword="word_limit or task_the_runner_accepts", tags=("robustness",)),
    Mutation(id="M4309", phase=4309, description="a reply the runner could not read is silently dropped",
             path=_M,
             anchor="        if result.state != ai_task_runner.STATE_OK:\n"
                    "            unread.append({\"passage\": index, \"reason\": result.reason})\n",
             replacement="        if result.state != ai_task_runner.STATE_OK:\n",
             target=_T, keyword="cannot_read_is_listed", tags=("honesty",)),
    Mutation(id="M4310", phase=4310, description="the pilot scores the number alone, ignoring the unit",
             path=APP.parent.parent / "scripts" / "pilot_ai_requirements.py",
             anchor="    return answer._unit_value_matches(a, b) or answer._unit_value_matches(b, a)\n",
             replacement="    return answer._value_matches(a[\"value\"], b[\"value\"])\n",
             target=_T, keyword="scores_value_and_unit", tags=("honesty",)),
)
