"""Judge calls side by side (the owner's order, 18 Nov 2026: a valve review spent about 5 of its 8 minutes judging batches one
after another). At most `workers` calls are in flight; the requests are built beforehand on the calling thread (they read rule
books through its database connection), so only the model call runs in a worker, in a COPY of the caller's context (the run id
of the spend ledger and the send gate's review run travel with it).

MONEY FIRST. Each call reserves its worst case on the run meter before it starts and releases it exactly once
(`engine.ClaudeModel.ask`); the spend ledger reserves and settles every call itself (`claude_spend.metered`, its own lock), so
the step, run, day and total caps hold. Here: a call whose worst case does not fit beside the calls in flight, on the run meter
OR under the spend ledger's caps (`_fits`), WAITS for one of them to end and settle (never refused only because others are
running); with nothing in flight it is asked as before and the meter and the ledger decide. A call refused for money while
other calls were in flight (a hold placed between the check and its own reservation) is asked ONCE more, alone; only a refusal
with nothing else in flight stops the run, exactly as one call after another would. Nothing new starts after a cancel or after
a failure that stops the run; the calls in flight finish and settle. Results come back by position, so the caller merges them
in the same order as one call after another. Each worker closes its own database connection when its call ends.
"""

from __future__ import annotations

import contextvars
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from .engine import StepFailed


def _one(model, request: dict):
    from app import db

    try:
        return ("ok", model.ask(**request))
    except StepFailed as exc:
        return ("failed", exc)
    finally:  # the worker's own database connection (one per thread) is closed when its call ends
        db.close_thread_connection()


def _refused_for_money(exc: StepFailed) -> bool:
    """Refused before anything was sent, by the run meter ("run_cap") or the spend ledger's caps ("stop usd_cap_reached")."""
    words = str(exc).split(":", 1)[-1].split()
    return bool(words) and (
        words[0] == "run_cap" or words[:2] == ["stop", "usd_cap_reached"]
    )


def _worst(model, request: dict) -> float:
    """This call's worst case, as `ClaudeModel.ask` reckons it; 0 for a dry (fake) model or one without a run meter."""
    from app import claude_spend

    if getattr(model, "dry", False) or not hasattr(
        getattr(model, "meter", None), "held"
    ):
        return 0.0
    chars = (
        len(request.get("system") or "")
        + len(request.get("cached") or "")
        + len(request.get("prompt") or "")
    )
    return float(
        claude_spend.worst_case_usd(request["model"], chars, request["max_tokens"])
    )


def _fits(model, step: str, worst: float, submitted: float) -> bool:
    """Does this call fit beside every call already SUBMITTED, on the run meter AND under the spend ledger's caps (step, run, day,
    total; read-only, holds included)? Submitted calls are counted from submission, so a call that has not yet placed its own
    hold is counted too (one already held is then counted twice: that only makes a call wait longer, never refuses it)."""
    from app import claude_spend

    meter = getattr(model, "meter", None)
    if not worst or meter is None:
        return True
    with meter.lock:
        if meter.spent + submitted + worst > meter.cap:
            return False
    try:
        claude_spend.ensure_affordable(step, submitted + worst)
    except claude_spend.BudgetExceeded:
        return False
    return True


def run_calls(
    model, requests: list[dict], *, workers: int, cancelled=None, done=None
) -> tuple[list, str]:
    """([("ok", answer) | ("failed", StepFailed) | None (never asked)] by position, the stop code or "")."""
    results: list = [None] * len(requests)
    stop, pending = "", {}
    queue, again = deque(range(len(requests))), set()
    width = max(1, int(workers))
    with ThreadPoolExecutor(max_workers=width) as pool:
        while queue or pending:
            while queue and len(pending) < width and not stop:
                if cancelled is not None and cancelled():
                    stop = "cancelled"
                    break
                i = queue[0]
                worst = _worst(model, requests[i])
                held = sum(w for _i, w, _alone in pending.values())
                if pending and (
                    i in again or not _fits(model, requests[i]["step"], worst, held)
                ):
                    break  # wait for a call in flight to end and settle
                queue.popleft()
                fut = pool.submit(
                    contextvars.copy_context().run, _one, model, requests[i]
                )
                pending[fut] = (i, worst, not pending)
                if i in again:
                    break  # asked again ALONE: nothing else starts beside it
            if not pending:
                break
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for fut in finished:
                i, _worst_usd, alone = pending.pop(fut)
                got = fut.result()
                if (
                    got[0] == "failed"
                    and not alone
                    and i not in again
                    and _refused_for_money(got[1])
                ):
                    again.add(i)  # refused only beside others: asked once more, alone
                    queue.appendleft(i)
                    continue
                results[i] = got
                if got[0] == "failed" and got[1].stops_run and not stop:
                    stop = str(got[1])
                if done is not None:
                    done()
    return results, stop
