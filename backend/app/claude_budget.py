"""The two numbers that keep a $20 API credit from vanishing in one run.

WHY THIS EXISTS. The first measured reader run cost $0.22 for three pages;
the whole corpus would cost about $500. The four model-assisted routes in
`claude_api` each make two calls per item (rule 5: asked twice, answered twice
the same), so a run over a datasheet with fifty findings is two hundred calls
before anyone notices. Nothing in the modules stops a loop, a re-run or a
mistaken corpus pass from spending the credit the demo needs.

TWO CONTROLS, BOTH DUMB ON PURPOSE:

  1. A CAP PER RUN. `Budget(max_calls)` wraps a `model_call`; the
     (max_calls + 1)th call raises `BudgetExhausted` instead of going out.
     The routes catch it, stop the run where it stands, and report
     `budget_exhausted` in the counts beside everything the run did get done.
     A run that stops early is reported as stopped early, never as complete.
     The cap comes from `STANDARDS_READER_MAX_CALLS_PER_RUN` (default 200).

  2. A RUNNING TOTAL. After every route, the transport's `usage` is added to
     one row in `model_spend`, which survives restarts. Every route answers
     with `spend_total`, so the person watching the demo sees the same number
     as the person paying for it. The dollar figure is an ESTIMATE from list
     prices in `PRICE_PER_MILLION` and says so; the invoice is the truth.

WHAT THIS IS NOT. Not a rate limiter and not a lock: two routes running at
once each get their own cap. It exists so that one route cannot spend more
than one route's worth, and so the total is never a surprise.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from .db import connect

ENV_MAX_CALLS = "STANDARDS_READER_MAX_CALLS_PER_RUN"
DEFAULT_MAX_CALLS = 200

BUDGET_EXHAUSTED = "budget_exhausted"

#: USD per million tokens, list price, for the estimate only. Keyed by the
#: first two words of the model id so a dated id still finds its family.
PRICE_PER_MILLION = {
    "claude-sonnet": (3.0, 15.0),
    "claude-haiku": (0.8, 4.0),
    "claude-opus": (15.0, 75.0),
}


class BudgetExhausted(RuntimeError):
    """The run's call cap was reached. The calls before it stand."""

    def __init__(self, max_calls: int):
        super().__init__(f"model call cap of {max_calls} reached for this run")
        self.max_calls = max_calls


def max_calls_per_run(env=None) -> int:
    env = os.environ if env is None else env
    raw = (env.get(ENV_MAX_CALLS) or "").strip()
    if not raw:
        return DEFAULT_MAX_CALLS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_CALLS
    return max(0, value)


class Budget:
    """A `model_call` that counts, and refuses past the cap."""

    def __init__(self, model_call, max_calls: int | None = None):
        self._call = model_call
        self.max_calls = max_calls_per_run() if max_calls is None else max_calls
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        if self.calls >= self.max_calls:
            raise BudgetExhausted(self.max_calls)
        self.calls += 1
        return self._call(prompt)

    @property
    def remaining(self) -> int:
        return max(0, self.max_calls - self.calls)


# ------------------------------------------------------------------ the total
def ensure_schema() -> None:
    conn = connect()
    with conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS model_spend (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                calls INTEGER NOT NULL DEFAULT 0,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT
            )""")
        conn.execute(
            "INSERT OR IGNORE INTO model_spend (id, calls, input_tokens, output_tokens)"
            " VALUES (1, 0, 0, 0)")


def record(usage: dict | None) -> dict:
    """Add one transport's usage to the running total; return the total."""
    ensure_schema()
    usage = usage or {}
    conn = connect()
    with conn:
        conn.execute(
            "UPDATE model_spend SET calls = calls + ?, input_tokens = input_tokens + ?,"
            " output_tokens = output_tokens + ?, updated_at = ? WHERE id = 1",
            (int(usage.get("calls") or 0), int(usage.get("input_tokens") or 0),
             int(usage.get("output_tokens") or 0),
             datetime.now(timezone.utc).isoformat(timespec="seconds")))
    return total()


def total(model: str | None = None) -> dict:
    ensure_schema()
    row = connect().execute(
        "SELECT calls, input_tokens, output_tokens, updated_at FROM model_spend WHERE id = 1"
    ).fetchone()
    out = dict(row) if row else {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                 "updated_at": None}
    out["estimated_usd"] = estimate_usd(out["input_tokens"], out["output_tokens"], model)
    return out


def estimate_usd(input_tokens: int, output_tokens: int, model: str | None = None) -> float:
    """List-price estimate, rounded to the cent. Sonnet prices when the model
    is unknown, because that is the reader's default."""
    family = "-".join((model or "claude-sonnet").split("-")[:2])
    per_in, per_out = PRICE_PER_MILLION.get(family, PRICE_PER_MILLION["claude-sonnet"])
    return round((input_tokens * per_in + output_tokens * per_out) / 1_000_000, 2)
