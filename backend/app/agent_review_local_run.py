"""The runner's local first-reader step: ONE item per request, asked about only the part of the paper that can hold its answer.

A mixin of `agent_review_run.Runner`, used only with a `LocalEngine`. The Claude path never reaches it. For an item it builds the windows
of `agent_review_excerpt.windows_for` (the label excerpt first, then every other part of every page), asks them one after another, and
decides at the first window that holds an answer. The item is decided by the same `decide` as on the Claude path, with the FULL stored page
text, so every quote is still verified against the whole page.

ABSENCE NEEDS FULL COVERAGE. An answer that says "not stated here" or "silent" is a claim about the paper only when EVERY window of EVERY
page was asked and none was discarded (a request too long, an answer the engine cut). If any was not asked the line is "not all of the paper
could be asked" (Not reviewed), never "not stated". At most `MAX_WINDOWS` windows are asked for one item, so a long paper is a stated limit,
not a silent one. What was asked is on the line's trace (`windows_asked` of `windows_total`) and on the run's counts (`asked N of M`).
Errors and logs carry counts and codes only, never paper text.
"""

from __future__ import annotations

import json
from typing import Any

from . import agent_review_excerpt as excerpt
from . import agent_review_local as local_mod
from . import agent_review_verdict as verdict
from .agent_review_request import (
    ANSWER_SHAPE,
    SYSTEM,
    _question,
    build_parts,
    held_texts,
)

MAX_WINDOWS = 8
PAGE_TAG_TOKENS = 40  # the tag around a shown page, in estimated tokens
#: What an answer must hold to end the search: a verdict with a paper quote, or a reason that does not depend on where the paper says it.
LOCATION_FREE = ("not_applicable", "needs_drawing_or_calc", "unclear_clause")


def decisive(answer: Any) -> bool:
    """Does this answer end the search of the windows? Not "absent", "silent" or an empty quote: those say only that THIS window lacks it."""
    if not isinstance(answer, dict):
        return False
    code = str(answer.get("reason_code") or "").strip().lower()
    if code in LOCATION_FREE:
        return True
    word = verdict.ai_verdict_word(answer.get("verdict"))
    return (
        word in (verdict.PASS, verdict.FAIL)
        and code in ("met", "not_met")
        and bool(str(answer.get("paper_quote") or "").strip())
    )


class LocalRunMixin:
    """`self` is a Runner with `self.local` set."""

    def _local_clauses(self, item: dict) -> tuple[dict, dict]:
        """(clauses for the prompt, held texts by item): the requirement whole and the clause trimmed to the stretch around it."""
        held = held_texts(item, self.clauses)
        req = next((h["text"] for h in held if h["kind"] == "requirement"), None)
        out: dict[str, dict] = {}
        for h in held:
            text = (
                excerpt.trim_clause(h["text"], req)
                if h["kind"] == "clause"
                else h["text"]
            )
            out.setdefault(
                h["ref"],
                {
                    **h,
                    "text": text,
                    "standard": item.get("standard"),
                    "clause": item.get("clause"),
                },
            )
        return out, {str(item.get("item_id")): held}

    def _local_budget(
        self, item: dict, clauses: dict, held_of: dict, out_tokens: int
    ) -> int:
        """Estimated tokens left for the page excerpt of this item's request (the window, less everything else in it)."""
        from . import context_budget as cb

        fixed = cb.estimate_tokens(SYSTEM + ANSWER_SHAPE) + cb.estimate_tokens(
            json.dumps({"items": [_question(item, held_of.get(str(item["item_id"])))]})
        )
        fixed += (
            sum(
                cb.estimate_tokens(c["text"]) + PAGE_TAG_TOKENS
                for c in clauses.values()
            )
            + PAGE_TAG_TOKENS
        )
        return excerpt.fit_budget(
            self.local.window(local_mod.FIRST),
            out_tokens,
            local_mod.WINDOW_MARGIN_TOKENS,
            fixed,
        )

    def local_windows(
        self, item: dict, full: dict[int, str]
    ) -> tuple[list, dict, dict, int]:
        clauses, held_of = self._local_clauses(item)
        out = self.local.first_tokens(1)
        budget = self._local_budget(item, clauses, held_of, out)
        wins = excerpt.windows_for(item, full, budget) if budget >= 200 else []
        return wins, clauses, held_of, budget

    def local_shown(self, item: dict) -> dict[int, str] | None:
        """The pages SHOWN to the first reader for this item (the window that decided it), for the second reader: the same evidence."""
        return self._local_decided.get(str(item.get("item_id")))

    def run_batch_local(self, batch: list[dict]) -> None:
        for item in batch:
            self._run_item_local(item)

    def _run_item_local(self, item: dict) -> None:
        iid = str(item.get("item_id"))
        full = {
            n: t
            for n in range(1, self.total_pages + 1)
            if (t := self.pages.page(self.paper, n))
        }
        box = self._box()
        if self._stop.is_set():
            self.emit(
                self.decide(
                    item, None, full, None, f"not run: {self.stopped}", box, 0.0
                )
            )
            return
        wins, clauses, held_of, budget = self.local_windows(item, full)
        total = len(wins)
        asked = failed = 0
        best: dict | None = (
            None  # the last answer that was not decisive (this window lacks it)
        )
        got, model, error, usd, decided_on = None, None, None, 0.0, None
        for win in wins[:MAX_WINDOWS]:
            parts = build_parts(self.paper, win.pages, clauses, [item], held_of)
            answer, spent, err, mdl = self._ask_lead([item], parts, False)
            usd += spent
            asked += 1
            model = mdl or model
            if answer is None or err:
                failed += 1
                error = err or "unparseable_reply"
                if self._stop.is_set():
                    break
                continue
            a = answer.get(iid)
            if decisive(a):
                got, decided_on, error = a, win, None
                break
            best = a or best
        complete = failed == 0 and asked == total and total <= MAX_WINDOWS and total > 0
        if got is None:
            if best is not None and complete:
                got, error = (
                    best,
                    None,
                )  # every part of every page was asked: "not found" is a claim about the paper
            elif best is not None:
                got, error = (
                    None,
                    local_mod.NOT_ALL_ASKED,
                )  # a part was not asked: never "not stated"
            elif not wins:
                error = (
                    local_mod.LOCAL_TOO_LONG
                )  # nothing fits the window with this item's own text
        shown = decided_on or (wins[0] if wins else None)
        self._local_decided[iid] = shown.pages if shown else None
        self.trace_record({"type": "batch", "item_ids": [iid], "windows_asked": asked, "windows_total": total, "complete": complete,
                           "budget_tokens": budget, "model_answered": model, "usd": usd, "error": error})  # fmt: skip
        self._ctx[iid] = {"batch_item_ids": [iid], "question": _question(item, held_of.get(iid)), "pages_opened": sorted(full),
                          "pages_read": sorted(full), "lead_model": model, "lead_error": error, "lead_answer": got}  # fmt: skip
        if model and model != "unknown":
            self.lead_models.add(model)
        line = self.decide(item, got, full, model, error, box, usd)
        line["windows_asked"], line["windows_total"] = asked, total
        self.emit(self.reread_silent_line(item, line, model, box))
