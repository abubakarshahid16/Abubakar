"""What the second AI (Groq) has cost, and the refusal before it costs more. Its OWN ledger and caps, apart from Claude's
(`claude_spend` is not touched and does not count these dollars).

CAPS (settings): `groq_crosscheck_usd_per_run` (default USD 0.50 for one review run) and `groq_crosscheck_usd_per_day`
(default USD 2.00 for one UTC day). A call RESERVES its worst case (every prompt byte a token, every allowed output token
spent: a strict upper bound) under the ledger lock before it leaves; the reservation is refused when it could cross either
cap. After the call it is SETTLED to what the answer's usage says (else the worst case), or RELEASED when the call provably
did no billable work (`groq_transport.unbilled`: refused here, never connected, or a 4xx). A reservation a dead process
left open counts at its worst case for good: errs toward spent.

THE LEDGER is a local JSONL file, `<data_dir>/groq_spend.jsonl`: time, run id, model, cost, and nothing else. Never a
prompt, a quote, an answer or the key. A torn line counts at the day cap (fail closed), as `claude_spend` does.

PRICES are list prices per million tokens (input, output) as known on 16 Nov 2026: an ESTIMATE, the invoice is the truth.
A model id not in the table is priced at `UNKNOWN_PRICE`, dearer than any listed, so a wrong id spends the cap slowly
rather than overshooting it.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import settings

log = logging.getLogger(__name__)

LEDGER_NAME = "groq_spend.jsonl"
#: USD per million tokens (input, output).
PRICES: dict[str, tuple[float, float]] = {
    "openai/gpt-oss-120b": (0.15, 0.75),
    "openai/gpt-oss-20b": (0.10, 0.50),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "qwen/qwen3-32b": (0.29, 0.59),
}
UNKNOWN_PRICE = (5.0, 15.0)
#: Tokens the chat template adds around the messages, counted on top of the characters.
TEMPLATE_TOKENS = 200
NO_RUN = "no_run"
RUN_CAP, DAY_CAP = "groq_run_cap", "groq_day_cap"


class GroqBudgetExceeded(RuntimeError):
    """The next call could cross a cap; it was not sent. `code` is RUN_CAP or DAY_CAP."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Reservation:
    id: str
    run: str
    model: str
    worst: float
    day: str


def price_for(model: str | None) -> tuple[float, float]:
    return PRICES.get(str(model or ""), UNKNOWN_PRICE)


def worst_case_usd(model: str | None, prompt_bytes: int, max_tokens: int) -> float:
    """The most one call could cost, a STRICT upper bound (review R-1854): a token is at least one byte of the UTF-8 prompt, so
    the prompt is at most `prompt_bytes` tokens plus the chat template's own, and every allowed output token is spent."""
    pin, pout = price_for(model)
    tokens_in = int(prompt_bytes) + TEMPLATE_TOKENS
    return round(tokens_in * pin / 1e6 + int(max_tokens) * pout / 1e6, 8)


def cost_usd(model: str | None, usage: object) -> float | None:
    """The cost from the answer's `usage` (prompt_tokens, completion_tokens), or None when it reported none."""
    if not isinstance(usage, dict):
        return None
    try:
        tin, tout = int(usage.get("prompt_tokens")), int(usage.get("completion_tokens"))
    except (TypeError, ValueError):
        return None
    pin, pout = price_for(model)
    return round(max(0, tin) * pin / 1e6 + max(0, tout) * pout / 1e6, 8)


def ledger_path() -> Path:
    return Path(settings.data_dir) / LEDGER_NAME


_THREAD_LOCK = threading.Lock()


@contextmanager
def _ledger_lock():
    """Exclusive access between threads of this process and, on POSIX, between processes using the same ledger."""
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _THREAD_LOCK, path.with_name(path.name + ".lock").open("a+b") as fh:
        try:
            import fcntl
        except ImportError:  # Windows: the thread lock alone
            yield
            return
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _raw_lines() -> list[dict]:
    path = ledger_path()
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except ValueError:
            value = None
        # a torn line is not "nothing spent": it counts at the day cap (fail closed)
        if not isinstance(value, dict):
            value = {"corrupt": True, "run": "", "day": _today(), "cost_usd": day_cap()}
        out.append(value)
    return out


def entries() -> list[dict]:
    """The ledger as calls: a settled reservation as its settlement, a released one not at all, an open one at its worst."""
    lines = _raw_lines()
    closed = {e.get("settles") for e in lines if e.get("settles")}
    closed |= {e.get("releases") for e in lines if e.get("releases")}
    return [
        e
        for e in lines
        if not e.get("releases")
        and not (e.get("reservation") and e["reservation"] in closed)
    ]


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def run_cap() -> float:
    return float(settings.groq_crosscheck_usd_per_run)


def day_cap() -> float:
    return float(settings.groq_crosscheck_usd_per_day)


def spent(*, run: str | None = None, day: str | None = None) -> float:
    """USD on the ledger for one run, one UTC day, or in all."""
    return round(
        sum(
            float(e.get("cost_usd") or 0.0)
            for e in entries()
            if (run is None or e.get("run") == run)
            and (day is None or e.get("day") == day)
        ),
        8,
    )


def _append(entry: dict) -> None:
    path = ledger_path()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def reserve(run: str | None, model: str, worst: float) -> Reservation:
    """Check both caps AND write the reservation in one step under the lock; `GroqBudgetExceeded` when it could cross one."""
    run = str(run or NO_RUN)
    worst = float(worst)
    with _ledger_lock():
        today = _today()
        if spent(run=run) + worst > run_cap():
            raise GroqBudgetExceeded(RUN_CAP)
        if spent(day=today) + worst > day_cap():
            raise GroqBudgetExceeded(DAY_CAP)
        res = Reservation(uuid.uuid4().hex, run, str(model), worst, today)
        _append(
            {"reservation": res.id, "at": datetime.now(UTC).isoformat(timespec="seconds"), "day": today,
             "run": run, "model": res.model, "cost_usd": worst}
        )  # fmt: skip
    return res


def settle(res: Reservation, usd: float | None) -> float:
    """Close the reservation at what the call cost (its usage), else at the reserved worst case. Returns what was charged.

    NEVER ABOVE THE RESERVATION (review R-1854): the caps were checked against the reservation, so a settlement above it could
    pass a cap. The charge is capped at the reserved worst case; anything above it is written on the line as `excess_usd` and
    logged as a warning (the reservation is a strict bound, so this means the price table or the usage is wrong)."""
    reported = res.worst if usd is None else float(usd)
    charged = min(reported, res.worst)
    excess = round(reported - charged, 8)
    if excess > 0:
        log.warning(
            "groq spend: a call reported more than its reservation (excess USD %.6f)",
            excess,
        )
    with _ledger_lock():
        _append(
            {"settles": res.id, "at": datetime.now(UTC).isoformat(timespec="seconds"), "day": res.day,
             "run": res.run, "model": res.model, "cost_usd": charged, "estimated": usd is None,
             **({"excess_usd": excess} if excess > 0 else {})}
        )  # fmt: skip
    return charged


def release(res: Reservation) -> float:
    """The call provably did no billable work: the reservation counts nothing. Returns 0.0."""
    with _ledger_lock():
        _append({"releases": res.id, "run": res.run, "day": res.day, "cost_usd": 0.0})
    return 0.0
