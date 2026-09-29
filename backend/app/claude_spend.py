"""What the Claude API has cost, and the refusal before it costs more.

OWNER RULE 2026-09-25: USD 5 per step, USD 20 in total; stop BEFORE exceeding
either. So the check is made before a call leaves, on the WORST CASE of that
call (every prompt token uncached, every allowed output token spent), against
what the ledger says was already spent. A call that could cross a cap is
refused - it never goes out and then gets reported as over budget.

THE LEDGER is a local JSONL file (`settings.claude_spend_log`), one line per
call: time, step, model, token counts, cost, and a digest of the prompt. It is
not in the database on purpose - measured runs use disposable database copies,
and a total kept in a copy would forget every run made against another copy.
It never holds prompt text, document text or the key.

THE CHECK IS A RESERVATION, NOT A READ (audit 2026-09-30). Checking the
ledger, sending, and only then writing the ledger let ten threads at $4.90
each see "$4.90 spent" and all send: the step reached $5.80. So a call now
`reserve`s its worst case - check AND ledger line in one step, under the
ledger lock - before it leaves, and `settle`s that reservation afterwards to
what it actually cost. Until it is settled, the reservation counts at its
worst case; a process that dies mid-call leaves it counted that way for
good, which errs toward spent, never toward unspent. `reasoning_provider`
(single call, stream and batch) and `metered` (the four `claude_api` review
routes) all go through `reserve`/`settle`/`settle_failure`. There is one
ledger; the per-run call cap in `claude_budget` is a second, separate limit,
not a second record of dollars. `ensure_affordable` remains as a read-only
check; it reserves nothing and is not a guard on its own.

A CALL THAT FAILS MAY STILL HAVE BEEN BILLED - a read timeout after the API
did the work, a stream dropped mid-answer, an answer refused locally for its
size. `settle_failure` charges such a call its actual usage when the API
reported it, otherwise the reserved worst case (marked `"estimated": true`),
and releases the reservation only when `unbilled(exc)` proves the API did no
billable work.

WHAT THE LOCK GUARANTEES. `_ledger_lock` is a process-local mutex plus an
exclusive OS lock on `<ledger>.lock` (`fcntl.flock` on POSIX, `msvcrt.locking`
on Windows). So the check-and-reserve is atomic between threads of one
process AND between processes on the same machine that use the SAME ledger
path through this module. It is NOT guaranteed: for processes pointed at
different ledger files (each is its own budget, by construction); on a
network filesystem whose locks are advisory or unsupported; or against
anything that writes the JSONL without this module. Settled figures are the
list-price ESTIMATE below, not the invoice.

PRICES are list prices per million tokens from Anthropic's pricing page
(platform.claude.com/docs/en/about-claude/pricing, read 2026-09-25). They are
an ESTIMATE; the invoice is the truth. An unknown model is priced at the most
expensive family listed, so an estimate errs toward refusing.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

#: (input, output, 5-minute cache write, cache read) USD per million tokens.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-sonnet-5": (2.0, 10.0, 2.5, 0.20),
    "claude-sonnet-4-6": (3.0, 15.0, 3.75, 0.30),
    "claude-sonnet-4-5": (3.0, 15.0, 3.75, 0.30),
    "claude-haiku-4-5": (1.0, 5.0, 1.25, 0.10),
    "claude-opus-5-5": (4.0, 20.0, 5.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 6.25, 0.50),
}
#: The price used for a model id not in the table: the dearest listed.
_UNKNOWN = max(PRICES.values())
#: Message Batches API: every token at half the list price (same pricing
#: page, "Batch processing"). Applied to all four rates; the caps and the
#: ledger are the same as for a single call.
BATCH_DISCOUNT = 0.5


class StopRun(RuntimeError):
    """A limit stopped a run before its next call. The calls before it were
    made and paid for, so a loop over items may catch this, keep what it
    finished and report itself stopped under `count_key`."""

    count_key = "stopped"


class BudgetExceeded(StopRun):
    """The next call could cross a USD cap, so it was not made."""

    count_key = "usd_cap_reached"


def price_for(model: str | None) -> tuple[float, float, float, float]:
    """List prices for `model`; a dated id ('...-20251001') finds its family."""
    name = (model or "").lower()
    for key in sorted(PRICES, key=len, reverse=True):
        if name == key or name.startswith(key + "-") or re.fullmatch(rf"{re.escape(key)}-\d{{8}}", name):
            return PRICES[key]
    return _UNKNOWN


def cost_usd(model: str | None, usage: dict | None, *, batch: bool = False) -> float:
    """USD for one call from the API's `usage` block; a Message Batches
    result (`batch=True`) at half price."""
    usage = usage or {}
    p_in, p_out, p_write, p_read = price_for(model)
    full = (int(usage.get("input_tokens") or 0) * p_in
            + int(usage.get("output_tokens") or 0) * p_out
            + int(usage.get("cache_creation_input_tokens") or 0) * p_write
            + int(usage.get("cache_read_input_tokens") or 0) * p_read) / 1_000_000
    return full * BATCH_DISCOUNT if batch else full


def worst_case_usd(model: str | None, prompt_chars: int, max_tokens: int,
                   image_tokens: int = 0, *, batch: bool = False) -> float:
    """The most one call can cost: prompt at ~3 chars per token (generous -
    English runs nearer 4), plus any image's tokens (width x height / 750),
    priced as an uncached cache WRITE (the dearest input rate), plus every
    allowed output token. Half for a batch request."""
    p_in, p_out, p_write, _ = price_for(model)
    tokens_in = prompt_chars // 3 + 1 + max(0, int(image_tokens))
    full = (tokens_in * max(p_in, p_write) + max_tokens * p_out) / 1_000_000
    return full * BATCH_DISCOUNT if batch else full


def _ledger_path() -> Path:
    return Path(settings.claude_spend_log)


#: Serialises ledger access between threads of this process; the OS lock in
#: `_ledger_lock` does the same between processes.
_THREAD_LOCK = threading.Lock()
#: How long to wait for another process's ledger lock before refusing.
LOCK_TIMEOUT_S = 30.0


def _os_lock(fh) -> None:
    try:
        import fcntl
    except ImportError:          # Windows
        import msvcrt
        deadline = time.monotonic() + LOCK_TIMEOUT_S
        while True:
            fh.seek(0)
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if time.monotonic() > deadline:
                    raise BudgetExceeded("the spend ledger is locked by another process; "
                                         "the call was not made") from None
                time.sleep(0.02)
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)


def _os_unlock(fh) -> None:
    try:
        import fcntl
    except ImportError:
        import msvcrt
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        return
    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


@contextmanager
def _ledger_lock():
    """Exclusive access to the ledger - see the module docstring for what
    this does and does not guarantee across processes. Not re-entrant."""
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _THREAD_LOCK:
        with open(path.with_name(path.name + ".lock"), "a+b") as fh:
            _os_lock(fh)
            try:
                yield
            finally:
                _os_unlock(fh)


def _raw_lines() -> list[dict]:
    path = _ledger_path()
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                out.append(value)
    return out


def entries() -> list[dict]:
    """The ledger as calls: a settled reservation shows as its settlement
    only, a released one not at all, and an OPEN one (still in flight, or
    its process died) at its reserved worst case, marked `"reserved": true`."""
    lines = _raw_lines()
    closed = {e.get("settles") for e in lines if e.get("settles")} | {
        e.get("releases") for e in lines if e.get("releases")}
    return [e for e in lines
            if not e.get("releases") and not (e.get("reservation") and e["reservation"] in closed)]


def _append(entry: dict) -> None:
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def spent(step: str | None = None) -> float:
    """USD spent in total, or on one step."""
    return round(sum(float(e.get("cost_usd") or 0) for e in entries()
                     if step is None or e.get("step") == step), 6)


@dataclass(frozen=True)
class Caps:
    per_step: float
    total: float

    @classmethod
    def from_settings(cls) -> Caps:
        return cls(float(settings.claude_budget_usd_per_step), float(settings.claude_budget_usd_total))


def ensure_affordable(step: str, worst_case: float, caps: Caps | None = None) -> None:
    """Refuse (raise) when `worst_case` on top of what is spent could cross
    the step cap or the total cap. READ-ONLY: it reserves nothing, so two
    callers can both pass it - a call that is about to be sent must use
    `reserve` instead."""
    _check(step, worst_case, caps or Caps.from_settings(), spent(step), spent())


def _check(step: str, worst_case: float, caps: Caps, step_spent: float, total_spent: float) -> None:
    if step_spent + worst_case > caps.per_step:
        raise BudgetExceeded(
            f"step {step!r}: spent ${step_spent:.4f}, next call up to ${worst_case:.4f}, "
            f"cap ${caps.per_step:.2f} per step")
    if total_spent + worst_case > caps.total:
        raise BudgetExceeded(
            f"total: spent ${total_spent:.4f}, next call up to ${worst_case:.4f}, "
            f"cap ${caps.total:.2f} in total")


def _entry(*, step: str, model: str, usage: dict | None, prompt_sha256: str,
           wall_time_s: float, finish_reason: str, batch: bool = False,
           estimated_usd: float | None = None) -> dict:
    usage = usage or {}
    entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "step": step, "model": model,
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens") or 0),
        "cache_read_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
        "cost_usd": round(cost_usd(model, usage, batch=batch), 6),
        "prompt_sha256": prompt_sha256, "wall_time_s": round(wall_time_s, 3),
        "finish_reason": finish_reason,
    }
    if batch:
        entry["batch"] = True
    if estimated_usd is not None:
        entry["cost_usd"] = round(float(estimated_usd), 6)
        entry["estimated"] = True
    return entry


def record(*, step: str, model: str, usage: dict | None, prompt_sha256: str,
           wall_time_s: float, finish_reason: str, batch: bool = False,
           estimated_usd: float | None = None) -> dict:
    """Append one call to the ledger and return the entry. Counts and a
    digest only - never text, never the key. A batch result is priced at the
    batch rate and marked `"batch": true`. `estimated_usd` is for a call
    whose real usage is unknown (it may have been billed but its answer was
    lost): that figure is charged and the entry is marked `"estimated": true`.
    For a call that is about to be SENT use `reserve` + `settle`; `record` is
    for a cost with no pre-send check to make (a cache hit at USD 0)."""
    entry = _entry(step=step, model=model, usage=usage, prompt_sha256=prompt_sha256,
                   wall_time_s=wall_time_s, finish_reason=finish_reason, batch=batch,
                   estimated_usd=estimated_usd)
    with _ledger_lock():
        _append(entry)
    return entry


@dataclass(frozen=True)
class Reservation:
    """A call's worst case, already in the ledger, waiting to be settled."""

    id: str
    step: str
    model: str
    worst_usd: float
    prompt_sha256: str
    started: float
    batch: bool = False


def reserve_all(items: list[tuple[str, float]], *, model: str, prompt_sha256: str = "",
                batch: bool = False, caps: Caps | None = None) -> list[Reservation]:
    """Check and reserve every `(step, worst_case)` in ONE locked step: all
    fit together, or `BudgetExceeded` is raised and nothing is reserved.
    Each item is checked on top of the ledger AND the items before it, so a
    batch cannot pass one request at a time and cross a cap together."""
    caps = caps or Caps.from_settings()
    now = time.time()
    out: list[Reservation] = []
    with _ledger_lock():
        current = entries()
        total = sum(float(e.get("cost_usd") or 0) for e in current)
        per_step: dict[str, float] = {}
        for e in current:
            per_step[e.get("step")] = per_step.get(e.get("step"), 0.0) + float(e.get("cost_usd") or 0)
        for step, worst in items:
            _check(step, worst, caps, round(per_step.get(step, 0.0), 6), round(total, 6))
            per_step[step] = per_step.get(step, 0.0) + worst
            total += worst
            out.append(Reservation(uuid.uuid4().hex, step, model, float(worst), prompt_sha256, now, batch))
        for r in out:
            line = _entry(step=r.step, model=model, usage=None, prompt_sha256=prompt_sha256,
                          wall_time_s=0.0, finish_reason="reserved", batch=batch,
                          estimated_usd=r.worst_usd)
            line["reservation"] = r.id
            line["reserved"] = True
            _append(line)
    return out


def reserve(step: str, worst_case: float, *, model: str, prompt_sha256: str = "",
            batch: bool = False, caps: Caps | None = None) -> Reservation:
    """Check `worst_case` against the caps and hold it in the ledger, in one
    locked step, BEFORE the call is sent. Raises `BudgetExceeded` (nothing
    held) when it could cross a cap. Follow with exactly one of `settle` or
    `settle_failure`; a reservation never settled stays charged at
    `worst_case`."""
    return reserve_all([(step, worst_case)], model=model, prompt_sha256=prompt_sha256,
                       batch=batch, caps=caps)[0]


def settle(reservation: Reservation, *, usage: dict | None, finish_reason: str,
           model: str | None = None, wall_time_s: float | None = None,
           estimated_usd: float | None = None) -> dict:
    """Replace `reservation` with what the call cost: `usage` as the API
    reported it, or `estimated_usd` when that is unknown. Returns the entry."""
    entry = _entry(step=reservation.step, model=model or reservation.model, usage=usage,
                   prompt_sha256=reservation.prompt_sha256,
                   wall_time_s=(time.time() - reservation.started) if wall_time_s is None else wall_time_s,
                   finish_reason=finish_reason, batch=reservation.batch, estimated_usd=estimated_usd)
    entry["settles"] = reservation.id
    with _ledger_lock():
        _append(entry)
    return entry


def release(reservation: Reservation, reason: str) -> None:
    """Drop `reservation`: the call provably cost nothing (never sent, never
    connected, rejected with a 4xx). Only `settle_failure` should decide that."""
    with _ledger_lock():
        _append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "releases": reservation.id, "step": reservation.step, "reason": reason})


def settle_failure(reservation: Reservation, exc: BaseException, *, unbilled=None,
                   usage: dict | None = None, model: str | None = None) -> dict | None:
    """Settle a call that raised `exc`. THE SAME RULE AS `metered`: released
    (None returned) only when `unbilled(exc)` proves the API did no billable
    work; otherwise charged - at `usage` when the API reported the call's
    final counts, else at the reserved worst case, marked `"estimated": true`."""
    if isinstance(exc, StopRun) or (unbilled is not None and unbilled(exc)):
        release(reservation, f"unbilled:{type(exc).__name__}")
        return None
    finish = f"failed:{type(exc).__name__}"
    if usage:
        return settle(reservation, usage=usage, finish_reason=finish, model=model)
    return settle(reservation, usage=None, finish_reason=finish, model=model,
                  estimated_usd=reservation.worst_usd)


def metered(send, step: str, *, unbilled=None):
    """Wrap a Messages transport `send(url, *, headers, body, timeout) -> dict`
    so that every call through it RESERVES its worst case against the caps
    BEFORE it leaves (`reserve`) and is settled to its cost AFTER it returns.

    The worst case is `worst_case_usd` - the one estimator - on the request
    body itself: the model it names, every character of `messages` and
    `system` as serialised (image data included, which errs toward refusing),
    and its `max_tokens`. A refusal raises `BudgetExceeded` and `send` is never
    called. The ledger line carries counts and a digest of the body, never its
    text. `.usage` of the wrapped transport is carried over so a caller can
    still read the per-run token counts off the result.

    A CALL THAT RAISES MAY STILL HAVE BEEN BILLED - a read timeout after the
    API did the work, an answer refused locally for its size. So a failure is
    charged at that same worst case, marked `"estimated": true`, unless
    `unbilled(exc)` says the API provably did no billable work (refused before
    sending, never connected, a 4xx rejection). With no `unbilled` given,
    every failure is charged: the cap errs toward counting too much, never too
    little. The exception is re-raised either way."""
    def _metered(url, *, headers, body, timeout):
        model = str(body.get("model") or "")
        prompt_chars = (len(json.dumps(body.get("messages") or [], ensure_ascii=False, default=str))
                        + len(json.dumps(body.get("system") or "", ensure_ascii=False, default=str)))
        worst = worst_case_usd(model, prompt_chars, int(body.get("max_tokens") or 0))
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
                                           default=str).encode("utf-8")).hexdigest()
        held = reserve(step, worst, model=model, prompt_sha256=digest)
        try:
            payload = send(url, headers=headers, body=body, timeout=timeout)
        except BaseException as exc:
            settle_failure(held, exc, unbilled=unbilled)
            raise
        answer = payload if isinstance(payload, dict) else {}
        settle(held, model=str(answer.get("model") or model), usage=answer.get("usage"),
               finish_reason=str(answer.get("stop_reason") or "error"))
        return payload
    _metered.usage = getattr(send, "usage", None)
    _metered.step = step
    return _metered
