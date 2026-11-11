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
    claude_spend,
)
from . import (
    agent_review_absence as absence,
)
from . import agent_review_context as ctxc
from . import agent_review_crs as crs_lines
from . import agent_review_items as items_mod
from . import agent_review_verdict as verdict
from . import agent_review_wording as wording
from .agent_trace import words
from .reader_api import _fold

log = logging.getLogger(__name__)

#: The context check / final check model (adaptive thinking). Taken from the code that names the lane's models.
FINAL_MODEL = "claude-opus-5-5"
FINAL_MAX_TOKENS = 4000
FINAL_SYSTEM_MARK = "CONTEXT CHECK"
ABSENCE_SECOND_MAX_TOKENS = 200
ABSENCE_SECOND_SYSTEM = (
    "ABSENCE CHECK. You are an independent senior engineer checking another reviewer's claim that a supplier paper "
    "does not state an item that a held requirement asks it to state. You are given EVERY page of the paper, then the "
    "requirement words and the field the requirement asks for (named as the field registry names it). Answer true "
    "only when no page states that item under any name or wording, and the requirement obliges this paper to state "
    "it. If any page states it, if it is marked to follow later, or if you are unsure, answer false."
)
MAX_PAGES_PER_CALL = 4
SMALL_PAPER_PAGES = 8
INFERRED_PAGES = 3
MAX_BATCH = 8
TOKENS_PER_ITEM = 700
TOKENS_BASE = 600
MAX_TOKENS_CAP = 8000
MAX_RETRIES = 3
#: a lead answer that stopped at max_tokens, or could not be read: the batch is split in half and asked once more per half
SPLITTABLE = ("stop_max_tokens", "unparseable_reply")
RETRY_BASE_SECONDS = 4.0
CONCURRENCY = 3
SECOND_MAX_TOKENS = agent_claude.SECOND_MAX_TOKENS
FATAL = (agent_claude.AgentBudgetStop, agent_claude.AgentGateClosed)
#: claude_approved refusals: an owner question, never bypassed.
APPROVAL_CODES = ("undeclared", "not_approved", "unknown_document", "undeclared_documents", "blocked")

SYSTEM = (
    "You are a senior engineer reviewing a supplier paper against held standard requirements, as a reviewer who signs "
    "the comment sheet. The paper pages come first; then, for each item, its REQUIREMENT (the held rule's own words "
    "from the standard) and, when given, the clause text around it for context; the items come last. For each item "
    "first copy the paper quote, then the requirement quote, then give the verdict and its reason_code.\n"
    "- Pass (reason_code met): the paper shows the requirement is met. Quote the paper words that show it and the "
    "requirement words it meets.\n"
    "- Fail (reason_code not_met): the paper states something that does not meet the requirement. Quote both.\n"
    "- Fail (reason_code absent): the requirement asks for something this paper should give, show or state, and the "
    "pages you were given do not. List every page you searched in pages_searched (only pages you were given; never "
    "guess). For paper_quote copy the paper words nearest to where it should be (a heading or a field label), or leave "
    "it empty.\n"
    "- Query only when you truly cannot decide, with ONE reason_code: not_applicable (the requirement does not apply to "
    "what this paper covers), needs_drawing_or_calc (deciding needs a drawing, a calculation or another document), "
    "sheet_silent (the paper does not mention it and the requirement does not oblige this paper to state it), "
    "unclear_clause (the requirement words are unclear or incomplete), other.\n"
    "Quote exactly, character for character, from the text given: code checks every quote against the stored text, "
    "and a quote it cannot find makes the line a query. Take clause_quote from the item's requirement block when there "
    "is one, else from its clause block. A silent paper is never Pass. When the item's rule is a limit, also give "
    "paper_figure and clause_figure: the exact words holding each number with its unit, taken from inside your two "
    "quotes; code compares the numbers, not you. reasoning: at most two plain sentences. comment: one sentence for the "
    "contractor saying what to correct or provide, without your reasoning. Never state confidence."
)
ANSWER_SHAPE = (
    'Reply with ONE JSON object and nothing else: {"answers": [{"item_id": "...", "field_label": "the field name as '
    'printed on the paper", "paper_page": 1, "paper_quote": "...", "clause_quote": "...", "paper_figure": "...", '
    '"clause_figure": "...", "pages_searched": [1, 2], "reasoning": "...", "comment": "...", "verdict": "Pass or Fail '
    'or Query", "reason_code": "met | not_met | absent | not_applicable | needs_drawing_or_calc | sheet_silent | '
    'unclear_clause | other"}]}. One answer per item, in the key order shown: quotes first, verdict last. Leave a key '
    "empty when you have nothing for it."
)
REASON_CODES = ("met", "not_met", "absent", "not_applicable", "needs_drawing_or_calc", "sheet_silent", "unclear_clause",
                "other")
#: Codes that make a line Query whatever the AI said (code cannot prove an absence).
TIGHTENING = ("absent", "absent_pages_not_named", "verdict_and_reason_differ")
PROMPT_VERSION = "app-lead-" + __import__("hashlib").sha256((SYSTEM + ANSWER_SHAPE).encode()).hexdigest()[:10]
REASON_FITS = {"Pass": ("met",), "Fail": ("not_met", "absent"),
               "Query": ("not_applicable", "needs_drawing_or_calc", "sheet_silent", "unclear_clause", "other")}


# ---------------------------------------------------------------- inputs


def held_texts(item: Mapping, cache: ClauseCache) -> list[dict]:
    """The held standard texts sent for an item, in order: the REQUIREMENT (the rule's own quote) first, then the clause text
    as context, only when there is no requirement text or when it holds the requirement. General: a text test, no layout."""
    out: list[dict] = []
    rule_ref, clause_ref = item.get("rule_quote_ref"), item.get("clause_quote_ref")
    rule_text = cache.text(rule_ref)
    if rule_text:
        out.append({"kind": "requirement", "ref": rule_ref, "text": rule_text, "page": cache.page(rule_ref)})
    clause_text = cache.text(clause_ref)
    if clause_text and clause_ref != rule_ref and (not rule_text or _fold(rule_text)[:60] in _fold(clause_text)):
        out.append({"kind": "clause", "ref": clause_ref, "text": clause_text,
                    "page": cache.page(clause_ref) or item.get("clause_page")})
    return out


class ClauseCache:
    """The clause texts the item builder filled: {clause_quote_ref: {'text', 'page', 'source', ...}}."""

    def __init__(self, data: Mapping | None) -> None:
        self._data = dict(data or {})

    def text(self, ref: Any) -> str | None:
        v = self._data.get(ref) if isinstance(ref, str) else None
        if isinstance(v, dict):
            v = v.get("text")
        return v if isinstance(v, str) and v.strip() else None

    def source(self, ref: Any) -> str | None:
        v = self._data.get(ref) if isinstance(ref, str) else None
        return v.get("source") if isinstance(v, dict) else None

    def page(self, ref: Any) -> int | None:
        v = self._data.get(ref) if isinstance(ref, str) else None
        p = v.get("page") if isinstance(v, dict) else None
        return p if isinstance(p, int) and not isinstance(p, bool) else None


class DbPages:
    """Page text of the paper, read ONCE in the job's thread (a sqlite connection does not cross threads)."""

    def __init__(self, conn: Any, paper: str) -> None:
        rows = conn.execute("SELECT page_no, text, needs_ocr FROM pages WHERE document_id = ?", (paper,)).fetchall()
        self.pages = {int(r["page_no"]): r["text"] or "" for r in rows}
        needs_ocr = {int(r["page_no"]): bool(r["needs_ocr"]) for r in rows}
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.ledger_rows: dict[int, dict] | None = {}
        if "page_ledger" in tables:
            for r in conn.execute("SELECT page_no, native_status, ocr_status FROM page_ledger WHERE document_id = ?",
                                  (paper,)):
                self.ledger_rows[int(r["page_no"])] = {"native_status": r["native_status"],
                                                       "ocr_status": r["ocr_status"],
                                                       "needs_ocr": needs_ocr.get(int(r["page_no"]), True)}
        self.facts = [dict(r) for r in conn.execute(
            "SELECT field_name, field_label, page FROM submittal_facts WHERE submittal_document_id = ?", (paper,))
        ] if "submittal_facts" in tables else []
        self.paper = paper

    def page(self, doc: str, n: int) -> str | None:
        return self.pages.get(n) if doc == self.paper else None

    def count(self, doc: str) -> int:
        return max(self.pages, default=0) if doc == self.paper else 0


class StdPages:
    """Stored pages of the rule books, read on demand on the calling thread's own connection (`__call__(doc, page)`)."""

    def __call__(self, doc: str, page: int) -> str | None:
        from .db import connect

        row = connect().execute("SELECT text FROM pages WHERE document_id = ? AND page_no = ?",
                                (doc, int(page))).fetchone()
        return row["text"] if row and (row["text"] or "").strip() else None


def _hints(item: Mapping) -> list[int]:
    return [p for p in item.get("page_hint") or [] if isinstance(p, int) and not isinstance(p, bool) and p >= 1]


def make_batches(items: list[dict], max_batch: int = MAX_BATCH) -> tuple[list[list[dict]], str]:
    """The item builder's `batch_by_page`, every batch then cut to `max_batch` items."""
    out = []
    for b in items_mod.batch_by_page(items):
        b = list(b)
        out.extend(b[i: i + max_batch] for i in range(0, len(b), max(1, max_batch)))
    return [b for b in out if b], "items.batch_by_page"


def page_cap(total_pages: int) -> int:
    """A short paper (a datasheet) is sent whole to every batch; a longer one at most MAX_PAGES_PER_CALL pages."""
    return total_pages if 0 < total_pages <= SMALL_PAPER_PAGES else MAX_PAGES_PER_CALL


def plan_pages(items: list[dict], pages: Any, paper: str, clauses: ClauseCache | None = None) -> list[dict]:
    """Copies of the items with a page hint for every item, so batches share pages (general: words, no layout)."""
    from .agent_bind import content_words

    total = pages.count(paper)
    texts = {n: content_words(pages.page(paper, n) or "") for n in range(1, total + 1)}
    out = []
    for it in items:
        it = dict(it)
        if _hints(it):
            it["page_hint_source"] = "items"
        elif 0 < total <= SMALL_PAPER_PAGES:
            it["page_hint"], it["page_hint_source"] = list(range(1, total + 1)), "short paper: all pages"
        else:
            roles = " ".join(str(r).replace("_", " ") for r in it.get("field_roles") or [])
            clause = (clauses.text(it.get("clause_quote_ref")) if clauses else "") or ""
            want = content_words(f"{it.get('question') or ''} {roles} {clause[:600]}")
            scored = sorted(((len(want & w), -n) for n, w in texts.items() if want & w), reverse=True)
            it["page_hint"] = sorted(-n for _s, n in scored[:INFERRED_PAGES])
            it["page_hint_source"] = "inferred by words" if scored else "none found"
        out.append(it)
    return out


def pages_for(batch: list[dict], total_pages: int) -> list[int]:
    cap = page_cap(total_pages)
    wanted: list[int] = []
    for it in batch:
        for p in _hints(it):
            if p not in wanted and (total_pages <= 0 or p <= total_pages):
                wanted.append(p)
    if not wanted:  # no page found: the first pages, never the whole book
        wanted = list(range(1, min(total_pages, cap) + 1))
    return sorted(wanted[:cap])


# ---------------------------------------------------------------- the request


def _question(item: Mapping, held: list[dict] | None = None) -> dict:
    keys = ("item_id", "question", "field_roles", "standard", "clause", "rule_kind", "comparator", "value", "unit",
            "page_hint")
    out = {k: item.get(k) for k in keys if item.get(k) not in (None, "", [])}
    for h in held or []:
        out[f"{h['kind']}_ref"] = h["ref"]  # which block below is this item's requirement / clause
    return out


def build_parts(paper: str, pages: Mapping[int, str], clauses: Mapping[str, dict], batch: list[dict],
                held_of: Mapping[str, list[dict]] | None = None) -> dict:
    """Documents first (pages, then the held texts), the items last. The documents are cache-marked."""
    content: list[dict] = []
    for n in sorted(pages):
        content.append({"type": "text", "text": f'<paper document="{paper}" page="{n}">\n{pages[n]}\n</paper>'})
    if content:  # breakpoint 1: the pages (the same for every batch of a short paper, so later batches read the cache)
        content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
    n_pages = len(content)
    for ref, c in clauses.items():
        tag = c.get("kind") or "clause"
        head = f'<{tag} ref="{ref}" standard="{c.get("standard") or ""}" clause="{c.get("clause") or ""}"'
        content.append({"type": "text", "text": f"{head} page=\"{c.get('page') or ''}\">\n{c['text']}\n</{tag}>"})
    if len(content) > n_pages:  # breakpoint 2: the held texts
        content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
    held_of = held_of or {}
    questions = [_question(i, held_of.get(str(i.get("item_id")))) for i in batch]
    content.append({"type": "text", "text": json.dumps({"items": questions}, ensure_ascii=False) + "\n\n" + ANSWER_SHAPE})
    return {
        "system": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": content}],
    }


def _text_of(answer: Mapping) -> str:
    return "".join(str(b.get("text") or "") for b in answer.get("content") or []
                   if isinstance(b, dict) and b.get("type") == "text")


def parse_answers(answer: Mapping) -> dict[str, dict] | None:
    obj = agent_claude.parse_json_object(_text_of(answer))
    got = obj.get("answers") if isinstance(obj, dict) else None
    if not isinstance(got, list):
        return None
    return {str(a.get("item_id")): a for a in got if isinstance(a, dict) and a.get("item_id") not in (None, "")}


def reason_of(answer: Mapping, ai: str | None, error: str | None, pages: Mapping[int, str]) -> tuple[str, list[int]]:
    """(reason code, pages searched). The AI's code from the closed list, else 'other'. Code adds: ai_call_failed;
    absent_pages_not_named (an 'absent' Fail must name searched pages, all of them pages it was sent);
    verdict_and_reason_differ (a code that does not fit the verdict). The last two turn the AI verdict into Query."""
    raw = answer.get("pages_searched")
    searched = sorted({p for p in raw if isinstance(p, int) and not isinstance(p, bool)}) if isinstance(raw, list) else []
    if error:
        return "ai_call_failed", searched
    code = str(answer.get("reason_code") or "").strip().lower()
    if not code and ai is not None:
        code = {"Pass": "met", "Fail": "not_met"}.get(ai, "other")
    code = code if code in REASON_CODES else "other"
    if ai is None:
        return code, searched
    if code not in REASON_FITS.get(ai, ()):
        if ai == verdict.QUERY:
            return "other", searched
        return "verdict_and_reason_differ", searched
    if code == "absent" and (not searched or not set(searched) <= set(pages)):
        return "absent_pages_not_named", searched
    return code, searched


def deferred_mark(field: str, pages: Any, paper: str, total: int) -> int | None:
    """The first page where ONE line carries all the field's content words AND a deferral mark from the existing vocabulary
    (`blank_markers.names_a_marker`: "By Contractor", "TBA", ...), else None. A figure followed by a deferral mark is not a
    confirmed value. General: words, no layout."""
    from . import blank_markers
    from .agent_bind import content_words

    want = content_words(field)
    if not want:
        return None
    for n in range(1, total + 1):
        for raw in (pages.page(paper, n) or "").splitlines():
            if blank_markers.names_a_marker(raw) and want <= content_words(raw):
                return n
    return None


# ---------------------------------------------------------------- the app's per-step cap: admission, never a raise


class StepCapStop(agent_claude.AgentBudgetStop):
    code = "app_step_cap"

    def __init__(self, reason: str) -> None:
        super().__init__(self.code)
        self.reason = reason


def app_worst_usd(model: str, parts: Mapping, max_tokens: int) -> float:
    """The worst case `claude_spend.metered` will RESERVE for this request (its own formula on the body)."""
    chars = (len(json.dumps(parts.get("messages") or [], ensure_ascii=False, default=str))
             + len(json.dumps(parts.get("system") or "", ensure_ascii=False, default=str)))
    return claude_spend.worst_case_usd(model, chars, int(max_tokens))


class AppStepGate:
    """Admission to the app's per-step cap of this review run (CLAUDE.md rule 1).

    Parallel batches each RESERVE their worst case; the third could cross the step cap and be refused before any call.
    Here a call WAITS until spent + calls in flight + its own worst case fit under the cap; only when it cannot fit with
    nothing in flight is the run stopped (a real cap, said with its numbers). The cap is never raised; the app's own check
    in `claude_spend.metered` stays the backstop."""

    def __init__(self, cap: float, settled: float = 0.0) -> None:
        self.cap, self.settled, self.inflight = float(cap), float(settled), 0.0
        self._cond = threading.Condition()

    def acquire(self, worst: float, stopped: Callable[[], bool]) -> None:
        with self._cond:
            while True:
                if self.settled + worst > self.cap:
                    raise StepCapStop(
                        f"step {agent_claude.STEP} of this review run: spent USD {self.settled:.4f}, next call up to USD "
                        f"{worst:.4f} by the app's estimate, cap USD {self.cap:.2f}")
                if self.settled + self.inflight + worst <= self.cap:
                    self.inflight += worst
                    return
                if stopped():
                    raise agent_claude.AgentBudgetStop("run_stopped")
                self._cond.wait(timeout=1.0)

    def release(self, worst: float, usd: float) -> None:
        with self._cond:
            self.inflight = max(0.0, self.inflight - worst)
            self.settled += float(usd)
            self._cond.notify_all()


def app_cap() -> float:
    """The app's cap for this step in a review run: per step, and never above the per-run cap."""
    from .config import settings

    caps = claude_spend.Caps.from_settings().for_step(agent_claude.STEP)
    return min(float(caps.per_step), float(getattr(settings, "claude_budget_usd_per_run", caps.per_step)))


def stop_reason(exc: BaseException, step_worst: float | None = None) -> tuple[str, str]:
    """(code, reason) of a stop, in plain words with numbers; ids and codes only, never document text."""
    code = str(getattr(exc, "code", None) or getattr(type(exc), "count_key", None) or type(exc).__name__)
    if isinstance(exc, StepCapStop):
        return code, exc.reason
    if code in APPROVAL_CODES:
        return code, "the Claude approval list refused a declared document: an owner question (nothing was sent)"
    if code == "usd_cap_reached" and step_worst is not None:
        try:  # read-only: reproduce which app cap refused, with its numbers
            claude_spend.ensure_affordable(agent_claude.STEP, step_worst)
        except claude_spend.StopRun as again:
            return code, str(again)
        return code, "an app USD cap refused the call; it fits now (calls in flight were holding it)"
    return code, code


# ---------------------------------------------------------------- the silent paper

SILENT_CODES = ("sheet_silent", "absent")
SILENT_WHY = "the paper is silent on this; for this paper kind silence is a question, never a finding"


def silence_guard(line: Mapping, paper_kind: str | None) -> dict:
    """Owner, 11 Nov 2026 (16.3 point 4): when the AI's "not met" rests only on the paper being silent and the paper kind is
    not a datasheet, the line is a Query, never "AI thinks: not met". The one exit calls this; with the AI reviewer on for
    datasheets only (`agent_review_gate.AGENT_REVIEW_KINDS`) it cannot fire, and stays wired so widening the kinds is safe.
    Only makes a line less confident."""
    out = dict(line)
    if (str(paper_kind or "").strip().lower() != "datasheet" and out.get("ai_verdict") == verdict.FAIL
            and out.get("reason_code_ai") in SILENT_CODES and not out.get("error")):
        out.update(verdict=verdict.QUERY, decided_by=verdict.BY_ENGINEER, why=SILENT_WHY, silent_query=True)
        return wording.apply({**out, "ai_verdict_was": out.get("ai_verdict"), "ai_verdict": None})
    return wording.apply(out)


# ---------------------------------------------------------------- the runner


class Runner:
    def __init__(self, *, paper: str, items: list[dict], pages: Any, clauses: ClauseCache, model: str,
                 send: Callable | None = None, env: dict | None = None, concurrency: int = CONCURRENCY,
                 max_batch: int = MAX_BATCH, retry_base: float = RETRY_BASE_SECONDS,
                 done_lines: Mapping[str, dict] | None = None, paper_kind: str | None = None,
                 equipment_type: str | None = None, absence_check: bool = False,
                 context_check: bool = True, std_pages: Callable[[str, int], str | None] | None = None,
                 sink: Callable[[dict, dict], None] | None = None, trace_path: Path | None = None,
                 tier_lookup: Callable[[Mapping], str | None] | None = None) -> None:
        self.paper, self.pages, self.clauses = paper, pages, clauses
        self.model, self.send, self.env = model, send, env
        self.concurrency, self.max_batch, self.retry_base = max(1, int(concurrency)), max_batch, retry_base
        self.context_check, self.std_pages = bool(context_check), std_pages
        self.sink, self.trace_path = sink, trace_path
        self.meter = agent_claude.SpendMeter(app_cap())  # a backstop: the step gate and `metered` are the binding ones
        self.opinion = agent_claude.ClaudeProvider(model=model, send=send, env=env, meter=self.meter)
        self.total_pages = pages.count(paper)
        self.tier_lookup = tier_lookup  # the CURRENT tier of a rule item, from the label table
        self.items = plan_pages(items, pages, paper, clauses)
        self.items_by_id = {str(i.get("item_id")): i for i in self.items}
        self.stopped = ""
        self.stop_text = ""
        self.gate: AppStepGate | None = None
        self.last_app_worst: float | None = None
        self.run_usd = 0.0
        self.paper_kind, self.equipment_type = paper_kind, equipment_type
        self.lines: dict[str, dict] = {k: self._kept(v) for k, v in dict(done_lines or {}).items()}
        self.absence_check = bool(absence_check)
        self.carried = absence.carried_roles(paper_kind, equipment_type) if absence_check else None
        self._ctx: dict[str, dict] = {}
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._warm = threading.Lock()
        self._warmed = False
        self.lead_models: set[str] = set()
        self.second_models: set[str] = set()
        self.calls = {"lead": 0, "second": 0, "context": 0, "retries": 0}
        self.counts: dict[str, int] = {}

    # ---- resume: a kept line of a rule that is not AI approved is capped again
    def _kept(self, line: dict) -> dict:
        """A stored line comes back through the SAME exit as a new one: its rule's CURRENT tier decides, so nothing a stored
        line earned under an old tier survives (a rule no longer approved is capped again)."""
        return {**self.exit_line(line), "resumed": True}

    def exit_line(self, line: Mapping) -> dict:
        """THE one exit every line goes through before it is stored or written (table row, xlsx, API): the tier from the
        CURRENT label table (`final_cap`), then the silent-paper rule. Only ever makes a line less confident."""
        out = wording.final_cap(line, self.items_by_id.get(str(line.get("item_id"))), self.tier_lookup)
        return silence_guard(out, self.paper_kind)

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
                    fh.write(json.dumps({"type": "item", "item_id": line["item_id"], **trace}, ensure_ascii=False,
                                        default=str) + "\n")
        log.info("agent review item decided: class=%s", line.get("verdict_class"))

    def _trace_of(self, line: Mapping) -> dict:
        """Per item: the question asked, every page opened, each model answer, the second opinion and every gate decision
        with its reason. Local only (it holds the prompt's text)."""
        ctx = self._ctx.pop(str(line["item_id"]), {})
        return {"prompt_version": PROMPT_VERSION, **ctx,
                "gate": {"verdict": line.get("verdict"), "decided_by": line.get("decided_by"), "why": line.get("why"),
                         "reason_code": line.get("reason_code"), "quotes_checked": line.get("quotes_checked"),
                         "compare": line.get("compare"), "second_opinion": line.get("second_opinion"),
                         "context_check": line.get("context_check"), "absence_check": line.get("absence_check"),
                         "conditional_hold": line.get("conditional_hold"), "table_note_hold": line.get("table_note_hold"),
                         "unapproved_cap": line.get("unapproved_cap"), "verdict_label": line.get("verdict_label"),
                         "verdict_class": line.get("verdict_class")}}

    def trace_record(self, rec: Mapping) -> None:
        if self.trace_path is not None:
            with self._lock, self.trace_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    # ---- one metered call, with the step gate and rate-limit backoff
    def call(self, model: str, parts: dict, max_tokens: int) -> tuple[dict, float]:
        app = app_worst_usd(model, parts, max_tokens)
        self.last_app_worst = app
        for attempt in range(MAX_RETRIES + 1):
            if self._stop.is_set():
                raise agent_claude.AgentBudgetStop(self.stopped or "run_stopped")
            self._admit(app)
            try:
                answer, usd = agent_claude._call(model, parts, max_tokens, self.send, self.env, None)
            except agent_claude.AgentBudgetStop:
                self._release(app, 0.0)  # refused before sending: nothing billed
                raise
            except agent_claude.AgentTransportError:
                self._release(app, app)  # may have been billed: charged at the worst case (the safe side)
                self._add_usd(app)
                if attempt < MAX_RETRIES:
                    self.calls["retries"] += 1
                    time.sleep(self.retry_base * (2 ** attempt))
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
        finding = {"item": item_id, "color": verdict.COLOUR_OF[ai_verdict],
                   "doc_quote": answer.get("paper_quote"), "clause_quote": answer.get("clause_quote")}
        runner = self
        kept: dict = {}

        class _Opinion:
            def second_opinion(self, f, evidence):
                prompt_chars = len(json.dumps(evidence, ensure_ascii=False)) + 1200
                worst = claude_spend.worst_case_usd(agent_claude.SECOND_MODEL, prompt_chars, SECOND_MAX_TOKENS)
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

    # ---- per item
    def decide(self, item: dict, answer: Mapping | None, pages: Mapping[int, str], lead_model: str | None,
               error: str | None, box: Any, usd_share: float) -> dict:
        """One line, by code."""
        iid = str(item.get("item_id"))
        ref = item.get("clause_quote_ref")
        held = held_texts(item, self.clauses)
        answer = answer or {}
        # a rule whose tier is not Owner / Engineer / AI approved never buys a call beyond the lead's own answer
        unapproved = not verdict.calls_allowed(item, self.tier_lookup)

        def needs_second(*a, **k):
            return (not unapproved) and verdict.needs_second_opinion(*a, **k)

        if answer == {} and not error:
            error = "no_answer_for_item"
        clause_text, held_kind = (held[0]["text"], held[0]["kind"]) if held else (None, None)
        for h in held:
            if verdict.check_clause_quote(answer.get("clause_quote"), h["text"])[0]:
                clause_text, held_kind = h["text"], h["kind"]
                break
        requirement = next((h["text"] for h in held if h["kind"] == "requirement"), None)
        checks = verdict.check_quotes(answer, pages, clause_text, requirement if held_kind == "requirement" else None)
        ai = verdict.ai_verdict_word(answer.get("verdict"))
        reason_code, searched = reason_of(answer, ai, error, pages)
        if reason_code in TIGHTENING:
            ai = verdict.QUERY  # code tightens, never loosens: an unsupported Fail or Pass is asked as a query
        absent = verdict.says_absent(answer)
        second, compare = None, None
        if verdict.is_number_item(item):
            compare = verdict.compare_figures(box, answer) if not error and checks.both else None
            decision = verdict.number_verdict(compare, checks, answer, error=error)
        else:
            if needs_second(ai, checks, error, absent) and not self._stop.is_set():
                try:
                    second = self.second_opinion(iid, ai, answer)
                except FATAL as exc:
                    self._halt(exc)
                    second = None
            decision = verdict.textual_verdict(ai, checks, second, lead_model, error=error, absent=absent)
        proof, absence_second, comment = None, None, answer.get("comment")
        if reason_code == "absent" and not error:
            decision = {**decision, "verdict": verdict.QUERY, "decided_by": verdict.BY_ENGINEER,
                        "why": "not shown on the sheet; code cannot prove an absence"}
            if (self.absence_check and not unapproved
                    and verdict.ai_verdict_word(answer.get("verdict")) == verdict.FAIL):
                decision, proof, absence_second = self.absence_decision(item, answer, checks, requirement, lead_model)
                if decision["verdict"] == verdict.FAIL:
                    comment = absence.comment(proof.field_words, item.get("standard"), item.get("clause"))
        # F1 (conditional rule), F3 (table row or note), then THE cap of a rule that is not approved
        decision = verdict.apply_holds(decision, item, clause_quote=answer.get("clause_quote"), requirement=requirement,
                                       clause_sources=[self.clauses.source(h["ref"]) for h in held])
        decision, ctx_info = self.context_check_fail(iid, item, [answer.get("paper_quote")], pages,
                                                     requirement or answer.get("clause_quote"), decision, lead_model)
        label = str(answer.get("field_label") or "").strip()
        label_ok = bool(label) and any(_fold(label) in _fold(t) for t in pages.values() if t)
        deferred_page = None
        if decision["verdict"] == verdict.PASS:  # deferral guard: a value marked 'By Contractor' is not confirmed
            guard = self.pass_guard(item, label if label_ok else "")
            if guard is not None:
                decision, reason_code, deferred_page = guard
        self._ctx.setdefault(iid, {}).update(second_opinion_answer=second, absence_second_answer=absence_second)
        return {
            "item_id": iid,
            "source": item.get("source"),
            "standard": item.get("standard"),
            "clause": item.get("clause"),
            "clause_page": self.clauses.page(ref) or item.get("clause_page"),
            "rule_kind": item.get("rule_kind"),
            "field_roles": item.get("field_roles") or [],
            "field": label if label_ok else None,
            "page_hint": _hints(item) if item.get("page_hint_source") in (None, "items") else [],
            "page_hint_source": item.get("page_hint_source"),
            "verdict": decision["verdict"],
            "decided_by": decision["decided_by"],
            "why": decision.get("why"),
            "model": lead_model if lead_model and lead_model != "unknown" else None,
            "second_opinion": None if second is None else {k: second.get(k) for k in ("agree", "model", "reason")
                                                            if k != "reason" or second.get("reason")},
            "ai_verdict": verdict.ai_verdict_word(answer.get("verdict")),
            "reason_code": reason_code,
            "reason_code_ai": str(answer.get("reason_code") or "") or None,
            "deferred_page": deferred_page,
            "pages_searched": searched,
            "requirement": requirement,
            "field_label_ai": label or None,
            "paper_figure": answer.get("paper_figure") or None,
            "clause_figure": answer.get("clause_figure") or None,
            "clause_quote_from": held_kind,
            "reasoning": crs_lines.two_sentences(answer.get("reasoning")),
            "comment": words(comment, crs_lines.MAX_COMMENT_WORDS),
            "paper_quote": answer.get("paper_quote") or None,
            "paper_page": verdict._page_no(answer.get("paper_page")),
            "clause_quote": answer.get("clause_quote") or None,
            "quotes_checked": checks.to_json(),
            "compare": compare,
            "error": error,
            "absence_check": None if proof is None else proof.to_json(),
            "absence_code": decision.get("absence_code"),
            "rule_tier": item.get("rule_tier"),
            "rule_unapproved_why": item.get("rule_unapproved_why"),
            "rule_label": item.get("rule_label"),
            "unapproved_cap": bool(decision.get("unapproved_cap")),
            "conditional_hold": bool(decision.get("conditional")),
            "table_note_hold": decision.get("table_note"),
            "context_hold": bool(decision.get("context_hold")),
            "context_check": None, "context_hash": None, "context_limits": None, "context_condition_met": None,
            **ctx_info,
            "usd": round(usd_share + float((second or {}).get("usd") or 0.0)
                         + float((absence_second or {}).get("usd") or 0.0), 6),
        }

    # ---- the absence proof (off by default)
    def absence_decision(self, item: Mapping, answer: Mapping, checks: Any, requirement: str | None,
                         lead_model: str | None) -> tuple[dict, Any, dict | None]:
        """(decision, proof, second). Fail only when code proves the absence, the clause quote is verified and strong, and a
        DIFFERENT model asked on the absence claim agrees. Else Query with the why."""
        texts = {n: self.pages.page(self.paper, n) or "" for n in range(1, self.total_pages + 1)}
        sentence = requirement or (answer.get("clause_quote") if checks.clause else None)
        proof = absence.prove(item, sentence, texts, self.total_pages, getattr(self.pages, "ledger_rows", None),
                              list(getattr(self.pages, "facts", []) or []), self.carried,
                              deferred=lambda w: deferred_mark(w, self.pages, self.paper, self.total_pages))

        def query(code: str) -> tuple[dict, Any, dict | None]:
            why = proof.why if code == proof.code else absence.ABSENCE_WHY[code]
            return {"verdict": verdict.QUERY, "decided_by": verdict.BY_ENGINEER, "why": why,
                    "absence_code": code}, proof, second

        second = None
        if not proof.proven:
            return query(str(proof.code))
        if not (checks.clause and checks.clause_strong):
            return query("absence_clause_weak")
        if self._stop.is_set():
            return query("absence_no_second_opinion")
        try:
            second = self.absence_second(item, answer, proof)
        except FATAL as exc:
            self._halt(exc)
            return query("absence_no_second_opinion")
        if second.get("model"):
            self.second_models.add(second["model"])
        if second.get("agree") is not True:
            return query("absence_second_disagreed" if second.get("agree") is False else "absence_no_second_opinion")
        if not agent_run_second.models_differ([lead_model or ""], second.get("model")):
            return query("absence_second_same_model")
        return {"verdict": verdict.FAIL, "decided_by": verdict.BY_ABSENCE, "why": None}, proof, second

    def absence_parts(self, item: Mapping, answer: Mapping, proof: Any) -> dict:
        content: list[dict] = [{"type": "text", "text": f'<paper document="{self.paper}" page="{n}">\n'
                                f'{self.pages.page(self.paper, n) or ""}\n</paper>'}
                               for n in range(1, self.total_pages + 1)]
        if content:
            content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
        claim = {"field": list(proof.field_words), "standard": item.get("standard"), "clause": item.get("clause"),
                 "requirement_quote": answer.get("clause_quote"),
                 "claim": "The paper does not state this field on any page.",
                 "question": 'Is the claim true? Reply with ONE JSON object: {"agree": true or false}'}
        content.append({"type": "text", "text": json.dumps(claim, ensure_ascii=False)})
        return {"system": [{"type": "text", "text": ABSENCE_SECOND_SYSTEM, "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": content}]}

    def absence_second(self, item: Mapping, answer: Mapping, proof: Any) -> dict:
        """One call to the SECOND model through the lane. The first call of a run goes alone so the page prefix is written
        to the cache once; the rest read it."""
        parts = self.absence_parts(item, answer, proof)

        def ask() -> dict:
            self.calls["second"] += 1
            raw, usd = self.call(agent_claude.SECOND_MODEL, parts, ABSENCE_SECOND_MAX_TOKENS)
            obj = agent_claude.parse_json_object(_text_of(raw)) or {}
            agree = obj.get("agree") if isinstance(obj, dict) else None
            return {"agree": agree if isinstance(agree, bool) else None, "model": agent_claude._answered_model(raw),
                    "usd": usd}

        try:
            if not self._warmed:
                with self._warm:
                    if not self._warmed:
                        try:
                            return ask()
                        finally:
                            self._warmed = True
            return ask()
        except FATAL:
            raise
        except agent_claude.AgentClaudeError:
            return {"agree": None, "model": None, "usd": 0.0}

    # ---- F4: the context check before a Fail is proven
    def context_check_fail(self, iid: str, item: Mapping, paper_quotes: list, pages: Mapping[int, str],
                           rule_text: str | None, decision: Mapping, lead_model: str | None) -> tuple[dict, dict]:
        """Before a Fail is proven, ONE call to the check model with the rule-book page. Returns (decision, line keys). Only a
        Fail is checked; the result can only HOLD it (never make it more confident). A Fail is proven only if THIS run made
        the check and it said proven; every other path (no call made) holds it: "context check not completed"."""
        if decision.get("verdict") != verdict.FAIL or not self.context_check:
            return dict(decision), {}
        fp = ctxc.fingerprint(rule_text, paper_quotes)

        def done(outcome: dict) -> tuple[dict, dict]:
            info = {"context_check": outcome["outcome"], "context_limits": outcome.get("limits"),
                    "context_condition_met": outcome.get("condition_met"), "context_hash": fp}
            if outcome["outcome"] == ctxc.PROVEN:
                return dict(decision), info
            return ctxc.held_decision(decision, outcome.get("why") or ctxc.WHY_NOT_DONE), info

        def failed() -> tuple[dict, dict]:
            return done({"outcome": ctxc.NOT_COMPLETED, "limits": None, "condition_met": None, "why": ctxc.WHY_NOT_DONE})

        doc = item.get("standard_document_id")
        page = self.clauses.page(item.get("rule_quote_ref")) or item.get("clause_page")
        first = self.std_pages(doc, page) if (self.std_pages and doc and isinstance(page, int)) else None
        if not first or not rule_text or not ctxc.quote_on_page(rule_text, first):  # no page, or the quote is not on its page
            return failed()
        wanted = ctxc.neighbour_pages(page, first, rule_text)
        rule_pages = {n: (first if n == page else self.std_pages(doc, n)) for n in wanted}
        rule_pages = {n: t for n, t in rule_pages.items() if t}
        parts = ctxc.build_parts(rule_text, item.get("clause"), rule_pages, [str(q) for q in paper_quotes if q], pages)
        if self._stop.is_set():
            return failed()
        trace: dict = {"rule_pages": sorted(rule_pages), "paper_pages": sorted(pages)}
        try:
            with self._lock:
                self.calls["context"] += 1
            raw, usd = self.call(FINAL_MODEL, parts, FINAL_MAX_TOKENS)
        except FATAL as exc:
            self._halt(exc)
            trace["error"] = "run stopped"
            self._ctx.setdefault(iid, {})["context_exchange"] = trace
            return failed()
        except agent_claude.AgentClaudeError as exc:
            trace["error"] = exc.code
            self._ctx.setdefault(iid, {})["context_exchange"] = trace
            return failed()
        model = agent_claude._answered_model(raw)
        obj = agent_claude.parse_json_object(_text_of(raw))
        trace.update(answer=obj, model=model, usd=usd)
        self._ctx.setdefault(iid, {})["context_exchange"] = trace
        if not agent_run_second.models_differ([lead_model or ""], model):  # a model of the lead's family cannot check it
            trace["error"] = "same model family as the lead, or unknown"
            return failed()
        outcome = ctxc.evaluate(obj, list(rule_pages.values()), [t for t in pages.values() if t])
        trace["code_decision"] = outcome
        return done(outcome)

    def _halt(self, exc: BaseException) -> None:
        with self._lock:
            if self._stop.is_set():
                return
            self.stopped, self.stop_text = stop_reason(exc, self.last_app_worst)
            self._stop.set()
        log.warning("agent review stopped: code=%s", self.stopped)

    def _box(self) -> Any:
        ctx = agent_tools.ToolContext(allowed_document_ids=frozenset({self.paper}), document_id=self.paper)
        return agent_tools.ToolBox(ctx, page_reader=lambda d, n: self.pages.page(d, n),
                                   searcher=lambda _q, _a: {"hits": []}, standard_pages=lambda _d: [])

    def run_batch(self, batch: list[dict], allow_split: bool = True) -> None:
        """One lead call for the batch. An answer cut off at max_tokens (or unreadable) is asked again ONCE per half of the batch;
        items a readable answer left out are asked again once; an item still without an answer is a failed call ("not
        reviewed"), never a verdict."""
        ids = [str(i.get("item_id")) for i in batch]
        numbers = pages_for(batch, self.total_pages)
        pages = {n: t for n in numbers if (t := self.pages.page(self.paper, n))}
        box = self._box()
        if self._stop.is_set():
            for it in batch:
                self.emit(self.decide(it, None, pages, None, f"not run: {self.stopped}", box, 0.0))
            return
        clauses: dict[str, dict] = {}
        held_of: dict[str, list[dict]] = {}
        for it in batch:
            held_of[str(it.get("item_id"))] = held = held_texts(it, self.clauses)
            for h in held:
                clauses.setdefault(h["ref"], {**h, "standard": it.get("standard"), "clause": it.get("clause")})
        parts = build_parts(self.paper, pages, clauses, batch, held_of)
        max_tokens = min(MAX_TOKENS_CAP, TOKENS_BASE + TOKENS_PER_ITEM * len(batch))
        answer, usd, error, model = None, 0.0, None, None
        try:
            with self._lock:
                self.calls["lead"] += 1
            raw, usd = self.call(self.model, parts, max_tokens)
            model = agent_claude._answered_model(raw)
            if model != "unknown":
                self.lead_models.add(model)
            answer = parse_answers(raw)
            if answer is None and not (allow_split and len(batch) > 1):  # one retry; a bigger batch is split instead
                with self._lock:
                    self.calls["retries"] += 1
                raw, usd2 = self.call(self.model, parts, max_tokens)
                usd += usd2
                answer = parse_answers(raw)
            if answer is None:
                error = "unparseable_reply"
        except FATAL as exc:
            self._halt(exc)
            error = f"not run: {self.stopped}"
        except agent_claude.AgentClaudeError as exc:
            error = exc.code
        except Exception as exc:  # noqa: BLE001  a failed call is a Query, never a verdict
            error = "error_" + type(exc).__name__
        if answer is None and allow_split and len(batch) > 1 and error in SPLITTABLE:
            self.trace_record({"type": "split", "item_ids": ids, "after": error})
            mid = (len(batch) + 1) // 2
            self.run_batch(batch[:mid], False)
            self.run_batch(batch[mid:], False)
            return
        share = usd / max(1, len(batch))
        self.trace_record({"type": "batch", "item_ids": ids, "prompt_version": PROMPT_VERSION, "pages_opened": numbers,
                           "pages_read": sorted(pages), "model_answered": model, "usd": usd, "error": error})
        for it in batch:
            iid = str(it.get("item_id"))
            self._ctx[iid] = {"batch_item_ids": ids, "question": _question(it, held_of.get(iid)),
                              "pages_opened": numbers, "pages_read": sorted(pages), "lead_model": model,
                              "lead_error": error, "lead_answer": (answer or {}).get(iid)}
        missing = []
        for it in batch:
            got = (answer or {}).get(str(it.get("item_id")))
            if got is None and answer is not None and allow_split:
                missing.append(it)  # a readable answer that left this item out: asked once more below
                continue
            self.emit(self.decide(it, got, pages, model, error if answer is None else None, box, share))
        if missing:
            self.run_batch(missing, False)

    def pass_guard(self, item: Mapping, label: str) -> tuple[dict, str, int | None] | None:
        """(decision, reason code, deferred page) when a Pass must become a Query, else None. Field words: the item's roles,
        else the field label found on the page. Unknown field words: Query on the safe side; the field marked deferred on any
        page ('By Contractor', 'TBA', ...): Query."""
        from .agent_bind import content_words

        field = " ".join(str(r).replace("_", " ") for r in item.get("field_roles") or []) or label
        if not content_words(field):
            return ({"verdict": verdict.QUERY, "decided_by": verdict.BY_ENGINEER,
                     "why": "field words unknown: code cannot check the sheet for a deferral mark"},
                    "field_unknown_cannot_check_deferral", None)
        page = deferred_mark(field, self.pages, self.paper, self.total_pages)
        if page is None:
            return None
        return ({"verdict": verdict.QUERY, "decided_by": verdict.BY_ENGINEER,
                 "why": f"the sheet marks this value as not final on page {page}"}, "value_deferred", page)

    def todo(self) -> list[dict]:
        """The items with no stored line, or whose stored line is a failed call: only these are asked."""
        return [i for i in self.items if str(i.get("item_id")) not in self.lines
                or self.lines[str(i.get("item_id"))].get("error")]

    def run(self) -> dict:
        """Call inside `claude_spend.for_run(...)` and `claude_approved.carrying(...)`: the step gate starts from what this
        review run has already spent (a resumed run keeps counting)."""
        self.gate = AppStepGate(app_cap(), claude_spend.step_spent(agent_claude.STEP))
        todo = self.todo()
        batches, source = make_batches(todo, self.max_batch)
        self.trace_record({"type": "prompt", "prompt_version": PROMPT_VERSION, "system": SYSTEM,
                           "answer_shape": ANSWER_SHAPE, "second_system": agent_claude.SECOND_SYSTEM,
                           "absence_second_system": ABSENCE_SECOND_SYSTEM})
        log.info("agent review run: %d items to ask in %d batches, %d kept from before, step cap USD %.2f, spent USD %.4f",
                 len(todo), len(batches), len(self.items) - len(todo), self.gate.cap, self.gate.settled)
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futures = [pool.submit(contextvars.copy_context().run, self.run_batch, b) for b in batches]
            for f in futures:
                f.result()
        return {"batches": len(batches), "batch_source": source}


def counts_of(lines: Iterable[Mapping]) -> dict:
    """Counts per class of the stored lines, with the not-run lines counted apart. No text."""
    ls = [wording.apply(ln) for ln in lines]
    out = crs_lines.run_counts(ls)
    out["not_run"] = sum(1 for ln in ls if str(ln.get("error") or "").startswith("not run"))
    return out
