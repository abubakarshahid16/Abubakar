"""#1584: what the compiler may still spend, read from the spend ledger. Writes nothing there except a release.

The caps are the owner's: USD 25 per standard, USD 100 a day, USD 500 in total. `claude_spend` will own the shared day
cap (#1595); until then `spent_today` reads its ledger, every route of it.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from . import claude_batch_run, claude_spend, standards_converter

#: Seconds. A batch ends within 24 hours, so a hold older than this that nothing owns has no call behind it.
STALE_HOLD_S = 25 * 3600.0


def _spent_today() -> float:
    """USD on EVERY route of the ledger today (UTC), open reservations at their worst case: the owner's USD 100 a day is
    the day's, not this job's. `claude_spend` will own the shared day cap (#1595); until then this reads its ledger."""
    today = datetime.now(UTC).date().isoformat()
    return sum(
        float(e.get("cost_usd") or 0)
        for e in claude_spend.entries()
        if str(e.get("at") or "").startswith(today)
    )


def release_left_over_holds(
    conn, steps, *, clock=time.time, force: bool = False
) -> dict:
    """A hold nothing in this copy owns must not block a standard for good: a process died holding it. On these steps, one
    older than `STALE_HOLD_S` (a batch cannot run longer) is released; with `force`, any age, for the operator who knows
    no other copy is running. The USD is reported: it may have been billed, and the invoice is the truth."""
    claude_batch_run.ensure_schema(conn)
    owned = {
        r["reservation_id"]
        for r in conn.execute(
            "SELECT reservation_id FROM claude_batch_requests WHERE state IN ('held', 'unconfirmed')"
        )
    }
    released = 0
    usd = 0.0
    for line in claude_spend.entries():
        if not line.get("reserved") or line.get("step") not in steps:
            continue
        if line.get("reservation") in owned:
            continue
        age = clock() - datetime.fromisoformat(line["at"]).timestamp()
        if force or age >= STALE_HOLD_S:
            claude_spend.release(
                claude_spend.Reservation(
                    line["reservation"],
                    line["step"],
                    str(line.get("model") or ""),
                    float(line.get("cost_usd") or 0),
                    "",
                    time.time(),
                    bool(line.get("batch")),
                ),
                "left_over_hold",
            )
            released += 1
            usd += float(line.get("cost_usd") or 0)
    return {"holds_released": released, "holds_released_usd": round(usd, 6)}


def _room_gate(max_usd: float):
    """(USD free on this standard's step, USD free in total and today): the USD 25 per standard (#1584: it governs here,
    not the USD 5 per step, because the step is `standards_convert:<standard>`), the total, and today's limit. A hair
    under, for the ledger's rounding, so the reservation behind it never refuses what this let through."""

    def room(step: str) -> tuple[float, float]:
        caps = claude_spend.Caps.from_settings().for_step(step)
        shared = min(caps.total - claude_spend.spent(), max_usd - _spent_today())
        return caps.per_step - claude_spend.spent(step) - 0.00001, shared - 0.00001

    return room


def _spent_on(label: str) -> dict:
    step = standards_converter.step_for(label)
    lines = [e for e in claude_spend.entries() if e.get("step") == step]
    return {
        "usd_on_this_standards_step": round(
            sum(float(e.get("cost_usd") or 0) for e in lines if not e.get("reserved")),
            6,
        ),
        "usd_still_held": round(
            sum(float(e.get("cost_usd") or 0) for e in lines if e.get("reserved")), 6
        ),
        "usd_boundary": "every call in the spend ledger charged to this standard's step, list-price estimate",
        "cache_read_tokens": sum(
            int(e.get("cache_read_input_tokens") or 0) for e in lines
        ),
        "cache_write_tokens": sum(
            int(e.get("cache_creation_input_tokens") or 0) for e in lines
        ),
        "input_tokens": sum(int(e.get("input_tokens") or 0) for e in lines),
        "output_tokens": sum(int(e.get("output_tokens") or 0) for e in lines),
    }
