"""The general review run (#1690, #781), ported from the lab run that was scored on 11 Nov 2026: parts 1 and 2 and the plumbing.
Parts 3 to 5 (the findings) and the second model are `agent_general_findings`; the five parts are:

    1  the rule books the paper cites that we do not hold (free, no call); the held books and why they were not used
    2  the completeness checklist of this kind of paper (only when its subject fits the paper), asked in batches
    3  the paper against ITSELF: code verifies every quote word for word on its page; a second model of ANOTHER family keeps or
       drops each survivor; figures are "differ: by code" only under the strict rule of `agent_general_review.figures_label`
    4  the paper against the PROJECT PAPERS the request named (never chosen silently); silence is a Query
    5  at most 10 AI engineering comments per run, each tied to a verified quote

Every line leaves through `agent_general_review.finalize_line` (the single exit). Calls go ONLY through the review runner's
`call` (`agent_claude._call` -> `reader_transport` -> `claude_spend.metered`, the step gate in front): the USD caps are the
existing ones and nothing here keeps a ledger of its own. A reply is stored per step under the run's folder (local disk) only
when it parses, so a resumed run never pays twice. A cut-off or unreadable answer is "Not reviewed", never a verdict, and an
error never makes a line more confident. No paper text goes to a log: the trace holds ids, page numbers and answers.
"""

from __future__ import annotations

import json
import threading
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from . import agent_claude
from . import agent_general_prompts as prompts
from . import agent_general_review as core
from . import agent_review_verdict as verdict
from .agent_general_findings import (  # noqa: F401  (the limits are re-exported for the callers and the tests)
    MAX_COMMENTS_P5,
    MAX_WORDS_NOTE,
    Dropped,
    FindingsMixin,
    _key,
    page_blocks,
    parts_of,
)
from .agent_general_review import (
    CLASS_NOT_CHECKED,
    CLASS_NOT_REVIEWED,
    CLASS_NOTE,
    CLASS_QUERY,
    Documents,
)
from .agent_review_request import FATAL, MAX_TOKENS_CAP, _text_of

LEAD_MODEL = agent_claude.LEAD_MODEL
SECOND_MODEL = agent_claude.SECOND_MODEL
WINDOW_TOKENS = 60_000
MAX_BATCH_P2 = 8
TOKENS_PER_ITEM_P2, TOKENS_BASE_P2 = 400, 600
P2_STATUSES = ("present", "partial", "absent", "unclear")


class GeneralRun(FindingsMixin):
    def __init__(
        self,
        *,
        paper: str,
        docs: Documents,
        kind: str,
        books: Mapping,
        items: list[dict],
        items_info: Mapping,
        project: list[str],
        run_dir: Path,
        runner: Any,
        unread: Iterable[int] = (),
        lead_model: str = LEAD_MODEL,
        second_model: str = SECOND_MODEL,
        window_tokens: int = WINDOW_TOKENS,
        concurrency: int = 3,
    ) -> None:
        self.paper, self.docs, self.kind = paper, docs, kind
        self.not_held = list(books.get("not_held") or [])
        self.held_fit = dict(books.get("held_fit") or {})
        self.held_not_fit = dict(books.get("held_not_fit") or {})
        for d in project:  # checked before ANY call: a project paper outside the carrier is never named, read or sent
            docs.pages(d)
        self.items, self.items_info, self.project = (
            items,
            dict(items_info),
            list(project),
        )
        self.run_dir, self.runner = Path(run_dir), runner
        self.lead_model, self.second_model, self.window_tokens = (
            lead_model,
            second_model,
            window_tokens,
        )
        self.concurrency = max(1, int(concurrency))
        self.pages = docs.pages(paper)
        self.unread = sorted({int(n) for n in unread})
        self.lines: list[dict] = []
        self.dropped = Dropped()
        self.part_counts: dict[int, dict] = {p: {} for p in core.PARTS}
        self.lead_models: set[str] = set()
        self.second_models: set[str] = set()
        self.calls: Counter = Counter()
        self.failures = 0
        self.stopped = ""
        self._lock = threading.Lock()
        (self.run_dir / "steps").mkdir(parents=True, exist_ok=True)

    # ---- trace and stored replies
    def trace(self, rec: Mapping) -> None:
        with (
            self._lock,
            (self.run_dir / "trace.jsonl").open("a", encoding="utf-8") as fh,
        ):
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def _step_path(self, key: str) -> Path:
        return self.run_dir / "steps" / f"{key}.json"

    def ask(
        self,
        key: str,
        model: str,
        parts: dict,
        max_tokens: int,
        kind: str,
        valid: Callable[[str], bool],
    ) -> dict:
        """One metered call, or the stored reply of an earlier attempt of the same step (never paid twice). The reply is stored
        only when `valid` accepts it."""
        path = self._step_path(key)
        if path.is_file():
            rec = json.loads(path.read_text(encoding="utf-8"))
            self.trace({"type": "resumed", "step": key, "model": rec.get("model")})
            self._note_model(model, rec.get("model"))
            return rec
        if self.runner._stop.is_set():
            raise agent_claude.AgentBudgetStop(self.runner.stopped or "run_stopped")
        blocks = parts["messages"][0]["content"]
        opened = [
            b["text"].split("\n", 1)[0] for b in blocks[:-1]
        ]  # the page tags only: ids and page numbers, not text
        self.trace({"type": "request", "step": key, "model": model, "max_tokens": max_tokens, "pages_opened": opened,
                    "question": blocks[-1]["text"]})  # fmt: skip
        answer, usd = self.runner.call(model, parts, max_tokens)
        rec = {
            "text": _text_of(answer),
            "model": agent_claude._answered_model(answer),
            "usd": usd,
        }
        with self._lock:
            self.calls[kind] += 1
        self.trace({"type": "answer", "step": key, **rec})
        self._note_model(model, rec["model"])
        if valid(rec["text"]):
            path.write_text(json.dumps(rec), encoding="utf-8")
        return rec

    def _note_model(self, asked: str, answered: Any) -> None:
        if answered and answered != "unknown":
            with self._lock:
                (
                    self.second_models
                    if asked == self.second_model
                    else self.lead_models
                ).add(str(answered))

    def halt(self, exc: BaseException) -> None:
        self.runner._halt(exc)
        self.stopped = self.runner.stopped

    @staticmethod
    def json_of(text: str) -> dict | None:
        return agent_claude.parse_json_object(text)

    def add(self, line: Mapping) -> dict:
        out = core.finalize_line(line)
        model_text = out["part"] in (3, 4, 5) or out.get("subkind") in (
            core.SUB_CHECKLIST,
            core.SUB_CONCERN,
        )
        out["text_source"] = core.TEXT_FROM_MODEL if model_text else None
        out["part_word"] = core.PART_WORDS[out["part"]]
        out["line_id"] = out["item_id"] = f"G-{len(self.lines) + 1:03d}"
        self.lines.append(out)
        return out

    def not_reviewed(self, part: int, why: str, **extra: Any) -> None:
        self.add({"part": part, "verdict_class": CLASS_NOT_REVIEWED, "subkind": None, "document": self.paper,
                  "text": f"not reviewed: {why}", **extra})  # fmt: skip
        self.part_counts[part]["not_reviewed"] = (
            self.part_counts[part].get("not_reviewed", 0) + 1
        )

    def _failure(self, part: int, exc: BaseException, label: str) -> None:
        """A call that failed (or an answer that was cut off): "Not reviewed" with the error code, never a verdict."""
        if isinstance(exc, FATAL):
            self.halt(exc)
        self.failures += 1
        self.not_reviewed(part, f"{label}: {getattr(exc, 'code', type(exc).__name__)}")

    def check(self, quote: Any, page: Any, doc: str) -> bool:
        ok, _why = verdict.check_paper_quote(quote, page, self.docs.pages(doc))
        return ok

    @staticmethod
    def quote_of(obj: Any) -> dict | None:
        if not isinstance(obj, dict):
            return None
        text = str(obj.get("text") or "").strip()
        n = verdict._page_no(obj.get("page"))
        return {"page": n, "text": text} if n and text else None

    def paper_blocks(self, window: list[int]) -> list[dict]:
        return page_blocks("paper", self.paper, self.pages, window)

    def papers_given(self) -> str:
        if not self.project:
            return "No other papers are given."
        names = "; ".join(f'{d}: "{self.docs.names.get(d, "")}"' for d in self.project)
        return (
            f"Papers given (the only other papers that exist for this review): {names}."
        )

    def fact(self) -> str:
        return core.picture_fact(self.unread)

    def on_unread(self, pages: Iterable[int], flag: Any, *words: Any) -> bool:
        """A claim that something is MISSING on a page whose pictures or formulas were not read as text cannot be checked."""
        return core.claims_missing(flag, *words) and any(
            p in self.unread for p in pages
        )

    # ---- PART 1
    def part1(self) -> None:
        for b in self.not_held:
            name = b["rule_book"]
            self.add({"part": 1, "verdict_class": CLASS_NOT_CHECKED, "subkind": None, "document": self.paper,
                      "text": f"not checked against {name}, rule book not held", "rule_book": name,
                      "why_listed": b.get("why") or "cited by the paper"})  # fmt: skip
        if self.held_not_fit:  # a held book that carries no approved rule for this kind: said, never silently dropped
            names = ", ".join(sorted(self.held_not_fit.values()))
            self.add({"part": 1, "verdict_class": CLASS_NOT_CHECKED, "subkind": None, "document": self.paper,
                      "text": f"this paper cites rule books we hold ({names}); they were not used in this general review: "
                      "none of their approved rules is for this kind of paper",
                      "held_rule_books": sorted(self.held_not_fit.values())})  # fmt: skip
        if self.held_fit:  # a held book that DOES carry approved rules of this kind: the mode still runs, and says so
            self.add({"part": 1, "verdict_class": CLASS_NOT_CHECKED, "subkind": None, "document": self.paper,
                      "text": core.HELD_FIT_LINE, "held_rule_books": sorted(self.held_fit.values())})  # fmt: skip
        self.part_counts[1] = {
            "not_held": len(self.not_held),
            "held_not_used": len(self.held_not_fit),
            "held_fit_not_used": len(self.held_fit),
        }

    # ---- PART 2
    def p2_question(self, batch: list[dict]) -> str:
        qs = [{"item_id": i["item_id"], "question": i["question"]} for i in batch]
        return (
            json.dumps({"checklist": qs}, ensure_ascii=False)
            + "\n\n"
            + prompts.P2_SHAPE
        )

    def _p2_collect(self) -> tuple[dict[str, dict], dict[str, str]]:
        found: dict[str, dict] = {}
        failed: dict[str, str] = {}
        windows = core.window_pages(self.pages, self.window_tokens)
        batches = [
            self.items[i : i + MAX_BATCH_P2]
            for i in range(0, len(self.items), MAX_BATCH_P2)
        ]
        for w, window in enumerate(windows):
            for b, batch in enumerate(batches):
                key = f"p2-w{w}-b{b}-{_key(self.lead_model, *[i['item_id'] for i in batch])}"
                try:
                    rec = self.ask(key, self.lead_model, parts_of(prompts.P2_SYSTEM, self.paper_blocks(window), self.p2_question(batch)),
                                   min(MAX_TOKENS_CAP, TOKENS_BASE_P2 + TOKENS_PER_ITEM_P2 * len(batch)), "lead",
                                   lambda t: isinstance(self.json_of(t), dict))  # fmt: skip
                except agent_claude.AgentClaudeError as exc:
                    if isinstance(exc, FATAL):
                        self.halt(exc)
                    self.failures += 1
                    for i in batch:
                        failed[i["item_id"]] = f"no answer from the AI: {exc.code}"
                    continue
                self._p2_take(rec, batch, found, failed)
        return found, failed

    def _p2_take(
        self, rec: Mapping, batch: list[dict], found: dict, failed: dict
    ) -> None:
        got = self.json_of(rec["text"])
        answers = {
            str(a.get("item_id")): a
            for a in (got or {}).get("answers") or []
            if isinstance(a, dict)
        }
        for item in batch:
            a = answers.get(item["item_id"])
            if a is None:
                failed.setdefault(item["item_id"], "no answer for the item")
                continue
            failed.pop(item["item_id"], None)
            status = str(a.get("status") or "").strip().lower()
            status = status if status in P2_STATUSES else "unclear"
            verified = status in ("present", "partial") and self.check(
                a.get("paper_quote"), a.get("paper_page"), self.paper
            )
            prev = found.get(item["item_id"])
            if prev is None or (verified and not prev["verified"]):
                found[item["item_id"]] = {
                    "status": status,
                    "verified": verified,
                    "a": a,
                }

    def _p2_line(self, item: Mapping, f: Mapping) -> bool:
        """One checklist line for an answered item. True when the item is covered (present, a verified quote, no concern)."""
        a, topic = f["a"], item["topic"]
        base = {
            "part": 2,
            "document": self.paper,
            "item_id": item["item_id"],
            "checklist_item": item["item_id"],
            "topic": topic,
        }
        quote = {"quote_a": {"document": self.paper, "page": verdict._page_no(a.get("paper_page")), "text": str(a.get("paper_quote") or "").strip()},
                 "quotes_verified_by_code": True} if f["verified"] else {}  # fmt: skip
        note = core.words_cut(a.get("note"), MAX_WORDS_NOTE)
        concern = core.words_cut(a.get("concern"), MAX_WORDS_NOTE)
        status = f["status"]
        if status == "present" and f["verified"] and not concern:
            self.trace(
                {
                    "type": "checklist_present",
                    "item_id": item["item_id"],
                    "page": a.get("paper_page"),
                }
            )
            return True
        if (
            status == "present" and f["verified"]
        ):  # present, and the model sees a problem in it: never lost
            self.add({**base, **quote, "verdict_class": CLASS_NOTE, "subkind": core.SUB_CONCERN,
                      "text": f"checklist: {topic}: covered, but {concern}"})  # fmt: skip
            return False
        if (
            status == "present"
        ):  # said present, the quote did not verify: never a claim, an open question
            text = f"checklist: {topic}: the AI said it is covered but its quote was not verified by code; the engineer to look"
            reason = "quote not verified"
        elif status == "partial":
            text = f"checklist: {topic}: partly covered: {note or 'what is missing was not said'}"
            reason = "partly covered"
        elif (
            status == "absent" and self.unread
        ):  # the place to look may be a page of pictures: never "not found"
            text = f"checklist: {topic}: could not be checked: {core.unread_words(self.unread)}"
            reason = "pictures not read"
        elif status == "absent":
            text = f"checklist: {topic}: not found in the paper; silence is a Query, not a failure"
            reason = "not found"
        else:
            text = (
                f"checklist: {topic}: the AI could not tell whether the paper covers it"
                + (f": {note}" if note else "")
            )
            reason = "unclear"
        self.add(
            {
                **base,
                **quote,
                "verdict_class": CLASS_QUERY,
                "subkind": core.SUB_CHECKLIST,
                "text": text,
                "reason": reason,
            }
        )
        return False

    def part2(self) -> None:
        if not self.items:
            self.add({"part": 2, "verdict_class": CLASS_NOT_REVIEWED, "subkind": None, "document": self.paper,
                      "text": core.NO_CHECKLIST})  # fmt: skip
            self.part_counts[2] = {
                "asked": 0,
                "note": core.NO_CHECKLIST,
                **self.items_info,
            }
            return
        found, failed = self._p2_collect()
        present = 0
        for item in self.items:
            f = found.get(item["item_id"])
            if f is None:
                self.not_reviewed(
                    2,
                    f"checklist {item['topic']}: {failed.get(item['item_id'], 'no answer')}",
                    item_id=item["item_id"],
                )
            elif self._p2_line(item, f):
                present += 1
        self.part_counts[2] = {
            "asked": len(self.items),
            "covered_with_verified_quote": present,
            "lines": sum(1 for ln in self.lines if ln["part"] == 2),
            **self.items_info,
        }

    # ---- all parts
    def run_all(self) -> None:
        self.part1()
        self.part2()
        self.part3()
        self.part4()
        known = [
            ln["text"]
            for ln in self.lines
            if ln["part"] in (2, 3, 4)
            and ln["verdict_class"] in (CLASS_NOTE, CLASS_QUERY)
        ]
        self.part5(known)
