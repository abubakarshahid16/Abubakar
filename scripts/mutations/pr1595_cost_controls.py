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
        "    if over := report_mod.over_caps(step, current_run(), worst_case, entries()):\n",
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
        "the report's switch turns the day cap off again",
        _R,
        '    """Why this call may not be made, or None."""\n',
        '    """Why this call may not be made, or None."""\n    if not enabled():\n        return None\n',
        "day_cap_binds_every_route",
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
    _m(
        "13",
        "the step cap is cumulative across runs again",
        _R,
        "    if run and not str(step).startswith(STANDARD_STEP_PREFIX):\n",
        "    if False:\n",
        "another_run_has_its_own or re_run_of_the_same",
    ),
    _m(
        "14",
        "a call with no run skips lines with a run, so runs' spend escapes it",
        _R,
        '        own = run if entry.get("run") == run else None\n',
        '        own = run if entry.get("run") == run else None\n'
        '        if not run and entry.get("run"):\n            continue\n',
        "no_run_reads_every_line",
    ),
    _m(
        "15",
        "a standard is read per run: a run id buys a new USD 25, and it uses up the run's USD 15",
        _R,
        "    if run and not str(step).startswith(STANDARD_STEP_PREFIX):\n",
        "    if run:\n",
        "standards_spend_is_not_charged or standard_stays_25",
    ),
    _m(
        "16",
        "a settlement outside the run slips off the run's cap",
        _S,
        '    if reservation.run:\n        entry["run"] = reservation.run\n',
        "",
        "settlement_outside_the_run",
    ),
    _m(
        "17",
        "the AI clause review step has no USD 10: it stops at USD 5",
        _S,
        "        if str(step) == CLAUSE_REVIEW_STEP and _RUN.get():\n",
        "        if False:\n",
        "clause_review_cannot_exceed_10 or on_clause_review",
    ),
    _m(
        "18",
        "the AI clause review step has USD 10 with no run too",
        _S,
        "        if str(step) == CLAUSE_REVIEW_STEP and _RUN.get():\n",
        "        if str(step) == CLAUSE_REVIEW_STEP:\n",
        "clause_review_with_no_run",
    ),
    _m(
        "19",
        "a reservation does not ask the run's USD 15",
        _S,
        "            if over := report_mod.over_run_cap(step, run, worst, per_step):\n",
        "            if False:\n",
        "whole_run_cannot_exceed_15 or share_the_15 or cannot_pass_15",
    ),
    _m(
        "20",
        "the run's total is never added up, so its USD 15 never binds",
        _R,
        "        held[(run,)] = held.get((run,), 0.0) + usd\n",
        "        pass\n",
        "whole_run_cannot_exceed_15 or batch_across_steps",
    ),
    _m(
        "21",
        "a call that lands exactly on USD 15 is refused",
        _R,
        "    if got + worst <= cap:\n",
        "    if got + worst < cap:\n",
        "whole_run_cannot_exceed_15",
    ),
    _m(
        "22",
        "the read-only check does not ask the run's USD 15",
        _R,
        "    return over_run_cap(step, run, worst, by_cap(lines, run)) or over_day_cap(\n",
        "    return over_day_cap(\n",
        "read_only_check_asks_the_run_cap",
    ),
)
