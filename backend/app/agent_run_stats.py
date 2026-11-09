"""Honest counts and the failure breaker of the agent proof test runner (#1690, part of #805).

A run that "finished" while every item hit a provider error, or while most tool calls failed, must never read
'Problems: none'. This module counts what went wrong (items ended by a provider error, tool calls that failed, items
that ended on the step limit), says when a run is UNRELIABLE, and decides when consecutive provider errors with no spend
stop the run. Codes and counts only: never a message, never document text.
"""

from __future__ import annotations

from typing import Any

KEYS = ("provider_errors", "tool_calls", "tool_failures", "step_limit")
FAIL_RATE = 0.30  # more than this share of failed tool calls makes the run unreliable
BREAKER_ITEMS = 2  # consecutive provider-error items with zero spend stop the run


class CountingBox:
    """Wraps the toolbox: counts every tool call and every one that did not come back ok. All else is delegated."""

    def __init__(self, inner: Any, stats: dict) -> None:
        self._inner, self._stats = inner, stats

    def run(self, name: str, args: Any) -> Any:
        res = self._inner.run(name, args)
        self._stats["tool_calls"] = self._stats.get("tool_calls", 0) + 1
        if not (isinstance(res, dict) and res.get("ok")):
            self._stats["tool_failures"] = self._stats.get("tool_failures", 0) + 1
        return res

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def load(meta: dict) -> dict:
    saved = meta.get("stats") if isinstance(meta.get("stats"), dict) else {}
    return {k: int(saved.get(k) or 0) for k in KEYS}


def count_item(stats: dict, out: dict | None) -> None:
    """Count how one item ended: by a provider error, or on the step limit."""
    why = (out or {}).get("why")
    if why == "provider error":
        stats["provider_errors"] += 1
    elif why == "step limit":
        stats["step_limit"] += 1


def failure_rate(stats: dict) -> float:
    calls = stats.get("tool_calls", 0)
    return stats.get("tool_failures", 0) / calls if calls else 0.0


def unreliable(stats: dict) -> bool:
    return bool(
        stats.get("provider_errors")
        or stats.get("step_limit")
        or failure_rate(stats) > FAIL_RATE
    )


def problem_count(stats: dict, run_problems: int = 0) -> int:
    """Logged problems plus one for each category above 0 (and one more when the tool failure rate is above 30%)."""
    kinds = sum(
        1 for k in ("provider_errors", "tool_failures", "step_limit") if stats.get(k)
    )
    return run_problems + kinds + (1 if failure_rate(stats) > FAIL_RATE else 0)


def problem_words(stats: dict) -> list[str]:
    """The three honest counts, as lines (also in the STATUS box)."""
    calls, failed = stats.get("tool_calls", 0), stats.get("tool_failures", 0)
    rate = f"{failure_rate(stats) * 100:.0f}%" if calls else "no tool calls"
    return [
        f"items ended by provider error: {stats.get('provider_errors', 0)}",
        f"tool calls failed: {failed} of {calls} ({rate})",
        f"items ended on the step limit: {stats.get('step_limit', 0)}",
    ]


def headline_warning(stats: dict) -> str:
    """'' for a clean run; otherwise the words the headline must carry."""
    if failure_rate(stats) > FAIL_RATE:
        return "run unreliable: tool failures"
    if unreliable(stats):
        return "run unreliable: provider errors or step limits"
    return ""


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
        self.items.append(item_id)
        self.codes.append(str(out.get("error") or "unknown"))
        return len(self.items) >= self.limit

    def words(self) -> str:
        return f"provider errors on {len(self.items)} items in a row ({', '.join(sorted(set(self.codes)))}): run stopped"
