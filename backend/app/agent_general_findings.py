"""Parts 3, 4 and 5 of the general review, and the second model (#1690, #781): the findings.

    3  the paper against ITSELF: code verifies every quote word for word on its page; a second model of ANOTHER family keeps or
       drops each survivor; figures are "differ: by code" only under the strict rule of `agent_general_review.figures_label`
    4  the paper against the PROJECT PAPERS the request named (never chosen silently); silence is a Query
    5  at most 10 AI engineering comments per run, each tied to a verified quote

A mixin of `agent_general_parts.GeneralRun` (it uses the run's `ask`, `add`, `check`, `dropped` and the runner). A finding whose
quote code cannot find is thrown away and counted by reason (never text); a second model that is not of another family than the
lead, or that errs, or gives no decision, never lets a finding be shown; a claim that something is MISSING on a page whose
pictures or formulas were not read as text is a Query, never a note.
"""

from __future__ import annotations

import concurrent.futures
import contextvars
import hashlib
import json
import threading
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from . import agent_claude, agent_run_second
from . import agent_general_prompts as prompts
from . import agent_general_review as core
from .agent_general_review import CLASS_NOT_REVIEWED, CLASS_NOTE, CLASS_QUERY
from .agent_review_request import FATAL
from .reader_api import _fold

GROUP_TOKENS = 8_000  # small project papers are asked together up to this size
MAX_FINDINGS_P3 = 30  # per window: findings beyond it are counted, never reviewed
MAX_FINDINGS_P4 = 15  # per call
MAX_COMMENTS_P5 = 10  # per RUN
MAX_WORDS_WHAT = 25
MAX_WORDS_NOTE = 40
MAX_TOKENS_P3, MAX_TOKENS_P4, MAX_TOKENS_P5, MAX_TOKENS_REVIEW = 6000, 4000, 3000, 1500

KINDS_P3 = ("disagreement", "broken_reference", "open_action", "count_mismatch")
SUB_OF_KIND = {
    "disagreement": core.SUB_SELF,
    "broken_reference": core.SUB_REF,
    "open_action": core.SUB_OPEN,
    "count_mismatch": core.SUB_COUNT,
}
SEVERITIES = ("low", "medium", "high")
WHOLE_PAPER_REVIEW = (
    "broken_reference",
    "open_action",
    "silent",
)  # absence claims need the paper, not two pages


def _key(*bits: Any) -> str:
    return hashlib.sha256("|".join(str(b) for b in bits).encode("utf-8")).hexdigest()[
        :16
    ]


def page_blocks(
    tag: str,
    doc: str,
    pages: Mapping[int, str],
    numbers: Iterable[int],
    cache: bool = True,
) -> list[dict]:
    blocks = [
        {
            "type": "text",
            "text": f'<{tag} document="{doc}" page="{n}">\n{pages[n]}\n</{tag}>',
        }
        for n in numbers
        if (pages.get(n) or "").strip()
    ]
    if blocks and cache:
        blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}
    return blocks


def parts_of(system: str, blocks: list[dict], question: str) -> dict:
    return {
        "system": [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [
            {"role": "user", "content": [*blocks, {"type": "text", "text": question}]}
        ],
    }


class Dropped:
    """Counts only: part -> reason -> n. Never text."""

    def __init__(self) -> None:
        self.n: dict[int, Counter] = {p: Counter() for p in core.PARTS}
        self._lock = threading.Lock()

    def add(self, part: int, reason: str, n: int = 1) -> None:
        with self._lock:
            self.n[part][reason] += n

    def as_json(self) -> dict:
        return {str(p): dict(sorted(c.items())) for p, c in self.n.items() if c}


class FindingsMixin:
    """Parts 3 to 5 and the second model; `self` is a GeneralRun."""

    # ---- the second model
    def review(
        self,
        part: int,
        rkey: str,
        finding_text: str,
        doc_pages: list[tuple[str, str, dict[int, str], list[int]]],
        whole: bool,
        window: list[int] | None,
    ) -> tuple[bool, str, bool | None]:
        """(keep, reason, quotes relate). keep only on an answer 'keep' from a model of another family than the lead."""
        blocks: list[dict] = []
        if whole and window is not None:
            blocks += page_blocks("paper", self.paper, self.pages, window)
        for tag, doc, pages, numbers in doc_pages:
            if not (whole and doc == self.paper):
                blocks += page_blocks(tag, doc, pages, numbers, cache=False)
        question = (
            finding_text
            + "\n\n"
            + '{"decision": "keep | drop", "reason": "...", "quotes_relate": "yes | no"}'
        )
        try:
            rec = self.ask(f"p{part}-review-{_key(self.second_model, rkey)}", self.second_model,
                           parts_of(prompts.REVIEW_SYSTEM, blocks, question), MAX_TOKENS_REVIEW, "second",
                           lambda t: isinstance(self.json_of(t), dict))  # fmt: skip
        except agent_claude.AgentClaudeError as exc:
            if isinstance(exc, FATAL):
                self.halt(exc)
            self.dropped.add(part, "second model error")
            return False, f"second model error: {exc.code}", None
        got = self.json_of(rec["text"]) or {}
        if not agent_run_second.models_differ(
            sorted(self.lead_models), rec.get("model")
        ):
            self.dropped.add(part, "second model unknown or not a different family")
            return False, "second model unknown or not a different family", None
        decision = str(got.get("decision") or "").strip().lower()
        if decision != "keep":
            self.dropped.add(
                part,
                "second model dropped"
                if decision == "drop"
                else "second model gave no decision",
            )
            return False, str(got.get("reason") or decision or "no decision"), None
        relate = (
            str(got.get("quotes_relate") or "").strip().lower() == "yes"
        )  # a missing answer is "not related": the stricter side
        return True, str(got.get("reason") or ""), relate

    def review_many(self, jobs: list[Callable[[], Any]]) -> list[Any]:
        if self.concurrency == 1 or len(jobs) < 2:
            return [j() for j in jobs]
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.concurrency
        ) as pool:
            futs = [pool.submit(contextvars.copy_context().run, j) for j in jobs]
            return [f.result() for f in futs]

    # ---- PART 3
    def _p3_collect(self) -> tuple[list[dict], int]:
        windows = self.windows()
        seen: set[tuple[str, str]] = set()
        survivors: list[dict] = []
        for w, window in enumerate(windows):
            q = (
                self.papers_given()
                + ("\n" + self.fact() if self.fact() else "")
                + "\n\n"
                + prompts.P3_SHAPE
            )
            try:
                rec = self.ask(f"p3-w{w}-{_key(self.lead_model, window[0], window[-1], self.fact())}", self.lead_model,
                               parts_of(prompts.P3_SYSTEM, self.paper_blocks(window), q), MAX_TOKENS_P3, "lead",
                               lambda t: isinstance(self.json_of(t), dict) and isinstance(self.json_of(t).get("findings"), list))  # fmt: skip
            except agent_claude.AgentClaudeError as exc:
                self._failure(3, exc, f"paper against itself, window {w + 1}")
                continue
            got = self.json_of(rec["text"])
            if not isinstance(got, dict) or not isinstance(got.get("findings"), list):
                self._failure(
                    3,
                    agent_claude.AgentBadReply("not_json"),
                    f"paper against itself, window {w + 1}",
                )
                continue
            self.read_pages[3].update(window)
            raw = got["findings"]
            self.dropped.add(
                3,
                "over the limit of findings per window",
                max(0, len(raw) - MAX_FINDINGS_P3),
            )
            for f in raw[:MAX_FINDINGS_P3]:
                s = self.verify_p3(f)
                if s is None:
                    continue
                dedupe = (
                    _fold(s["quote_a"]["text"]),
                    _fold((s["quote_b"] or {}).get("text") or ""),
                )
                if dedupe in seen or (dedupe[1], dedupe[0]) in seen:
                    self.dropped.add(3, "duplicate")
                    continue
                seen.add(dedupe)
                s["window"] = window
                survivors.append(s)
        return survivors, len(windows)

    def part3(self) -> None:
        survivors, n_windows = self._p3_collect()
        self.part3_finish(survivors, n_windows)

    def second_reader_missing(self, part: int, survivors: list) -> bool:
        """On the local engine with no usable second reader: nothing with a verified quote may be shown on one reader's word. Said
        once, with the count; True when the candidates were set aside."""
        if self.local is None or not survivors or self.local.second_ready()[0]:
            return False
        self.dropped.add(part, "second reader not available", len(survivors))
        what = "the AI engineering comments were not made" if part == 5 else f"{len(survivors)} finding(s) with a verified quote were not shown"
        self.add({"part": part, "verdict_class": CLASS_NOT_REVIEWED, "subkind": None, "document": self.paper,
                  "text": f"{what}: {self.local.second_ready()[1]}, and one AI reader alone is never enough"})  # fmt: skip
        return True

    def part3_finish(self, survivors: list[dict], n_windows: int) -> None:
        self.part_counts[3] = {
            "windows": n_windows,
            "candidates_verified": len(survivors),
        }
        if self.second_reader_missing(3, survivors):
            return
        results = self.review_many([self.review_job_p3(s) for s in survivors])
        kept = 0
        for s, (keep, reason, relate) in zip(survivors, results, strict=True):
            if not keep:
                continue
            if (
                relate is False and s["quote_b"]
            ):  # the second model kept it but said the two quotes are not about one thing
                self.dropped.add(3, "second model: the two quotes do not relate")
                continue
            kept += 1
            qa, qb = s["quote_a"], s["quote_b"]
            line = {"part": 3, "verdict_class": CLASS_NOTE, "subkind": SUB_OF_KIND[s["kind"]], "document": self.paper,
                    "text": s["what"], "severity_models_opinion": s["severity"], "quote_a": {"document": self.paper, **qa},
                    "quote_b": {"document": self.paper, **qb} if qb else None, "quotes_verified_by_code": True,
                    "figures": core.figures_label(s["kind"], qa["text"], qb["text"] if qb else None),
                    "second_model_reason": reason, "second_model": sorted(self.second_models)}  # fmt: skip
            if self.on_unread(
                [qa["page"], *([qb["page"]] if qb else [])],
                s["claims_missing"],
                s["what"],
            ):
                line = {**line, "verdict_class": CLASS_QUERY, "subkind": core.SUB_UNREAD, "figures": None,
                        "text": f"{core.UNREAD_QUERY} ({s['what']})"}  # fmt: skip
            self.add(line)
        self.part_counts[3]["shown"] = kept

    def verify_p3(self, f: Any) -> dict | None:
        if not isinstance(f, dict) or f.get("kind") not in KINDS_P3:
            self.dropped.add(3, "malformed finding")
            return None
        qa, qb = self.quote_of(f.get("quote_a")), self.quote_of(f.get("quote_b"))
        two = f["kind"] in ("disagreement", "count_mismatch")
        if qa is None or (two and qb is None):
            self.dropped.add(3, "malformed finding")
            return None
        if not two:
            qb = None  # quote_b is null for these kinds, whatever the model put there
        if not self.check(qa["text"], qa["page"], self.paper) or (
            qb and not self.check(qb["text"], qb["page"], self.paper)
        ):
            self.dropped.add(3, "quote not verified")
            return None
        if qb and qa["page"] == qb["page"] and _fold(qa["text"]) == _fold(qb["text"]):
            self.dropped.add(3, "the same quote twice")
            return None
        sev = str(f.get("severity") or "").strip().lower()
        what = core.words_cut(f.get("what"), MAX_WORDS_WHAT)
        return {"kind": f["kind"], "quote_a": qa, "quote_b": qb, "what": what, "claims_missing": core.claims_missing(f.get("claims_missing"), what),
                "severity": sev if sev in SEVERITIES else "not given"}  # fmt: skip

    def review_job_p3(self, s: dict) -> Callable[[], tuple[bool, str, bool | None]]:
        def job() -> tuple[bool, str, bool | None]:
            qa, qb = s["quote_a"], s["quote_b"]
            numbers = sorted({qa["page"], *([qb["page"]] if qb else [])})
            whole = s["kind"] in WHOLE_PAPER_REVIEW
            text = json.dumps(
                {
                    "finding": {
                        "kind": s["kind"],
                        "what": s["what"],
                        "quote_a": qa,
                        "quote_b": qb,
                    }
                },
                ensure_ascii=False,
            )
            return self.review(3, _key(s["kind"], qa["page"], qa["text"], qb and qb["text"]), text,
                               [("paper", self.paper, self.pages, numbers)], whole, s["window"] if whole else None)  # fmt: skip

        return job

    # ---- PART 4
    def groups_p4(self) -> list[list[str]]:
        groups: list[list[str]] = []
        cur: list[str] = []
        used = 0
        for d in sorted(self.project):
            cost = sum(core.tokens_of(t) + 20 for t in self.docs.pages(d).values())
            if cur and used + cost > self.group_tokens:
                groups.append(cur)
                cur, used = [], 0
            cur.append(d)
            used += cost
        if cur:
            groups.append(cur)
        return groups

    def _p4_collect(self) -> tuple[list[dict], int]:
        windows = self.windows()
        survivors: list[dict] = []
        seen: set[tuple] = set()
        calls = 0
        for g, group in enumerate(self.groups_p4()):
            doc_blocks: list[dict] = []
            for d in group:
                doc_blocks += page_blocks(
                    "project_document",
                    d,
                    self.docs.pages(d),
                    sorted(self.docs.pages(d)),
                    cache=False,
                )
            for w, window in enumerate(windows):
                calls += 1
                q = (
                    f"Project papers in this call: {', '.join(group)}.\n\n"
                    + prompts.P4_SHAPE
                )
                try:
                    rec = self.ask(f"p4-g{g}-w{w}-{_key(self.lead_model, *group, window[0], window[-1])}", self.lead_model,
                                   parts_of(prompts.P4_SYSTEM, [*self.paper_blocks(window), *doc_blocks], q), MAX_TOKENS_P4, "lead",
                                   lambda t: isinstance(self.json_of(t), dict) and isinstance(self.json_of(t).get("findings"), list))  # fmt: skip
                except agent_claude.AgentClaudeError as exc:
                    self._failure(
                        4, exc, f"paper against project papers, group {g + 1}"
                    )
                    continue
                got = self.json_of(rec["text"])
                if not isinstance(got, dict) or not isinstance(
                    got.get("findings"), list
                ):
                    self._failure(
                        4,
                        agent_claude.AgentBadReply("not_json"),
                        f"paper against project papers, group {g + 1}",
                    )
                    continue
                raw = got["findings"]
                self.dropped.add(
                    4,
                    "over the limit of findings per call",
                    max(0, len(raw) - MAX_FINDINGS_P4),
                )
                for f in raw[:MAX_FINDINGS_P4]:
                    s = self.verify_p4(f, group)
                    if s is None:
                        continue
                    dedupe = (
                        s["document"],
                        s["kind"],
                        _fold(s["quote_other"]["text"]),
                        _fold((s["quote_paper"] or {}).get("text") or ""),
                    )
                    if dedupe in seen:
                        self.dropped.add(4, "duplicate")
                        continue
                    seen.add(dedupe)
                    s["window"] = window
                    survivors.append(s)
        return survivors, calls

    def _p4_line(self, s: Mapping, reason: str, relate: bool | None) -> None:
        qp, qo, d = s["quote_paper"], s["quote_other"], s["document"]
        base = {"part": 4, "document": self.paper, "other_document": d, "quotes_verified_by_code": True,
                "quote_paper": {"document": self.paper, **qp} if qp else None, "quote_other": {"document": d, **qo},
                "second_model_reason": reason, "second_model": sorted(self.second_models)}  # fmt: skip
        if s["kind"] == "silent":  # silence is a Query, never "not met"
            text = f"the paper is silent on this requirement of {d}: {s['what']}"
            if self.unread:  # the place to look may be a page of pictures: not "silent"
                text = f"could not be checked: {core.unread_words(self.unread)}; the requirement of {d} may be met there: {s['what']}"
            self.add(
                {
                    **base,
                    "verdict_class": CLASS_QUERY,
                    "subkind": core.SUB_SILENT,
                    "text": text,
                }
            )
        elif (
            relate is False
        ):  # kept, but the second model says the two quotes are not about one thing: never "disagrees with"
            self.add({**base, "quote_other": None, "second_model_reason": None, "verdict_class": CLASS_NOTE,
                      "subkind": core.SUB_ENGINEERING,
                      "text": f"a possible conflict with {d} was raised, but the two quotes do not relate; the paper quote is shown for the engineer to look"})  # fmt: skip
        else:
            self.add(
                {
                    **base,
                    "verdict_class": CLASS_NOTE,
                    "subkind": core.SUB_DISAGREES.format(document=d),
                    "text": s["what"],
                }
            )

    def part4(self) -> None:
        if not self.project:
            self.add({"part": 4, "verdict_class": CLASS_NOT_REVIEWED, "subkind": None, "document": self.paper,
                      "text": core.NO_PROJECT_PAPER})  # fmt: skip
            self.part_counts[4] = {"note": core.NO_PROJECT_PAPER, "project_papers": 0}
            return
        survivors, calls = self._p4_collect()
        self.part4_finish(survivors, calls)

    def part4_finish(self, survivors: list[dict], calls: int) -> None:
        if not self.project:
            return
        self.part_counts[4] = {"calls": calls, "groups": len(self.groups_p4()), "candidates_verified": len(survivors),
                               "project_papers": len(self.project)}  # fmt: skip
        if self.second_reader_missing(4, survivors):
            return
        results = self.review_many([self.review_job_p4(s) for s in survivors])
        kept = 0
        for s, (keep, reason, relate) in zip(survivors, results, strict=True):
            if keep:
                kept += 1
                self._p4_line(s, reason, relate)
        self.part_counts[4]["shown"] = kept

    def verify_p4(self, f: Any, group: list[str]) -> dict | None:
        if (
            not isinstance(f, dict)
            or f.get("kind") not in ("contradicts", "silent")
            or str(f.get("document")) not in group
        ):
            self.dropped.add(4, "malformed finding")
            return None
        d = str(f["document"])
        qo, qp = (
            self.quote_of(f.get("quote_other")),
            self.quote_of(f.get("quote_paper")),
        )
        if qo is None or (f["kind"] == "contradicts" and qp is None):
            self.dropped.add(4, "malformed finding")
            return None
        if not self.check(qo["text"], qo["page"], d) or (
            qp and not self.check(qp["text"], qp["page"], self.paper)
        ):
            self.dropped.add(4, "quote not verified")
            return None
        if f["kind"] == "silent":
            qp = None  # silence has no paper quote
        return {"kind": f["kind"], "document": d, "quote_paper": qp, "quote_other": qo,
                "what": core.words_cut(f.get("what"), MAX_WORDS_WHAT)}  # fmt: skip

    def review_job_p4(self, s: dict) -> Callable[[], tuple[bool, str, bool | None]]:
        def job() -> tuple[bool, str, bool | None]:
            qp, qo, d = s["quote_paper"], s["quote_other"], s["document"]
            whole = s["kind"] == "silent"
            pairs = [("project_document", d, self.docs.pages(d), [qo["page"]])]
            if qp:
                pairs.append(("paper", self.paper, self.pages, [qp["page"]]))
            text = json.dumps({"finding": {"kind": s["kind"], "what": s["what"], "quote_paper": qp, "quote_other": qo, "document": d}},
                              ensure_ascii=False)  # fmt: skip
            return self.review(
                4,
                _key(d, s["kind"], qo["text"], qp and qp["text"]),
                text,
                pairs,
                whole,
                s["window"] if whole else None,
            )

        return job

    # ---- PART 5
    def _p5_line(self, c: Any, seen: set[str]) -> bool:
        """One comment into a line; False (and counted) when it is malformed, unverified or a repeat."""
        q = self.quote_of(c.get("quote")) if isinstance(c, dict) else None
        text = (
            core.words_cut(c.get("comment"), MAX_WORDS_NOTE)
            if isinstance(c, dict)
            else ""
        )
        if q is None or not text:
            self.dropped.add(5, "malformed comment")
            return False
        if not self.check(q["text"], q["page"], self.paper):
            self.dropped.add(5, "quote not verified")
            return False
        if _fold(q["text"]) in seen:
            self.dropped.add(5, "duplicate")
            return False
        seen.add(_fold(q["text"]))
        line = {"part": 5, "verdict_class": CLASS_NOTE, "subkind": core.SUB_ENGINEERING, "document": self.paper, "text": text,
                "quote_a": {"document": self.paper, **q}, "quote_b": None, "quotes_verified_by_code": True}  # fmt: skip
        if self.on_unread([q["page"]], c.get("claims_missing"), text):
            line = {
                **line,
                "verdict_class": CLASS_QUERY,
                "subkind": core.SUB_UNREAD,
                "text": f"{core.UNREAD_QUERY} ({text})",
            }
        self.add(line)
        return True

    def part5(self, known: list[str]) -> None:
        if self.second_reader_missing(5, [None]):  # comments come from one reader: with no usable second reader none is made
            self.part_counts[5] = {"windows": 0, "shown": 0, "second_reader": "not available"}
            return
        windows = self.windows()
        shown = 0
        seen: set[str] = set()
        for w, window in enumerate(windows):
            q = ("Known findings (do not repeat): " + json.dumps(known[:60], ensure_ascii=False)
                 + ("\n" + self.fact() if self.fact() else "") + "\n\n" + prompts.P5_SHAPE)  # fmt: skip
            try:
                rec = self.ask(f"p5-w{w}-{_key(self.lead_model, window[0], window[-1], self.fact(), *known)}", self.lead_model,
                               parts_of(prompts.P5_SYSTEM, self.paper_blocks(window), q), MAX_TOKENS_P5, "lead",
                               lambda t: isinstance(self.json_of(t), dict) and isinstance(self.json_of(t).get("comments"), list))  # fmt: skip
            except agent_claude.AgentClaudeError as exc:
                self._failure(5, exc, f"AI engineering comments, window {w + 1}")
                continue
            got = self.json_of(rec["text"])
            if not isinstance(got, dict) or not isinstance(got.get("comments"), list):
                self._failure(
                    5,
                    agent_claude.AgentBadReply("not_json"),
                    f"AI engineering comments, window {w + 1}",
                )
                continue
            self.read_pages[5].update(window)
            for c in got["comments"]:
                if shown >= MAX_COMMENTS_P5:  # at most 10 per RUN, not per window
                    self.dropped.add(5, "over the limit of comments")
                elif self._p5_line(c, seen):
                    shown += 1
        self.part_counts[5] = {"windows": len(windows), "shown": shown}
