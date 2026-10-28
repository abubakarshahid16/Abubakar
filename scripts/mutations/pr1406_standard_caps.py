"""Order 271.3 (PR 1406): the November Claude caps. `claude_spend.py` is the budget gate, so its cap logic gets
entries (the converter itself and the review hook are ordinary code with ordinary tests). Ids M1406-01 onwards,
phase 1406."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_271_standard_cap.py"
_TAGS = ("budget", "o271")


def _m(n, description, path, anchor, replacement, keyword):
    return Mutation(
        id=f"M1406-{n}",
        phase=1406,
        description=description,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAGS,
    )


_S = APP / "claude_spend.py"
_C = APP / "config.py"

MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "a standard's conversion has no cap of its own any more: it falls back to USD 5",
        _S,
        "        if str(step).startswith(STANDARD_STEP_PREFIX):\n"
        "            return Caps(float(settings.claude_budget_usd_per_standard), self.total)\n"
        "        return self\n",
        "        return self\n",
        "up_to_25",
    ),
    _m(
        "02",
        "a standard's step gets the per-standard cap as the TOTAL cap too",
        _S,
        "            return Caps(float(settings.claude_budget_usd_per_standard), self.total)\n",
        "            return Caps(float(settings.claude_budget_usd_per_standard), float(settings.claude_budget_usd_per_standard))\n",
        "total_is_500",
    ),
    _m(
        "03",
        "any step with 'standards' in its name earns the larger cap",
        _S,
        "        if str(step).startswith(STANDARD_STEP_PREFIX):\n",
        '        if "standards" in str(step):\n',
        "keeps_its_5_dollar_cap",
    ),
    _m(
        "04",
        "a reservation checks every step against the plain per-step cap",
        _S,
        "                explicit or caps.for_step(step),\n",
        "                explicit or caps,\n",
        "each_standard_has_its_own_25",
    ),
    _m(
        "05",
        "a caller's own caps are replaced by the settings' caps",
        _S,
        "explicit or caps.for_step(step),",
        "caps.for_step(step),",
        "passes_its_own_caps",
    ),
    _m(
        "06",
        "the read-only affordability check uses the plain per-step cap",
        _S,
        "        caps or Caps.from_settings().for_step(step),\n",
        "        caps or Caps.from_settings(),\n",
        "read_only_check",
    ),
    _m(
        "07",
        "the total cap is back at USD 20",
        _C,
        "    claude_budget_usd_total: float = 500.0\n",
        "    claude_budget_usd_total: float = 20.0\n",
        "owners_numbers",
    ),
    _m(
        "08",
        "the per-standard cap is back at USD 5",
        _C,
        "    claude_budget_usd_per_standard: float = 25.0\n",
        "    claude_budget_usd_per_standard: float = 5.0\n",
        "owners_numbers",
    ),
    _m(
        "09",
        "the raised total never lapses: December still has USD 500",
        _S,
        "    return min(total, BASELINE_TOTAL_USD) if _today() > TOTAL_RAISED_UNTIL else total\n",
        "    return total\n",
        "window",
    ),
    _m(
        "10",
        "the window ends a day early: 30 November is already back at 20",
        _S,
        "if _today() > TOTAL_RAISED_UNTIL else total",
        "if _today() >= TOTAL_RAISED_UNTIL else total",
        "last_day_of_november",
    ),
    _m(
        "11",
        "after the window a bigger value in .env keeps the cap raised",
        _S,
        "min(total, BASELINE_TOTAL_USD) if",
        "max(total, BASELINE_TOTAL_USD) if",
        "bigger_env_value",
    ),
    _m(
        "12",
        "an unreadable ledger line counts at the setting's total, not the cap in force",
        _S,
        '                            "cost_usd": total_cap(),',
        '                            "cost_usd": float(settings.claude_budget_usd_total),',
        "unreadable_ledger_line",
    ),
)
