"""The model behind every AI step of the general review, and the run.

ClaudeModel: every call is declared with `claude_approved.carrying(<the documents the prompt carries>)`, sent by the app's one
Claude socket `reader_transport.transport()` through `agent_claude._send_once`, which wraps it in `claude_spend.metered(step=...)`
(the approved-document gate, the step / run / day caps, the ledger); the request is built by `agent_claude._request` (both egress
flags, https, the allowed host, the key from the app's settings, never kept). The run calls them inside
`claude_spend.for_run(run_id)` and `claude_approved.reviewing(run_id)`. The run's own meter (`max_usd`) stops before a call whose
worst case would cross it. Nothing here reads backend/.env or logs a key or any document text: errors are codes.

FakeModel: no network. It answers each step with fixed JSON built from the prompt's own material (so quotes verify) and asks the
gate the same question (`claude_approved.refusal()` inside the same declaration). Tests use it; it costs nothing.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field

from .prompts import (
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
        }


@dataclass
class Meter:
    cap: float
    spent: float = 0.0
    calls: list[CallRecord] = field(default_factory=list)


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
        from app import agent_claude, claude_approved, claude_spend, reader_transport

        parts = build_parts(system, cached, prompt, effort)
        chars = len(system) + len(cached or "") + len(prompt)
        cap_tokens = int(claude_spend.output_cap(model, max_tokens))
        worst = claude_spend.worst_case_usd(model, chars, max_tokens)
        rec = CallRecord(step=step, model=model, prompt_chars=chars)
        if self.meter.spent + worst > self.meter.cap:
            rec.ok, rec.code = False, "run_cap"
            self.meter.calls.append(rec)
            raise StepFailed(
                f"{step}: run_cap (USD {self.meter.cap:.2f} would be crossed)"
            )
        t0 = time.time()
        with claude_approved.carrying(sorted(carries)):
            raw = reader_transport.transport()
            if raw is None:
                rec.ok, rec.code = False, "gate_closed"
                self.meter.calls.append(rec)
                raise StepFailed(f"{step}: gate_closed")
            try:
                request = agent_claude._request(model, max_tokens, None)
            except agent_claude.AgentClaudeError:
                rec.ok, rec.code = False, "gate_closed"
                self.meter.calls.append(rec)
                raise StepFailed(f"{step}: gate_closed") from None
            body = dict(request["body"])
            body.update(parts)
            body["model"], body["max_tokens"] = model, cap_tokens
            problems = check_body(body)
            if problems:
                del request
                rec.ok, rec.code = False, "bad_shape"
                self.meter.calls.append(rec)
                raise StepFailed(f"{step}: bad_shape ({'; '.join(problems)})")
            answer, failure = agent_claude._send_once(raw, request, body, step)
            del (
                request
            )  # the headers (the key) leave this frame before anything is raised
        rec.seconds = round(time.time() - t0, 2)
        if failure is not None:
            kind, code, billed, _retry = failure
            rec.ok, rec.code, rec.usd = False, str(code), (worst if billed else 0.0)
            self.meter.spent += rec.usd
            self.meter.calls.append(rec)
            raise StepFailed(f"{step}: {'stop' if kind == 'stop' else kind} {code}")
        answer = answer if isinstance(answer, dict) else {}
        usage = answer.get("usage") or {}
        rec.usd = float(claude_spend.cost_usd(model, usage)) if usage else worst
        rec.input_tokens = int(usage.get("input_tokens") or 0)
        rec.output_tokens = int(usage.get("output_tokens") or 0)
        rec.cache_read = int(usage.get("cache_read_input_tokens") or 0)
        rec.cache_write = int(usage.get("cache_creation_input_tokens") or 0)
        self.meter.spent += rec.usd
        self.meter.calls.append(rec)
        if answer.get("stop_reason") in ("max_tokens", "refusal"):
            rec.ok, rec.code = False, "stop_" + str(answer.get("stop_reason"))
            raise StepFailed(f"{step}: {rec.code}")
        out = parse_json(_text_of(answer))
        if out is None:
            rec.ok, rec.code = False, "no_json"
            raise StepFailed(f"{step}: no_json")
        return out


# ------------------------------------------------------------------ the fake model (tests)


def _long_lines(text: str):
    return [ln.strip() for ln in text.splitlines() if len(ln.strip()) >= 25]


class FakeModel:
    """No network: fixed JSON per step built from the material in the prompt; the gate is asked, nothing is sent.

    `answers` may give a step's answer (a dict, or a function of (step, cached, prompt)); `fail` makes a step raise; `asked`
    keeps every call's step, model, carries and whether a paper block was cached (for tests)."""

    dry = True

    def __init__(
        self,
        *,
        kind: str = "datasheet",
        equipment_type: str | None = None,
        subject_key: str = "fake",
        answers: dict | None = None,
        fail: dict | None = None,
        meter: Meter | None = None,
    ) -> None:
        self.meter = meter or Meter(cap=0.0)
        self.kind, self.equipment_type, self.subject_key = (
            kind,
            equipment_type,
            subject_key,
        )
        self.answers = dict(answers or {})
        self.fail = dict(fail or {})
        self.asked: list[dict] = []

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
        from app import claude_approved, claude_spend

        with claude_approved.carrying(sorted(carries)):
            refused = claude_approved.refusal()
        body = {
            "model": model,
            "max_tokens": int(claude_spend.output_cap(model, max_tokens)),
            **build_parts(system, cached, prompt, effort),
        }
        problems = check_body(body)
        chars = len(system) + len(cached or "") + len(prompt)
        rec = CallRecord(step=step, model=model, prompt_chars=chars, code="fake")
        self.asked.append(
            {
                "step": step,
                "model": model,
                "carries": frozenset(carries),
                "cached": bool(cached),
                "prompt": prompt,
                "cached_text": cached or "",
            }
        )
        if problems:
            rec.ok, rec.code = False, "bad_shape"
            self.meter.calls.append(rec)
            raise StepFailed(f"{step}: bad_shape ({'; '.join(problems)})")
        if refused is not None:
            rec.ok, rec.code = False, f"refused:{refused[0]}"
            self.meter.calls.append(rec)
            raise StepFailed(f"{step}: stop {refused[0]}")
        self.meter.calls.append(rec)
        if step in self.fail:
            rec.ok, rec.code = False, str(self.fail[step])
            raise StepFailed(f"{step}: {self.fail[step]}")
        given = self.answers.get(step)
        if callable(given):
            return given(step, cached or "", prompt)
        if given is not None:
            return given
        return self.fake_answer(step, cached or "", prompt)

    def fake_answer(self, step: str, cached: str, prompt: str):
        """Deterministic stand-in answers that exercise every code path (quotes found and not found, numbers, labels)."""
        pages = re.findall(r"=== PAGE (\d+) ===\n(.*?)(?=\n=== PAGE|\Z)", cached, re.S)
        if step == "aim_identify":
            n, txt = pages[0]
            q = (_long_lines(txt) or [txt.strip()[:40]])[0][:60]
            return {
                "kind": self.kind,
                "equipment_type": self.equipment_type,
                "subject": "fake subject",
                "subject_key": self.subject_key,
                "service": "",
                "evidence": [{"page": int(n), "quote": q}],
                "cited": [],
            }
        if step == "aim_select":
            ids = re.findall(r'"alias": "(B\d+)"', prompt)[:10]
            return {
                "books": [{"alias": a, "why": "fake", "subjects": "all"} for a in ids],
                "not_held_needed": [],
            }
        if step in ("aim_checklist", "aim_checklist_retry"):
            rules = re.findall(
                r'\{"rule": "(R\d+)", "book": "(B\d+)", "clause": "([^"]*)", "page": (\d+), "text": "((?:[^"\\]|\\.)*)"',
                prompt,
            )
            items = []
            for i, (_rid, b, cl, pg, tx) in enumerate(rules[:4]):
                items.append(
                    {
                        "topic": f"fake {i}",
                        "what_to_check": "fake check",
                        "book": b,
                        "clause": cl,
                        "page": int(pg),
                        "rule_quote": json.loads(f'"{tx}"')[:80],
                        "applies_when": "always",
                        "paper_fields": ["any"],
                        "kind": "presence",
                        "source": "held standard",
                    }
                )
            items.append(
                {
                    "topic": "fake knowledge",
                    "what_to_check": "y",
                    "book": "",
                    "clause": "",
                    "page": None,
                    "rule_quote": "",
                    "applies_when": "always",
                    "paper_fields": ["any"],
                    "kind": "presence",
                    "source": "not from a held standard",
                    "stands_in_for": "an unheld practice",
                }
            )
            return {"items": items}
        if step == "aim_attack":
            return {"remove": [], "fix": [], "add": []}
        if step == "aim_judge":
            ids = re.findall(r'"id": "([CG]\d+)"', prompt)
            n, txt = pages[0]
            q = (_long_lines(txt) or [txt.strip()[:40]])[0][:50]
            labels = ["Not met", "Question", "Met", "AI opinion", "Does not apply"]
            return {
                "judgments": [
                    {
                        "id": cid,
                        "label": labels[i % len(labels)],
                        "page": int(n),
                        "quote": q,
                        "field": "fake field",
                        "comment": "fake comment",
                    }
                    for i, cid in enumerate(ids)
                ]
            }
        return {}


# ------------------------------------------------------------------ the run


def _models() -> tuple[str, str]:
    """(lead model, strong model): the gate's settings, the one place they are read (`aim_review_gate`)."""
    from app import aim_review_gate

    return str(aim_review_gate.lead_model()), str(aim_review_gate.strong_model())


def gate_checker():
    """`gate_ok(doc_id) -> None | refusal code`: what the send gate would say about a prompt that carries that one book."""
    from app import claude_approved

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
):
    """The general review of one paper. Never writes the database itself (the checklist is saved through `store`), never raises
    for a model failure: a stopped run keeps the lines it judged and the rest as Question "not judged (<code>)"."""
    from app import claude_approved, claude_spend

    from . import Result

    t0 = time.time()
    meter = Meter(cap=float(max_usd))
    inner = model if model is not None else ClaudeModel()
    inner.meter = meter
    allowed_books = frozenset(str(b) for b in allowed_books or ()) - {str(paper_id)}
    state = _RunState(run_id=str(run_id), paper_id=str(paper_id))
    mdl = _Carried(inner, state.books, str(paper_id))

    def say(pct: int, words: str) -> None:
        if progress is not None:
            try:
                progress(int(pct), words)
            except Exception:  # noqa: BLE001 - a progress callback never stops the review
                log.debug("general review %s: progress callback failed", run_id)

    try:
        with claude_spend.for_run(str(run_id)), claude_approved.reviewing(str(run_id)):
            _steps(conn, state, mdl, allowed_books, store, say, cancelled)
    except StepFailed as exc:
        state.stop(str(exc))
    except Exception as exc:  # noqa: BLE001 - a fault is a stopped run with its code, never a crash of the worker
        log.warning(
            "general review %s stopped by a fault (%s)", run_id, type(exc).__name__
        )
        state.stop(f"fault: {type(exc).__name__}")
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
        books=sorted(state.books),
        not_held=state.not_held,
        unlisted_books=sorted(state.unlisted),
        unlisted_count=len(state.unlisted),
        lines=state.lines(),
        calls=calls,
        usd=ledger_usd,
        seconds=round(time.time() - t0, 2),
    )


#: Failures raised BEFORE anything was sent: the documents of that call were not carried.
_NOT_SENT = ("run_cap", "gate_closed", "bad_shape", "stop", "build_saw_paper")


class _Carried:
    """The model as the run sees it: it records which rule books a prompt really carried (`Result.books`)."""

    def __init__(self, model, books: set[str], paper_id: str) -> None:
        self.model, self.books, self.paper_id = model, books, paper_id

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
                self.books |= ids
            raise
        self.books |= ids
        return out


class _RunState:
    def __init__(self, *, run_id: str, paper_id: str) -> None:
        self.run_id, self.paper_id = run_id, paper_id
        self.stop_reason = ""
        self.identity: dict = {}
        self.key, self.sha, self.reused = "", "", False
        self.books: set[str] = set()
        self.not_held: list[dict] = []
        self.unlisted: set[str] = set()
        self.decided: list[dict] = []

    def stop(self, why: str) -> None:
        if not self.stop_reason:
            self.stop_reason = why[:300]
            log.info(
                "general review %s stopped: %s",
                self.run_id,
                self.stop_reason.split(" ", 2)[:2],
            )

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
    }


def _steps(
    conn, state: _RunState, mdl, allowed_books: frozenset[str], store, say, cancelled
) -> None:
    from . import library as L
    from . import steps as S
    from .paper import load_paper, windows

    lead, strong = _models()
    say(0, "read the paper")
    paper = load_paper(conn, state.paper_id)
    # The trace says where each page's text came from (counts only, no text): a row of the run's calls, no model, no cost.
    mdl.meter.calls.append(
        CallRecord(
            step="aim_read_pages",
            model="code",
            prompt_chars=0,
            code=paper.source_note(),
        )
    )
    if not paper.pages:
        raise StepFailed("no_pages: the paper has no stored page text")
    say(5, "name the paper")
    ident = S.s1_identify(mdl, paper, _known_keys(store), lead)
    state.identity = {
        k: ident.get(k)
        for k in ("kind", "equipment_type", "subject", "subject_key", "service")
    }
    state.key = (
        L.checklist_key(ident["kind"], ident["equipment_type"], ident["subject_key"])
        or f"{ident['kind']}__other"
    )
    text = L.BookText(conn)
    say(15, "checklist")
    checklist = _checklist(
        conn, state, mdl, ident, allowed_books, store, text, lead, strong
    )
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
        say(96, "judge")
        S.s5_edit(mdl, paper, state.decided, lead)


def _known_keys(store) -> list[str]:
    """The checklist keys the store already holds (type names only), when it can list them; S1 reuses one of the same type."""
    keys = getattr(store, "keys", None)
    if not callable(keys):
        return []
    try:
        return sorted(str(k) for k in keys())
    except Exception as exc:  # noqa: BLE001 - a store that cannot list its keys gives none
        log.info("general review: checklist keys unreadable (%s)", type(exc).__name__)
        return []


def _wanted_not_held(not_held) -> frozenset[str]:
    """The governing and method books a checklist was written WITHOUT (`checklist.wanted`'s not-held part, by name): when this set
    changes (a book is now held, or the governing table changed), a saved checklist is not reused. Told apart by the explicit
    `source` key (`checklist.WANTED_SOURCES`), never by the words of `why`: an AI's "needed" name never forces a rebuild. A name
    saved before the key existed has no `source` at all (an AI name always had one): it is read by its `why`."""
    from . import WHY_GOVERNS, WHY_METHOD
    from . import checklist as CL

    def table_name(n: dict) -> bool:
        if "source" in n:
            return n.get("source") in CL.WANTED_SOURCES
        return str(n.get("why") or "").startswith((WHY_GOVERNS, WHY_METHOD))

    return frozenset(
        str(n.get("name") or "")
        for n in not_held or []
        if isinstance(n, dict) and table_name(n)
    )


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
    from . import checklist as CL

    saved = store.get(state.key) if store is not None else None
    if (
        isinstance(saved, dict)
        and saved.get("built_from") in CL.BUILT_FROMS
        and isinstance(saved.get("items"), list)
    ):
        want = CL.wanted(conn, state.paper_id, CL.type_identity(ident), allowed_books)
        if _wanted_not_held(saved.get("not_held")) == _wanted_not_held(
            want["not_held"]
        ):
            state.reused = True
            state.sha = str(saved.get("sha256") or "")
            state.not_held = list(saved.get("not_held") or [])
            state.unlisted |= set(want["unlisted"])
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
    )
    state.not_held = list(sel["not_held"])
    state.unlisted |= set(sel["unlisted"])
    if store is None:
        return checklist
    try:
        usd = round(mdl.meter.spent - usd_before, 6)
        state.sha = str(
            store.put(state.key, checklist, run_id=state.run_id, usd=usd) or ""
        )
    except Exception as exc:  # noqa: BLE001 - a store that refuses the checklist: judged anyway, not saved, said so
        log.warning(
            "general review %s: checklist not saved (%s)",
            state.run_id,
            type(exc).__name__,
        )
        state.sha = ""
    return checklist


NOT_CITED = (
    "a company standard this paper neither cites nor is governed by: it does not apply"
)


def _company_books(conn, state, books: dict, allowed_books) -> frozenset[str]:
    """The saved checklist's books that are COMPANY standards not offered for this paper (`library.not_offered_company`)."""
    from . import library as L

    ids = {str(b.get("book")) for b in books.values() if b.get("book")} - set(
        allowed_books
    )
    return L.not_offered_company(conn, state.paper_id, state.identity, ids)


def _not_cited_line(S, it: dict, paper, books: dict) -> dict:
    """An item of a saved checklist from a company standard this paper does not cite: "Does not apply" (never sent, never counted
    as a book to review again)."""
    line = S._decide(
        it, {"label": "Does not apply", "comment": NOT_CITED}, paper, books, ""
    )
    line["code"] = NOT_CITED
    return line


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
    """The decided lines of every checklist item, in order: one per item, or one per place where it fails (by page, at most
    `steps.MAX_FINDINGS`). An item whose book is not on the list shown is never sent: it is
    "not judged" and its book is counted as unlisted."""
    from . import steps as S

    books = {b["alias"]: b for b in checklist.get("books") or [] if isinstance(b, dict)}
    from . import always

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
    company = _company_books(text.conn, state, books, allowed_books)
    for it in items:
        bid = S.item_book(it, books)
        if bid and bid not in allowed_books and bid in company:
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
    )
    by_id: dict[str, list[dict]] = {}
    for ln in lines:
        by_id.setdefault(ln["item_id"], []).append(ln)
    for it in items:
        if it["id"] in not_cited:
            own = [dict(_not_cited_line(S, it, paper, books), finding_no=1)]
        elif it["id"] in held_back:
            own = [dict(S._decide(it, None, paper, books, NOT_ON_LIST), finding_no=1)]
        else:
            own = by_id[it["id"]]
        for line in own:
            line["book_document_id"] = S.item_book(it, books)
            state.decided.append(line)
    if stop:
        state.stop(stop)
