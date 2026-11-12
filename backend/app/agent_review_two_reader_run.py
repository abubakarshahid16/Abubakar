"""The runner's second-reader step (owner order 13, point 10; behind `AGENT_REVIEW_TWO_READER_VERDICT_ENABLED`, default off).

A mixin of `agent_review_run.Runner` (a new module so no shared file grows). After the first reader's lines are decided, every
CANDIDATE line (`agent_review_two_reader.is_candidate`) is put to a second reader of a different model family, which answers the
SAME question the first reader answered: the request is built by the SAME `build_parts` from the items, the page text and the held
rule text ONLY, so it holds nothing the first reader said (no verdict, no quote, no reasoning, no comment). What the second
reader returns is stored on the line as `two_reader`; the class itself is re-derived by `agent_review_wording.classify`.

BOUNDS. One call per batch of at most `MAX_BATCH` (8) candidate items that share a page group (the first reader's own grouping,
`batch_by_page`), sent ONCE (`once=True`: never re-sent after a transport failure; a cut-off or unreadable reply is not retried or
split). So the calls of a run are the sum over page groups of ceil(group size / 8): ceil(candidates / 8) for a paper of up to 8
pages (every item then has every page), never more than the number of candidates; the
worst case of each is reserved through the same `AppStepGate` and `claude_spend.metered` as every other call, with the
approved-document check and the caps. Batches run one after the other.

OPTIONAL STEP (the pattern of an optional AI step): a cap or approval refusal, a failed or unreadable call, an unknown first-reader
model, or a line that could not be stored switches the step OFF for the rest of the run, leaves every line exactly as it was,
and records the code on the run (`two_reader_state["off"]`, counted in the summary). It never stops the run and is never
`_halt`ed. An item the reply left out is left as it was, and counted as not confirmed.
"""

from __future__ import annotations

import logging
from typing import Any

from . import agent_claude, agent_run_second
from . import agent_review_crs as crs_lines
from . import agent_review_items as items_mod
from . import agent_review_two_reader as two
from . import agent_review_wording as wording
from .agent_review_request import (
    FATAL,
    build_parts,
    held_texts,
    pages_for,
    parse_answers,
)

log = logging.getLogger(__name__)


class TwoReaderMixin:
    # ---- the switch: a Runner argument wins (tests); else the setting
    def two_reader_on(self) -> bool:
        if self._two_reader is not None:
            return bool(self._two_reader)
        from . import agent_review_gate

        return agent_review_gate.two_reader_enabled()

    def record_two_reader_off(self, code: str, **trace: Any) -> None:
        st = self.two_reader_state
        if st["off"] is None:
            st["off"] = code
        self.trace_record({"type": "two_reader_off", "code": code, **trace})
        log.warning(
            "agent review: the second-reader step is off for this run: %s", code
        )

    def run_two_readers(self) -> None:
        """The whole step. Never raises (a failure inside it is recorded, the lines stay as they were)."""
        self.two_reader_state["enabled"] = True
        try:
            if self._stop.is_set():
                self.record_two_reader_off(two.OFF_RUN_STOPPED)
                return
            self._two_reader_pass()
        except Exception as exc:  # noqa: BLE001  an optional step never fails the run
            self.record_two_reader_off(two.OFF_CALL_FAILED, error=type(exc).__name__)
        if (
            self.absence_on()
        ):  # its own switch; never before the value step, never without it
            self.run_absence()
        if self.other_on():  # its own switch, after the others, never without the first
            self.run_other()

    def two_reader_counts(self) -> dict:
        """What the run row keeps of the step (counts and the one code that switched it off): {} when the step did not run."""
        st = self.two_reader_state
        if not st["enabled"]:
            return {}
        return {
            "two_reader_step": {
                k: v for k, v in st.items() if k not in ("enabled", "usd")
            },
            **self.two_reader_absence_counts(),
            **self.two_reader_other_counts(),
        }

    def two_reader_candidates(self) -> list[dict]:
        """The lines to ask: candidates with no stored second answer (a resumed line that already has one is never asked again),
        whose item is known and whose first-reader model is of another family than the second reader."""
        out = []
        for iid, line in sorted(self.lines.items()):
            if two.FIELD in line or not two.is_candidate(line):
                continue
            if iid in self.items_by_id:
                out.append(line)
        return out

    def _two_reader_pass(self) -> None:
        st = self.two_reader_state
        cands = self.two_reader_candidates()
        st["candidates"] = len(cands)
        ask = [
            ln
            for ln in cands
            if agent_run_second.models_differ(
                [str(ln.get("model") or "")], agent_claude.SECOND_MODEL
            )
        ]
        if cands and not ask:
            self.record_two_reader_off(two.OFF_LEAD_UNKNOWN)
            return
        items = [self.items_by_id[str(ln["item_id"])] for ln in ask]
        batches = items_mod.batch_by_page(items, two.MAX_BATCH)
        for batch in batches:
            if st["off"] is not None:
                break
            self._two_reader_batch(batch)

    def _two_reader_batch(self, batch: list[dict]) -> None:
        st = self.two_reader_state
        ids = [str(i.get("item_id")) for i in batch]
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
        max_tokens = min(
            two.TOKENS_CAP, two.TOKENS_BASE + two.TOKENS_PER_ITEM * len(batch)
        )
        st["asked"] += len(batch)
        st["calls"] += 1
        try:
            raw, usd = self.call(
                agent_claude.SECOND_MODEL, parts, max_tokens, once=True
            )
        except FATAL as exc:
            code = two.OFF_RUN_STOPPED if self._stop.is_set() else two.OFF_CAP
            self.record_two_reader_off(
                code, cause=str(getattr(exc, "code", type(exc).__name__))
            )
            return
        except Exception as exc:  # noqa: BLE001  a failed call: off, lines as they were
            self.record_two_reader_off(
                two.OFF_CALL_FAILED, error=getattr(exc, "code", type(exc).__name__)
            )
            return
        st["usd"] = round(st["usd"] + float(usd), 6)
        model = agent_claude._answered_model(raw)
        if model != "unknown":
            self.second_models.add(model)
        got = parse_answers(raw)
        if got is None:
            self.record_two_reader_off(two.OFF_CALL_FAILED, error="unparseable_reply")
            return
        share = float(usd) / max(1, len(batch))
        for it in batch:
            if st["off"] is not None:
                break
            self._two_reader_line(
                it, got.get(str(it.get("item_id"))), pages, model, share
            )
        self.trace_record(
            {
                "type": "two_reader_batch",
                "item_ids": ids,
                "pages_read": sorted(pages),
                "model_answered": model,
                "usd": usd,
            }
        )

    def _two_reader_line(
        self, item: dict, answer: dict | None, pages: dict, model: str, share: float
    ) -> None:
        st = self.two_reader_state
        iid = str(item.get("item_id"))
        if answer is None:  # the reply left it out: the line stays as it was
            st["unconfirmed"] += 1
            return
        ev = self._evidence(item, answer, pages, None)
        second = two.second_answer(
            answer,
            ai=ev["ai"],
            reason_code=ev["reason_code"],
            checks=ev["checks"],
            absent=ev["absent"],
            model=model,
            usd=share,
            two_sentences=crs_lines.two_sentences,
        )
        line = self.lines[iid]
        new = self.exit_line(
            {
                **line,
                two.FIELD: second,
                "usd": round(float(line.get("usd") or 0.0) + share, 6),
            }
        )
        try:
            if (
                self.sink is not None
            ):  # the table's own CHECK is the last guard; a refusal switches the step off
                self.sink(new, None)
        except Exception as exc:  # noqa: BLE001
            self.record_two_reader_off(
                two.OFF_CALL_FAILED, error="store_" + type(exc).__name__
            )
            return
        with self._lock:
            self.lines[iid] = new
        if wording.is_two_reader(new):
            st["agreed"] += 1
        elif two.disagrees(new):
            st["disagreed"] += 1
        else:
            st["unconfirmed"] += 1
        self.trace_record(
            {
                "type": "two_reader_item",
                "item_id": iid,
                "second_reader": {k: v for k, v in second.items() if k != "usd"},
                "class": new.get("verdict_class"),
            }
        )
