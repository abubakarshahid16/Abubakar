"""Sweep items (#1690): one skill item with `repeat: true` yields several findings.

The runner runs the item again and again as ordinary items, each run through the SAME loop and the same
record_finding checks. Run n is named `<item id>#<n>`; it is told, in `already_recorded`, the doc quotes (80 chars
each) already accepted in runs 1..n-1 and is asked for one NEW matching field. The sweep stops when a run ends
without an accepted finding, when a doc quote is accepted twice (the second is dropped), or at `repeat_max`.
A sweep finding is never GREEN or RED: the colour is forced to YELLOW here (a restriction only). No document
text goes anywhere new: `already_recorded` is only in the model prompt of the same run.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import agent_loop

DEFAULT_MAX = 15
SEP = "#"
CUT = 80


def is_sweep(skill_item: Any) -> bool:
    return isinstance(skill_item, dict) and skill_item.get("repeat") is True


def fold(text: Any) -> str:
    return " ".join(str(text or "").split())


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


def _forced(finding: dict, rid: str) -> dict:
    out = {**finding, "item": rid, "sweep": True}
    if out.get("color") in ("GREEN", "RED"):
        out["color"] = "YELLOW"
    return out


def run_sweep(
    loop_item: dict,
    skill_item: dict,
    finals: dict,
    sink: Any,
    run_one: Callable[[dict, dict], tuple[dict | None, str]],
    put: Callable[[str, dict], None],
    halt: Callable[[], str],
) -> str:
    """Run the repeats of one item. Returns "" or the reason the whole run stops (a cap, a trip, a fatal)."""
    iid = str(loop_item["id"])
    limit = skill_item.get("repeat_max", DEFAULT_MAX)
    seen: list[str] = []
    quotes: set[str] = set()
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
        stored = sink.get(rid)
        if stored is None:
            if (
                rid not in finals and n == 1
            ):  # nothing found at all: the item's one honest yellow
                put(
                    rid,
                    _forced(
                        res["finding"]
                        if res
                        else agent_loop.yellow("result lost in a restart", loop_item),
                        rid,
                    ),
                )
            return ""
        quote = fold(stored.get("doc_quote"))
        if quote in quotes:
            return ""  # the same quote twice: the repeat is over, the copy is not kept
        quotes.add(quote)
        seen.append(quote[:CUT])
        if rid not in finals:
            put(rid, _forced(stored, rid))
    return ""
