"""The model behind every AI step of the general review, and the run.

ClaudeModel: every call is declared with `claude_approved.carrying(<the documents the prompt carries>)`, sent by the app's one
Claude socket `reader_transport.transport()` through `agent_claude._send_once`, which wraps it in `claude_spend.metered(step=...)`
(the approved-document gate, the step / run / day caps, the ledger); the request is built by `agent_claude._request` (both egress
flags, https, the allowed host, the key from the app's settings, never kept), inside `claude_spend.for_run(run_id)` and
`claude_approved.reviewing(run_id)`; the run's meter (`max_usd`) stops a call whose worst case would cross it; never reads backend/.env, logs no key or text.

LocalModel (`local_model`): the same ask() on the local model (`model_transport` only, USD 0, the sizes of `budget.LOCAL`). FakeModel:
no network; fixed JSON per step from the prompt's own material (quotes verify); asks the gate the same question. Tests; USD 0.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field

from . import budget
from .prompts import (
    ANSWER_KEYS,
    _text_of,
    build_parts,
    check_body,
    parse_json,
)

log = logging.getLogger(__name__)

#: Why an item of a saved checklist was not judged: its rule book was not on the list shown before the start.
NOT_ON_LIST = "the rule book was not on the list you saw"
#: Codes after which no later call of the run can succeed: the run stops (the rest of its items are "not judged").
RUN_STOPS = ("run_cap", "gate_closed", "stop")


class StepFailed(RuntimeError):
    """A step that could not finish. The message is a code and plain words, never document text."""

    @property
    def stops_run(self) -> bool:
        code = str(self).split(":", 1)[-1].strip().split(" ", 1)[0]
        return code in RUN_STOPS or str(self).startswith(RUN_STOPS)


@dataclass
class CallRecord:
    step: str
    model: str
    prompt_chars: int
    usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    seconds: float = 0.0
    ok: bool = True
    code: str = ""
    #: "local" and what the call read, on the local model (`local_model`); "" for Claude (a Claude run's calls are unchanged)
    engine: str = ""
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "step": self.step,
            "model": self.model,
            "usd": round(self.usd, 6),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "seconds": self.seconds,
            "ok": self.ok,
            "code": self.code,
        } | {k: v for k, v in (("engine", self.engine), ("note", self.note)) if v}


@dataclass
class Meter:
    """The run's own money meter. `held` is the worst case of every call in flight: a call starts only when spent + held + its
    worst case stays within `cap`, all under `lock` (judge calls run side by side; `aim_review.parallel`)."""

    cap: float
    spent: float = 0.0
    calls: list[CallRecord] = field(default_factory=list)
    held: float = 0.0
    lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    def charge(self, rec: CallRecord) -> None:
        with self.lock:
            self.spent += rec.usd
            self.calls.append(rec)


class ClaudeModel:
    """Claude through the app's one lane. `meter` is bound by `run`."""

    dry = False

    def __init__(self, meter: Meter | None = None) -> None:
        self.meter = meter or Meter(cap=0.0)

    def ask(
        self,
        *,
        step: str,
        model: str,
        system: str,
        cached: str | None,
        prompt: str,
        carries: set[str],
        max_tokens: int,
        effort: str | None = None,
    ):
        from app import claude_spend

        parts = build_parts(system, cached, prompt, effort)
        chars = len(system) + len(cached or "") + len(prompt)
        cap_tokens = int(claude_spend.output_cap(model, max_tokens))
        worst = claude_spend.worst_case_usd(model, chars, max_tokens)
        rec = CallRecord(step=step, model=model, prompt_chars=chars)
        with (
            self.meter.lock
        ):  # the worst case of every call in flight is counted before another starts
            if self.meter.spent + self.meter.held + worst > self.meter.cap:
                rec.ok, rec.code = False, "run_cap"
                self.meter.calls.append(rec)
                raise StepFailed(
                    f"{step}: run_cap (USD {self.meter.cap:.2f} would be crossed)"
                )
            self.meter.held += worst
        try:
            return self._send(
                step, model, parts, carries, max_tokens, cap_tokens, worst, rec
            )
        finally:  # this call's hold on the run meter is released exactly once, on every path
            with self.meter.lock:
                self.meter.held -= worst

    def _send(self, step, model, parts, carries, max_tokens, cap_tokens, worst, rec):
        from app import agent_claude, claude_approved, claude_spend, reader_transport

        t0 = time.time()
        with claude_approved.carrying(sorted(carries)):
            raw = reader_transport.transport()
            if raw is None:
                rec.ok, rec.code = False, "gate_closed"
                self.meter.charge(rec)
                raise StepFailed(f"{step}: gate_closed")
            try:
                request = agent_claude._request(model, max_tokens, None)
            except agent_claude.AgentClaudeError:
                rec.ok, rec.code = False, "gate_closed"
                self.meter.charge(rec)
                raise StepFailed(f"{step}: gate_closed") from None
            body = dict(request["body"])
            body.update(parts)
            body["model"], body["max_tokens"] = model, cap_tokens
            problems = check_body(body)
            if problems:
                del request
                rec.ok, rec.code = False, "bad_shape"
                self.meter.charge(rec)
                raise StepFailed(f"{step}: bad_shape ({'; '.join(problems)})")
            answer, failure = agent_claude._send_once(raw, request, body, step)
            del (
                request
            )  # the headers (the key) leave this frame before anything is raised
        rec.seconds = round(time.time() - t0, 2)
        if failure is not None:
            kind, code, billed, _retry = failure
            rec.ok, rec.code, rec.usd = False, str(code), (worst if billed else 0.0)
            self.meter.charge(rec)
            raise StepFailed(f"{step}: {'stop' if kind == 'stop' else kind} {code}")
        answer = answer if isinstance(answer, dict) else {}
        usage = answer.get("usage") or {}
        rec.usd = float(claude_spend.cost_usd(model, usage)) if usage else worst
        rec.input_tokens = int(usage.get("input_tokens") or 0)
        rec.output_tokens = int(usage.get("output_tokens") or 0)
        rec.cache_read = int(usage.get("cache_read_input_tokens") or 0)
        rec.cache_write = int(usage.get("cache_creation_input_tokens") or 0)
        self.meter.charge(rec)
        if answer.get("stop_reason") in ("max_tokens", "refusal"):
            rec.ok, rec.code = False, "stop_" + str(answer.get("stop_reason"))
            raise StepFailed(f"{step}: {rec.code}")
        out = parse_json(_text_of(answer), ANSWER_KEYS.get(step))
        if out is None:
            rec.ok, rec.code = False, "no_json"
            raise StepFailed(f"{step}: no_json")
        return out


# ------------------------------------------------------------------ the run


def _models() -> tuple[str, str]:
    """(lead model, strong model): the gate's settings, the one place they are read (`aim_review_gate`)."""
    from app import aim_review_gate

    return str(aim_review_gate.lead_model()), str(aim_review_gate.strong_model())


def gate_checker():
    """`gate_ok(doc_id) -> None | refusal code`: what the send gate would say about a prompt that carries that one book."""
    from app import claude_approved

    if budget.is_local():  # nothing is sent on the local model
        return lambda _doc_id: None

    def gate_ok(doc_id: str) -> str | None:
        with claude_approved.carrying([doc_id]):
            r = claude_approved.refusal()
        return None if r is None else r[0]

    return gate_ok


def _stamp() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


#: The cost of a run whose ledger could not be read after it: shown as these words, never as 0.
COST_NOT_READ = "cost not read: the spend ledger could not be read after the review"


def _ledger_cost(run_id: str, calls: list[dict]) -> float | None:
    """The run's cost from the ledger's own lines for it (review R1 N4). A ledger that cannot be read AFTER the run never loses
    the judged lines (review fix check): None (null, rendered as nothing, never 0), and `calls` gets a line saying why. The
    ledger's own caps bound the run whatever this says."""
    from app import claude_spend

    try:
        with claude_spend.for_run(run_id):
            return round(claude_spend.run_spent(), 6)
    except Exception as exc:  # noqa: BLE001 - an unreadable ledger must not fail a paid run's lines
        log.warning(
            "general review %s: the spend ledger could not be read (%s)",
            run_id,
            type(exc).__name__,
        )
        calls.append(
            {
                "step": "ledger",
                "model": "",
                "usd": None,
                "ok": False,
                "code": COST_NOT_READ,
            }
        )
        return None


def run(
    conn,
    *,
    run_id: str,
    paper_id: str,
    allowed_books: frozenset[str],
    store,
    max_usd: float,
    progress=None,
    cancelled=None,
    model=None,
    cited_books=None,
):
    """The general review of one paper. `cited_books`: the ids of the held company books the paper cites (the job may pass
    them; ids only); None: read by code from the stored paper (`library.cited_company`). Never writes the database itself (the checklist is saved through `store`), never raises
    for a model failure: a stopped run keeps the lines it judged and the rest as Question "not judged (<code>)"."""
    from . import Result, faults, updates

    t0 = time.time()
    meter = Meter(cap=float(max_usd))
    inner = model if model is not None else ClaudeModel()
    inner.meter = meter
    allowed_books = frozenset(str(b) for b in allowed_books or ()) - {str(paper_id)}
    state = _RunState(run_id=str(run_id), paper_id=str(paper_id))
    state.cited = (
        None if cited_books is None else frozenset(str(b) for b in cited_books)
    )
    mdl = updates.nine_wrap(_Carried(inner, state.books, str(paper_id)), str(run_id), str(paper_id))  # off: the _Carried itself  # fmt: skip

    def say(pct: int, words: str) -> None:
        if progress is not None:
            try:
                progress(int(pct), words)
            except Exception:  # noqa: BLE001 - a progress callback never stops the review
                log.debug("general review %s: progress callback failed", run_id)

    try:  # budget.of: smaller pieces per call on the local model; faults.during_run: ledger, papers it may send, failed steps
        with budget.of(inner), faults.during_run(str(run_id), meter.calls):
            _steps(conn, state, mdl, allowed_books, store, say, cancelled)
    except StepFailed as exc:
        state.stop(str(exc))
    except Exception as exc:  # noqa: BLE001 - a fault is a stopped run with its code, never a crash of the worker
        where = _fault_at(exc)
        log.warning(
            "general review %s stopped by a fault (%s at %s)",
            run_id,
            type(exc).__name__,
            where,
        )
        state.stop(f"fault: {type(exc).__name__} at {where}")
    say(100, "counts")
    # THE COST IS THE LEDGER'S (review R1 N4; REVIEW.md: a paid run's cost is read from the ledger's lines, never from one stored
    # field): what this run's lines in `claude_spend` hold, an open hold at its worst case. The run's own meter only stops calls.
    calls = [c.as_dict() for c in meter.calls]
    ledger_usd = _ledger_cost(str(run_id), calls)
    return Result(
        status="stopped" if state.stop_reason else "done",
        stop_reason=state.stop_reason,
        identity=state.identity,
        checklist_key=state.key,
        checklist_sha256=state.sha,
        checklist_reused=state.reused,
        books=sorted(state.books - state.reference_ids),
        not_held=state.not_held,
        unlisted_books=sorted(state.unlisted),
        unlisted_count=len(state.unlisted),
        lines=state.lines(),
        calls=calls,
        usd=ledger_usd,
        seconds=round(time.time() - t0, 2),
        references=state.references,
        answered=state.answered,
        book_why=state.every_reason(),
    )


#: Failures raised BEFORE anything was sent: the documents of that call were not carried.
_NOT_SENT = ("run_cap", "gate_closed", "bad_shape", "stop", "build_saw_paper")


class _Carried:
    """The model as the run sees it: it records which rule books a prompt really carried (`Result.books`)."""

    def __init__(self, model, books: set[str], paper_id: str) -> None:
        self.model, self.books, self.paper_id = model, books, paper_id
        self._lock = threading.Lock()  # judge calls run side by side

    @property
    def dry(self) -> bool:
        return bool(getattr(self.model, "dry", False))

    @property
    def meter(self) -> Meter:
        return self.model.meter

    def ask(self, **kw):
        ids = {str(c) for c in kw.get("carries") or ()} - {self.paper_id}
        try:
            out = self.model.ask(**kw)
        except StepFailed as exc:
            code = str(exc).split(":", 1)[-1].strip().split(" ", 1)[0]
            if code not in _NOT_SENT:
                with self._lock:
                    self.books |= ids
            raise
        with self._lock:
            self.books |= ids
        return out


class _RunState:
    def __init__(self, *, run_id: str, paper_id: str) -> None:
        self.run_id, self.paper_id = run_id, paper_id
        self.stop_reason = ""
        self.identity: dict = {}
        self.key, self.sha, self.reused = "", "", False
        self.books: set[str] = set()
        self.references: list[dict] = []
        self.answered: list[
            dict
        ] = []  # the whole-paper check's verdicts (local run record)
        self.reference_ids: set[str] = set()
        self.book_why: dict[str, str] = {}
        self.book_fallback: dict[str, str] = {}
        self.not_held: list[dict] = []
        self.unlisted: set[str] = set()
        self.decided: list[dict] = []
        self.cited: frozenset[str] | None = (
            None  # the held company books the paper cites (ids)
        )

    def stop(self, why: str) -> None:
        if not self.stop_reason:
            self.stop_reason = why[:300]
            log.info(
                "general review %s stopped: %s",
                self.run_id,
                self.stop_reason.split(" ", 2)[:2],
            )

    def every_reason(self) -> dict[str, str]:
        from . import book_names as BN

        return BN.every_reason(self.book_why, self.book_fallback, self.books - self.reference_ids, self.reused)  # fmt: skip

    def lines(self) -> list[dict]:
        return [to_line(i + 1, d) for i, d in enumerate(self.decided)]


def to_line(n: int, d: dict) -> dict:
    """One decided item as section D's `aim_lines` columns (`shown_label` is D's: one home)."""
    return {
        "line_no": n,
        "item_id": d.get("item_id") or "",
        "finding_no": d.get("finding_no")
        or 1,  # the place's index within its item (1 when the item has one line)
        "label": d.get("label") or "Question",
        "field": d.get("field") or "",
        "page": d.get("page") if isinstance(d.get("page"), int) else None,
        "quote": d.get("quote") or "",
        "quote_unverified": d.get("quote_unverified") or "",
        "comment": d.get("comment") or "",
        "standard": d.get("standard") or "",
        "book_document_id": d.get("book_document_id") or "",
        "clause": d.get("clause") or "",
        "source": d.get("source") or "",
        "topic": d.get("topic") or "",
        "code_note": d.get("code") or "",
        "numbers_json": json.dumps(d["numbers"], ensure_ascii=False)
        if d.get("numbers")
        else None,
        "named_books_json": json.dumps(d["named_books"], ensure_ascii=False)
        if d.get("named_books")
        else None,
        "code_compare_json": json.dumps(d["code_compare"], ensure_ascii=False)
        if d.get("code_compare")
        else None,
        "deferred": bool(
            d.get("deferred")
        ),  # the store's shown_label reads it: a deferred value is always a Question
        "ask": d.get("ask")
        or None,  # what a Question asks (`steps._ask`); recorded only
    }


def _steps(
    conn, state: _RunState, mdl, allowed_books: frozenset[str], store, say, cancelled
) -> None:
    from app import document_groups as DG

    from . import library as L
    from . import pictures as PIC
    from . import steps as S
    from . import unread as U
    from .paper import load_paper, windows

    lead, strong = _models()
    say(0, "read the paper")
    PIC.read(conn, state.paper_id, mdl.meter)  # page pictures first (switch on)
    paper = load_paper(conn, state.paper_id)
    # The trace says where each page's text came from (counts only, no text): a row of the run's calls, no model, no cost.
    paper = U.with_unread(conn, state.paper_id, paper, load_paper)
    mdl.meter.calls.extend(U.read_calls(paper))
    if not paper.pages:
        raise StepFailed("no_pages: the paper has no stored page text")
    say(5, "name the paper")
    ident = DG.route(conn, state, S.s1_identify(mdl, paper, _known_keys(store), lead), _identity_record)  # fmt: skip
    from app import aim_review_store

    aim_review_store.keep_identity(conn, state.run_id, state.identity)
    if state.cited is None:
        state.cited = L.cited_company(conn, state.paper_id)
    state.key = L.cited_key(
        L.checklist_key(ident["kind"], ident["equipment_type"], ident["subject_key"])
        or f"{ident['kind']}__other",
        state.cited,
    )
    text = L.BookText(conn)
    say(15, "checklist")
    checklist = _checklist(
        conn, state, mdl, ident, allowed_books, store, text, lead, strong
    )
    from . import book_names as BN

    state.book_why = _book_reasons(checklist)
    state.book_fallback = BN.fallback_reasons(conn, state.paper_id, ident, allowed_books, state.cited)  # fmt: skip
    # the standards the paper itself cites (S1, each verified in its quote) that no held document answers: said as not held
    state.not_held = BN.with_cited_not_held(
        conn, state.paper_id, ident.get("cited"), state.not_held
    )
    state.not_held = BN.unique_not_held(state.not_held)  # each standard said once
    say(25, "judge")
    _judge(
        state,
        mdl,
        paper,
        checklist,
        text,
        allowed_books,
        windows(paper, ident["kind"]),
        lead,
        say,
        cancelled,
    )
    if not state.stop_reason:
        _after_judge(conn, state, mdl, paper, checklist, allowed_books, lead, say)
        from .updates import formula_lines

        formula_lines(conn, paper, state)  # own switch, on; off: none
    state.decided += BN.cited_points(
        state.not_held
    )  # a cited book not held: one point each, on All points, never sent


def _after_judge(
    conn, state, mdl, paper, checklist: dict, allowed_books, lead: str, say
) -> None:
    """After the judge, in order: the contract's reference papers (G), the second reader (S4c: a finding the AI alone decided
    needs two readers), the whole-paper check (S4b, behind its switch: a line whose claim the paper contradicts is not sent), the
    editor (S5), and last the no-ask mark (code: a Question that asks nothing is kept on All points, not sent)."""
    from . import asks, contract_code
    from . import references as R
    from .updates import s4b

    s4b_answered = s4b()  # 6b's guard v3, else main's check
    from .editor import s5_edit
    from .second_read import s4c_second_read

    # a contract's open questions that name a held Schedule of its own package are checked against it (reference papers)
    state.references, state.reference_ids = R.check(
        conn, mdl, paper, state.decided, allowed_books, lead
    )
    say(95, "whole-paper check and second reader")
    from app import aim_review_gate

    s4c_second_read(mdl, paper, state.decided, checklist, lead)
    if (
        aim_review_gate.answered_check_on()
    ):  # off by default (a way-back switch): code proves the quote, not the answer
        s4b_answered(
            mdl, paper, state.decided, lead, state.answered
        )  # after the second reader: its words are claims too
    say(96, "judge")
    s5_edit(mdl, paper, state.decided, lead)
    asks.mark(
        state.decided
    )  # last, after every AI step: a Question that asks nothing is kept on All points, not sent
    contract_code.add_lines(
        conn, state, paper, allowed_books
    )  # a contract's code checks (builder C): after every AI step, so none rewrites a code line


def _fault_at(exc: BaseException) -> str:
    """Where a fault was raised, as "file.py:line" of the innermost frame in the app's own code (no message: a key or value
    could hold document words), or "unknown"."""
    import traceback
    from pathlib import Path

    frames = [
        f
        for f in traceback.extract_tb(exc.__traceback__)
        if "/app/" in f.filename.replace("\\", "/")
    ]
    if not frames:
        return "unknown"
    f = frames[-1]
    return f"{Path(f.filename).parent.name}/{Path(f.filename).name}:{f.lineno}"


def _book_reasons(checklist: dict) -> dict[str, str]:
    """{book id: why the scope step chose it}, read from the checklist's own book list (a built one and a saved one alike)."""
    out: dict[str, str] = {}
    for b in (checklist or {}).get("books") or []:
        if isinstance(b, dict) and b.get("book"):
            out[str(b["book"])] = str(b.get("why") or "")
    return out


def _known_keys(store) -> list[str]:
    """The checklist keys the store already holds (type names only), when it can list them; S1 reuses one of the same type."""
    keys = getattr(store, "keys", None)
    if not callable(keys):
        return []
    from . import faults
    from . import library as L

    try:
        return sorted({L.base_key(str(k)) for k in keys()})  # the type names only
    except Exception as exc:  # noqa: BLE001 - none listed: named without them, and the run says so
        faults.record("aim_checklist_keys", "listing the saved checklists", exc)
        return []


def _saved_current(store, state: _RunState) -> dict | None:
    """The saved checklist of the run's key when it was built by THIS checklist method (`checklist.CHECKLIST_METHOD`); one from
    another method is not reused (the run builds it again once; the old one stays in the store as history)."""
    from . import checklist as CL

    saved = store.get(state.key) if store is not None else None
    if isinstance(saved, dict) and saved.get("method") != CL.checklist_method():
        log.info(
            "general review %s: the saved checklist is from another checklist method: built again",
            state.run_id,
        )
        return None
    return saved


def _lost_knowledge(checklist: dict, sel: dict, run_id: str) -> bool:
    """True when books are needed but not held and the knowledge step wrote NO item (a failed call, every item set aside): such a
    checklist is used for this run only and never saved (18 Nov 2026: a HAZOP one saved without its risk items would be reused)."""
    if not sel.get("not_held") or checklist.get("knowledge_items"):
        return False
    log.warning(
        "general review %s: no knowledge item written while books are not held: checklist not saved",
        run_id,
    )
    return True


def _identity_record(ident: dict) -> dict:
    """What the run record keeps of S1's answer: kind, type, subject, service, verified scope, and the standards read by name and page only."""
    return {
        # the standards S1 read on the paper, names and pages only (the run record shows what it found; no quote)
        "cited": [
            {"name": str(c.get("name") or ""), "page": c.get("page")}
            for c in ident.get("cited") or []
        ],
        "cited_unverified": len(ident.get("cited_unverified") or []),
    } | {
        k: ident.get(k)
        for k in (
            "kind",
            "equipment_type",
            "subject",
            "subject_key",
            "service",
            "scope_quote",
            "scope_page",
        )
    }


def _checklist(
    conn,
    state: _RunState,
    mdl,
    ident: dict,
    allowed_books,
    store,
    text,
    lead: str,
    strong: str,
) -> dict:
    """The saved checklist of the paper's type, else one built from the listed books (standards only) and saved."""
    from . import book_names as BN
    from . import checklist as CL
    from . import library as L
    from . import scope_books as SB

    saved = _saved_current(store, state)
    if (
        isinstance(saved, dict)
        and saved.get("built_from") in CL.BUILT_FROMS
        and isinstance(saved.get("items"), list)
    ):
        want = CL.wanted(
            conn, state.paper_id, CL.type_identity(ident), allowed_books, state.cited
        )
        # the saved AI "needed" names sorted again: a held book now on the list means build again; held, not listed: unlisted
        use, unlisted, still = BN.resort_saved(conn, state.paper_id, saved.get("not_held"), allowed_books, ident.get("kind"), gate_checker())  # fmt: skip
        # a book this run requires (governing, method, cited by the paper) that the saved checklist does not rest on: build again
        use += BN.new_required(conn, state.paper_id, saved, want["listed"], state.cited, allowed_books, ident.get("kind"), gate_checker())  # fmt: skip
        if (
            L.wanted_not_held(saved.get("not_held"))
            == L.wanted_not_held(want["not_held"])
            and SB.saved_fits_scope(conn, saved, ident, state.cited or frozenset())
            and not use
        ):
            state.reused = True
            state.sha = str(saved.get("sha256") or "")
            state.not_held = still
            state.unlisted |= set(want["unlisted"]) | set(unlisted)
            return saved
        # a book the saved checklist was written without is now held (or the governing table changed): build again
        log.info(
            "general review %s: the held books changed since the checklist was saved: built again",
            state.run_id,
        )
    usd_before = mdl.meter.spent
    checklist, sel = CL.build(
        mdl,
        conn,
        paper_id=state.paper_id,
        ident=ident,
        allowed_books=allowed_books,
        gate_ok=gate_checker(),
        lead=lead,
        strong=strong,
        text=text,
        key=state.key,
        made_at=_stamp(),
        cited=state.cited,
    )
    state.not_held = list(sel["not_held"])
    state.unlisted |= set(sel["unlisted"])
    if store is None or _lost_knowledge(checklist, sel, state.run_id):
        return checklist
    try:
        usd = round(mdl.meter.spent - usd_before, 6)
        state.sha = str(
            store.put(state.key, checklist, run_id=state.run_id, usd=usd) or ""
        )
    except Exception as exc:  # noqa: BLE001 - a store that refuses the checklist: judged anyway, not saved, said so in the run
        from . import faults

        faults.record("aim_checklist_save", "saving the checklist", exc)
        state.sha = ""
    return checklist


#: The code note of a saved item from a COMPANY rule book this paper does not cite (the store shows it as
#: `aim_review_store.NOT_CITED_SHOWN`): true by construction, the book is used only when the paper cites it.
NOT_CITED = "rule book not cited by this paper"


def _judge(
    state: _RunState,
    mdl,
    paper,
    checklist: dict,
    text,
    allowed_books,
    wins,
    lead: str,
    say,
    cancelled,
) -> None:
    """The decided lines of every checklist item, in order (one per item, or per failing place). An item whose book is not on
    the list shown is never sent: "not judged", its book counted as unlisted. Company books not cited: "Does not apply"."""
    from . import always, updates
    from . import library as L
    from . import steps as S
    from . import verify as V

    books = {b["alias"]: b for b in checklist.get("books") or [] if isinstance(b, dict)}
    items = [
        it
        for it in checklist.get("items") or []
        if isinstance(it, dict) and it.get("id")
    ]
    # the three always-on checks of every review (G1 cited standards, G2 internal consistency, G3 required entries)
    items += always.items(
        text.conn, state.identity, checklist, allowed_books, paper.pages
    )
    judged, held_back, not_cited = [], set(), set()
    company = L.company_books_not_cited(text.conn, state.paper_id, books)
    for it in items:
        bid = S.item_book(it, books)
        if (
            bid and bid in company
        ):  # a company book the paper does not cite: it does not apply, listed or not
            not_cited.add(
                it["id"]
            )  # a company standard this paper neither cites nor is governed by: it does not apply
        elif bid and bid not in allowed_books:
            held_back.add(it["id"])
            state.unlisted.add(bid)
        else:
            judged.append(it)
    lines, stop = S.s4_judge(
        mdl,
        paper,
        checklist,
        text,
        items=judged,
        windows=wins,
        lead=lead,
        cancelled=cancelled,
        progress=lambda pct, _w: say(25 + int(pct * 0.7), "judge"),
        scope=state.identity,
    )
    lines, stop = updates.nine_missed(mdl, paper, checklist, text, judged, lines, stop, windows=wins, lead=lead, cancelled=cancelled, scope=state.identity)  # role 5, after the judge (nine roles; off: unchanged)  # fmt: skip
    by_id: dict[str, list[dict]] = {}
    for ln in lines:
        by_id.setdefault(ln["item_id"], []).append(ln)
    for it in items:
        if it["id"] in not_cited:
            own = [dict(S.decided_as(it, NOT_CITED, paper, books), finding_no=1)]
        elif it["id"] in held_back:
            own = [dict(S._decide(it, None, paper, books, NOT_ON_LIST), finding_no=1)]
        else:
            own = by_id[it["id"]]
        for line in own:
            line["book_document_id"] = S.item_book(it, books)
            V.keep_clause_if_found(
                line, text
            )  # a clause the book does not print is not shown
            state.decided.append(line)
    if stop:
        state.stop(stop)


from .fake import FakeModel  # noqa: E402, F401 - tests and the dry run (its own module)
from .local_model import LocalModel  # noqa: E402, F401
