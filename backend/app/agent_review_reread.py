"""Owner order 13 (12 Nov 2026), C4: before a line is closed as "the paper does not state this", a SECOND, different model
reads the whole stored text of the page(s) where the field would stand and answers one narrow question.

WHAT COUNTS AS SILENT (`silent_cause`): a line the gate left a Query (or an AI opinion) only because the first reader found no
value: its reason code is absent / absent_pages_not_named / sheet_silent, or the met-guard says "not stated" (`NOT_STATED_WHY`)
or "only the field's name" (`NO_VALUE_WHY`). A line with an error, a resumed line, a rule that is not AI approved (it never
buys a call: `calls_allowed`), a drawing or calculation reason, an unclear clause and "not applicable" are NOT silent: no call.

THE STEP (behind `AGENT_REVIEW_REREAD_SILENT_ENABLED`, default OFF): ONE extra call per silent line at most (`once`: never sent
again after a transport failure), always to `agent_claude.SECOND_MODEL` and only when it is a different model family from
the lead. The call goes through the runner's own `call` (the step gate's reservation, `agent_claude._call`, the lane gate,
the approved-document check and the caps: nothing here opens a socket or keeps a ledger). Output limit `REREAD_MAX_TOKENS`.

PAGES (the bound is `REREAD_MAX_PAGES`, 3): the page the first reader cited when it is a page of this paper with text, else
the pages code already selected for the item (its page hint), the ones with most field words first. Whole stored page text.

THE ANSWER IS NOT TRUSTED: its quote must stand word for word on one of those pages (code checks). If it does, the line is
decided AGAIN by the SAME `decide` (the same gate, holds, guards and caps) on an answer made of that quote; a text line can end
no better than "AI thinks" there, because the gate's second opinion would come from the same model (`no_second`). If the
second reader says there is no value, its quote is not on the page, or it gave no usable answer, the line stays the Query it
was, now carrying `reread = {"found": False}`, which `agent_review_wording` words as "two AI readers found no value for this".
A failed or refused call leaves the line exactly as it was (`reread = {"found": None}`): never a claim that two readers looked.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from . import agent_claude, agent_run_second
from . import agent_review_verdict as verdict
from .agent_review_request import FATAL, _hints, _text_of, held_texts, pages_for
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
    _reread_off = False  # a refused call (a cap, a closed lane) ends the optional step for the rest of the run

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
    def reread_silent_line(
        self,
        item: Mapping,
        line: dict,
        answer: Mapping | None,
        lead_model: str | None,
        box: Any,
    ) -> dict:
        """`line` unchanged unless the step is on, the line is silent and the second reader's quote verifies; then the line
        decided again by the same gate. Every other outcome is the same line plus the `reread` record (see the module doc)."""
        cause = silent_cause(line)
        if (
            not self.reread_enabled
            or self._reread_off
            or cause is None
            or self._stop.is_set()
            or not verdict.calls_allowed(item, self.tier_lookup)
        ):
            return line
        if lead_model and not agent_run_second.models_differ(
            [lead_model], agent_claude.SECOND_MODEL
        ):
            return line  # the same family would be one reader twice: no call, no claim of two readers
        numbers = self.reread_pages(item, line)
        texts = {n: self.pages.page(self.paper, n) or "" for n in numbers}
        if not texts:
            return line
        held = held_texts(item, self.clauses)
        try:
            got, model, usd = self._ask_reread(self.reread_parts(item, texts, held))
        except FATAL:
            self._reread_off = (
                True  # optional step: the lead's own calls decide whether the run stops
            )
            return {**line, "reread": {"asked": True, "found": None, "cause": cause}}
        except agent_claude.AgentClaudeError:
            return {**line, "reread": {"asked": True, "found": None, "cause": cause}}
        usd_total = round(float(line.get("usd") or 0.0) + usd, 6)
        if (
            lead_model
            and model
            and not agent_run_second.models_differ([lead_model], model)
        ):
            got = None  # the lane answered with the lead's own family: that is not a second reader
        record = {
            "asked": True,
            "cause": cause,
            "pages": sorted(texts),
            "model": model,
            "usd": usd,
        }
        iid = str(item.get("item_id"))
        self._ctx.setdefault(iid, {})["reread_exchange"] = {
            **record,
            "answer": got,
            "first_gate": {
                "why": line.get("why"),
                "reason_code": line.get("reason_code"),
            },
        }
        page = self._verified_page(got, texts)
        if page is None:
            return {
                **line,
                "usd": usd_total,
                "reread": {**record, "found": False if got is not None else None},
            }
        new_answer = self._answer_from(answer or {}, got or {}, page)
        again = self.decide(
            dict(item),
            new_answer,
            texts,
            model,
            None,
            box,
            usd_total,
            no_second=True,
        )
        return {**again, "reread": {**record, "found": True, "page": page}}

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

    @staticmethod
    def _answer_from(first: Mapping, got: Mapping, page: int) -> dict:
        """The answer the gate decides again: the second reader's own quote, figures and view. What the FIRST reader said
        about silence (its reasoning, comment, `mentioned`, pages searched) is dropped; its field label is kept."""
        meets = got.get("meets")
        word = {True: "Pass", False: "Fail"}.get(meets, "Query")
        out = {
            k: v
            for k, v in first.items()
            if k not in ("mentioned", "reasoning", "comment", "pages_searched")
        }
        out.update(
            paper_quote=got.get("paper_quote"),
            paper_page=page,
            paper_figure=got.get("paper_figure") or "",
            clause_quote=got.get("clause_quote") or first.get("clause_quote"),
            clause_figure=got.get("clause_figure") or first.get("clause_figure"),
            reasoning=got.get("reasoning") or "",
            comment=got.get("comment") or "",
            verdict=word,
            reason_code={"Pass": "met", "Fail": "not_met"}.get(word, "other"),
        )
        return out
