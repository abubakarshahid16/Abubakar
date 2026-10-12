"""Mutations for the 2026-09-30 spend-cap audit: backend/app/claude_spend.py,
the Claude paths in backend/app/reasoning_provider.py, and the turn cost and
refusal wording in backend/app/chat_claude_first.py.

1. A call that may have been sent is always counted (M1470-M1472, M1479).
2. The check-and-reserve is atomic across threads and processes (M1473,
   M1474) and a batch is reserved as a whole (M1478).
3. Claude-first chat reports the whole turn's cost and the real cause of a
   failure (M1475-M1477).
Target: backend/tests/test_claude_spend_audit.py (M1479: the existing
backend/tests/test_claude_spend_routes.py).
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_claude_spend_audit.py"
_SPEND = APP / "claude_spend.py"
_RP = APP / "reasoning_provider.py"
_CCF = APP / "chat_claude_first.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1470", phase=1470,
             description="reason(): a read timeout after the call left is not settled as charged",
             path=_RP,
             anchor="            charged = _charged(claude_spend.settle_failure(held, exc, unbilled=_unbilled))\n",
             replacement="            charged = 0.0\n",
             target=_T, keyword="read_timeout_in_reason", tags=("budget", "critical")),
    Mutation(id="M1471", phase=1471,
             description="stream: a dropped or 1 MB-capped stream is not settled as charged",
             path=_RP,
             anchor="        charged = _charged(claude_spend.settle_failure(\n"
                    "            held, exc, unbilled=_unbilled, usage=usage if final_usage else None, model=model))\n",
             replacement="        charged = 0.0\n",
             target=_T, keyword="fails_before_its_final_usage", tags=("budget", "critical")),
    Mutation(id="M1472", phase=1472,
             description="stream: a failure after the final usage arrived ignores that usage",
             path=_RP,
             anchor="usage=usage if final_usage else None, model=model))\n",
             replacement="usage=None, model=model))\n",
             target=_T, keyword="fails_after_its_final_usage", tags=("budget",)),
    Mutation(id="M1473", phase=1473,
             description="the ledger lock is gone: check-then-write races between threads",
             path=_SPEND,
             anchor="    with _THREAD_LOCK:\n"
                    "        with open(path.with_name(path.name + \".lock\"), \"a+b\") as fh:\n"
                    "            _os_lock(fh)\n",
             replacement="    if True:\n"
                         "        with open(path.with_name(path.name + \".lock\"), \"a+b\") as fh:\n"
                         "            (lambda _fh: None)(fh)\n",
             target=_T, keyword="ten_threads", tags=("budget", "critical")),
    Mutation(id="M1474", phase=1474,
             description="only the in-process lock is taken: processes sharing a ledger race",
             path=_SPEND,
             anchor="            _os_lock(fh)\n",
             replacement="            (lambda _fh: None)(fh)\n",
             target=_T, keyword="four_processes", tags=("budget", "critical")),
    Mutation(id="M1475", phase=1475,
             description="chat: the turn reports the last call's cost only",
             path=_CCF,
             anchor="    cost = round(turn_cost, 6) if turn_cost is not None else response.cost_usd\n",
             replacement="    cost = response.cost_usd\n",
             target=_T, keyword="cost_of_every_call", tags=("honesty", "budget")),
    Mutation(id="M1476", phase=1476,
             description="chat: every mid-loop failure is blamed on the spending cap",
             path=_CCF,
             anchor="    if isinstance(exc, claude_spend.BudgetExceeded):\n"
                    "        return f\"the spending cap",
             replacement="    if True:\n"
                         "        return f\"the spending cap",
             target=_T, keyword="not_called_the_spending_cap", tags=("honesty",)),
    Mutation(id="M1477", phase=1477,
             description="chat: a consent exit mid-loop drops the cost of the calls already made",
             path=_CCF,
             anchor="                    result[\"cost_usd\"] = round(turn_cost, 6)\n",
             replacement="                    pass\n",
             target=_T, keyword="consent_exit", tags=("honesty", "budget")),
    Mutation(id="M1478", phase=1478,
             description="reserve_all checks each request alone: a batch crosses a cap together",
             path=_SPEND,
             anchor="            per_step[step] = per_step.get(step, 0.0) + worst\n"
                    "            total += worst\n",
             replacement="            pass\n",
             target=_T, keyword="reserved_as_a_whole", tags=("budget",)),
    Mutation(id="M1479", phase=1479,
             description="metered: a failed review-route call leaves its reservation unsettled",
             path=_SPEND,
             anchor="            settle_failure(held, exc, unbilled=unbilled)\n",
             replacement="            pass\n",
             target="tests/test_claude_spend_routes.py", keyword="may_have_been_billed or provably_was_not",
             tags=("budget",)),
)
