"""#805 rule boxes (a tool of `scripts/`: only the CLI uses it): the shared runner of the three Claude steps (label, check, second check), on a COPY of the database.

It sends nothing by itself. The caller (`scripts/rule_boxes.py`, explicit CLI use, dry by default) hands it `Job`s: one
prompt each, the documents the prompt carries, and what to do with the answer. This module owns only the lane:

  * GROUPS. Jobs are packed, in order, into groups whose WORST CASE is under `GROUP_CAP_USD` (the owner's USD 5 per
    step). Each group is its own spend step, so the per-step cap, the per-day cap and the November cap in
    `claude_spend` apply to it, and a group can never be the one that crosses a cap by itself.
  * IN FLIGHT. Up to `WORKERS` calls at once inside a group (a thread each); the answers are applied on the calling
    thread, one at a time, so the copy is written by one thread only.
  * EVERY CALL goes `reader_api` -> `claude_spend.metered` -> `reader_transport`: reserved first, settled after, the
    approved-document list asked first (`claude_approved.carrying`), the answer cache first (a repeat is free).
  * STOPS CLEANLY at any cap: the first `StopRun` ends the run, nothing further is sent, answers already received are
    kept, and the report says `stopped`. A second run takes up where this one stopped (the caller skips what is stored).
  * COUNTS ONLY in a report. No prompt, answer or rule text is printed or logged here.
"""

from __future__ import annotations

import concurrent.futures
import dataclasses
import json
import os
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app import (
    claude_approved,
    claude_spend,
    reader_api,
    reader_transport,
    reasoning_provider,
)

#: The owner's USD 5 per step, kept clear of: a group's worst case is at most this.
GROUP_CAP_USD = 4.5
#: The process environment variable that names this tool's engine (never a setting of the app).
ENGINE_ENV = "RULE_BOXES_ENGINE"
WORKERS = 20
TIMEOUT_S = 120.0
#: A reply the API gave up on for load: tried again a few times, each try reserved and settled on its own.
_RETRY_STATUS = {429, 500, 502, 503, 504, 529}
_PAUSES = (2.0, 6.0, 15.0)
DONE, STOPPED, PARTIAL, NOTHING = "done", "stopped", "partial", "nothing_to_do"


@dataclass(frozen=True)
class Job:
    """One prompt. `key` names it for the caller; `docs` are the documents its text carries."""

    key: str
    prompt: str
    docs: frozenset[str]
    max_tokens: int


def worst_of(model: str, job: Job) -> float:
    """The most this job can cost: the one estimator, on the same serialised body `claude_spend.metered` measures."""
    chars = (
        len(json.dumps([{"role": "user", "content": job.prompt}], ensure_ascii=False))
        + 2
    )
    return claude_spend.worst_case_usd(model, chars + 64, job.max_tokens)


def groups(
    model: str, jobs: Iterable[Job], cap: float = GROUP_CAP_USD
) -> tuple[list[list[Job]], list[Job]]:
    """(groups, too_big): jobs packed in order under `cap`; a job that alone is over it is returned, never sent."""
    out: list[list[Job]] = []
    too_big: list[Job] = []
    current: list[Job] = []
    total = 0.0
    for job in jobs:
        worst = worst_of(model, job)
        if worst > cap:
            too_big.append(job)
            continue
        if current and total + worst > cap:
            out.append(current)
            current, total = [], 0.0
        current.append(job)
        total += worst
    if current:
        out.append(current)
    return out, too_big


def worst_total(model: str, jobs: Iterable[Job]) -> float:
    return sum(worst_of(model, j) for j in jobs)


def _status_of(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    return int(code) if isinstance(code, int) else None


def _sender(step: str, version: str, send):
    if send is None:
        code, why = reasoning_provider.claude_unavailable_for_task(
            os.environ.get(ENGINE_ENV)
        )
        if code is not None:
            raise reader_transport.TransportRefused(f"{code}: {why}")
    transport = send or reader_transport.transport()
    if transport is None:
        raise reader_transport.TransportRefused(
            "egress is off (STANDARDS_READER_ENABLED / STANDARDS_READER_ALLOW_PUBLIC_EGRESS)"
        )
    return claude_spend.metered(
        transport, step, unbilled=reader_transport.unbilled, version=version
    )


def _ask(job: Job, cfg, step: str, version: str, send, sleep) -> str:
    """One job's reply text. Retries only a load error, under the same step; budget errors are never retried."""
    metered = _sender(step, version, send)
    last: BaseException | None = None
    for attempt in range(len(_PAUSES) + 1):
        try:
            with claude_approved.carrying(job.docs):
                return reader_api.call_claude(job.prompt, transport=metered, cfg=cfg)
        except claude_spend.StopRun:
            raise
        except Exception as exc:
            last = exc
            if _status_of(exc) not in _RETRY_STATUS or attempt >= len(_PAUSES):
                raise
            sleep(_PAUSES[attempt])
    raise last  # pragma: no cover - the loop always returns or raises


def run(
    jobs: list[Job],
    *,
    model: str,
    step_prefix: str,
    version: str,
    apply: Callable[[Job, str], bool],
    send=None,
    workers: int = WORKERS,
    cap: float = GROUP_CAP_USD,
    sleep=time.sleep,
) -> dict:
    """Send every job under the caps and hand each reply to `apply(job, text) -> stored?` on this thread.

    Counts only: groups, asked, stored, rejected_by_code (apply said no), failed (a call error), too_big, spent_usd
    and `status`. A budget stop ends the run: `stopped`, with `stop_reason` one fixed word."""
    report = {
        "status": NOTHING,
        "groups": 0,
        "asked": 0,
        "stored": 0,
        "rejected_by_code": 0,
        "failed": 0,
        "too_big": 0,
        "spent_usd": 0.0,
    }
    batches, too_big = groups(model, jobs, cap)
    report["too_big"] = len(too_big)
    if not batches:
        return report
    run_id = uuid.uuid4().hex[:8]
    spent_before = claude_spend.spent()
    status = DONE
    for n, batch in enumerate(batches, 1):
        step = f"{step_prefix}:{run_id}:g{n:04d}"
        cfg = dataclasses.replace(
            reader_api.ReaderSettings.from_env(),
            model=model,
            max_tokens=max(j.max_tokens for j in batch),
            timeout_seconds=TIMEOUT_S,
        )
        report["groups"] += 1
        stop = False
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {
                pool.submit(_ask, job, cfg, step, version, send, sleep): job
                for job in batch
            }
            for future in concurrent.futures.as_completed(futures):
                job = futures[future]
                try:
                    text = future.result()
                except claude_spend.StopRun as exc:
                    stop = True
                    report["stop_reason"] = type(exc).__name__
                    for other in futures:
                        other.cancel()
                    continue
                except concurrent.futures.CancelledError:
                    continue
                except Exception:  # noqa: BLE001 - counted; the cause is not printed (it can carry a body)
                    report["failed"] += 1
                    status = PARTIAL
                    continue
                report["asked"] += 1
                if apply(job, text):
                    report["stored"] += 1
                else:
                    report["rejected_by_code"] += 1
        if stop:
            status = STOPPED
            break
    if report["rejected_by_code"] or report["failed"]:
        status = status if status == STOPPED else PARTIAL
    report["status"] = status
    report["spent_usd"] = round(claude_spend.spent() - spent_before, 4)
    return report
