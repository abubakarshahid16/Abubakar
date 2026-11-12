"""The other-paper class "Not checked on this paper" (lead, 12 Nov 2026), behind `AGENT_REVIEW_TWO_READER_OTHER_PAPER_ENABLED`.

A mixin of `agent_review_run.Runner`. A line is a candidate when the FIRST reader's own answer says the rule cannot be checked on this
paper: its stored CLOSED reason code `needs_drawing_or_calc` (a value of `agent_review_request.REASON_CODES`, read by `reason_of`;
never matched in free text), with a verified clause quote, an approved rule or a checklist item. The second reader, of another family,
is asked the SAME question (`build_parts`: items, page text and held rule text only; it never sees the first answer). Its answer:
the same code and a verified clause quote = the class (both readers, both clause quotes); a verdict (met or not met) with both
quotes verified = a disagreement, the line stays a Query and its answer goes to Evidence; anything else, a failure or a refusal =
the line is unchanged. Optional step: a cap refusal or failure switches it off for the rest of the run and records it. One call per
at most 8 candidates per page group, sent once.
"""

from __future__ import annotations

import logging
from typing import Any

from . import agent_claude, agent_run_second
from . import agent_review_crs as crs_lines
from . import agent_review_items as items_mod
from . import agent_review_two_reader as two
from .agent_review_request import (
    FATAL,
    build_parts,
    held_texts,
    pages_for,
    parse_answers,
)

log = logging.getLogger(__name__)


class OtherPaperMixin:
    def other_on(self) -> bool:
        if self._two_reader_other is not None:
            return bool(self._two_reader_other) and self.two_reader_on()
        from . import agent_review_gate

        return agent_review_gate.two_reader_other_paper_enabled()

    def record_other_off(self, code: str, **trace: Any) -> None:
        st = self.two_reader_other_state
        if st["off"] is None:
            st["off"] = code
        self.trace_record({"type": "two_reader_other_off", "code": code, **trace})
        log.warning("agent review: the other-paper step is off for this run: %s", code)

    def two_reader_other_counts(self) -> dict:
        st = self.two_reader_other_state
        if not st["enabled"]:
            return {}
        return {
            "two_reader_other_step": {
                k: v for k, v in st.items() if k not in ("enabled", "usd")
            }
        }

    def run_other(self) -> None:
        """Never raises: a failure is recorded and the lines stay as they were."""
        self.two_reader_other_state["enabled"] = True
        try:
            if self._stop.is_set() or self.two_reader_state["off"] in (
                two.OFF_CAP,
                two.OFF_RUN_STOPPED,
            ):
                self.record_other_off(two.OFF_RUN_STOPPED)
                return
            self._other_pass()
        except Exception as exc:  # noqa: BLE001  an optional step never fails the run
            self.record_other_off(two.OFF_CALL_FAILED, error=type(exc).__name__)

    def _other_pass(self) -> None:
        st = self.two_reader_other_state
        cands = [
            ln
            for iid, ln in sorted(self.lines.items())
            if iid in self.items_by_id
            and two.OTHER_FIELD not in ln
            and two.is_other_candidate(ln)
        ]
        st["candidates"] = len(cands)
        ask = [
            ln for ln in cands
            if agent_run_second.models_differ([str(ln.get("model") or "")], agent_claude.SECOND_MODEL)
        ]  # fmt: skip
        if cands and not ask:
            self.record_other_off(two.OFF_LEAD_UNKNOWN)
            return
        items = [self.items_by_id[str(ln["item_id"])] for ln in ask]
        for batch in items_mod.batch_by_page(items, two.MAX_BATCH):
            if st["off"] is not None:
                break
            self._other_batch(batch)

    def _other_batch(self, batch: list[dict]) -> None:
        st = self.two_reader_other_state
        numbers = pages_for(batch, self.total_pages)
        pages = {n: t for n in numbers if (t := self.pages.page(self.paper, n))}
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
        st["asked"] += len(batch)
        st["calls"] += 1
        try:
            raw, usd = self.call(
                agent_claude.SECOND_MODEL,
                parts,
                min(two.TOKENS_CAP, two.TOKENS_BASE + two.TOKENS_PER_ITEM * len(batch)),
                once=True,
            )
        except FATAL as exc:
            self.record_other_off(
                two.OFF_RUN_STOPPED if self._stop.is_set() else two.OFF_CAP,
                cause=str(getattr(exc, "code", type(exc).__name__)),
            )
            return
        except Exception as exc:  # noqa: BLE001  a failed call: off, lines as they were
            self.record_other_off(
                two.OFF_CALL_FAILED, error=getattr(exc, "code", type(exc).__name__)
            )
            return
        st["usd"] = round(st["usd"] + float(usd), 6)
        model = agent_claude._answered_model(raw)
        if model != "unknown":
            self.second_models.add(model)
        got = parse_answers(raw)
        if got is None:
            self.record_other_off(two.OFF_CALL_FAILED, error="unparseable_reply")
            return
        for it in batch:
            if st["off"] is not None:
                break
            self._other_line(
                it,
                got.get(str(it.get("item_id"))),
                pages,
                model,
                float(usd) / len(batch),
            )

    def _other_line(
        self, item: dict, answer: dict | None, pages: dict, model: str, share: float
    ) -> None:
        st = self.two_reader_other_state
        iid = str(item.get("item_id"))
        if answer is None:
            st["unconfirmed"] += 1
            return
        ev = self._evidence(item, answer, pages, None)
        rec = two.second_answer(
            answer, ai=ev["ai"], reason_code=ev["reason_code"], checks=ev["checks"], absent=ev["absent"],
            model=model, usd=share, two_sentences=crs_lines.two_sentences,
        )  # fmt: skip
        line = self.lines[iid]
        new = self.exit_line(
            {
                **line,
                two.OTHER_FIELD: rec,
                "usd": round(float(line.get("usd") or 0.0) + share, 6),
            }
        )
        try:
            if self.sink is not None:
                self.sink(new, None)
        except Exception as exc:  # noqa: BLE001
            self.record_other_off(
                two.OFF_CALL_FAILED, error="store_" + type(exc).__name__
            )
            return
        with self._lock:
            self.lines[iid] = new
        if new.get("verdict_class") == two.CLASS_NOT_CHECKED_HERE:
            st["agreed"] += 1
        elif two.other_disagrees(new):
            st["disagreed"] += 1
        else:
            st["unconfirmed"] += 1
        self.trace_record(
            {
                "type": "two_reader_other_item",
                "item_id": iid,
                "second_reader": {k: v for k, v in rec.items() if k != "usd"},
                "class": new.get("verdict_class"),
            }
        )
