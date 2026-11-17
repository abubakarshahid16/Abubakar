"""The money of the online search for rule books not held (order 14, paid run of 17 Nov 2026): no hold is left open, and the
review's own recorded cost includes what its search cost.

WHAT WENT WRONG. A paid pump review on a copy made two search holds (`claude_spend.reserve`) that were never settled or released:
the job marked the run "completed" BEFORE the search ran, the trial driver saw "completed" and stopped the app, and the worker
thread (a daemon) ended with the request in flight, so `search_one`'s own `finally` never ran. The ledger counted both holds at
their worst case for good, and the run's `usd` (written before the search) did not hold the search fee.

NOW: the search runs before the run is marked completed (`agent_review_jobs._done`); every search run first closes this step's
holds that are older than any search request can still be running (`close_stale_holds`: settled at their worst
case, marked estimated, never released, since whether the API billed them is unknown); and after the search its ledger cost
for the run is added to `agent_review_run.usd`, the part stated apart under `counts_json[COST_KEY]` (so the CRS file says the
search is included). Counts and ids only, never a name or an answer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from . import claude_spend
from .db import connect

#: The run's counts key that holds the search's part of the run's `usd` (present only once it was added).
COST_KEY = "online_search_usd"
#: A search request ends within its own timeout (60 s) and a run's search within its time limit (180 s); an hour later no
#: request of this step can still be running, so a hold that old was left by a process that ended.
STALE_AFTER_SECONDS = 3600.0
STALE_REASON = "process_ended"
#: The CRS row of a run whose `usd` includes the search (`COST_ROW` of `standards_web_search` says it is not included).
COST_ROW_INCLUDED = "Online search for rule books not held: cost (USD, included in the AI review's cost)"


def _stale(e: dict, step: str, cutoff: datetime) -> bool:
    """True for an OPEN hold of `step` made at or before `cutoff`. A line whose time cannot be read stays open (counted)."""
    if not e.get("reserved") or not e.get("reservation") or e.get("step") != step:
        return False
    try:
        at = datetime.fromisoformat(str(e.get("at")))
    except ValueError:
        return False
    return at.tzinfo is not None and at <= cutoff


def close_stale_holds(step: str, *, older_than_s: float, reason: str) -> list[dict]:
    """Settle every hold of `step` still open `older_than_s` seconds after it was made: the process that held it ended before
    it could settle or release it (a stop, a crash, a worker thread ended at exit). Whether the API billed it is unknown, so it is
    NEVER released: settled at its reserved worst case, marked `"estimated": true`, `finish_reason` `failed:<reason>`, on the run
    it was held for. The caps see the same figure as before; the hold is now closed and counted once. The check and the write are
    ONE step under the ledger's own lock, so a hold is closed exactly once however many callers sweep. Returns the settlement
    lines written (each names the hold it `settles`): counts and ids, never text. The caps are unchanged."""
    cutoff = datetime.now(UTC) - timedelta(seconds=float(older_than_s))
    out: list[dict] = []
    with claude_spend._ledger_lock():
        for e in claude_spend.entries():
            if not _stale(e, step, cutoff):
                continue
            line = claude_spend._entry(
                step=step,
                model=str(e.get("model") or ""),
                usage=None,
                prompt_sha256=str(e.get("prompt_sha256") or ""),
                wall_time_s=0.0,
                finish_reason=f"failed:{reason}",
                batch=bool(e.get("batch")),
                estimated_usd=float(e.get("cost_usd") or 0.0),
            )
            line.pop("run", None)  # the hold's run, never the caller's
            if e.get("run") is not None:
                line["run"] = e["run"]
            line["settles"] = e["reservation"]
            claude_spend._append(line)
            out.append(line)
    return out


def close_stale(step: str) -> int:
    """Close this step's holds left open by a process that ended; how many were closed."""
    return len(
        close_stale_holds(step, older_than_s=STALE_AFTER_SECONDS, reason=STALE_REASON)
    )


def run_cost(run_id: str, step: str) -> float:
    """What the ledger charges this run's search: settled lines, closed stale holds and any hold still open at its worst case."""
    return round(
        sum(
            float(e.get("cost_usd") or 0.0)
            for e in claude_spend.entries()
            if e.get("run") == run_id and e.get("step") == step
        ),
        6,
    )


def add_to_run(run_id: str, step: str) -> float | None:
    """Make the run's `usd` include its search cost, once: the earlier added part is replaced, never added twice. None (and
    nothing changed) when the run has no row, or its search cost nothing and none was added before."""
    cost = run_cost(run_id, step)
    with connect() as conn:
        row = conn.execute(
            "SELECT usd, counts_json FROM agent_review_run WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        counts = json.loads(row["counts_json"] or "{}")
        before = float(counts.get(COST_KEY) or 0.0)
        if not cost and COST_KEY not in counts:
            return None
        own = float(row["usd"] or 0.0) - before
        counts[COST_KEY] = cost
        conn.execute(
            "UPDATE agent_review_run SET usd = ?, counts_json = ? WHERE run_id = ?",
            (round(own + cost, 6), json.dumps(counts, default=str), run_id),
        )
    return cost


def included(counts_json: str | None) -> bool:
    """True when the run's `usd` includes its search cost (a run recorded before this change does not)."""
    try:
        return COST_KEY in (json.loads(counts_json or "{}") or {})
    except (TypeError, ValueError):
        return False
