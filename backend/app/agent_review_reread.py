"""Owner order 13 (12 Nov 2026), C4: before a line is closed as "the paper does not state this", a SECOND, different model
reads the whole stored text of the page(s) where the field would stand and answers one narrow question.

WHAT COUNTS AS SILENT (`silent_cause`): a line the gate left a Query (or an AI opinion) only because the first reader found no
value: its reason code is absent / absent_pages_not_named / sheet_silent, or the met-guard says "not stated" (`NOT_STATED_WHY`)
or "only the field's name" (`NO_VALUE_WHY`). A line with an error, a resumed line, a rule that is not AI approved (it never
buys a call: `calls_allowed`), a drawing or calculation reason, an unclear clause and "not applicable" are NOT silent: no call.

THE STEP (behind `AGENT_REVIEW_REREAD_SILENT_ENABLED`, default OFF): a second-model page re-read (`once`: never sent
again after a transport failure), always to `agent_claude.SECOND_MODEL` and only when it is a different model family from
the lead. The call goes through the runner's own `call` (the step gate's reservation, `agent_claude._call`, the lane gate,
the approved-document check and the caps: nothing here opens a socket or keeps a ledger). Output limit `REREAD_MAX_TOKENS`.

PAGES (the bound is `REREAD_MAX_PAGES`, 3): the page the first reader cited when it is a page of this paper with text, else
the pages code already selected for the item (its page hint), the ones with most field words first. Whole stored page text.

THE ANSWER IS NOT TRUSTED, AND ONE READER NEVER DECIDES: its quote must stand word for word on one of those pages (code). If
it does, the FIRST (lead) model is asked the item once more on that page with the quote pointed out, and its answer goes
through the normal `decide` (gate, holds, caps and the normal second opinion). Per silent line at most: 1 re-read + 1 lead
re-ask (`once`: a transport failure is not re-sent; main's cut-off and unreadable-reply retry apply) + the normal second opinion + the context check of a Fail. If the lead again
finds nothing, or the second opinion disagrees, the line stays what it was and says one reader pointed to text on page N
and the other did not confirm it. Three other outcomes, three sets of words: the reader says no value (`no_value`: two
readers found none), its quote is not on the page (`quote_not_found`: not used), the call failed, was refused or unreadable
(`failed`: the line says nothing and is charged the call's reserved worst case).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from typing import Any

from . import agent_claude, agent_run_second
from . import agent_review_verdict as verdict
from .agent_review_request import (
    FATAL,
    _hints,
    _text_of,
    app_worst_usd,
    build_parts,
    held_texts,
    pages_for,
)
from .reader_api import _fold

REREAD_MAX_PAGES = 3
REREAD_MAX_TOKENS = 600
REREAD_MAX_REQUIREMENT_CHARS = 1500
SILENT_CODES = ("absent", "absent_pages_not_named", "sheet_silent")
REREAD_SYSTEM = (
    "PAGE RE-READ. You are a second, separate reader. Another reviewer reported that a supplier paper gives no "
    "value for one field. You are given the WHOLE stored text of the page or pages where that field would stand, tables "
    "and notes included, then the field and the requirement it is checked against. Answer one narrow question: is a "
    "value for this field on these pages? If it is, copy the words that hold it exactly, character for character, from "
    "the page text, with their page number. A field name alone, a blank cell, a mark such as 'TBA', 'by contractor' or "
    "'not applicable', or a value you have to infer is NOT a value: answer found false. Never guess."
)
REREAD_SHAPE = (
    'Reply with ONE JSON object and nothing else: {"found": true or false, "paper_page": 1, "paper_quote": "...", '
    '"paper_figure": "the exact words holding the number with its unit, from inside the quote, or empty", '
    '"clause_quote": "words copied from the requirement text, or empty", "clause_figure": "the exact words holding '
    'its number with its unit, or empty", "meets": true or false or null, "reasoning": "at most two plain sentences", '
    '"comment": "one sentence for the contractor, empty when it meets"}. meets is null when you cannot tell.'
)


def silent_cause(line: Mapping) -> str | None:
    """Why this stored line rests on the paper's silence, else None. Pure; reads only the line."""
    if line.get("error") or line.get("verdict") != verdict.QUERY:
        return None
    code = str(line.get("reason_code") or "")
    if code in SILENT_CODES:
        return code
    unsafe = verdict.met_unsafe_why(line)
    if unsafe == verdict.NOT_STATED_WHY:
        return "not_stated"
    if unsafe == verdict.NO_VALUE_WHY:
        return "no_value"
    return None


def stop_word(exc: BaseException) -> str:
    """Plain words for why the optional step ended: what the code saw, no detail from any document."""
    if isinstance(exc, agent_claude.AgentGateClosed):
        return "the Claude lane was closed"
    if isinstance(exc, agent_claude.AgentBudgetStop):
        return "a spending cap refused a call"
    return f"an error ({type(exc).__name__})"


def reread_facts(enabled: bool, stopped: str | None, lines: Any) -> dict | None:
    """The run's record of the optional step: None when it is off or ran fully (null renders as nothing, never 0); else
    {"why", "not_reread"}, `not_reread` = the lines whose stored `reread.outcome` is `step_off` (counts equal lines)."""
    if not enabled or not stopped:
        return None
    n = sum(
        1
        for ln in lines
        if isinstance(ln.get("reread"), Mapping)
        and ln["reread"].get("outcome") == "step_off"
    )
    return {"why": stopped, "not_reread": n}


def stopped_sentence(facts: Mapping) -> str:
    """The one sentence the screen and the workbook notes show (the screen builds it from the same two fields)."""
    return f"The second reading of pages stopped early: {facts['not_reread']} lines were not re-read ({facts['why']})"


def parse_reread(text: str) -> dict | None:
    """The reader's JSON object with a boolean `found`, else None (unusable)."""
    obj = agent_claude.parse_json_object(text)
    if not isinstance(obj, dict) or not isinstance(obj.get("found"), bool):
        return None
    return obj


def _field_words(item: Mapping) -> str:
    roles = " ".join(str(r).replace("_", " ") for r in item.get("field_roles") or [])
    return f"{item.get('question') or ''} {roles}".strip()


class RereadMixin:
    """A mixin of `agent_review_run.Runner`; needs `pages`, `paper`, `total_pages`, `call`, `decide`, `emit`'s state."""

    reread_enabled = False
    #: True on the calling thread while the optional step runs: a cap refusal then ends the step, never the review
    _optional = threading.local()
    _reread_off = False  # a refused call (a cap, a closed lane) ends the optional step for the rest of the run
    reread_stopped: str | None = (
        None  # why it ended, in plain words (`stop_word`); None while it has not ended
    )

    def note_reread_stop(self, exc: BaseException) -> None:
        """The optional step ends for the rest of the run, and the run says so (`reread_facts`)."""
        self._reread_off = True
        self.reread_stopped = self.reread_stopped or stop_word(exc)

    # ---- which pages
    def reread_pages(self, item: Mapping, line: Mapping) -> list[int]:
        """At most REREAD_MAX_PAGES page numbers with stored text: the cited page, else the item's selected pages."""
        has = lambda n: bool(  # noqa: E731
            isinstance(n, int)
            and 1 <= n <= self.total_pages
            and (self.pages.page(self.paper, n) or "").strip()
        )
        cited = verdict._page_no(line.get("paper_page"))
        if cited is not None and has(cited):
            return [cited]
        chosen = [n for n in _hints(item) if has(n)] or [
            n for n in pages_for([dict(item, page_hint=[])], self.total_pages) if has(n)
        ]
        chosen = list(dict.fromkeys(chosen))
        if len(chosen) > REREAD_MAX_PAGES:
            from .agent_bind import content_words

            want = content_words(_field_words(item))
            chosen.sort(
                key=lambda n: (
                    -len(want & content_words(self.pages.page(self.paper, n) or "")),
                    n,
                )
            )
            chosen = chosen[:REREAD_MAX_PAGES]
        return sorted(chosen)

    # ---- the request
    def reread_parts(self, item: Mapping, texts: Mapping[int, str], held: list) -> dict:
        content: list[dict] = [
            {
                "type": "text",
                "text": f'<paper document="{self.paper}" page="{n}">\n{texts[n]}\n</paper>',
            }
            for n in sorted(texts)
        ]
        content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
        ask = {
            k: item.get(k)
            for k in ("question", "field_roles", "comparator", "value", "unit")
            if item.get(k) not in (None, "", [])
        }
        if held:
            ask["requirement_text"] = held[0]["text"][:REREAD_MAX_REQUIREMENT_CHARS]
        content.append(
            {
                "type": "text",
                "text": json.dumps({"field": ask}, ensure_ascii=False)
                + "\n\n"
                + REREAD_SHAPE,
            }
        )
        return {
            "system": [
                {
                    "type": "text",
                    "text": REREAD_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": content}],
        }

    def _ask_reread(self, parts: dict) -> tuple[dict | None, str | None, float]:
        """(parsed answer or None, answering model, usd). ONE call: `once` = never sent again after a transport failure."""
        with self._lock:
            self.calls["reread"] = self.calls.get("reread", 0) + 1
        raw, usd = self.call(
            agent_claude.SECOND_MODEL, parts, REREAD_MAX_TOKENS, once=True
        )
        model = agent_claude._answered_model(raw)
        if model != "unknown":
            self.second_models.add(model)
        return parse_reread(_text_of(raw)), model, float(usd or 0.0)

    # ---- the step
    def _unchanged(self, line: dict, cause: str, extra: Mapping, usd: float) -> dict:
        """The line as it was, plus the `reread` record and what the extra calls cost (a line never understates)."""
        out = {**line, "reread": {"asked": True, "cause": cause, **extra}}
        if usd:
            out["usd"] = round(float(line.get("usd") or 0.0) + usd, 6)
        return out

    def in_optional_step(self) -> bool:
        return bool(getattr(self._optional, "on", False))

    def reread_silent_line(
        self, item: Mapping, line: dict, lead_model: str | None, box: Any
    ) -> dict:
        """The step, guarded. Every paid call inside it (re-read, lead re-ask, the second opinion and the context check of
        the recovered line) runs with `_optional` set on this thread: `Runner._halt` then only switches the step off and
        records `refused`, and the line comes back EXACTLY as it was (no claim). A cap stop of an item's NORMAL calls
        (outside the step) halts the review as before: the two are told apart by that flag."""
        self._optional.on, self._optional.refused, self._optional.paid = (
            True,
            False,
            0.0,
        )
        try:
            out = self._step(item, line, lead_model, box)
            if (
                self._optional.refused
            ):  # as it was, marked as not read, charged what was already paid
                return self._unchanged(
                    line,
                    silent_cause(line) or "",
                    {"outcome": "step_off"},
                    self._optional.paid,
                )
            return out
        finally:
            self._optional.on = False

    def _step(
        self, item: Mapping, line: dict, lead_model: str | None, box: Any
    ) -> dict:
        """`line` unchanged unless the step is on and the line is silent. THE FLOW (per silent line at most: 1 page re-read by
        the second model + 1 lead re-ask + the normal second opinion + the context check of a Fail, all through `Runner.call`):
        (a) the second model reads the pages; its quote must stand on one of them (code); (b) the FIRST (lead) model is asked
        the item once more on that page with the quote pointed out; (c) its answer goes through the normal `decide`, second
        opinion included; (d) if the lead again finds nothing, or the second opinion disagrees, the line stays what it was
        and says one reader pointed to text on page N and the other did not confirm it. No line becomes a "met", a Pass or a
        Fail on one reader's word. Outcomes recorded in `reread["outcome"]`: no_value, quote_not_found, not_confirmed,
        recovered; a failed, refused or unreadable call records `failed` and the line says nothing about it."""
        cause = silent_cause(line)
        if (
            not self.reread_enabled
            or cause is None
            or self._stop.is_set()
            or not verdict.calls_allowed(item, self.tier_lookup)
        ):
            return line
        if not lead_model or not agent_run_second.models_differ(
            [lead_model], agent_claude.SECOND_MODEL
        ):
            return line  # unknown, or the same family: one reader twice, never counted as two
        if self._reread_off:  # the step ended earlier in this run: this silent line was not re-read, and it says so
            return {
                **line,
                "reread": {"asked": False, "cause": cause, "outcome": "step_off"},
            }
        numbers = self.reread_pages(item, line)
        texts = {n: self.pages.page(self.paper, n) or "" for n in numbers}
        if not texts:
            return line
        held = held_texts(item, self.clauses)
        parts = self.reread_parts(item, texts, held)
        try:
            got, model, usd = self._ask_reread(parts)
        except FATAL as exc:
            self.note_reread_stop(
                exc
            )  # optional step: the lead's own calls decide whether the run stops
            return self._unchanged(line, cause, {"outcome": "step_off"}, 0.0)
        except agent_claude.AgentClaudeError:
            worst = app_worst_usd(agent_claude.SECOND_MODEL, parts, REREAD_MAX_TOKENS)
            return self._unchanged(line, cause, {"outcome": "failed"}, worst)
        self._optional.paid = usd
        if model and not agent_run_second.models_differ([lead_model], model):
            got = None  # the lane answered with the lead's own family: not a second reader
        record = {"pages": sorted(texts), "model": model, "reread_usd": usd}
        iid = str(item.get("item_id"))
        self._ctx.setdefault(iid, {})["reread_exchange"] = {
            **record,
            "answer": got,
            "first_gate": {
                "why": line.get("why"),
                "reason_code": line.get("reason_code"),
            },
        }
        if got is None:
            return self._unchanged(line, cause, {**record, "outcome": "failed"}, usd)
        if got.get("found") is False:
            return self._unchanged(line, cause, {**record, "outcome": "no_value"}, usd)
        page = self._verified_page(got, texts)
        if page is None:
            return self._unchanged(
                line, cause, {**record, "outcome": "quote_not_found"}, usd
            )
        return self._lead_again(
            item, line, cause, got, page, texts, held, box, record, usd
        )

    def _lead_again(
        self, item, line, cause, got, page, texts, held, box, record, usd
    ) -> dict:
        """(b) and (c): the lead is asked the item once more on the page; its answer goes through `decide` like a first one."""
        iid = str(item.get("item_id"))
        one = dict(item, page_hint=[page])
        pointer = {
            "a_second_reader_points_to": {
                "page": page,
                "quote": got.get("paper_quote"),
            },
            "note": "A second reader says a value for this item may stand at that quote. Check the page yourself and "
            "decide only from the page text; quote what you find word for word; if those words are not a value for "
            "this field, say so (reason_code sheet_silent).",
        }
        clauses = {
            h["ref"]: {
                **h,
                "standard": item.get("standard"),
                "clause": item.get("clause"),
            }
            for h in held
        }
        parts = build_parts(
            self.paper, {page: texts[page]}, clauses, [one], {iid: held}
        )
        last = parts["messages"][0]["content"][-1]
        last["text"] = json.dumps(pointer, ensure_ascii=False) + "\n\n" + last["text"]
        answers, lead_usd, error, model = self._ask_lead([one], parts, False, once=True)
        spent = usd + lead_usd
        self._optional.paid = spent
        base = {**record, "page": page, "lead_usd": lead_usd}
        again_answer = (answers or {}).get(iid)
        if error or again_answer is None or not model:
            return self._unchanged(line, cause, {**base, "outcome": "failed"}, spent)
        self._ctx.setdefault(iid, {})["reread_lead_answer"] = again_answer
        again = self.decide(
            dict(item), again_answer, {page: texts[page]}, model, None, box,
            round(float(line.get("usd") or 0.0) + spent, 6),
        )  # fmt: skip
        second = again.get("second_opinion")
        disagreed = isinstance(second, Mapping) and second.get("agree") is False
        if (
            silent_cause(again) is not None
            or disagreed
            or again.get("ai_verdict") not in (verdict.PASS, verdict.FAIL)
            or not (again.get("quotes_checked") or {}).get("paper")
        ):
            return self._unchanged(
                line, cause, {**base, "outcome": "not_confirmed"}, spent
            )
        return {**again, "reread": {**base, "cause": cause, "outcome": "recovered"}}

    @staticmethod
    def _verified_page(got: Mapping | None, texts: Mapping[int, str]) -> int | None:
        """The ONE page, among those given, whose stored text holds the reader's quote word for word; else None. The reader
        says `found` and names a page, but only the text decides (a wrong page number is mended, a missing quote is not)."""
        if not got or got.get("found") is not True:
            return None
        quote = str(got.get("paper_quote") or "").strip()
        if len(quote) < verdict.MIN_QUOTE_CHARS:
            return None
        hits = [n for n, t in texts.items() if _fold(quote) in _fold(str(t))]
        named = verdict._page_no(got.get("paper_page"))
        if named in hits:
            return named
        return hits[0] if len(hits) == 1 else None


def facts_of(runner: Any, lines: Any) -> dict | None:
    """`reread_facts` of a runner (None without one)."""
    return (
        reread_facts(runner.reread_enabled, runner.reread_stopped, lines)
        if runner
        else None
    )
