"""Honest counts and the failure breaker of the agent proof test runner (#1690, part of #805).

A run that "finished" while every item hit a provider error, or while most tool calls failed, must never read
'Problems: none'. This module is the ONE source of the problems text, the problem count and the headline note: LIVE.md,
RESULTS.md, the STATUS box and live.log all take them from `view`, so they cannot disagree.

Counts are PER ITEM, with the LATEST outcome of each item: an item the breaker stopped and a resume then ran well no
longer counts as an error (it is listed on a separate, clearly labelled 'retried after error' line). Codes and counts
only: never a message, never document text.
"""

from __future__ import annotations

from typing import Any

FAIL_RATE = 0.30  # MORE than this share of failed tool calls makes the run unreliable
BREAKER_ITEMS = 2  # consecutive provider-error items with zero spend stop the run
THRESHOLD_WORDS = "limit: over 30%"


class RunStats:
    """Per-item outcome, tool calls and failures. `measured` is False for a run whose metadata predates the counts."""

    def __init__(self, items: dict | None = None, measured: bool = True) -> None:
        self.items: dict[str, dict] = items or {}
        self.measured = measured
        self.runs = 1  # this run's number: 1 for the first, 2 for the first resume, ...
        self._cur: str | None = None
        self._prev: dict | None = None
        self._begun: set[str] = (
            set()
        )  # keys started in THIS process: a second start is an in-run rerun

    @classmethod
    def load(cls, meta: dict) -> RunStats:
        saved = meta.get("stats")
        if isinstance(saved, dict) and isinstance(saved.get("items"), dict):
            items = {
                str(k): dict(v)
                for k, v in saved["items"].items()
                if isinstance(v, dict)
            }
            st = cls(items, measured=saved.get("measured", True) is not False)
            st.runs = int(saved.get("runs") or 0) + 1
            return st
        return cls(
            measured=not meta
        )  # an old metadata file (it has other keys, no counts): not measured

    def to_json(self) -> dict:
        return {"items": self.items, "measured": self.measured, "runs": self.runs}

    # one item ------------------------------------------------------------------------------------------------
    def begin(self, item_id: str) -> None:
        self._cur, self._prev = str(item_id), self.items.get(str(item_id))
        was_error = bool(self._prev) and (
            self._prev.get("outcome") == "provider_error" or self._prev.get("retried")
        )
        rerun = self._cur in self._begun and bool(self._prev)
        self._begun.add(self._cur)
        self.items[self._cur] = {
            "outcome": "",
            "error": "",
            "calls": int(self._prev["calls"])
            if rerun
            else 0,  # an in-run rerun adds to attempt 1
            "fails": int(self._prev["fails"]) if rerun else 0,
            "retried": was_error,
            "attempts": int((self._prev or {}).get("attempts") or 1) + 1
            if self._prev
            else 1,
            "rerun": (self._prev or {}).get("outcome", "") if rerun else "",
        }

    def abort(self) -> None:
        """The item did not finish (run cap, fatal stop): its earlier record comes back."""
        if self._cur is not None:
            if self._prev is None:
                self.items.pop(self._cur, None)
            else:
                self.items[self._cur] = self._prev
        self._cur = None

    def call(self, ok: bool) -> None:
        if self._cur is not None:
            rec = self.items[self._cur]
            rec["calls"] += 1
            rec["fails"] += 0 if ok else 1

    def end(self, out: dict | None) -> None:
        if self._cur is None:
            return
        why = (out or {}).get("why")
        rec = self.items[self._cur]
        rec["outcome"] = {
            "provider error": "provider_error",
            "step limit": "step_limit",
        }.get(why, "ok")
        rec["error"] = (
            str((out or {}).get("error") or "")
            if rec["outcome"] == "provider_error"
            else ""
        )
        self._cur = None

    # totals --------------------------------------------------------------------------------------------------
    def total(self, key: str) -> int:
        return sum(int(r.get(key) or 0) for r in self.items.values())

    def count_outcome(self, outcome: str) -> int:
        """SKILL ITEMS with this outcome (a sweep item counts once, however many of its runs `<id>#<n>` had it)."""
        return len(
            {
                k.split("#")[0]
                for k, r in self.items.items()
                if r.get("outcome") == outcome
            }
        )

    def sweep_runs(self, outcome: str | None = None) -> int:
        """Sweep RUNS (keys `<id>#<n>`), all or with this outcome. With no outcome every ATTEMPT is counted, so a
        run asked again counts twice; with an outcome, the latest outcome of each run."""
        if outcome is None:
            return sum(
                int(r.get("attempts") or 1) for k, r in self.items.items() if "#" in k
            )
        return sum(
            1 for k, r in self.items.items() if "#" in k and r.get("outcome") == outcome
        )

    def sweep_reruns(self, outcome: str) -> int:
        """Sweep runs asked again in the same invocation after this outcome (provider_error, step_limit)."""
        return sum(
            1 for k, r in self.items.items() if "#" in k and r.get("rerun") == outcome
        )

    @property
    def provider_errors(self) -> int:
        return self.count_outcome("provider_error")

    @property
    def step_limit(self) -> int:
        return self.count_outcome("step_limit")

    @property
    def retried(self) -> int:
        return sum(1 for r in self.items.values() if r.get("retried"))

    @property
    def rate(self) -> float:
        calls = self.total("calls")
        return self.total("fails") / calls if calls else 0.0


class CountingBox:
    """Wraps the toolbox: counts every tool call and every one that did not come back ok. All else is delegated."""

    def __init__(self, inner: Any, stats: RunStats) -> None:
        self._inner, self._stats = inner, stats

    def run(self, name: str, args: Any) -> Any:
        res = self._inner.run(name, args)
        self._stats.call(isinstance(res, dict) and bool(res.get("ok")))
        return res

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def percent(rate: float) -> str:
    """The rate with the precision the 30% rule uses: 30.4% is printed as 30.4%, never as 30%."""
    return f"{rate * 100:.1f}%"


def unreliable_note(stats: RunStats) -> str:
    """'' for a clean (or unmeasured) run, else the words the headline must carry."""
    if stats.rate > FAIL_RATE:
        return "run unreliable: tool failures"
    if stats.provider_errors or stats.step_limit:
        return "run unreliable: provider errors or step limits"
    return ""


NOT_MEASURED = (
    "earlier items: not measured (this run started before the counts were kept)"
)


def stat_lines(stats: RunStats) -> list[str]:
    """The honest count lines (the same text in every output). For a run resumed from before the counts were kept, the
    earlier items are labelled 'not measured' and the counts below cover the items run since."""
    earlier = [NOT_MEASURED] if not stats.measured else []
    if not stats.measured and not problem_count(stats) and not stats.retried:
        return earlier  # nothing went wrong in the measured items: say only what is not measured, never a bare 0
    calls, failed = stats.total("calls"), stats.total("fails")
    rate = f"{percent(stats.rate)}; {THRESHOLD_WORDS}" if calls else "no tool calls"
    lines = [
        *earlier,
        f"items ended by provider error: {stats.provider_errors}",
        f"tool calls failed: {failed} of {calls} ({rate})",
        f"items ended on the step limit: {stats.step_limit}",
    ]
    if stats.sweep_runs():
        again = ""
        pe, sl = stats.sweep_reruns("provider_error"), stats.sweep_reruns("step_limit")
        if pe or sl:
            again = f"; retried after provider error {pe}, rerun on the higher step cap {sl}"
        lines.append(
            f"sweep runs asked: {stats.sweep_runs()} (ended by provider error {stats.sweep_runs('provider_error')}, "
            f"on the step limit {stats.sweep_runs('step_limit')}{again}); the item counts above count skill items"
        )
    if stats.retried:
        lines.append(
            f"retried after error: {stats.retried} (they ran again; their latest outcome is counted above)"
        )
    return lines


def problem_count(stats: RunStats, run_problems: int = 0) -> int:
    """Logged problems plus one for each category above 0 (and one more when the failure rate is over 30%)."""
    kinds = sum(
        1 for n in (stats.provider_errors, stats.total("fails"), stats.step_limit) if n
    )
    return run_problems + kinds + (1 if stats.rate > FAIL_RATE else 0)


def view(stats: RunStats | None, run_problems: list[str]) -> tuple[list[str], str]:
    """THE one source: (the problem lines to print, the headline note ' | run unreliable...' or '').

    The lines are the run's own problems plus the honest counts when there is anything to say (or nothing measured)."""
    if stats is None:
        return list(run_problems), ""
    say = (not stats.measured) or problem_count(stats) > 0 or stats.retried
    lines = list(run_problems) + (stat_lines(stats) if say else [])
    note = unreliable_note(stats)
    return lines, (f" | {note}" if note else "")


def count_for_results(stats: RunStats | None, run_problems: list[str]) -> int:
    return (
        problem_count(stats, len(run_problems))
        if stats is not None
        else len(run_problems)
    )


class Breaker:
    """Stops the run after BREAKER_ITEMS consecutive items that ended in a provider error and spent nothing."""

    def __init__(self, limit: int = BREAKER_ITEMS) -> None:
        self.limit, self.items, self.codes = limit, [], []

    def seen(self, item_id: str, out: dict | None) -> bool:
        """Record one finished item; True when the breaker trips."""
        bad = bool(out) and out.get("why") == "provider error" and not out.get("usd")
        if not bad:
            self.items, self.codes = [], []
            return False
        if not (self.items and self.items[-1] == item_id):
            self.items.append(
                item_id
            )  # the same run asked again (a retry) is not a second item
        self.codes.append(str(out.get("error") or "unknown"))
        return len(self.items) >= self.limit

    def words(self) -> str:
        return f"provider errors on {len(self.items)} items in a row ({', '.join(sorted(set(self.codes)))}): run stopped"
