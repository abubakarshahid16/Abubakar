"""What the Claude lane really cost, per step, and the owner's USD 100 a day (#805 plan change 6 E, #1584).

SETTLED LINES ONLY. A reservation is a call's worst case held before it leaves; it is not a cost. A past report
added holds to spend and said USD 3.71 against a real USD 0.35. So `report` adds up settled lines, and an open hold
(in flight, or its process died) is listed apart under its own words and never in `usd`. `usd_estimated` is the part
of `usd` charged at the worst case because the API's usage is unknown (`claude_spend.settle_failure`).

THE DAY CAP COUNTS MORE THAN THE REPORT, ON PURPOSE. A report says what was spent; a cap must err toward spent. So
`charged_today` also counts an open hold at its worst case, and a line it cannot date. An open hold counts for
`OPEN_HOLD_WINDOW` from when it was placed, across midnight, because a Message Batch may finish that long after its
hold; older, it is a dead process's and stops eating each new day (the total cap keeps it for good). The day is the
UTC day, the same clock as the ledger and the November window in `claude_spend.total_cap`.

`claude_spend.reserve_all` asks here inside its locked step, and every Claude call reserves there, so the cap is one
check on every route. A stored answer (`answer_on_file`) is asked before it and costs nothing, so it still answers.

THE DAY CAP HAS NO SWITCH (owner, #1584: a day cannot exceed USD 100). `claude_cost_controls_enabled`, off, governs
only the report: off, nothing is written. The ledger holds counts and digests, so nothing here can carry document
text. Step names and USD only.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta

from .config import settings

log = logging.getLogger(__name__)

#: A call whose step starts with this is charged to ONE standard (`claude_spend.Caps.for_step`).
STANDARD_STEP_PREFIX = "standards_convert:"
#: Where the figures sit in `review_runs.outcome_json`, and in the audit's AI section.
OUTCOME_KEY = "claude_spend"
#: The owner's cap (#805 plan change 6). The setting can only narrow it: raising it is a reviewed change here.
DAY_CAP_USD = 100.0
#: A Message Batch ends within 24 hours, so its hold can still become a cost for that long.
OPEN_HOLD_WINDOW = timedelta(hours=24)
LEDGER_UNREADABLE = "not recorded: spend ledger unreadable"
HOLD_WORDS = "still held, not cost: an open reservation at its worst case, in flight or its process died"
_ASKED = "Asked is charged calls + stored answers + refused + still held"
_USD = "USD is the list-price estimate of settled calls, not the invoice"
RUN_BOUNDARY = (
    "Claude calls whose ledger line names this review run. Not in it: a document read at upload, a chat "
    f"answer, a call the API rejected unbilled. {_USD}. {_ASKED}"
)
LEDGER_BOUNDARY = (
    "Claude calls on this machine's spend ledger, {whose}. A call the API rejected unbilled is not in it. "
    f"{_USD}. {_ASKED}"
)
USD_FIELDS = ("usd", "usd_estimated", "saved_usd", "held_worst_usd")


def enabled() -> bool:
    return bool(settings.claude_cost_controls_enabled)


def _now() -> datetime:
    return datetime.now(UTC)


def day_cap() -> float:
    return min(float(settings.claude_budget_usd_per_day), DAY_CAP_USD)


def _when(entry: dict) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(entry.get("at")))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def charged_today(lines: Iterable[dict]) -> float:
    """USD the day cap counts, over `claude_spend.entries()`: settled today, plus open holds young enough to become a
    cost, plus any line with no readable time (fail closed, as a torn ledger line does for the total)."""
    now = _now()
    charged = 0.0
    for entry in lines:
        when = _when(entry)
        if when is None:
            counts = True
        elif entry.get("reserved"):
            counts = now - when < OPEN_HOLD_WINDOW
        else:
            counts = when.date() == now.date()
        if counts:
            charged += float(entry.get("cost_usd") or 0)
    return round(charged, 6)


def over_day_cap(worst: float, charged: float) -> str | None:
    """Why this call may not be made, or None."""
    cap = day_cap()
    if charged + worst <= cap:
        return None
    return f"today (UTC): charged ${charged:.4f}, next call up to ${worst:.4f}, cap ${cap:.2f} a day"


def cap_key(step, run: str | None):
    """What the step cap is counted against: step + run; with no run, or for a standard, the step whatever the run."""
    if run and not str(step).startswith(STANDARD_STEP_PREFIX):
        return (run, step)
    return step


def is_runs(step, run: str | None) -> bool:
    """Whether this call is held to its review run's caps: not a call with no run, not a standard."""
    return isinstance(cap_key(step, run), tuple)


def charge(held: dict, step, run: str | None, usd: float) -> None:
    """`usd` on its `cap_key`, and on its run's total `(run,)` when it counts there. A standard's spend does not."""
    key = cap_key(step, run)
    held[key] = held.get(key, 0.0) + usd
    if is_runs(step, run):
        held[(run,)] = held.get((run,), 0.0) + usd


def by_cap(lines: Iterable[dict], run: str | None) -> dict:
    """USD on each key, seen from a call in `run`: only that run's own lines fall on its keys. Holds count, as they
    do for every cap. With no run, each line falls on its step, whichever run wrote it."""
    held: dict = {}
    for entry in lines:
        own = run if entry.get("run") == run else None
        charge(held, entry.get("step"), own, float(entry.get("cost_usd") or 0))
    return held


def run_cap() -> float:
    return float(settings.claude_budget_usd_per_run)


def over_run_cap(step, run: str | None, worst: float, held: dict) -> str | None:
    """Why this call would take its whole review run past the owner's USD 15 (#1584), or None."""
    if not is_runs(step, run):
        return None
    cap, got = run_cap(), round(held.get((run,), 0.0), 6)
    if got + worst <= cap:
        return None
    return f"this review run: spent ${got:.4f}, next call up to ${worst:.4f}, cap ${cap:.2f} per review run"


def over_caps(step, run: str | None, worst: float, lines: list[dict]) -> str | None:
    """The read-only check's question: this run's USD 15, then the day."""
    return over_run_cap(step, run, worst, by_cap(lines, run)) or over_day_cap(
        worst, charged_today(lines)
    )


def _blank(step: str) -> dict:
    return {
        "step": step,
        "asked": 0,
        "calls_charged": 0,
        "stored_answers": 0,
        "batch_calls": 0,
        "refused": 0,
        "usd": 0.0,
        "usd_estimated": 0.0,
        "saved_usd": 0.0,
        "held_calls": 0,
        "held_worst_usd": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


def _add(row: dict, entry: dict) -> None:
    """One ledger line into its step's row. `cost_usd` is read as cost only for a settled line, never for a hold."""
    row["asked"] += 1
    cost = float(entry.get("cost_usd") or 0)
    if entry.get("reserved"):
        row["held_calls"] += 1
        row["held_worst_usd"] += cost
    elif entry.get("cached"):
        row["stored_answers"] += 1
        row["saved_usd"] += float(entry.get("saved_usd") or 0)
    elif entry.get("refused"):
        row["refused"] += 1
    else:
        row["calls_charged"] += 1
        row["usd"] += cost
        row["usd_estimated"] += cost if entry.get("estimated") else 0.0
        row["batch_calls"] += 1 if entry.get("batch") else 0
        row["input_tokens"] += int(entry.get("input_tokens") or 0)
        row["output_tokens"] += int(entry.get("output_tokens") or 0)
        row["cache_read_tokens"] += int(entry.get("cache_read_input_tokens") or 0)
        row["cache_write_tokens"] += int(entry.get("cache_creation_input_tokens") or 0)


def _wanted(entry: dict, run_id, start, step_prefix) -> bool:
    if run_id is not None and entry.get("run") != run_id:
        return False
    if step_prefix and not str(entry.get("step") or "").startswith(step_prefix):
        return False
    if start is not None:
        when = _when(entry)
        return when is not None and when >= start
    return True


def _boundary(run_id, since, step_prefix) -> str:
    if run_id is not None:
        return RUN_BOUNDARY
    whose = [f"steps starting {step_prefix!r}"] if step_prefix else []
    whose.append(f"since {since}" if since else "the whole ledger")
    return LEDGER_BOUNDARY.format(whose=", ".join(whose))


def report(
    lines: Iterable[dict],
    *,
    run_id: str | None = None,
    since: str | None = None,
    step_prefix: str | None = None,
) -> dict:
    """Spend per step over `claude_spend.entries()`: one review run (`run_id`), or a time window and step prefix.
    A reservation settled twice (a crash between the settlement and its commit) is one call here."""
    start = None
    if since is not None:
        start = datetime.fromisoformat(since).replace(microsecond=0)
        start = start if start.tzinfo else start.replace(tzinfo=UTC)
    rows: dict[str, dict] = {}
    seen: set[str] = set()
    unreadable = 0
    for entry in lines:
        if entry.get("corrupt"):  # no run, step or time: nobody can say whose it was
            unreadable += 1
            continue
        settles = entry.get("settles")
        if settles in seen or not _wanted(entry, run_id, start, step_prefix):
            continue
        if settles:
            seen.add(settles)
        step = str(entry.get("step") or "")
        _add(rows.setdefault(step, _blank(step)), entry)
    steps = sorted(rows.values(), key=lambda r: r["step"])
    totals = {k: sum(r[k] for r in steps) for k in _blank("") if k != "step"}
    for row in [*steps, totals]:
        for name in USD_FIELDS:
            row[name] = round(row[name], 6)
    return {
        **totals,
        "steps": steps,
        "unreadable_lines": unreadable,
        "held_words": HOLD_WORDS,
        "boundary": _boundary(run_id, since, step_prefix),
    }


def for_review_run(review_run_id: str) -> dict:
    from . import claude_spend

    return report(claude_spend.entries(), run_id=review_run_id)


def record_run(review_run_id: str | None) -> None:
    """Write this run's spend per step in its record. Switch off, or a run with no Claude call: nothing. An unreadable
    ledger says so on the run, and never breaks a finished review."""
    if not enabled() or not review_run_id:
        return
    from .db import connect

    try:
        figures: dict = for_review_run(review_run_id)
    except (OSError, ValueError) as exc:
        log.warning("claude spend: the ledger is unreadable (%s)", type(exc).__name__)
        figures = {"not_recorded": LEDGER_UNREADABLE}
    if figures.get("asked") == 0:
        return
    try:
        conn = connect()
        row = conn.execute(
            "SELECT outcome_json FROM review_runs WHERE id = ?", (review_run_id,)
        ).fetchone()
        if row is None:
            return
        outcome = json.loads(row["outcome_json"] or "{}")
        outcome[OUTCOME_KEY] = figures
        with conn:
            conn.execute(
                "UPDATE review_runs SET outcome_json = ? WHERE id = ?",
                (json.dumps(outcome), review_run_id),
            )
    except (ValueError, sqlite3.Error) as exc:
        log.warning(
            "claude spend: the run record was not written (%s)", type(exc).__name__
        )


@contextlib.contextmanager
def for_route(review_run_id: str) -> Iterator[None]:
    """A reviewer's Claude route on a finished run: its calls name the run, so the run's USD 5 per step is what they
    are held to, switch or no switch. With the report's switch on, the run's record is brought up to date."""
    from . import claude_spend

    try:
        with claude_spend.for_run(review_run_id):
            yield
    finally:
        record_run(review_run_id)
