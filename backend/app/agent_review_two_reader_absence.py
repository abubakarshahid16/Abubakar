"""The absence word of the class "AI verdict, two readers agree": "AI verdict: not stated" (lead, 12 Nov 2026).

Behind `AGENT_REVIEW_TWO_READER_ABSENCE_ENABLED` (default off; it needs `AGENT_REVIEW_TWO_READER_VERDICT_ENABLED` on too). A mixin of
`agent_review_run.Runner`. For a line whose first reader said "the paper should state it and does not" (reason "absent", still
unproven, a held rule, approved, strong verified clause quote), the step

  1. runs the code's OWN absence search, the one home: `agent_review_absence.prove` (rule binds, field known and carried by this
     paper kind, EVERY page readable, no field read from the paper names it, no page carries its words, no deferral mark). Not
     proven = the line is not a candidate and nothing is said or asked;
  2. asks a second reader of another family, independently: the request is the WHOLE stored text of EVERY page (never a selected
     page), then the item's held rule text, and a neutral question ("does the paper state a value for this, anywhere?"). It holds
     nothing the first reader said (no verdict, no claim of absence, no quote, no reasoning). A paper over `ABSENCE_MAX_PAGE_CHARS`
     characters has no candidate. One call per at most 8 candidates, sent once, one after the other, through `Runner.call`;
  3. stores the answer as `two_reader_absence`. The class is re-derived from the stored line (`agent_review_two_reader.
     absence_agrees`): the second reader found no value, its clause quote is verified and strong, code's search found nothing,
     every page read. A value the second reader quotes and code verifies on its page is a DISAGREEMENT: the line is a Query with
     the two-readers-disagree reason and its quote is on the Evidence sheet.

Optional step, like the value step: a cap refusal or failure switches it off for the rest of the run, leaves the lines, and is
recorded (`two_reader_absence_state`). Never a Fail, never a proof, never in the contractor copy.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from . import agent_claude, agent_run_second
from . import agent_review_absence as absence
from . import agent_review_two_reader as two
from . import agent_review_verdict as verdict
from . import agent_review_wording as wording
from .agent_review_request import (
    FATAL,
    _question,
    deferred_mark,
    held_texts,
    parse_answers,
)
from .agent_review_two_reader_run import base_of

log = logging.getLogger(__name__)

ABSENCE_SYSTEM = (
    "You are a senior engineer reading a supplier paper. Every page of the paper is given first, in full. Then, for each item, "
    "its REQUIREMENT (the held rule's own words from the standard) and, when given, the clause text around it. For each item "
    "decide whether the paper states a value or an entry that the requirement asks for, anywhere on any page, in a table, a "
    "note or running text, under any name or wording. found=true only when you can copy the paper words that state it exactly, "
    "character for character, and give their page. found=false when no page states it. If the paper leaves it open (blank, "
    "'by vendor', 'TBA', 'to follow'), that is not a value: found=false and open=true. Also copy the requirement words you "
    "relied on, exactly, as clause_quote. Never state confidence."
)
ABSENCE_SHAPE = (
    'Reply with ONE JSON object and nothing else: {"answers": [{"item_id": "...", "found": true or false, "page": 1, '
    '"paper_quote": "...", "clause_quote": "...", "open": true or false}]}. One answer per item. Leave a key empty when you '
    "have nothing for it."
)
MAX_TOKENS_BASE, MAX_TOKENS_PER_ITEM = 300, 250


def build_absence_parts(
    paper: str, texts: dict[int, str], clauses: dict, batch: list[dict], held_of: dict
) -> dict:
    """EVERY page whole, then the held rule texts, then the neutral questions. Built from items, pages and held text only."""
    content: list[dict] = [
        {
            "type": "text",
            "text": f'<paper document="{paper}" page="{n}">\n{texts[n]}\n</paper>',
        }
        for n in sorted(texts)
    ]
    if content:
        content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
    pages = len(content)
    for ref, c in clauses.items():
        tag = c.get("kind") or "clause"
        head = f'<{tag} ref="{ref}" standard="{c.get("standard") or ""}" clause="{c.get("clause") or ""}"'
        content.append(
            {
                "type": "text",
                "text": f'{head} page="{c.get("page") or ""}">\n{c["text"]}\n</{tag}>',
            }
        )
    if len(content) > pages:
        content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
    questions = [_question(i, held_of.get(str(i.get("item_id")))) for i in batch]
    content.append(
        {
            "type": "text",
            "text": json.dumps({"items": questions}, ensure_ascii=False)
            + "\n\n"
            + ABSENCE_SHAPE,
        }
    )
    return {
        "system": [
            {
                "type": "text",
                "text": ABSENCE_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": content}],
    }


class AbsenceMixin:
    def absence_on(self) -> bool:
        if self._two_reader_absence is not None:
            return bool(self._two_reader_absence) and self.two_reader_on()
        from . import agent_review_gate

        return agent_review_gate.two_reader_absence_enabled()

    def record_absence_off(self, code: str, **trace: Any) -> None:
        st = self.two_reader_absence_state
        if st["off"] is None:
            st["off"] = code
        self.trace_record({"type": "two_reader_absence_off", "code": code, **trace})
        log.warning("agent review: the absence step is off for this run: %s", code)

    def two_reader_absence_counts(self) -> dict:
        st = self.two_reader_absence_state
        if not st["enabled"]:
            return {}
        return {
            "two_reader_absence_step": {
                k: v for k, v in st.items() if k not in ("enabled", "usd")
            }
        }

    def run_absence(self) -> None:
        """Never raises: a failure is recorded and the lines stay as they were."""
        self.two_reader_absence_state["enabled"] = True
        try:
            if self._stop.is_set() or self.two_reader_state["off"] in (
                two.OFF_CAP,
                two.OFF_RUN_STOPPED,
            ):
                self.record_absence_off(two.OFF_RUN_STOPPED)
                return
            self._absence_pass()
        except Exception as exc:  # noqa: BLE001  an optional step never fails the run
            self.record_absence_off(two.OFF_CALL_FAILED, error=type(exc).__name__)

    def _absence_requirement(self, line: dict) -> str | None:
        q = line.get("quotes_checked") or {}
        return line.get("requirement") or (
            line.get("clause_quote") if q.get("clause") else None
        )

    def _skip_absence(self, iid: str, why: str) -> None:
        self.two_reader_absence_state["skipped"] += 1
        self.trace_record({"type": "two_reader_absence_skip", "item_id": iid, "why": why})

    def absence_candidates(self, texts: dict[int, str]) -> list[dict]:
        """The lines worth asking: first-reader absence lines (a verified clause, a held rule or an approved checklist item, a plain
        binding requirement) whose first reader was given EVERY page and whose model is of another family than the second reader's.
        The code's own field search (`absence.prove_field`) is a VETO and evidence, never a gate on knowing the field: a value found,
        a deferral or an unreadable page ends it (nothing asked); a rule the code cannot search (no known field) stays a candidate
        and the verdict says "the code could not check this itself"."""
        carried = absence.carried_roles(self.paper_kind, self.equipment_type)
        ledger = getattr(self.pages, "ledger_rows", None)
        facts = list(getattr(self.pages, "facts", []) or [])
        every = list(range(1, self.total_pages + 1))
        out = []
        for iid, line in sorted(self.lines.items()):
            item = self.items_by_id.get(iid)
            if item is None or two.ABSENCE_FIELD in line or not two.is_absence_candidate(line):
                continue
            if not agent_run_second.models_differ([str(line.get("model") or "")], agent_claude.SECOND_MODEL):
                continue
            if sorted(set(line.get("pages_searched") or [])) != every:
                self._skip_absence(iid, "the first reader was not given every page of the paper")  # not awarded
                continue
            requirement = self._absence_requirement(line)
            plain = absence.plain_requirement_code(item, requirement)
            if plain:
                self._skip_absence(iid, "not a plain binding requirement: " + plain)
                continue
            proof = absence.prove_field(
                item, requirement, texts, self.total_pages, ledger, facts, carried,
                deferred=lambda w: deferred_mark(w, self.pages, self.paper, self.total_pages),
            )  # fmt: skip
            self.trace_record({"type": "two_reader_absence_search", "item_id": iid, "proven": proof.proven, "code": proof.code})
            if proof.proven:
                check = two.CHECK_SEARCHED
            elif proof.code in absence.CANNOT_SEARCH:
                check = two.CHECK_COULD_NOT
            else:
                self._skip_absence(iid, "the code's search vetoed it: " + str(proof.code))
                continue
            out.append({"line": line, "item": item, "proof": proof.to_json(), "check": check})
        return out

    def _absence_pass(self) -> None:
        st = self.two_reader_absence_state
        texts = {
            n: self.pages.page(self.paper, n) or ""
            for n in range(1, self.total_pages + 1)
        }
        if self.total_pages > two.ABSENCE_MAX_PAGES or sum(len(t) for t in texts.values()) > two.ABSENCE_MAX_PAGE_CHARS:
            self.record_absence_off(two.OFF_PAPER_TOO_LONG)  # not awarded: nothing is asked, the lines say nothing
            return
        cands = self.absence_candidates(texts)
        st["candidates"] = len(cands)
        if not cands:
            return
        for k in range(0, len(cands), two.MAX_BATCH):
            if st["off"] is not None:
                break
            self._absence_batch(cands[k : k + two.MAX_BATCH], texts)

    def _absence_batch(self, batch: list[dict], texts: dict[int, str]) -> None:
        st = self.two_reader_absence_state
        items = [b["item"] for b in batch]
        clauses: dict[str, dict] = {}
        held_of: dict[str, list[dict]] = {}
        for it in items:
            held_of[str(it.get("item_id"))] = held = held_texts(it, self.clauses)
            for h in held:
                clauses.setdefault(
                    h["ref"],
                    {**h, "standard": it.get("standard"), "clause": it.get("clause")},
                )
        parts = build_absence_parts(self.paper, texts, clauses, items, held_of)
        st["asked"] += len(batch)
        st["calls"] += 1
        try:
            raw, usd = self.call_for_batch(
                batch,
                agent_claude.SECOND_MODEL,
                parts,
                MAX_TOKENS_BASE + MAX_TOKENS_PER_ITEM * len(batch),
                once=True,
                **self.reuse_kw(),
            )
        except FATAL as exc:
            code = two.OFF_RUN_STOPPED if self._stop.is_set() else two.OFF_CAP
            self.record_absence_off(
                code, cause=str(getattr(exc, "code", type(exc).__name__))
            )
            return
        except Exception as exc:  # noqa: BLE001  a failed call: off, lines as they were
            self.record_absence_off(
                two.OFF_CALL_FAILED, error=getattr(exc, "code", type(exc).__name__)
            )
            return
        st["usd"] = round(st["usd"] + float(usd), 6)
        model = agent_claude._answered_model(raw)
        if model != "unknown":
            self.second_models.add(model)
        got = parse_answers(raw)
        if got is None:
            self.record_absence_off(two.OFF_CALL_FAILED, error="unparseable_reply")
            return
        for b in batch:
            if st["off"] is not None:
                break
            self._absence_line(
                b,
                got.get(str(b["item"].get("item_id"))),
                texts,
                model,
                float(usd) / len(batch),
            )
        self.settle_second(
            [str(b["item"].get("item_id")) for b in batch], "two_reader_absence"
        )

    def _checked(
        self, item: dict, answer: dict, texts: dict[int, str]
    ) -> tuple[bool, bool, bool]:
        """(paper quote verified on its page, clause quote verified, clause strong): by code, as for the first reader."""
        held = held_texts(item, self.clauses)
        requirement = next(
            (h["text"] for h in held if h["kind"] == "requirement"), None
        )
        clause_text, whole = None, None
        for h in held:
            if verdict.check_clause_quote(answer.get("clause_quote"), h["text"])[0]:
                clause_text, whole = (
                    h["text"],
                    requirement if h["kind"] == "requirement" else None,
                )
                break
        clause_ok, _why, strong = verdict.check_clause_quote(
            answer.get("clause_quote"), clause_text, whole
        )
        paper_ok = verdict.check_paper_quote(
            answer.get("paper_quote"), answer.get("page"), texts
        )[0]
        return paper_ok, clause_ok, strong

    def _absence_line(
        self,
        b: dict,
        answer: dict | None,
        texts: dict[int, str],
        model: str,
        share: float,
    ) -> None:
        st = self.two_reader_absence_state
        item, iid = b["item"], str(b["item"].get("item_id"))
        if answer is None:
            st["unconfirmed"] += 1
            return
        paper_ok, clause_ok, strong = self._checked(item, answer, texts)
        rec = two.absence_answer(
            found=answer.get("found"), quote=answer.get("paper_quote"), page=answer.get("page"),
            clause_quote=answer.get("clause_quote"), paper_ok=paper_ok, clause_ok=clause_ok, strong=strong,
            open_=answer.get("open") is True, model=model, usd=share, code_search=b["proof"], pages_total=self.total_pages,
            first_pages=b["line"].get("pages_searched"), second_pages=texts, base=base_of(b["line"]), code_check=b["check"],
        )  # fmt: skip
        line = self.lines[iid]
        new = self.exit_line(
            {
                **line,
                two.ABSENCE_FIELD: rec,
                "usd": round(float(line.get("usd") or 0.0) + share, 6),
            }
        )
        try:
            if self.sink is not None:
                self.sink(new, None)
        except Exception as exc:  # noqa: BLE001
            self.record_absence_off(
                two.OFF_CALL_FAILED, error="store_" + type(exc).__name__
            )
            return
        with self._lock:
            self.lines[iid] = new
        if wording.is_two_reader(new):
            st["agreed"] += 1
        elif two.absence_disagrees(new):
            st["disagreed"] += 1
        else:
            st["unconfirmed"] += 1
        self.trace_record(
            {
                "type": "two_reader_absence_item",
                "item_id": iid,
                "second_reader": {k: v for k, v in rec.items() if k != "usd"},
                "class": new.get("verdict_class"),
            }
        )
