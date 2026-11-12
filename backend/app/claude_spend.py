"""What the Claude API has cost, and the refusal before it costs more.

OWNER RULE 2026-09-25: USD 5 per step, USD 20 in total; stop BEFORE exceeding either. Plan change 4 (#805,
28 Oct 2026): USD 25 per converted standard, USD 500 in total for November 2026 only (`total_cap`). Plan change 6:
USD 100 a day (`claude_spend_report`). The check is made before a call leaves, on the WORST CASE of that call (every
prompt token uncached, every allowed output token spent), against what the ledger says was already spent. A call
that could cross a cap is refused, never sent and then reported as over budget.

PER REVIEW RUN (owner, #1584, 2 Nov 2026, 15:05 PKT): USD 5 per step, USD 10 for the AI clause review step, at most
USD 15 for the whole run, all checked in the same reservation (`for_run`, `claude_spend_report.cap_key`). A re-run
under a new run id starts again, so the day cap limits re-runs. A call with NO run (chat, a read at upload, a script,
an offline job) has USD 5 on every line of its step, run or not: as tight as before. A `standards_convert:` step stays
USD 25 per standard, whatever the run, apart from the run's USD 15.

THE LEDGER is a local JSONL file (`settings.claude_spend_log`), one line per
call: time, step, model, token counts, cost, and a digest of the prompt. It is
not in the database on purpose - measured runs use disposable database copies,
and a total kept in a copy would forget every run made against another copy.
It never holds prompt text, document text or the key.

THE CHECK IS A RESERVATION, NOT A READ (audit 2026-09-30). Checking the ledger, sending, and only then writing the
ledger let ten threads at $4.90 each see "$4.90 spent" and all send: the step reached $5.80. So a call now `reserve`s
its worst case - check AND ledger line in one step, under the ledger lock - before it leaves, and `settle`s that
reservation afterwards to what it actually cost. Until it is settled, the reservation counts at its worst case; a
process that dies mid-call leaves it counted that way for good, which errs toward spent. `reasoning_provider` (single
call, stream and batch) and `metered` (the three `claude_api` review routes) all go through
`reserve`/`settle`/`settle_failure`. There is one ledger; the per-run call cap in `claude_budget` is a second, separate
limit, not a second record of dollars. `ensure_affordable` is a read-only check, not a guard on its own.

A CALL THAT FAILS MAY STILL HAVE BEEN BILLED - a read timeout after the API did the work, a stream dropped mid-answer,
an answer refused locally for its size. `settle_failure` charges its actual usage when the API reported it, otherwise
the reserved worst case (marked `"estimated": true`), and releases it only when `unbilled(exc)` proves no billable work.

WHAT THE LOCK GUARANTEES. `_ledger_lock` is a process-local mutex plus an exclusive OS lock on `<ledger>.lock`
(`fcntl.flock` on POSIX, `msvcrt.locking` on Windows). So the check-and-reserve is atomic between threads of one process
AND between processes on the same machine that use the SAME ledger path through this module. It is NOT guaranteed: for
processes pointed at different ledger files (each is its own budget, by construction); on a network filesystem whose
locks are advisory or unsupported; or against anything that writes the JSONL without this module. Settled figures are
the list-price ESTIMATE below, not the invoice.

PRICES are list prices per million tokens from Anthropic's pricing page (platform.claude.com/docs/en/about-claude/
pricing, read 2026-09-25): an ESTIMATE; the invoice is the truth. An unknown model is priced at the dearest family.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timezone
from pathlib import Path

from . import claude_spend_report as report_mod
from .claude_image_tokens import json_counts
from .config import settings

#: (input, output, 5-minute cache write, cache read) USD per million tokens.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-sonnet-5-5": (2.0, 10.0, 2.5, 0.20),
    "claude-sonnet-5": (2.0, 10.0, 2.5, 0.20),
    "claude-sonnet-4-6": (3.0, 15.0, 3.75, 0.30),
    "claude-sonnet-4-5": (3.0, 15.0, 3.75, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
    "claude-haiku-4-5": (1.0, 5.0, 1.25, 0.10),
    "claude-opus-5-5": (4.0, 20.0, 5.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 6.25, 0.50),
}
#: The price used for a model id not in the table: the dearest listed.
_UNKNOWN = max(PRICES.values())
#: Haiku 5.5 has two rate cards, chosen by the length of the PROMPT (input plus
#: cache tokens): over this many tokens every token of the call costs five times as much.
LONG_PROMPT_TOKENS = 100_000
LONG_PROMPT_PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-haiku-5-5": (0.50, 2.50, 0.625, 0.05),
}
#: Order 271.3 (owner, #805 plan change 4): a call whose step starts with this is charged to ONE
#: standard's step and capped at `claude_budget_usd_per_standard` (the converter, `standards_converter`).
STANDARD_STEP_PREFIX = report_mod.STANDARD_STEP_PREFIX
#: `clause_review.STEP` (a test pins them equal): inside a review run its step cap is the owner's USD 10.
CLAUSE_REVIEW_STEP = "clause_review"
#: Order 271.3: the raised total is for NOVEMBER 2026 only (UTC dates). After this day the total is
#: `BASELINE_TOTAL_USD` whatever the setting says, so a lapsed approval fails closed; renewing it is a
#: reviewed change here, not a line in `.env`.
TOTAL_RAISED_UNTIL = date(2026, 11, 30)
BASELINE_TOTAL_USD = 20.0
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


class DocumentNotApproved(BudgetExceeded):
    """#806 S3: the prompt carries a document the owner has not approved for
    the cloud model (or its caller declared nothing), so the call was not
    made. A `BudgetExceeded` on purpose: it is refused at the same place, for
    the same kind of reason (an owner limit), before anything leaves, and
    every caller that already stops cleanly on a cap stops cleanly on this.
    `code` is `claude_approved.UNDECLARED / NOT_APPROVED / UNKNOWN_DOCUMENT`."""

    count_key = "document_not_approved"

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code


def price_for(
    model: str | None, prompt_tokens: int = 0
) -> tuple[float, float, float, float]:
    """List prices for `model`; a dated id ('...-20251001') finds its family.
    `prompt_tokens` picks the rate card of a model that has two."""
    name = (model or "").lower()
    for key in sorted(PRICES, key=len, reverse=True):
        if name == key or name.startswith(key + "-") or re.fullmatch(rf"{re.escape(key)}-\d{{8}}", name):
            if prompt_tokens > LONG_PROMPT_TOKENS and key in LONG_PROMPT_PRICES:
                return LONG_PROMPT_PRICES[key]
            return PRICES[key]
    return _UNKNOWN


def cost_usd(model: str | None, usage: dict | None, *, batch: bool = False) -> float:
    """USD for one call from the API's `usage` block; a Message Batches
    result (`batch=True`) at half price."""
    usage = usage or {}
    prompt_tokens = (
        int(usage.get("input_tokens") or 0)
        + int(usage.get("cache_creation_input_tokens") or 0)
        + int(usage.get("cache_read_input_tokens") or 0)
    )
    p_in, p_out, p_write, p_read = price_for(model, prompt_tokens)
    full = (int(usage.get("input_tokens") or 0) * p_in
            + int(usage.get("output_tokens") or 0) * p_out
            + int(usage.get("cache_creation_input_tokens") or 0) * p_write
            + int(usage.get("cache_read_input_tokens") or 0) * p_read) / 1_000_000
    return full * BATCH_DISCOUNT if batch else full


def thinks_by_default(model: str | None) -> bool:
    """True for an id in `settings.claude_models_thinking_by_default` (prefix match)."""
    name = (model or "").lower()
    return any(
        name == p or name.startswith(p + "-")
        for p in settings.claude_models_thinking_by_default
    )


def output_cap(model: str | None, max_tokens: int) -> int:
    """The `max_tokens` a request carries: a short cap is raised for a model that
    thinks by default (`settings.claude_min_output_tokens`), never lowered."""
    if thinks_by_default(model):
        return max(int(max_tokens), int(settings.claude_min_output_tokens))
    return int(max_tokens)


def worst_case_usd(model: str | None, prompt_chars: int, max_tokens: int,
                   image_tokens: int = 0, *, batch: bool = False) -> float:
    """The most one call can cost: prompt at ~3 chars per token (generous -
    English runs nearer 4), plus any image's tokens (width x height / 750),
    priced as an uncached cache WRITE (the dearest input rate), plus every
    allowed output token. Half for a batch request."""
    tokens_in = prompt_chars // 3 + 1 + max(0, int(image_tokens))
    p_in, p_out, p_write, _ = price_for(model, tokens_in)
    max_tokens = output_cap(model, max_tokens)  # what the request will actually carry
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


#: The step a torn ledger line is charged to (r2 S6).
CORRUPT_STEP = "ledger:unreadable"


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
                value = None
            if isinstance(value, dict):
                out.append(value)
            else:
                # r2 S6 / B-9: A TORN OR INVALID LINE IS NOT "NOTHING SPENT".
                # It used to be skipped, so one half-written line (a crash
                # mid-append) silently dropped a reservation and lifted the
                # cap. Fail closed: it counts at the TOTAL cap, so no further
                # call fits until a person has looked at the ledger. The
                # caps themselves are unchanged.
                out.append({"step": CORRUPT_STEP, "corrupt": True,
                            "cost_usd": total_cap(),
                            "finish_reason": "unreadable ledger line"})
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


def models_used(
    *, since: str, steps=None, exclude_prefixes: tuple[str, ...] = ()
) -> list[str]:
    """The models that ANSWERED since `since` (ISO time), sorted: settled lines and cache hits, which name the model the
    API reported. An open reservation only names what was asked for, and a call charged at an estimate never showed an
    answer, so neither counts. `steps` narrows to those steps; `exclude_prefixes` leaves out steps starting with these.
    Whole seconds, like the ledger's `at`. The boundary is this time window on this ledger: another run in it counts."""
    start = datetime.fromisoformat(since).replace(microsecond=0)
    start = start if start.tzinfo else start.replace(tzinfo=UTC)
    found = set()
    for entry in entries():
        answered = entry.get("settles") and not entry.get("estimated")
        served = entry.get("finish_reason") == "cache_hit"
        if not (answered or served) or not entry.get("model"):
            continue
        step = str(entry.get("step") or "")
        if step.startswith(exclude_prefixes) or (
            steps is not None and step not in steps
        ):
            continue
        if datetime.fromisoformat(entry["at"]) >= start:
            found.add(str(entry["model"]))
    return sorted(found)


def _append(entry: dict) -> None:
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # r2 S6: a ledger that does not end in a newline (a torn last write) must
    # not have the next line glued onto it, which would corrupt BOTH.
    lead = ""
    try:
        if path.exists() and path.stat().st_size:
            with path.open("rb") as probe:
                probe.seek(-1, 2)
                if probe.read(1) != b"\n":
                    lead = "\n"
    except OSError:
        lead = "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(lead + json.dumps(entry) + "\n")


def spent(step: str | None = None) -> float:
    """USD spent in total, or on one step."""
    return round(sum(float(e.get("cost_usd") or 0) for e in entries()
                     if step is None or e.get("step") == step), 6)


def step_spent(step: str) -> float:
    """What the step cap reads for a call made here and now, holds included. `spent(step)` is the step, every run."""
    run = current_run()
    held = report_mod.by_cap(entries(), run)
    return round(held.get(report_mod.cap_key(step, run), 0.0), 6)


def run_spent() -> float:
    """What this review run has charged across its steps, holds included; 0 with no run."""
    run = current_run()
    return round(report_mod.by_cap(entries(), run).get((run,), 0.0), 6)


def _today() -> date:
    return datetime.now(UTC).date()


def total_cap() -> float:
    """The USD cap in total: the setting, but never above `BASELINE_TOTAL_USD` after `TOTAL_RAISED_UNTIL`."""
    total = float(settings.claude_budget_usd_total)
    return min(total, BASELINE_TOTAL_USD) if _today() > TOTAL_RAISED_UNTIL else total


@dataclass(frozen=True)
class Caps:
    per_step: float
    total: float

    @classmethod
    def from_settings(cls) -> Caps:
        return cls(float(settings.claude_budget_usd_per_step), total_cap())

    def for_step(self, step: str) -> Caps:
        """Order 271.3: the steps that convert ONE standard (`standards_convert:<standard>`) each have
        their own, larger cap - USD 25 per standard - while every other step keeps `per_step`. Only
        the caps read from settings are resolved per step: a caller that passed its own `Caps` meant them."""
        if str(step).startswith(STANDARD_STEP_PREFIX):
            return Caps(float(settings.claude_budget_usd_per_standard), self.total)
        if str(step) == CLAUSE_REVIEW_STEP and _RUN.get():
            return Caps(float(settings.claude_budget_usd_clause_review), self.total)
        return self


def ensure_affordable(step: str, worst_case: float, caps: Caps | None = None) -> None:
    """Refuse (raise) when `worst_case` on top of what is spent could cross
    the step cap or the total cap. READ-ONLY: it reserves nothing, so two
    callers can both pass it - a call that is about to be sent must use
    `reserve` instead."""
    _check(
        step,
        worst_case,
        caps or Caps.from_settings().for_step(step),
        step_spent(step),
        spent(),
    )
    if over := report_mod.over_caps(step, current_run(), worst_case, entries()):
        raise BudgetExceeded(over)


def _check(step: str, worst_case: float, caps: Caps, step_spent: float, total_spent: float) -> None:
    if step_spent + worst_case > caps.per_step:
        raise BudgetExceeded(
            f"step {step!r}: spent ${step_spent:.4f}, next call up to ${worst_case:.4f}, "
            f"cap ${caps.per_step:.2f} per step{' of this review run' if report_mod.is_runs(step, current_run()) else ''}")
    if total_spent + worst_case > caps.total:
        raise BudgetExceeded(
            f"total: spent ${total_spent:.4f}, next call up to ${worst_case:.4f}, "
            f"cap ${caps.total:.2f} in total")


#: The review run this context's calls belong to (`for_run`): the only thing that tells
#: them from a chat answer on another thread in the same minutes. Ids only.
_RUN: ContextVar[str | None] = ContextVar("claude_spend_run", default=None)


def current_run() -> str | None:
    return _RUN.get()


@contextmanager
def for_run(review_run_id: str | None):
    """Ledger lines written inside this block carry the run's id."""
    token = _RUN.set(review_run_id)
    try:
        yield
    finally:
        _RUN.reset(token)


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
    if (run := _RUN.get()) is not None:
        entry["run"] = run
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
    for a cost with no pre-send check to make."""
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
    #: The run it was held for: its settlement counts on that run's step cap, wherever it is settled.
    run: str | None = field(default_factory=lambda: _RUN.get())


#: What the reader is told when #806 S3 stopped a Claude answer. One wording,
#: in every chat path; ids are in the bracket, never a file name.
NOT_APPROVED_WORDS = ("a document this answer needs is not approved for the cloud model, so nothing "
                      "was sent to it and no answer was generated; choose the Local model to answer "
                      "from this document")


def refusal_words(exc: BaseException, cap_words: str) -> str:
    """The reason shown for a call refused before it left: the approved-list
    wording for `DocumentNotApproved`, else the caller's own spending-cap
    wording (`cap_words`). The exception's text follows in brackets."""
    words = NOT_APPROVED_WORDS if isinstance(exc, DocumentNotApproved) else cap_words
    return f"{words} ({exc})"


def _refuse_unapproved(
    steps: list[str], *, model: str, prompt_sha256: str, batch: bool
) -> None:
    """#806 S3, BEFORE THE CAPS AND BEFORE ANYTHING IS HELD OR SERVED: every Claude
    call reserves or looks up its stored answer through here (the `metered` lane
    and the `ClaudeProvider` lane), so this is the one place a prompt carrying an
    unapproved document - or one whose caller declared nothing - is stopped. The
    refusal is written to the ledger at USD 0 (step, code, ids; never a title), for
    the log review."""
    from . import claude_approved
    refused = claude_approved.refusal()
    if refused is not None:
        code, reason = refused
        with _ledger_lock():
            for step in steps:
                line = _entry(step=step, model=model, usage=None, prompt_sha256=prompt_sha256,
                              wall_time_s=0.0, finish_reason=f"refused:{code}", batch=batch)
                line["refused"] = code
                line["documents"] = sorted(claude_approved.carried() or ())
                _append(line)
        raise DocumentNotApproved(code, reason)


def reserve_all(
    items: list[tuple[str, float]],
    *,
    model: str,
    prompt_sha256: str = "",
    batch: bool = False,
    caps: Caps | None = None,
) -> list[Reservation]:
    """Check and reserve every `(step, worst_case)` in ONE locked step: all
    fit together, or `BudgetExceeded` is raised and nothing is reserved.
    Each item is checked on top of the ledger AND the items before it, so a
    batch cannot pass one request at a time and cross a cap together."""
    _refuse_unapproved(
        [step for step, _worst in items],
        model=model,
        prompt_sha256=prompt_sha256,
        batch=batch,
    )
    from . import claude_approved

    # #1584: what this call carries goes on its reservation line, so a send and
    # its record are one write (switch off, or no document content: nothing).
    sent_documents = claude_approved.sent_documents()
    explicit = caps
    caps = caps or Caps.from_settings()
    now = time.time()
    out: list[Reservation] = []
    with _ledger_lock():
        current = entries()
        total = sum(float(e.get("cost_usd") or 0) for e in current)
        run = current_run()
        per_step = report_mod.by_cap(current, run)
        day = report_mod.charged_today(current)
        for step, worst in items:
            _check(
                step,
                worst,
                explicit or caps.for_step(step),
                round(per_step.get(report_mod.cap_key(step, run), 0.0), 6),
                round(total, 6),
            )
            if over := report_mod.over_run_cap(step, run, worst, per_step):
                raise BudgetExceeded(over)
            if over := report_mod.over_day_cap(worst, round(day, 6)):
                raise BudgetExceeded(over)
            report_mod.charge(per_step, step, run, worst)
            total += worst
            day += worst
            out.append(Reservation(uuid.uuid4().hex, step, model, float(worst), prompt_sha256, now, batch))
        for r in out:
            line = _entry(step=r.step, model=model, usage=None, prompt_sha256=prompt_sha256,
                          wall_time_s=0.0, finish_reason="reserved", batch=batch,
                          estimated_usd=r.worst_usd)
            line["reservation"] = r.id
            line["reserved"] = True
            if sent_documents:
                line["sent_documents"] = sent_documents
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
    reported it, or `estimated_usd` when that is unknown. Returns the entry.

    #459 (audit B07): A REPLY WITH NO USAGE IS NOT A FREE REPLY. An answer with no `usage` block (a proxy that strips
    it, a new shape) used to settle at USD 0: billed, and the caps believed nothing was spent. With neither token count
    reported and no estimate given, it settles at its reserved worst case, marked `"estimated": true`."""
    if estimated_usd is None and not _usage_reported(usage):
        estimated_usd = reservation.worst_usd
    entry = _entry(step=reservation.step, model=model or reservation.model, usage=usage,
                   prompt_sha256=reservation.prompt_sha256,
                   wall_time_s=(time.time() - reservation.started) if wall_time_s is None else wall_time_s,
                   finish_reason=finish_reason, batch=reservation.batch, estimated_usd=estimated_usd)
    entry["settles"] = reservation.id
    if reservation.run:
        entry["run"] = reservation.run
    with _ledger_lock():
        _append(entry)
    return entry


def _usage_reported(usage) -> bool:
    """True when the API said how many tokens the call used (#459)."""
    return isinstance(usage, dict) and ("input_tokens" in usage or "output_tokens" in usage)


def release(reservation: Reservation, reason: str) -> None:
    """Drop `reservation`: the call provably cost nothing (never sent, never
    connected, rejected with a 4xx). Only `settle_failure` should decide that."""
    with _ledger_lock():
        _append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "releases": reservation.id, "step": reservation.step, "reason": reason})


#: #872: the one failure the owner must act on, as a closed word and in plain
#: words. The API answers an empty credit balance with HTTP 400 and the
#: generic type `invalid_request_error`; only its message says so.
NO_CREDIT = "no_credit"
NO_CREDIT_WORDS = "the Claude account has no credit (the owner tops it up in the Anthropic console)"
#: U5: the other standing refusal: the API answers a reached usage limit with HTTP 400 or 429; only its message says so.
USAGE_LIMIT = "usage_limit"
USAGE_LIMIT_WORDS = "the Claude account's usage limit is reached"
#: How long a standing refusal is believed without a newer call: a limit may reset, and a screen that says "not available" stops the
#: calls that would show it has.
STANDING_REFUSAL_HOURS = 3
_ERROR_TYPE = re.compile(r"[a-z][a-z_]{0,39}")


def failure_word(exc: BaseException) -> str:
    """A CLOSED description of why a call failed, for the ledger and the run:
    the exception's type, and for an API rejection its HTTP status and the
    API's error type - `HTTPStatusError:http_400:invalid_request_error`.

    #872, live run of 12 Oct 2026: every call failed with HTTP 400 and the ledger said only "unbilled:HTTPStatusError";
    the cause (no credit left) had to be read from the provider's console.

    NEVER THE MESSAGE. The API's message is free text and could echo a request field, so it is only TESTED for the one
    case with a closed answer (`no_credit`), never stored, logged or returned. The error type is copied only when it
    has the shape of the API's own enum (lower-case letters and underscores, at most 40). Nothing here can raise."""
    name = type(exc).__name__
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if not isinstance(status, int) or isinstance(status, bool):
        return name
    kind, no_credit, limit = "", False, False
    try:
        err = response.json().get("error", {})
        if isinstance(err, dict):
            stated = str(err.get("type") or "")
            kind = stated if _ERROR_TYPE.fullmatch(stated) else ""
            message = str(err.get("message") or "").lower()
            no_credit = status == 400 and "credit balance" in message
            limit = status in (400, 429) and "usage limit" in message
    except (ValueError, TypeError, AttributeError, LookupError):
        # A body that is not the API's JSON says nothing more than its status.
        kind, no_credit, limit = "", False, False
    if no_credit:
        return f"{name}:http_{status}:{NO_CREDIT}"
    if limit:
        return f"{name}:http_{status}:{USAGE_LIMIT}"
    return f"{name}:http_{status}" + (f":{kind}" if kind else "")


def failure_words(exc: BaseException) -> str | None:
    """Plain words for a failure the owner must act on (no credit, usage limit reached), else None."""
    word = failure_word(exc)
    if word.endswith(":" + NO_CREDIT):
        return NO_CREDIT_WORDS
    return USAGE_LIMIT_WORDS if word.endswith(":" + USAGE_LIMIT) else None


def standing_refusal(now: datetime | None = None) -> dict | None:
    """The Claude lane's standing refusal as the ledger holds it: the NEWEST call that failed for no credit or a reached usage limit,
    when no call has succeeded since, and it is not older than `STANDING_REFUSAL_HOURS`; else None (nothing is known, not "available").
    `{"cause": "no_credit" | "usage_limit", "words": plain words, "at": ISO time}`. Counts and a closed word only; never a message, a
    prompt or a key. Read only."""
    now = now or datetime.now(UTC)
    found: dict | None = None
    for e in _raw_lines():
        why = str(e.get("finish_reason") or e.get("reason") or "")
        if e.get("releases") or e.get("settles") or "finish_reason" in e:
            if why.endswith(":" + NO_CREDIT) or why.endswith(":" + USAGE_LIMIT):
                cause = NO_CREDIT if why.endswith(":" + NO_CREDIT) else USAGE_LIMIT
                found = {"cause": cause, "at": str(e.get("at") or ""),
                         "words": NO_CREDIT_WORDS if cause == NO_CREDIT else USAGE_LIMIT_WORDS}
            elif "finish_reason" in e and not why.startswith(("failed:", "unbilled:")) and not e.get("corrupt") \
                    and not e.get("cached") and e.get("input_tokens"):
                found = None  # a call went through after it: the lane works
    if found is None:
        return None
    try:
        at = datetime.fromisoformat(found["at"])
    except ValueError:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return found if (now - at).total_seconds() <= STANDING_REFUSAL_HOURS * 3600 else None


def settle_failure(reservation: Reservation, exc: BaseException, *, unbilled=None,
                   usage: dict | None = None, model: str | None = None) -> dict | None:
    """Settle a call that raised `exc`. THE SAME RULE AS `metered`: released
    (None returned) only when `unbilled(exc)` proves the API did no billable
    work; otherwise charged - at `usage` when the API reported the call's
    final counts, else at the reserved worst case, marked `"estimated": true`."""
    if isinstance(exc, StopRun) or (unbilled is not None and unbilled(exc)):
        release(reservation, f"unbilled:{failure_word(exc)}")
        return None
    finish = f"failed:{failure_word(exc)}"
    if usage:
        return settle(reservation, usage=usage, finish_reason=finish, model=model)
    return settle(reservation, usage=None, finish_reason=finish, model=model,
                  estimated_usd=reservation.worst_usd)


def answer_on_file(
    step: str, body: dict, *, version: str = "", valid=None, prompt_sha256: str = ""
) -> tuple[dict | None, str]:
    """THE ONE DOOR OF THE ANSWER CACHE: `(stored answer or None, key)` for the
    request `body`. Asked before `reserve` on every lane (single call, stream, batch,
    `metered`). The approved-list gate comes first, so a blocked document never gets
    a stored answer. A hit opens no socket: one ledger line at USD 0, marked `cached`,
    with the USD it saved, and the audit says "not sent: cache hit". Counts only,
    never text."""
    from . import ai_call_ledger, claude_answer_cache

    model = str(body.get("model") or "")
    _refuse_unapproved([step], model=model, prompt_sha256=prompt_sha256, batch=False)
    key = claude_answer_cache.key_of(step, version, body)
    stored = claude_answer_cache.read(key, valid=valid)
    if stored is None:
        return None, key
    line = _entry(
        step=step,
        model=str(stored.get("model") or model),
        usage=None,
        prompt_sha256=prompt_sha256,
        wall_time_s=0.0,
        finish_reason="cache_hit",
    )
    line["cached"] = True
    line["saved_usd"] = round(float(stored.get("cost_usd") or 0.0), 6)
    line["sent"] = claude_answer_cache.NOT_SENT
    with _ledger_lock():
        _append(line)
    ai_call_ledger.cache_hit(step, line["model"])
    return stored, key


def keep_answer(key: str, step: str, payload, *, cost_usd: float, valid=None) -> bool:
    """Store a paid answer, when it is complete and valid (`claude_answer_cache.write`)."""
    from . import claude_answer_cache

    return claude_answer_cache.write(
        key, step=step, payload=payload, cost_usd=cost_usd, valid=valid
    )


def cache_report(*, run_id: str | None = None) -> dict:
    """Hits, misses and the USD saved (`claude_answer_cache.report`), over this ledger."""
    from . import claude_answer_cache

    return claude_answer_cache.report(entries(), run_id=run_id)


def metered(send, step: str, *, unbilled=None, version: str = "", keep_if=None):
    """Wrap a Messages transport `send(url, *, headers, body, timeout) -> dict`
    so that every call through it RESERVES its worst case against the caps
    BEFORE it leaves (`reserve`) and is settled to its cost AFTER it returns.

    The worst case is `worst_case_usd` - the one estimator - on the request body itself: the model it names, every
    character of `messages` and `system` as serialised but an image block by the published image rule (`json_counts`),
    and its `max_tokens`. A refusal raises `BudgetExceeded` and `send` is never called. The ledger line carries counts
    and a digest of the body, never its text. `.usage` of the wrapped transport is carried over.

    A CALL THAT RAISES MAY STILL HAVE BEEN BILLED - a read timeout after the API did the work, an answer refused
    locally for its size. So a failure is charged at that same worst case, marked `"estimated": true`, unless
    `unbilled(exc)` says the API provably did no billable work (refused before sending, never connected, a 4xx
    rejection). With no `unbilled` given, every failure is charged. The exception is re-raised either way.

    THE ANSWER CACHE (`answer_on_file`) IS ASKED FIRST, under `version`. Every prompt on this lane asks for JSON, so
    `keep_if` defaults to `claude_answer_cache.is_json`; a caller with a stricter check hands it in. The N-th ask of the
    same body through one wrapper has its own stored answer (a stability check that asks twice must compare two answers
    the model really gave, `ai_task_runner.reuse_or_ask`'s rule); only an answer worth keeping uses up its slot."""
    from . import claude_answer_cache

    valid = keep_if or claude_answer_cache.is_json
    asked: dict[str, int] = {}

    def _metered(url, *, headers, body, timeout):
        model = str(body.get("model") or "")
        parts = [body.get("messages") or [], body.get("system") or ""]
        prompt_chars, images = json_counts(parts, ensure_ascii=False)
        cap = int(body.get("max_tokens") or 0)
        worst = worst_case_usd(model, prompt_chars, cap, image_tokens=images)
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
                                           default=str).encode("utf-8")).hexdigest()
        nth = asked.get(digest, 0)
        slot = f"{version}#{nth}" if nth else version
        stored, key = answer_on_file(
            step, body, version=slot, valid=valid, prompt_sha256=digest
        )
        if stored is not None:
            asked[digest] = nth + 1
            _metered.last_model = str(stored.get("model") or "") or _metered.last_model
            return stored
        held = reserve(step, worst, model=model, prompt_sha256=digest)
        try:
            payload = send(url, headers=headers, body=body, timeout=timeout)
        except BaseException as exc:
            settle_failure(held, exc, unbilled=unbilled)
            raise
        answer = payload if isinstance(payload, dict) else {}
        entry = settle(
            held,
            model=str(answer.get("model") or model),
            usage=answer.get("usage"),
            finish_reason=str(answer.get("stop_reason") or "error"),
        )
        if keep_answer(key, step, answer, cost_usd=entry["cost_usd"], valid=valid):
            asked[digest] = nth + 1
        # What ANSWERED, for a run record; the ledger line above says the same.
        _metered.last_model = str(answer.get("model") or "") or _metered.last_model
        return payload
    _metered.usage = getattr(send, "usage", None)
    _metered.step = step
    _metered.last_model = None
    return _metered
