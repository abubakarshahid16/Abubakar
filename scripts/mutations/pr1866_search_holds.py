"""Review R-1866 (17 Nov 2026): the online search's money holds are closed exactly once, and a hold already closed is never
closed again. `standards_web_search_money.py` writes the ledger through `claude_spend`'s own lock and line writer (rule-6 money
code); `claude_spend.py` is in the danger zone (rule 6). Ids M1866-01.. (named after the PR, rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_M = APP / "standards_web_search_money.py"
_S = APP / "claude_spend.py"
_T = "tests/test_standards_web_search_money.py"
_TAGS = ("budget", "critical")


def _m(n: str, desc: str, path, anchor: str, repl: str, kw: str) -> Mutation:
    return Mutation(id=f"M1866-{n}", phase=1866, description=desc, path=path, anchor=anchor, replacement=repl,
                    target=_T, keyword=kw, tags=_TAGS)  # fmt: skip


_SKIP = '{e.get("settles") or e.get("releases") for e in _raw_lines()}:  # fmt: skip\n'

MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "two sweeps at once close one hold twice (the ledger lock is dropped)",
        _M,
        "    with claude_spend._ledger_lock():\n        for e in claude_spend.entries():\n",
        "    if True:\n        for e in claude_spend.entries():\n",
        "same_time",
    ),
    _m(
        "02",
        "a hold still in flight is closed (the age check is dropped)",
        _M,
        "    return at.tzinfo is not None and at <= cutoff\n",
        "    return True\n",
        "younger_than",
    ),
    _m(
        "03",
        "a stale hold is closed at USD 0, not at its worst case",
        _M,
        '                estimated_usd=float(e.get("cost_usd") or 0.0),\n',
        "                estimated_usd=0.0,\n",
        "closed_once_at_its_worst_case",
    ),
    _m(
        "04",
        "a stale hold is booked to the sweeping run, not to its own",
        _M,
        '                line["run"] = e["run"]\n',
        "                pass\n",
        "closed_once_at_its_worst_case",
    ),
    _m(
        "05",
        "the closing line names no hold, so the hold stays open",
        _M,
        '            line["settles"] = e["reservation"]\n',
        '            line["settles"] = None\n',
        "closed_once_at_its_worst_case",
    ),
    _m(
        "06",
        "the search cost is added to the run's usd again on every call",
        _M,
        '        own = float(row["usd"] or 0.0) - before\n',
        '        own = float(row["usd"] or 0.0)\n',
        "search_fee_once",
    ),
    _m(
        "07",
        "a late settle closes a hold the sweep already settled (charged twice)",
        _S,
        "            _append(entry)\n    return entry if done is None",
        "            pass\n            _append(entry)\n    return entry if done is None",
        "never_closes_it_again and settle",
    ),
    _m(
        "08",
        "a late release closes a hold the sweep already closed",
        _S,
        "        if reservation.id not in " + _SKIP + '            _append({"at"',
        '        if True:\n            _append({"at"',
        "never_closes_it_again and release",
    ),
    _m(
        "09",
        "a settle after a release is skipped: a call billed after all is never charged (spend lowered without proof)",
        _S,
        'if e.get("settles") == reservation.id), None)',
        'if reservation.id in (e.get("settles"), e.get("releases"))), None)',
        "billed_after_all",
    ),
    _m(
        "10",
        "a skipped settle returns a line that pretends it was written, so a caller summing settlements counts twice",
        _S,
        'return entry if done is None else {**done, "skipped": True, "cost_usd": 0.0, "charged_before_usd": done.get("cost_usd")}',
        "return entry",
        "cannot_count_twice",
    ),
)
