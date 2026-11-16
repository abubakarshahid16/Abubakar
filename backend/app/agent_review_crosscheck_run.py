"""The runner's cross-check step: a second AI of another company (Groq) is asked about the lines code did not prove.

A mixin of `agent_review_run.Runner` (a new module so no shared file grows). Behind `groq_crosscheck_enabled` (default
off): off, nothing here runs, no state is kept and no line changes. Runs after the first reader and the optional second
readers, on the Claude path only (a local run and a Local-only plan send nothing anywhere).

WHICH LINES (`candidate`): an AI met or not met that code did not prove ("AI thinks: met / not met", either class, and
"AI verdict, two readers agree"). Never a line already a Query (the Claude second opinion said no, two readers disagree):
no answer could change what it shows. Never a proven Pass or Fail,
never a code line, never a failed call, never a line already answered (resume).

WHAT LEAVES, per line, through `groq_transport.send` only: the system sentence and THE SAME narrow question as the Claude
second opinion (`agent_claude.second_prompt`: the colour, the paper quote and the clause quote). Both quotes must have been
verified by code on their pages, and each at most `MAX_QUOTE_CHARS` (a longer quote keeps the line at home, never cut and
sent); the paper, and the rule book the clause quote is from, must pass `groq_approved.refusal` (the run's stored plan showed
the second AI's line before the start, both approved lists, no block, no contract). Never a page, a whole document, a file
name or a title.

MONEY: `groq_spend` reserves the worst case before each call (USD per run and per day caps of its own), settles to the
answer's usage after, releases a call that did no billable work (a 4xx, a refusal before sending). Counted on the run as
`crosscheck_step` (its own usd), never in the Claude total `run_usd` nor in a line's `usd`.

OPTIONAL STEP: a cap stops the step for the rest of the run (the lines left say so); a failed call leaves its line as it
was (said); nothing here stops the review or raises out of `run_crosscheck`.
"""

from __future__ import annotations

import contextvars
import json
import logging
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor

from . import (
    agent_claude,
    agent_run_second,
    claude_spend,
    groq_approved,
    groq_spend,
    groq_transport,
)
from . import agent_review_crosscheck as cc
from . import agent_review_verdict as verdict
from . import agent_review_wording as wording
from .agent_trace import words
from .config import settings

log = logging.getLogger(__name__)

#: Output tokens of one answer: a reasoning model thinks before its one JSON line.
MAX_TOKENS = 1024
#: Lines asked at once (the ledger and the line table are locked; Groq's rate limit is low on a free key).
CONCURRENCY = 2
CANDIDATE_CLASSES = frozenset(
    {wording.CLASS_OPINION, wording.CLASS_UNAPPROVED, wording.CLASS_TWO_READERS}
)
OFF_LOCAL, OFF_STOPPED = "local_run", "run_stopped"
#: The longest quote that may leave (characters). A longer one keeps its line at home (review R-1854: send less).
MAX_QUOTE_CHARS = 400


def candidate(line: Mapping) -> bool:
    """May the second AI be asked about this stored line? Only an AI met or not met the engineer would see as an opinion or as
    "two readers agree": a line already a Query (the Claude second opinion said no, two readers disagree) is never sent, since
    no answer could change what it shows (review R-1854: send less)."""
    if cc.answered(line) or not cc.unproven_ai_line(line):
        return False
    # "the second reader said no" has ONE home (rule 8); such a line is a Query by the wording's own rule (#1851)
    if agent_run_second.disagreed(line.get("second_opinion")):
        return False
    return wording.classify(line)["verdict_class"] in CANDIDATE_CLASSES


def quotes_too_long(line: Mapping) -> bool:
    """A quote longer than `MAX_QUOTE_CHARS`: the line is not sent at all (never cut and sent)."""
    return any(
        len(str(line.get(k) or "")) > MAX_QUOTE_CHARS
        for k in ("paper_quote", "clause_quote")
    )


def quotes_verified(line: Mapping) -> bool:
    checks = line.get("quotes_checked")
    return (
        isinstance(checks, Mapping)
        and checks.get("paper") is True
        and checks.get("clause") is True
        and bool(str(line.get("paper_quote") or "").strip())
        and bool(str(line.get("clause_quote") or "").strip())
    )


def body_for(line: Mapping, model: str) -> dict:
    """The one request body: the second-opinion system sentence and question, the colour and the two quotes. Nothing else."""
    colour = verdict.COLOUR_OF[line["ai_verdict"]]
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": agent_claude.SECOND_SYSTEM},
            {
                "role": "user",
                "content": agent_claude.second_prompt(
                    colour, line.get("paper_quote"), line.get("clause_quote")
                ),
            },
        ],
        "temperature": 0,
        "max_completion_tokens": MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    if model.startswith("openai/gpt-oss"):
        body["reasoning_effort"] = "low"
    return body


def parse_reply(answer: Mapping) -> tuple[bool | None, str | None, str | None]:
    """(agree, reason of at most 20 words, the model that answered) from a chat completion. Anything else: (None, ...)."""
    model = answer.get("model")
    model = str(model)[:80] if isinstance(model, str) and model.strip() else None
    choices = answer.get("choices")
    first = (
        choices[0]
        if isinstance(choices, list) and choices and isinstance(choices[0], Mapping)
        else {}
    )
    message = first.get("message") if isinstance(first.get("message"), Mapping) else {}
    if first.get("finish_reason") not in (None, "stop"):
        return None, None, model
    obj = agent_claude.parse_json_object(str(message.get("content") or "")) or {}
    agree = obj.get("agree")
    if not isinstance(agree, bool):
        return None, None, model
    return agree, words(obj.get("reason"), 20) or None, model


def stats_template() -> dict:
    return {
        "enabled": True,
        "candidates": 0,
        "asked": 0,
        "agreed": 0,
        "disagreed": 0,
        "no_answer": 0,
        "not_approved": 0,
        "not_verified": 0,
        "too_long": 0,
        "not_shown": 0,
        "not_run_cap": 0,
        "off": None,
        "model": None,
        "usd": 0.0,
    }


def _not_run(code: str, said: str) -> dict:
    return {
        "asked": False,
        "agree": None,
        "model": None,
        "usd": 0.0,
        "reason": None,
        "code": code,
        "said": said,
    }


class CrosscheckMixin:
    def crosscheck_counts(self) -> dict:
        """What the run row keeps of the step: {} when it is switched off."""
        st = getattr(self, "_crosscheck", None)
        if not st:
            return {}
        return {"crosscheck_step": {k: v for k, v in st.items() if k != "enabled"}}

    def run_crosscheck(self) -> None:
        """Ask the second AI about every candidate line. Never raises; off = nothing at all."""
        if not settings.groq_crosscheck_enabled:
            return
        st = self._crosscheck = stats_template()
        st["model"] = str(settings.groq_crosscheck_model)
        if self.local is not None:
            st["off"] = OFF_LOCAL
            return
        if self._stop.is_set():
            st["off"] = OFF_STOPPED
            return
        lines = [ln for _iid, ln in sorted(self.lines.items()) if candidate(ln)]
        st["candidates"] = len(lines)
        run = claude_spend.current_run()
        try:
            with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
                jobs = [
                    pool.submit(
                        contextvars.copy_context().run, self._crosscheck_one, ln, run
                    )
                    for ln in lines
                ]
                for job in jobs:
                    job.result()
        except Exception as exc:  # noqa: BLE001  an optional step never fails the run; the code is recorded
            st["off"] = st["off"] or "error_" + type(exc).__name__
            log.warning("groq cross-check stopped: %s", type(exc).__name__)

    def _crosscheck_one(self, line: Mapping, run: str | None) -> None:
        st = self._crosscheck
        with self._lock:
            off = st["off"]
        if off is not None:
            rec = _not_run(
                str(off),
                cc.CAP_SAID
                if off in (groq_spend.RUN_CAP, groq_spend.DAY_CAP)
                else cc.STOPPED_SAID,
            )
            return self._crosscheck_store(
                line, rec, "not_run_cap" if rec["said"] == cc.CAP_SAID else None
            )
        if not quotes_verified(line):
            return self._crosscheck_store(
                line,
                _not_run("quotes_not_verified", cc.NOT_VERIFIED_SAID),
                "not_verified",
            )
        if quotes_too_long(line):
            return self._crosscheck_store(
                line, _not_run("quote_too_long", cc.TOO_LONG_SAID), "too_long"
            )
        ids = sorted(
            {str(self.paper)}
            | (
                {str(line["standard_document_id"])}
                if line.get("standard_document_id")
                else set()
            )
        )
        refused = groq_approved.refusal(ids)
        if refused == groq_approved.NOT_SHOWN:
            return self._crosscheck_store(
                line, _not_run(refused, cc.NOT_SHOWN_SAID), "not_shown"
            )
        if refused is not None:
            return self._crosscheck_store(
                line, _not_run(refused, cc.NOT_APPROVED_SAID), "not_approved"
            )
        return self._crosscheck_store(line, self._crosscheck_ask(line, ids, run), None)

    def _crosscheck_ask(self, line: Mapping, ids: list[str], run: str | None) -> dict:
        """One reserved, sent and settled call. A cap switches the step off for the rest of the run."""
        st, model = self._crosscheck, str(settings.groq_crosscheck_model)
        body = body_for(line, model)
        sent_bytes = json.dumps(body["messages"], ensure_ascii=False).encode("utf-8")
        worst = groq_spend.worst_case_usd(model, len(sent_bytes), MAX_TOKENS)
        try:
            res = groq_spend.reserve(run, model, worst)
        except groq_spend.GroqBudgetExceeded as exc:
            with self._lock:
                st["off"] = st["off"] or exc.code
            return {**_not_run(exc.code, cc.CAP_SAID), "_count": "not_run_cap"}
        try:
            answer = groq_transport.send(body, document_ids=ids)
        except Exception as exc:  # noqa: BLE001  a failed call leaves the line as it was; its code is kept
            usd = (
                groq_spend.release(res)
                if groq_transport.unbilled(exc)
                else groq_spend.settle(res, None)
            )
            code = getattr(exc, "code", None) or type(exc).__name__
            log.warning(
                "groq cross-check: no answer for a line (%s)", type(exc).__name__
            )
            sent = not isinstance(exc, groq_transport.GroqRefused) or exc.sent
            return {
                **_not_run(str(code), cc.NO_ANSWER_SAID),
                "asked": sent,
                "usd": usd,
                "_count": "no_answer",
            }
        usd = groq_spend.settle(res, groq_spend.cost_usd(model, answer.get("usage")))
        agree, reason, answered_by = parse_reply(answer)
        if agree is None:
            rec = {
                **_not_run("no_usable_answer", cc.NO_ANSWER_SAID),
                "asked": True,
                "model": answered_by,
            }
            return {**rec, "usd": usd, "_count": "no_answer"}
        rec = {
            "asked": True,
            "agree": agree,
            "model": answered_by,
            "usd": usd,
            "reason": reason,
            "code": None,
        }
        return {**rec, "said": None, "_count": "agreed" if agree else "disagreed"}

    def _crosscheck_store(self, line: Mapping, rec: dict, count: str | None) -> None:
        """The record onto the line, through the runner's one exit, into the table (under the runner's lock)."""
        st = self._crosscheck
        count = rec.pop("_count", count)
        iid = str(line["item_id"])
        with self._lock:
            if count:
                st[count] += 1
            st["asked"] += 1 if rec.get("asked") else 0
            st["usd"] = round(st["usd"] + float(rec.get("usd") or 0.0), 8)
            new = self.exit_line({**self.lines.get(iid, line), cc.FIELD: rec})
            self.lines[iid] = new
            try:
                if self.sink is not None:
                    self.sink(new, None)
            except Exception:  # noqa: BLE001  the line stays decided in memory; the run row says the step ran
                log.warning("groq cross-check: a line was not stored")
