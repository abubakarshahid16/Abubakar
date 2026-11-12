"""The AI reviewer's runner, rewritten for the app from the experiment runner (#1690, owner order 11 Nov 2026).

ONE Claude call per batch of items that share pages: the paper pages first (text), then the held rule texts, the items last;
every answer gives its quotes before its verdict. The lane is `agent_claude._call` -> `reader_transport` ->
`claude_spend.metered`: the existing step caps (USD 5 per step, USD 15 per run) are the only money rule; nothing here changes
a cap or keeps a ledger of its own. A call WAITS for room under the step cap (`AppStepGate`), and a run that cannot fit the
next call stops with a PARTIAL result and says so.

Then, per item, CODE decides (`agent_review_verdict`): the paper quote and the rule quote are verified word for word against
the stored page text; a number line is decided by `compare_figures`; a textual Pass or Fail needs a second opinion from a
different model family on the verified quotes; a Fail is proven only after the context check (F4: one call with the
rule-book page) and the holds (F1 conditional rule, F3 table row or note); a rule that is not AI approved is capped to the
AI's opinion (`cap_unapproved`) and never buys a second opinion. What code did not prove is "AI thinks: met / not met" with
the reason (`agent_review_wording`). A failed call is a Query with the error code, never a verdict.

RESUME: a stored line without an error is kept and never asked again; only items without a line (or with a failed one) are
asked. A kept line of a rule that is NOT AI approved is capped again (nothing lifts the cap).

PRIVACY: no paper or rule-book text goes to a log; logs carry ids, counts and codes. The trace (questions, pages opened,
answers, every gate decision) goes to the run's own table and folder on the local disk only.

NOT in this version: page pictures (drawings and scans: a page without text yields no Pass or Fail), the round-2 experiments.
The absence proof (`absence_check`) is built but OFF by default: an "absent" answer stays a Query.
"""

from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import (
    agent_claude,
    agent_run_second,
    agent_tools,
    claude_auto_approve,
    claude_spend,
)
from . import agent_review_absence as absence
from . import agent_review_crs as crs_lines
from . import agent_review_verdict as verdict
from . import agent_review_wording as wording
from .agent_review_decide import DecideMixin
from .agent_review_request import (
    ABSENCE_SECOND_SYSTEM,
    ANSWER_SHAPE,
    CONCURRENCY,
    CUT_OFF_TWICE,
    FATAL,
    MAX_BATCH,
    MAX_RETRIES,
    MAX_TOKENS_CAP,
    PROMPT_VERSION,
    RETRY_BASE_SECONDS,
    RETRY_MAX_TOKENS,
    RETRY_TOKEN_FACTOR,
    SECOND_MAX_TOKENS,
    SECOND_UNREADABLE,
    SPLITTABLE,
    SYSTEM,
    TOKENS_BASE,
    TOKENS_PER_ITEM,
    AppStepGate,
    ClauseCache,
    _question,
    app_cap,
    app_worst_usd,
    build_parts,
    held_texts,
    make_batches,
    pages_for,
    parse_answers,
    plan_pages,
    stop_reason,
)
from .agent_review_reread import RereadMixin

log = logging.getLogger(__name__)


class Runner(DecideMixin, RereadMixin):
    def __init__(
        self,
        *,
        paper: str,
        items: list[dict],
        pages: Any,
        clauses: ClauseCache,
        model: str,
        send: Callable | None = None,
        env: dict | None = None,
        concurrency: int = CONCURRENCY,
        max_batch: int = MAX_BATCH,
        retry_base: float = RETRY_BASE_SECONDS,
        done_lines: Mapping[str, dict] | None = None,
        paper_kind: str | None = None,
        equipment_type: str | None = None,
        absence_check: bool = False,
        reread_silent: bool = False,
        context_check: bool = True,
        std_pages: Callable[[str, int], str | None] | None = None,
        sink: Callable[[dict, dict], None] | None = None,
        trace_path: Path | None = None,
        tier_lookup: Callable[[Mapping], str | None] | None = None,
    ) -> None:
        self.paper, self.pages, self.clauses = paper, pages, clauses
        self.model, self.send, self.env = model, send, env
        self.concurrency, self.max_batch, self.retry_base = (
            max(1, int(concurrency)),
            max_batch,
            retry_base,
        )
        self.context_check, self.std_pages = bool(context_check), std_pages
        self.sink, self.trace_path = sink, trace_path
        self.meter = agent_claude.SpendMeter(
            app_cap()
        )  # a backstop: the step gate and `metered` are the binding ones
        self.opinion = agent_claude.ClaudeProvider(
            model=model, send=send, env=env, meter=self.meter
        )
        self.total_pages = pages.count(paper)
        self.tier_lookup = (
            tier_lookup  # the CURRENT tier of a rule item, from the label table
        )
        self.items = plan_pages(items, pages, paper, clauses)
        self.items_by_id = {str(i.get("item_id")): i for i in self.items}
        self.stopped = ""
        self.stop_text = ""
        self.gate: AppStepGate | None = None
        self.last_app_worst: float | None = None
        self.run_usd = 0.0
        self.paper_kind, self.equipment_type = paper_kind, equipment_type
        self.lines: dict[str, dict] = {
            k: self._kept(v) for k, v in dict(done_lines or {}).items()
        }
        self.absence_check = bool(absence_check)
        self.reread_enabled = bool(reread_silent)  # C4: off unless the job passes the switch
        self.carried = (
            absence.carried_roles(paper_kind, equipment_type) if absence_check else None
        )
        self._ctx: dict[str, dict] = {}
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._warm = threading.Lock()
        self._warmed = False
        self.lead_models: set[str] = set()
        self.second_models: set[str] = set()
        self.calls = {"lead": 0, "second": 0, "context": 0, "retries": 0, "reread": 0}
        self.counts: dict[str, int] = {}

    # ---- resume: a kept line of a rule that is not AI approved is capped again
    def _kept(self, line: dict) -> dict:
        """A stored line comes back through the SAME exit as a new one: its rule's CURRENT tier decides, so nothing a stored
        line earned under an old tier survives (a rule no longer approved is capped again)."""
        return {**self.exit_line(line), "resumed": True}

    def exit_line(self, line: Mapping) -> dict:
        """THE one exit every line goes through before it is stored or written (table row, xlsx, API): the core's
        `final_cap_all` with the CURRENT label table (`tier_lookup`), the silent-paper rule (`paper_kind`) and the
        "Not reviewed" class. Only ever makes a line less confident."""
        return wording.final_cap_all(
            [line], self.items_by_id, self.tier_lookup, None, self.paper_kind
        )[0]

    # ---- output
    def emit(self, line: dict) -> None:
        line = self.exit_line(line)
        with self._lock:
            self.lines[str(line["item_id"])] = line
            trace = self._trace_of(line)
            if self.sink is not None:
                self.sink(line, trace)
            if self.trace_path is not None:
                with self.trace_path.open("a", encoding="utf-8") as fh:
                    fh.write(
                        json.dumps(
                            {"type": "item", "item_id": line["item_id"], **trace},
                            ensure_ascii=False,
                            default=str,
                        )
                        + "\n"
                    )
        log.info("agent review item decided: class=%s", line.get("verdict_class"))

    def _trace_of(self, line: Mapping) -> dict:
        """Per item: the question asked, every page opened, each model answer, the second opinion and every gate decision
        with its reason. Local only (it holds the prompt's text)."""
        ctx = self._ctx.pop(str(line["item_id"]), {})
        return {
            "prompt_version": PROMPT_VERSION,
            **ctx,
            "gate": {
                "verdict": line.get("verdict"),
                "decided_by": line.get("decided_by"),
                "why": line.get("why"),
                "reason_code": line.get("reason_code"),
                "quotes_checked": line.get("quotes_checked"),
                "compare": line.get("compare"),
                "second_opinion": line.get("second_opinion"),
                "context_check": line.get("context_check"),
                "absence_check": line.get("absence_check"),
                "conditional_hold": line.get("conditional_hold"),
                "not_mentioned_hold": line.get("not_mentioned_hold"),
                "table_note_hold": line.get("table_note_hold"),
                "unapproved_cap": line.get("unapproved_cap"),
                "verdict_label": line.get("verdict_label"),
                "verdict_class": line.get("verdict_class"),
            },
        }

    def trace_record(self, rec: Mapping) -> None:
        if self.trace_path is not None:
            with self._lock, self.trace_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    # ---- one metered call, with the step gate and rate-limit backoff
    def call(
        self, model: str, parts: dict, max_tokens: int, once: bool = False
    ) -> tuple[dict, float]:
        app = app_worst_usd(model, parts, max_tokens)
        self.last_app_worst = app
        for attempt in range(MAX_RETRIES + 1):
            if self._stop.is_set():
                raise agent_claude.AgentBudgetStop(self.stopped or "run_stopped")
            self._admit(app)
            try:
                answer, usd = agent_claude._call(
                    model, parts, max_tokens, self.send, self.env, None
                )
            except agent_claude.AgentBudgetStop:
                self._release(app, 0.0)  # refused before sending: nothing billed
                raise
            except agent_claude.AgentTransportError:
                self._release(
                    app, app
                )  # may have been billed: charged at the worst case (the safe side)
                self._add_usd(app)
                if attempt < MAX_RETRIES and not once:
                    self.calls["retries"] += 1
                    time.sleep(self.retry_base * (2**attempt))
                    continue
                raise
            except agent_claude.AgentBadReply:
                self._release(app, app)
                self._add_usd(app)
                raise
            except Exception:
                self._release(app, 0.0)
                raise
            self._release(app, usd)
            self._add_usd(usd)
            return answer, usd
        raise agent_claude.AgentTransportError("retries_exhausted")

    def _add_usd(self, usd: float) -> None:
        with self._lock:
            self.run_usd += float(usd)

    def _admit(self, app: float) -> None:
        if self.gate is not None:
            self.gate.acquire(app, self._stop.is_set)

    def _release(self, app: float, usd: float) -> None:
        if self.gate is not None:
            self.gate.release(app, usd)

    # ---- the second opinion (agent_run_second.ask_second_opinion through the same lane and the step gate)
    def second_opinion(self, item_id: str, ai_verdict: str, answer: Mapping) -> dict:
        finding = {
            "item": item_id,
            "color": verdict.COLOUR_OF[ai_verdict],
            "doc_quote": answer.get("paper_quote"),
            "clause_quote": answer.get("clause_quote"),
        }
        runner = self
        kept: dict = {}

        class _Opinion:
            def second_opinion(self, f, evidence):
                prompt_chars = len(json.dumps(evidence, ensure_ascii=False)) + 1200
                worst = claude_spend.worst_case_usd(
                    agent_claude.SECOND_MODEL, prompt_chars, SECOND_MAX_TOKENS
                )
                runner._admit(worst)
                try:
                    reply = runner.opinion.second_opinion(f, evidence)
                except Exception:
                    runner._release(worst, worst)
                    runner._add_usd(worst)
                    raise
                usd = float(reply.get("usd") or 0.0) if isinstance(reply, dict) else 0.0
                if isinstance(reply, dict) and reply.get("reason"):
                    kept["reason"] = str(reply.get("reason"))
                runner._release(worst, usd)
                runner._add_usd(usd)
                return reply

        class _Trace:
            usd = 0.0

            def add_spend(self, usd):
                self.usd += usd

        trace = _Trace()
        self.calls["second"] += 1
        got = agent_run_second.ask_second_opinion(_Opinion(), finding, trace)
        got = {**got, "usd": trace.usd, **kept}
        if got.get("model") and got["model"] != agent_run_second.UNKNOWN:
            self.second_models.add(got["model"])
        return got

    def _halt(self, exc: BaseException) -> None:
        with self._lock:
            if self._stop.is_set():
                return
            self.stopped, self.stop_text = stop_reason(exc, self.last_app_worst)
            self._stop.set()
        log.warning("agent review stopped: code=%s", self.stopped)

    def _box(self) -> Any:
        ctx = agent_tools.ToolContext(
            allowed_document_ids=frozenset({self.paper}), document_id=self.paper
        )
        return agent_tools.ToolBox(
            ctx,
            page_reader=lambda d, n: self.pages.page(d, n),
            searcher=lambda _q, _a: {"hits": []},
            standard_pages=lambda _d: [],
        )

    # BOUND of lead calls for one asked group (a single item, or a half already split): at most 2 (first + one retry, whether
    # the retry is for a cut-off at twice the limit or for an unreadable reply at the same limit); a retry after a
    # cut-off is never followed by a third call, and is never re-sent after a transport failure or timeout (a lead call
    # waits `agent_claude.request_timeout(limit)` = max(120 s, limit / 40 tokens a second): at least 120 s, longer as the limit grows, 300 s at the 12,000-token ceiling). A batch of N > 1 that is cut
    # off is 1 call, then at most 2 per half (<= 5 calls), plus <= 2 per re-asked group of items a readable answer left
    # out. COST: the returned usd is the sum of every lead call made for the group (a cut-off call at its reserved worst
    # case, as the run is charged); `run_batch` shares it equally over the group's items. The cut-off call of a batch that
    # is then split is charged to the run, not to any line.
    def _ask_lead(
        self, batch: list[dict], parts: dict, split_ok: bool
    ) -> tuple[dict | None, float, str | None, str | None]:
        """(answers by item id or None, usd, error code or None, answering model); the bound and the cost rule are above."""
        max_tokens = min(MAX_TOKENS_CAP, TOKENS_BASE + TOKENS_PER_ITEM * len(batch))
        answer, usd, error, model = None, 0.0, None, None
        spent = retry_worst = (
            0.0  # what the run was charged for the cut-off call, and for the retry if it was sent
        )
        cut_retry = False  # the larger-limit retry was made: nothing more is asked for this item
        try:
            with self._lock:
                self.calls["lead"] += 1
            try:
                raw, usd = self.call(self.model, parts, max_tokens)
            except agent_claude.AgentBadReply as exc:
                if exc.code != "stop_max_tokens" or (split_ok and len(batch) > 1):
                    raise  # a bigger batch is split by the caller instead
                # cut off, and it cannot be split: ONE more ask with a larger limit. `call` reserves the worst case of THIS
                # limit and the run's caps apply as to any call. Still cut off: "not reviewed", never a guessed verdict.
                # The cut-off call's own cost is not returned; the line carries what the run was charged for it (its
                # reserved worst case), so the line never understates.
                spent = app_worst_usd(self.model, parts, max_tokens)
                retry_worst = 0.0
                bigger = min(RETRY_MAX_TOKENS, max_tokens * RETRY_TOKEN_FACTOR)
                with self._lock:
                    self.calls["lead"] += 1
                    self.calls["retries"] += 1
                cut_retry = True
                retry_worst = app_worst_usd(self.model, parts, bigger)
                try:  # once: a failed or timed-out retry is not sent again
                    raw, usd2 = self.call(self.model, parts, bigger, once=True)
                except agent_claude.AgentBadReply as exc2:
                    if exc2.code == "stop_max_tokens":
                        return (
                            None,
                            spent + retry_worst,
                            CUT_OFF_TWICE,
                            None,
                        )
                    raise
                usd = spent + usd2
            model = agent_claude._answered_model(raw)
            if model != "unknown":
                self.lead_models.add(model)
            answer = parse_answers(raw)
            if answer is None and cut_retry:
                return None, usd, SECOND_UNREADABLE, model
            if answer is None and not (
                split_ok and len(batch) > 1
            ):  # one retry; a bigger batch is split instead
                with self._lock:
                    self.calls["retries"] += 1
                raw, usd2 = self.call(self.model, parts, max_tokens)
                usd += usd2
                answer = parse_answers(raw)
            if answer is None:
                error = "unparseable_reply"
        except FATAL as exc:
            usd = spent  # refused before sending: only the cut-off call was charged
            self._halt(exc)
            error = f"not run: {self.stopped}"
        except agent_claude.AgentClaudeError as exc:
            usd = (
                spent + retry_worst
            )  # a failed retry may have been billed: the run was charged its worst case
            error = exc.code
        except Exception as exc:  # noqa: BLE001  a failed call is "not reviewed", never a verdict
            usd = spent
            log.warning("agent review lead call failed: %s", type(exc).__name__)
            error = "error_" + type(exc).__name__
        return answer, usd, error, model

    def run_batch(self, batch: list[dict], allow_split: bool = True) -> None:
        """One lead call for the batch. An answer cut off at max_tokens (or unreadable) is asked again ONCE per half of the
        batch; items a readable answer left out are asked again once; an item still without an answer is a failed call
        ("not reviewed"), never a verdict."""
        ids = [str(i.get("item_id")) for i in batch]
        numbers = pages_for(batch, self.total_pages)
        pages = {n: t for n in numbers if (t := self.pages.page(self.paper, n))}
        box = self._box()
        if self._stop.is_set():
            for it in batch:
                self.emit(
                    self.decide(
                        it, None, pages, None, f"not run: {self.stopped}", box, 0.0
                    )
                )
            return
        clauses: dict[str, dict] = {}
        held_of: dict[str, list[dict]] = {}
        for it in batch:
            held_of[str(it.get("item_id"))] = held = held_texts(it, self.clauses)
            for h in held:
                clauses.setdefault(
                    h["ref"],
                    {**h, "standard": it.get("standard"), "clause": it.get("clause")},
                )
        parts = build_parts(self.paper, pages, clauses, batch, held_of)
        answer, usd, error, model = self._ask_lead(batch, parts, allow_split)
        if answer is None and allow_split and len(batch) > 1 and error in SPLITTABLE:
            self.trace_record({"type": "split", "item_ids": ids, "after": error})
            mid = (len(batch) + 1) // 2
            self.run_batch(batch[:mid], False)
            self.run_batch(batch[mid:], False)
            return
        self.trace_record(
            {
                "type": "batch",
                "item_ids": ids,
                "prompt_version": PROMPT_VERSION,
                "pages_opened": numbers,
                "pages_read": sorted(pages),
                "model_answered": model,
                "usd": usd,
                "error": error,
            }
        )
        for it in batch:
            iid = str(it.get("item_id"))
            self._ctx[iid] = {
                "batch_item_ids": ids,
                "question": _question(it, held_of.get(iid)),
                "pages_opened": numbers,
                "pages_read": sorted(pages),
                "lead_model": model,
                "lead_error": error,
                "lead_answer": (answer or {}).get(iid),
            }
        share, missing = usd / max(1, len(batch)), []
        for it in batch:
            got = (answer or {}).get(str(it.get("item_id")))
            if got is None and answer is not None and allow_split:
                missing.append(
                    it
                )  # a readable answer that left this item out: asked once more below
                continue
            line = self.decide(
                it, got, pages, model, error if answer is None else None, box, share
            )
            self.emit(self.reread_silent_line(it, line, got, model, box))
        if missing:
            self.run_batch(missing, False)

    def restore(self) -> None:
        """Kept lines went through the exit again in `__init__` (the CURRENT tier); file them again so the table never holds a
        verdict its rule no longer earns. The stored trace is kept."""
        if self.sink is None:
            return
        for line in self.lines.values():
            self.sink({k: v for k, v in line.items() if k != "resumed"}, None)

    def todo(self) -> list[dict]:
        """The items with no stored line, or whose stored line is a failed call: only these are asked."""
        return [
            i
            for i in self.items
            if str(i.get("item_id")) not in self.lines
            or self.lines[str(i.get("item_id"))].get("error")
        ]

    def run(self) -> dict:
        """Call inside `claude_spend.for_run(...)` and `claude_approved.carrying(...)`: the step gate starts from what this
        review run has already spent (a resumed run keeps counting)."""
        self.restore()
        claude_auto_approve.on_agent_standards(
            self.paper, [i.get("standard_document_id") for i in self.items]
        )  # #1584 comment 6806441133 (to be confirmed by the owner): the books this run asks rules from are approved with the paper (off: nothing)
        self.gate = AppStepGate(app_cap(), claude_spend.step_spent(agent_claude.STEP))
        todo = self.todo()
        batches, source = make_batches(todo, self.max_batch)
        self.trace_record(
            {
                "type": "prompt",
                "prompt_version": PROMPT_VERSION,
                "system": SYSTEM,
                "answer_shape": ANSWER_SHAPE,
                "second_system": agent_claude.SECOND_SYSTEM,
                "absence_second_system": ABSENCE_SECOND_SYSTEM,
            }
        )
        log.info(
            "agent review run: %d items to ask in %d batches, %d kept from before, step cap USD %.2f, spent USD %.4f",
            len(todo),
            len(batches),
            len(self.items) - len(todo),
            self.gate.cap,
            self.gate.settled,
        )
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futures = [
                pool.submit(contextvars.copy_context().run, self.run_batch, b)
                for b in batches
            ]
            for f in futures:
                f.result()
        return {"batches": len(batches), "batch_source": source}


def counts_of(lines: Iterable[Mapping]) -> dict:
    """Counts per class of the stored lines, with the not-run lines counted apart. No text."""
    ls = [wording.apply(ln) for ln in lines]
    out = crs_lines.run_counts(ls)
    out["not_run"] = sum(
        1 for ln in ls if str(ln.get("error") or "").startswith("not run")
    )
    return out
