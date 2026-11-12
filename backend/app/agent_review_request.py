"""The AI reviewer's request side: prompts, batches, pages, answers, the step cap's admission and the silent-paper rule.

Split from `agent_review_run` (the runner) so no file passes the size bar. Nothing here talks to the network except through
`agent_claude._call`, called by the runner; pure helpers and constants otherwise.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Mapping
from typing import Any

from . import agent_claude, claude_spend
from . import agent_review_verdict as verdict
from .reader_api import _fold

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
#: Starting output limit of a first-reader batch: TOKENS_BASE + TOKENS_PER_ITEM x items, at most MAX_TOKENS_CAP. Measured on the
#: four trial papers (12 Nov, two paid rounds): complete answers used up to 6,041 tokens for 8 items and 3,292 for 4 (about 750 an
#: item with the reader's own thinking), and the old limit (600 + 700 x items: 6,200 and 3,400) cut off 4 batches, each then split
#: and asked again with different companions, so a cut-off changed the next batch's request. 1,000 + 1,100 x items is 9,800 for 8
#: items and 5,400 for 4: about 60% above the largest answer seen. A limit is only a ceiling (it is billed by use); the worst-case
#: reservation is higher by the difference (see `app_worst_usd`). A cut-off still retries as before, up to RETRY_MAX_TOKENS.
TOKENS_PER_ITEM = 1100
TOKENS_BASE = 1000
MAX_TOKENS_CAP = 10000
MAX_RETRIES = 3
#: a lead answer that stopped at max_tokens, or could not be read: the batch is split in half and asked once more per half
SPLITTABLE = ("stop_max_tokens", "unparseable_reply")
#: an answer cut off at its limit, for an item that cannot be split further (a single item, or a half already split), is
#: asked ONCE more with RETRY_TOKEN_FACTOR times the limit, never above RETRY_MAX_TOKENS. Measured (12 Nov trial, 72 lines):
#: 2 cut-offs, a batch of 8 at 6,200 and a half of 4 at 3,400 (about 850+ tokens an item); complete answers used 1,000 to
#: 5,500 tokens. Twice the limit clears all of them; the ceiling keeps the worst case of one call near USD 0.12.
RETRY_TOKEN_FACTOR = 2
RETRY_MAX_TOKENS = 12000
#: the line's error when the retry was cut off too (shown as "no answer from the AI: <this>")
CUT_OFF_TWICE = "answer cut off twice (the second try had twice the limit)"
#: the line's error when the larger-limit retry came back whole but unreadable (no third call is made)
SECOND_UNREADABLE = "the second answer could not be read (after a cut-off)"
RETRY_BASE_SECONDS = 4.0
CONCURRENCY = 3
SECOND_MAX_TOKENS = agent_claude.SECOND_MAX_TOKENS
FATAL = (agent_claude.AgentBudgetStop, agent_claude.AgentGateClosed)
#: claude_approved refusals: an owner question, never bypassed.
APPROVAL_CODES = (
    "undeclared",
    "not_approved",
    "unknown_document",
    "undeclared_documents",
    "blocked",
)

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
REASON_CODES = (
    "met",
    "not_met",
    "absent",
    "not_applicable",
    "needs_drawing_or_calc",
    "sheet_silent",
    "unclear_clause",
    "other",
)
#: Codes that make a line Query whatever the AI said (code cannot prove an absence).
TIGHTENING = ("absent", "absent_pages_not_named", "verdict_and_reason_differ")
PROMPT_VERSION = (
    "app-lead-"
    + __import__("hashlib").sha256((SYSTEM + ANSWER_SHAPE).encode()).hexdigest()[:10]
)
REASON_FITS = {
    "Pass": ("met",),
    "Fail": ("not_met", "absent"),
    "Query": (
        "not_applicable",
        "needs_drawing_or_calc",
        "sheet_silent",
        "unclear_clause",
        "other",
    ),
}


# ---------------------------------------------------------------- inputs


def held_texts(item: Mapping, cache: ClauseCache) -> list[dict]:
    """The held standard texts sent for an item, in order: the REQUIREMENT (the rule's own quote) first, then the clause text
    as context, only when there is no requirement text or when it holds the requirement. General: a text test, no layout."""
    out: list[dict] = []
    rule_ref, clause_ref = item.get("rule_quote_ref"), item.get("clause_quote_ref")
    rule_text = cache.text(rule_ref)
    if rule_text:
        out.append(
            {
                "kind": "requirement",
                "ref": rule_ref,
                "text": rule_text,
                "page": cache.page(rule_ref),
            }
        )
    clause_text = cache.text(clause_ref)
    if (
        clause_text
        and clause_ref != rule_ref
        and (not rule_text or _fold(rule_text)[:60] in _fold(clause_text))
    ):
        out.append(
            {
                "kind": "clause",
                "ref": clause_ref,
                "text": clause_text,
                "page": cache.page(clause_ref) or item.get("clause_page"),
            }
        )
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
        rows = conn.execute(
            "SELECT page_no, text, needs_ocr FROM pages WHERE document_id = ?", (paper,)
        ).fetchall()
        self.pages = {int(r["page_no"]): r["text"] or "" for r in rows}
        needs_ocr = {int(r["page_no"]): bool(r["needs_ocr"]) for r in rows}
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.ledger_rows: dict[int, dict] | None = {}
        if "page_ledger" in tables:
            for r in conn.execute(
                "SELECT page_no, native_status, ocr_status FROM page_ledger WHERE document_id = ?",
                (paper,),
            ):
                self.ledger_rows[int(r["page_no"])] = {
                    "native_status": r["native_status"],
                    "ocr_status": r["ocr_status"],
                    "needs_ocr": needs_ocr.get(int(r["page_no"]), True),
                }
        self.facts = (
            [
                dict(r)
                for r in conn.execute(
                    "SELECT field_name, field_label, page FROM submittal_facts WHERE submittal_document_id = ?",
                    (paper,),
                )
            ]
            if "submittal_facts" in tables
            else []
        )
        self.paper = paper

    def page(self, doc: str, n: int) -> str | None:
        return self.pages.get(n) if doc == self.paper else None

    def count(self, doc: str) -> int:
        return max(self.pages, default=0) if doc == self.paper else 0


class StdPages:
    """Stored pages of the rule books, read on demand on the calling thread's own connection (`__call__(doc, page)`)."""

    def __call__(self, doc: str, page: int) -> str | None:
        from .db import connect

        row = (
            connect()
            .execute(
                "SELECT text FROM pages WHERE document_id = ? AND page_no = ?",
                (doc, int(page)),
            )
            .fetchone()
        )
        return row["text"] if row and (row["text"] or "").strip() else None


def _hints(item: Mapping) -> list[int]:
    return [
        p
        for p in item.get("page_hint") or []
        if isinstance(p, int) and not isinstance(p, bool) and p >= 1
    ]


def _bits(item: Mapping) -> bytes:
    """The item's place in the split order: the hash of its clause (so items of one clause stay together), then the hash of its own
    id (so a clause with many items can still be split). A property of the item only; it never depends on the other items."""
    clause = hashlib.sha256(str(item.get("clause_quote_ref") or "").encode()).digest()
    return clause + hashlib.sha256(str(item.get("item_id")).encode()).digest()


def _bit(key: bytes, depth: int) -> int:
    return (key[depth // 8] >> (7 - depth % 8)) & 1


def _split(members: list[dict], max_items: int, depth: int = 0) -> list[list[dict]]:
    """A group that is too big is split on the next bit of its members' keys, again and again, until every part holds at most
    `max_items` (point E, steady results). Which part an item lands in depends on its own key and on how many items share its
    key prefix, nothing else: adding one item changes the one part it lands in (and splits that part when it grows past the
    limit); the other parts keep their members and their order."""
    if len(members) <= max_items:
        return [members]
    if depth >= 8 * 64:  # identical keys (a repeated id): cut by position, no way to tell them apart
        return [members[i : i + max_items] for i in range(0, len(members), max_items)]
    zero = [m for m in members if _bit(_bits(m), depth) == 0]
    one = [m for m in members if _bit(_bits(m), depth) == 1]
    if not zero or not one:
        return _split(members, max_items, depth + 1)
    return _split(zero, max_items, depth + 1) + _split(one, max_items, depth + 1)


def stable_batches(items: list[dict], max_items: int = MAX_BATCH) -> list[list[dict]]:
    """Batches that move one at a time. The rule: items with the same page hint form a group; a group of at most `max_items` is one
    batch; a bigger group is split on the hash of the items' clause and id (`_split`); inside a batch the items are ordered by
    (clause_quote_ref, item_id), which keeps items of one clause side by side. The old rule cut every `max_items` items from the
    start of a group, so one added rule shifted every later batch and changed all their requests. Now: adding one item changes the
    one batch it joins (a batch that grows past `max_items` is split in two); removing one changes the one batch it was in, or
    joins that batch with its neighbour when together they fit. Measured on 400 random additions to 30, 53 and 86 items: one
    batch changed every time. Groups come out in the item builder's order (no page hint last). No item is dropped or repeated."""
    groups: dict[tuple[int, ...], list[dict]] = {}
    for it in items:
        groups.setdefault(tuple(sorted(set(it.get("page_hint") or []))), []).append(it)
    out: list[list[dict]] = []
    for pages in sorted(groups, key=lambda p: (not p, p)):
        for part in _split(groups[pages], max(1, int(max_items))):
            out.append(
                sorted(
                    part,
                    key=lambda i: (str(i.get("clause_quote_ref") or ""), str(i["item_id"])),
                )
            )
    return [b for b in out if b]


def make_batches(
    items: list[dict], max_batch: int = MAX_BATCH
) -> tuple[list[list[dict]], str]:
    """The stable batches (`stable_batches`), each at most `max_batch` items."""
    return stable_batches(items, max_batch), "items.stable_batches"


def page_cap(total_pages: int) -> int:
    """A short paper (a datasheet) is sent whole to every batch; a longer one at most MAX_PAGES_PER_CALL pages."""
    return total_pages if 0 < total_pages <= SMALL_PAPER_PAGES else MAX_PAGES_PER_CALL


def plan_pages(
    items: list[dict], pages: Any, paper: str, clauses: ClauseCache | None = None
) -> list[dict]:
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
            it["page_hint"], it["page_hint_source"] = (
                list(range(1, total + 1)),
                "short paper: all pages",
            )
        else:
            roles = " ".join(
                str(r).replace("_", " ") for r in it.get("field_roles") or []
            )
            clause = (clauses.text(it.get("clause_quote_ref")) if clauses else "") or ""
            want = content_words(f"{it.get('question') or ''} {roles} {clause[:600]}")
            scored = sorted(
                ((len(want & w), -n) for n, w in texts.items() if want & w),
                reverse=True,
            )
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
    keys = (
        "item_id",
        "question",
        "field_roles",
        "standard",
        "clause",
        "rule_kind",
        "comparator",
        "value",
        "unit",
        "page_hint",
    )
    out = {k: item.get(k) for k in keys if item.get(k) not in (None, "", [])}
    for h in held or []:
        out[f"{h['kind']}_ref"] = h[
            "ref"
        ]  # which block below is this item's requirement / clause
    return out


def build_parts(
    paper: str,
    pages: Mapping[int, str],
    clauses: Mapping[str, dict],
    batch: list[dict],
    held_of: Mapping[str, list[dict]] | None = None,
) -> dict:
    """Documents first (pages, then the held texts), the items last. The documents are cache-marked."""
    content: list[dict] = []
    for n in sorted(pages):
        content.append(
            {
                "type": "text",
                "text": f'<paper document="{paper}" page="{n}">\n{pages[n]}\n</paper>',
            }
        )
    if content:  # breakpoint 1: the pages (the same for every batch of a short paper, so later batches read the cache)
        content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
    n_pages = len(content)
    for ref, c in clauses.items():
        tag = c.get("kind") or "clause"
        head = f'<{tag} ref="{ref}" standard="{c.get("standard") or ""}" clause="{c.get("clause") or ""}"'
        content.append(
            {
                "type": "text",
                "text": f'{head} page="{c.get("page") or ""}">\n{c["text"]}\n</{tag}>',
            }
        )
    if len(content) > n_pages:  # breakpoint 2: the held texts
        content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
    held_of = held_of or {}
    questions = [_question(i, held_of.get(str(i.get("item_id")))) for i in batch]
    content.append(
        {
            "type": "text",
            "text": json.dumps({"items": questions}, ensure_ascii=False)
            + "\n\n"
            + ANSWER_SHAPE,
        }
    )
    return {
        "system": [
            {"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [{"role": "user", "content": content}],
    }


def _text_of(answer: Mapping) -> str:
    return "".join(
        str(b.get("text") or "")
        for b in answer.get("content") or []
        if isinstance(b, dict) and b.get("type") == "text"
    )


def parse_answers(answer: Mapping) -> dict[str, dict] | None:
    obj = agent_claude.parse_json_object(_text_of(answer))
    got = obj.get("answers") if isinstance(obj, dict) else None
    if not isinstance(got, list):
        return None
    return {
        str(a.get("item_id")): a
        for a in got
        if isinstance(a, dict) and a.get("item_id") not in (None, "")
    }


def reason_of(
    answer: Mapping, ai: str | None, error: str | None, pages: Mapping[int, str]
) -> tuple[str, list[int]]:
    """(reason code, pages searched). The AI's code from the closed list, else 'other'. Code adds: ai_call_failed;
    absent_pages_not_named (an 'absent' Fail must name searched pages, all of them pages it was sent);
    verdict_and_reason_differ (a code that does not fit the verdict). The last two turn the AI verdict into Query."""
    raw = answer.get("pages_searched")
    searched = (
        sorted({p for p in raw if isinstance(p, int) and not isinstance(p, bool)})
        if isinstance(raw, list)
        else []
    )
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
    chars = len(
        json.dumps(parts.get("messages") or [], ensure_ascii=False, default=str)
    ) + len(json.dumps(parts.get("system") or "", ensure_ascii=False, default=str))
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
                        f"{worst:.4f} by the app's estimate, cap USD {self.cap:.2f}"
                    )
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
    return min(
        float(caps.per_step),
        float(getattr(settings, "claude_budget_usd_per_run", caps.per_step)),
    )


def stop_reason(exc: BaseException, step_worst: float | None = None) -> tuple[str, str]:
    """(code, reason) of a stop, in plain words with numbers; ids and codes only, never document text."""
    code = str(
        getattr(exc, "code", None)
        or getattr(type(exc), "count_key", None)
        or type(exc).__name__
    )
    if isinstance(exc, StepCapStop):
        return code, exc.reason
    if code in APPROVAL_CODES:
        return (
            code,
            "the Claude approval list refused a declared document: an owner question (nothing was sent)",
        )
    if code == "usd_cap_reached" and step_worst is not None:
        try:  # read-only: reproduce which app cap refused, with its numbers
            claude_spend.ensure_affordable(agent_claude.STEP, step_worst)
        except claude_spend.StopRun as again:
            return code, str(again)
        return (
            code,
            "an app USD cap refused the call; it fits now (calls in flight were holding it)",
        )
    return code, code
