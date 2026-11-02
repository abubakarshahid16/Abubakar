"""PR 1595: the USD 100 a day in `claude_spend` (the budget gate) and what `claude_spend_report` counts for it.
Ids M1595-01 onwards, phase 1595."""

from __future__ import annotations

from ._base import APP, Mutation

_TEST = "tests/test_claude_cost_controls.py"
_S = APP / "claude_spend.py"
_R = APP / "claude_spend_report.py"
_TAGS = ("budget", "day_cap")


def _m(n, description, path, anchor, replacement, keyword):
    return Mutation(
        id=f"M1595-{n}",
        phase=1595,
        description=description,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=_TEST,
        keyword=keyword,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "a call is reserved without asking the day cap",
        _S,
        "            if over := report_mod.over_day_cap(worst, round(day, 6)):\n",
        "            if False:\n",
        "day_cap_refuses_every_route",
    ),
    _m(
        "02",
        "a batch passes the day cap one request at a time",
        _S,
        "            day += worst\n",
        "",
        "cross_the_cap_together",
    ),
    _m(
        "03",
        "the read-only check does not ask the day cap",
        _S,
        "    if over := report_mod.over_day_cap(worst_case, report_mod.charged_today(entries())):\n",
        "    if False:\n",
        "read_only_check",
    ),
    _m(
        "04",
        "an open hold is not counted against the day, so ten calls in flight all pass",
        _R,
        "            counts = now - when < OPEN_HOLD_WINDOW\n",
        "            counts = False\n",
        "settled_replaces_its_hold or across_midnight",
    ),
    _m(
        "05",
        "a dead process's hold eats every new day for ever",
        _R,
        "            counts = now - when < OPEN_HOLD_WINDOW\n",
        "            counts = True\n",
        "across_midnight",
    ),
    _m(
        "06",
        "every settled line counts against today, whatever its date",
        _R,
        "            counts = when.date() == now.date()\n",
        "            counts = True\n",
        "yesterdays_settled or utc_day",
    ),
    _m(
        "07",
        "a line nobody can date counts as nothing today",
        _R,
        "        if when is None:\n            counts = True\n",
        "        if when is None:\n            counts = False\n",
        "torn_ledger_line",
    ),
    _m(
        "08",
        "the setting can raise the owner's USD 100",
        _R,
        "    return min(float(settings.claude_budget_usd_per_day), DAY_CAP_USD)\n",
        "    return float(settings.claude_budget_usd_per_day)\n",
        "narrows_the_owners_100",
    ),
    _m(
        "09",
        "a call that lands exactly on the cap is refused",
        _R,
        "    if charged + worst <= cap:\n",
        "    if charged + worst < cap:\n",
        "cross_the_cap_together",
    ),
    _m(
        "10",
        "the switch is ignored, so the cap binds with it off",
        _R,
        "    if not enabled():\n        return None\n    cap = day_cap()\n",
        "    cap = day_cap()\n",
        "switch_off_no_route",
    ),
    _m(
        "11",
        "an open hold is reported as cost: USD 3.71 against a real USD 0.35",
        _R,
        '    if entry.get("reserved"):\n        row["held_calls"] += 1\n',
        '    if False:\n        row["held_calls"] += 1\n',
        "never_a_hold",
    ),
    _m(
        "12",
        "a reservation settled twice is reported as two calls",
        _R,
        "        if settles:\n            seen.add(settles)\n",
        "",
        "settled_twice",
    ),
)
