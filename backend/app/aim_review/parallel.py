"""Judge calls side by side (the owner's order, 18 Nov 2026: a valve review spent about 5 of its 8 minutes judging batches one
after another). At most `workers` calls are in flight; the requests are built beforehand on the calling thread (they read rule
books through its database connection), so only the model call runs in a worker, in a COPY of the caller's context (the run id
of the spend ledger and the send gate's review run travel with it).

MONEY FIRST. Each call reserves its worst case on the run meter before it starts and releases it exactly once
(`engine.ClaudeModel.ask`); the spend ledger reserves and settles every call itself (`claude_spend.metered`, its own lock), so
the day and month caps hold. Here: a call whose worst case does not fit beside the calls in flight WAITS for one of them to end
(never refused only because others are running); with nothing in flight it is asked as before and the meter decides. Nothing
new starts after a cancel or after a failure that stops the run; the calls in flight finish and settle. Results come back by
position, so the caller merges them in the same order as one call after another.
"""

from __future__ import annotations

import contextvars
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from .engine import StepFailed


def _one(model, request: dict):
    try:
        return ("ok", model.ask(**request))
    except StepFailed as exc:
        return ("failed", exc)


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


def _fits(model, worst: float, submitted: float) -> bool:
    """Does this call fit beside every call already SUBMITTED (counted from submission, so a call that has not yet placed its
    own hold on the meter is counted too)?"""
    meter = getattr(model, "meter", None)
    if not worst or meter is None:
        return True
    with meter.lock:
        return meter.spent + submitted + worst <= meter.cap


def run_calls(
    model, requests: list[dict], *, workers: int, cancelled=None, done=None
) -> tuple[list, str]:
    """([("ok", answer) | ("failed", StepFailed) | None (never asked)] by position, the stop code or "")."""
    results: list = [None] * len(requests)
    stop, nxt, pending = "", 0, {}
    width = max(1, int(workers))
    with ThreadPoolExecutor(max_workers=width) as pool:
        while nxt < len(requests) or pending:
            while nxt < len(requests) and len(pending) < width and not stop:
                if cancelled is not None and cancelled():
                    stop = "cancelled"
                    break
                worst = _worst(model, requests[nxt])
                if pending and not _fits(
                    model, worst, sum(w for _i, w in pending.values())
                ):
                    break  # wait for a call in flight to end and settle
                fut = pool.submit(
                    contextvars.copy_context().run, _one, model, requests[nxt]
                )
                pending[fut] = (nxt, worst)
                nxt += 1
            if not pending:
                break
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for fut in finished:
                results[pending.pop(fut)[0]] = got = fut.result()
                if got[0] == "failed" and got[1].stops_run and not stop:
                    stop = str(got[1])
                if done is not None:
                    done()
    return results, stop
