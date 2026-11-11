"""Sweep items (#1690): one skill item with `repeat: true` yields several findings.

The runner runs the item again and again as ordinary items, each run through the SAME loop and the same
record_finding checks. Run n is named `<item id>#<n>`; it is told, in `already_recorded`, the doc quotes (80 chars
each) already accepted in runs 1..n-1 and is asked for one NEW matching field. The sweep stops when a run ends
without an accepted finding, when a doc quote is accepted twice (the second is dropped), or at `repeat_max`.
A sweep finding is never GREEN or RED: the colour is forced to YELLOW here (a restriction only). No document
text goes anywhere new: `already_recorded` is only in the model prompt of the same run.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from . import agent_loop
from .word_fold import fold_compat

DEFAULT_MAX = 15
# A repeat run that ended on the step limit gets ONE more run with this higher cap (twice the normal one). The rerun is a
# fresh run of the same run id (the loop deletes a finished run's checkpoint), so it has the whole higher cap.
# Repeat runs only: a plain item keeps agent_loop.MAX_STEPS. Why 2x: a sweep run walks a field list and often needs
# one more look per field; the item USD cap still bounds the cost of a run that never finds a field.
REPEAT_RETRY_STEPS = 2 * agent_loop.MAX_STEPS
SEP = "#"
CUT = 80


def is_sweep(skill_item: Any) -> bool:
    return isinstance(skill_item, dict) and skill_item.get("repeat") is True


def fold(text: Any) -> str:
    """A quote as compared for repeats: the project's own fold (case, look-alikes, marks), then words only."""
    return " ".join(re.findall(r"[^\W_]+", fold_compat(text)))


def keys_for(item: dict, finals: dict) -> list[str]:
    """The finals keys of one skill item, in run order: [id] for a normal item, id#1, id#2.. for a sweep."""
    iid = str(item["id"])
    if not is_sweep(item):
        return [iid] if iid in finals else []
    pre = iid + SEP
    mine = [k for k in finals if k.startswith(pre) and k[len(pre) :].isdigit()]
    return sorted(mine, key=lambda k: int(k[len(pre) :]))


def base_id(item_id: Any) -> str:
    return str(item_id).split(SEP)[0]


STOP_KEY = SEP + "stop"
_WHY = {
    "asked the engineer": "none left",
    "provider error": "provider error",
    "step limit": "step limit",
    "usd cap": "item cap",
}
_RETRY = (
    "provider error",
)  # a failed run n>1 is not marked done: a resume asks it again
QUIET = ("none left",)  # the only stop that is not shown in RESULTS Problems


def _again(
    run_one, item: dict, skill_item: dict, rid: str, res: dict, trace: Any, halt
):
    """ONE immediate rerun of a run that ended on a provider error (same cap) or on the step limit (higher cap).
    Returns (result, stop). The run is taken back out of the done set first, so the loop does not skip it."""
    why = res.get("why")
    if why not in ("provider error", "step limit"):
        return res, ""
    trace.unmark_done(rid)  # also when halted below: a resume asks this run again
    if (
        stop := halt()
    ):  # the total cap is checked before every attempt, a rerun included
        return res, stop
    spent = float(
        res.get("usd") or 0.0
    )  # the item cap bounds the first attempt plus the rerun
    if why == "provider error":
        return run_one(item, skill_item, spent=spent)
    return run_one(item, skill_item, max_steps=REPEAT_RETRY_STEPS, spent=spent)


def _forced(finding: dict, rid: str) -> dict:
    """The finding as kept. The colour is already YELLOW (agent_loop forces it before anything is stored)."""
    return {**finding, "item": rid, "sweep": True}


def stops(finals: dict, chosen: list[dict]) -> list[str]:
    """RESULTS Problems lines: why a sweep stopped, for every reason but 'none left' (fixed codes, no text)."""
    out = []
    for item in chosen:
        why = finals.get(str(item["id"]) + STOP_KEY)
        if is_sweep(item) and why and why not in QUIET:
            out.append(f"sweep stopped early: {why} ({item['id']})")
    return out


def run_sweep(
    loop_item: dict,
    skill_item: dict,
    finals: dict,
    trace: Any,
    run_one: Callable[..., tuple[dict | None, str]],
    put: Callable[[str, Any], None],
    halt: Callable[[], str],
) -> str:
    """Run the repeats of one item. Returns "" or the reason the whole run stops (a cap, a trip, a fatal).

    Why the sweep itself ended is kept in finals under `<id>#stop` (none left, provider error, step limit, item cap,
    repeat_max, duplicate quote)."""
    iid = str(loop_item["id"])
    limit = skill_item.get("repeat_max", DEFAULT_MAX)
    seen: list[str] = []
    quotes: set[str] = set()
    why = finals.get(iid + STOP_KEY)

    def end(reason: str) -> str:
        if finals.get(iid + STOP_KEY) != reason:
            put(iid + STOP_KEY, reason)
        trace.sweep_finished.add(iid)
        return ""

    for n in range(1, limit + 1):
        rid = f"{iid}{SEP}{n}"
        res = None
        if rid not in finals:
            if stop := halt():
                return stop
            item = {**loop_item, "id": rid, "already_recorded": list(seen)}
            res, stop = run_one(item, skill_item)
            if stop:
                return stop
            if res is not None:
                res, stop = _again(run_one, item, skill_item, rid, res, trace, halt)
                if stop:
                    return stop
            # no result: the run was done before this start, so the saved reason stands
            if res is not None:
                why = _WHY.get(res.get("why"), "other")
        stored = trace.sink.get(rid)
        if stored is None:
            if (
                rid not in finals and n == 1
            ):  # nothing found at all: the item's one honest yellow
                lost = agent_loop.yellow("result lost in a restart", loop_item)
                put(rid, _forced(res["finding"] if res else lost, rid))
            elif rid not in finals and why in _RETRY:
                trace.unmark_done(rid)  # a resume asks this run again
            elif rid not in finals:
                trace.uncount(rid)
            return end(why or "none left")
        quote = fold(stored.get("doc_quote"))
        if quote in quotes:
            if rid not in finals:
                trace.uncount(rid)  # the copy is not kept, so no colour count keeps it
            return end("duplicate quote")
        quotes.add(quote)
        seen.append(" ".join(str(stored.get("doc_quote")).split())[:CUT])
        if rid not in finals:
            put(rid, _forced(stored, rid))
    return end("repeat_max")
