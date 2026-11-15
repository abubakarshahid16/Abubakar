"""Role 4, the reviewer: reads real chapters of the rule books against the paper, with the fact sheet and the project context, and
writes ONE finding per issue (nine-role reviewer, builder B4).

The model call leaves ONLY through the one call seam of the nine-role review (`nine_call.ask`, builder B1): this module builds the BLOCK
list (the same list is the request, the document declaration and the role record) and reads the answer. It opens no socket, names no
model, sends nothing by itself. What it sends is decided before: only chapters of the books on the run's stored list (the reading list,
role 3), the paper, the digest of the fact sheet and the context note.

  prefix  = the paper's pages (text), the fact-sheet digest, the context note   (cached after the first call)
  one call = prefix + ONE chapter group (at most `GROUP_TOKENS` tokens of chapter text; 3 calls at a time)
  answer  = {"findings": [RawFinding, ...]} : one finding per issue, quotes copied character for character

Nothing a model says is trusted: `nine_findings` checks every quote against the stored pages that were SENT in that call, matches the
finding to a stored rule, joins findings of different calls and hands each to today's `Runner.decide`. If every call fails, or the model
finds nothing, `ReviewerRun.ok` is False and role 5 asks every item (today's review): the run is never weaker than today's.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Protocol

from . import nine_findings
from .nine_contract import RawFinding

ROLE_NO = 4
#: Claude: tokens of chapter text one call may carry (estimate: characters / 3, the cap estimator's own ratio)
GROUP_TOKENS = 40_000
CONCURRENCY = 3
MAX_FINDINGS_PER_CALL = 60
MAX_ISSUE_WORDS = 25
CHARS_PER_TOKEN = 3

SYSTEM = (
    "You are a senior engineer who signs the review of a supplier paper. You are given, in this order: the whole paper (page by page), "
    "a digest of the values read from it, a note on the project's own context, and then ONE group of chapters copied from the held "
    "rule books. Read the chapters against the paper like a reviewer: find every place where the paper does not meet a requirement "
    "of these chapters, every requirement of these chapters the paper meets, and every requirement it does not state. "
    "Write ONE finding per issue (never two findings for one issue; never a finding about something the chapters do not say). "
    "For each finding copy, character for character: paper_quote (the paper words, with paper_page) and clause_quote (the chapter "
    "words, with the clause number as the chapter prints it and book_id as the chapter block names it). The quotes must be from the "
    "pages and chapters you were given; code checks every quote against the stored text and a quote it cannot find makes the finding "
    "a question. verdict is one of: met, not_met, not_stated (the requirement asks the paper to state it and it does not), "
    "not_applicable, cannot_tell. When the requirement is a limit, give paper_figure and clause_figure: the exact words holding each "
    "number with its unit, taken from inside your two quotes; code compares the numbers, not you. issue: at most 25 words. "
    "reasoning: at most two plain sentences. comment: one sentence for the contractor, without your reasoning. When the requirement "
    "holds a condition (a service, 'when', 'where', 'if', 'unless'), a met also needs condition_quote and condition_page. "
    "fact_ids: the ids of the digest values you used. Never state confidence. If you find nothing, return an empty list."
)
ANSWER_SHAPE = (
    'Reply with ONE JSON object and nothing else: {"findings": [{"issue": "...", "field_label": "the field name as printed on the '
    'paper", "paper_page": 1, "paper_quote": "...", "book_id": "...", "clause": "4.1.2", "clause_quote": "...", "paper_figure": "...", '
    '"clause_figure": "...", "condition_quote": "...", "condition_page": 1, "verdict": "met | not_met | not_stated | not_applicable | '
    'cannot_tell", "reasoning": "...", "comment": "...", "fact_ids": ["f:1:2"]}]}. Leave a key empty when you have nothing for it.'
)
PROMPT_VERSION = (
    "nine-reviewer-" + hashlib.sha256((SYSTEM + ANSWER_SHAPE).encode()).hexdigest()[:10]
)


# ---------------------------------------------------------------- the seam (B1) and the blocks


@dataclass(frozen=True)
class SeamResult:
    """What the call seam hands back: the model's text (None when the call did not answer), the error code, the model that answered,
    the id of the call in the record, and what the call cost (None = not known)."""

    text: str | None
    error: str | None = None
    model: str | None = None
    call_id: str = ""
    usd: float | None = None


class Seam(Protocol):
    """`nine_call.ask` as this module uses it: the role number, the block list, the question; the system text and the output limit."""

    def __call__(
        self,
        role: int,
        blocks: list[dict],
        question: str,
        *,
        system: str,
        max_tokens: int,
    ) -> SeamResult: ...


@dataclass(frozen=True)
class ChapterText:
    """One chapter (or one part of a long one) of a rule book, exactly as stored (nothing cleaned: a quote is checked against the same
    text). `pages`: the pages of the book it covers. Built by the librarian (role 3); this module only packs them."""

    book_id: str
    chapter_id: str
    part_no: int
    part_of: int
    pages: tuple[int, ...]
    text: str


def estimate_tokens(text: str) -> int:
    return -(-len(text) // CHARS_PER_TOKEN)


def group_chapters(
    chapters: Iterable[ChapterText], limit: int = GROUP_TOKENS
) -> list[list[ChapterText]]:
    """Pack chapters into calls in their reading order (the librarian's rank): a call holds at most `limit` tokens of chapter text; one part
    that is alone over the limit still goes alone (the chapter cutter keeps parts under it)."""
    groups: list[list[ChapterText]] = []
    size = 0
    for c in chapters:
        need = estimate_tokens(c.text)
        if not groups or size + need > limit:
            groups.append([])
            size = 0
        groups[-1].append(c)
        size += need
    return groups


def prefix_blocks(
    paper_id: str,
    paper_pages: Mapping[int, str],
    digest: str,
    context: str,
    run_id: str,
) -> list[dict]:
    """The part every call shares (cached after the first): the paper page by page, then the fact-sheet digest and the context note.
    The digest and the note are the run's own records (`review_record`), not a document."""
    blocks = [
        {
            "document_id": paper_id,
            "document_kind": "paper",
            "pages": [n],
            "chapter_id": None,
            "part": None,
            "part_of": None,
            "text": t,
        }
        for n, t in sorted(paper_pages.items())
        if str(t or "").strip()
    ]
    for label, text in (("fact sheet", digest), ("project context", context)):
        if str(text or "").strip():
            blocks.append(
                {
                    "document_id": run_id,
                    "document_kind": "review_record",
                    "pages": [],
                    "chapter_id": label,
                    "part": None,
                    "part_of": None,
                    "text": text,
                }
            )
    if blocks:
        blocks[-1] = {**blocks[-1], "cache": True}  # the shared part ends here
    return blocks


def chapter_blocks(group: Sequence[ChapterText]) -> list[dict]:
    return [
        {
            "document_id": c.book_id, "document_kind": "rule_book", "pages": list(c.pages), "chapter_id": c.chapter_id,
            "part": c.part_no, "part_of": c.part_of, "text": c.text,
        }
        for c in group
    ]  # fmt: skip


def sent_of(
    call_id: str, blocks: Sequence[Mapping], model: str | None = None
) -> nine_findings.Sent:
    """What a call sent, DERIVED from the block list the request was built from (never from the model's answer)."""
    paper: set[int] = set()
    books: dict[str, set[int]] = {}
    refs: list[tuple[str, str, int]] = []
    for b in blocks:
        pages = {
            int(p)
            for p in b.get("pages") or []
            if isinstance(p, int) and not isinstance(p, bool)
        }
        if b.get("document_kind") == "paper":
            paper |= pages
        elif b.get("document_kind") == "rule_book":
            books.setdefault(str(b.get("document_id")), set()).update(pages)
            refs.append(
                (
                    str(b.get("document_id")),
                    str(b.get("chapter_id") or ""),
                    int(b.get("part") or 1),
                )
            )
    return nine_findings.Sent(
        call_id,
        frozenset(paper),
        {k: frozenset(v) for k, v in books.items()},
        model,
        tuple(dict.fromkeys(refs)),
    )


def question_of(group: Sequence[ChapterText]) -> str:
    """The question of one call: which chapters it holds (ids only), then the answer shape."""
    held = "; ".join(
        f"book {c.book_id} chapter {c.chapter_id} (part {c.part_no} of {c.part_of}, pages {c.pages[0]}-{c.pages[-1]})"
        for c in group
        if c.pages
    )
    return f"Chapters given in this call: {held}.\n\n{ANSWER_SHAPE}"


# ---------------------------------------------------------------- the answer


_JSON = re.compile(r"\{.*\}", re.DOTALL)
_STR_KEYS = (
    "issue", "field_label", "paper_quote", "book_id", "clause", "clause_quote", "paper_figure", "clause_figure", "condition_quote",
    "verdict", "reasoning", "comment",
)  # fmt: skip


def _int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if v >= 1 else None
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip()) or None
    return None


def parse_findings(text: str | None) -> list[RawFinding] | None:
    """The findings of one answer; None when the answer is not a readable object with a `findings` list (the call counts as failed);
    [] when the model found nothing. A finding with no verdict word of the five is dropped; keys are coerced, nothing is invented."""
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        m = _JSON.search(text)
        try:
            data = json.loads(m.group(0)) if m else None
        except ValueError:
            data = None
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        return None
    out: list[RawFinding] = []
    for item in data["findings"][:MAX_FINDINGS_PER_CALL]:
        if not isinstance(item, dict):
            continue
        raw: dict[str, Any] = {k: str(item.get(k) or "").strip() for k in _STR_KEYS}
        raw["issue"] = " ".join(raw["issue"].split()[:MAX_ISSUE_WORDS])
        raw["paper_page"] = _int(item.get("paper_page"))
        raw["condition_page"] = _int(item.get("condition_page"))
        ids = item.get("fact_ids")
        raw["fact_ids"] = (
            [str(x) for x in ids if isinstance(x, str)] if isinstance(ids, list) else []
        )
        if nine_findings.verdict_of(raw) is None:
            continue
        out.append(raw)  # type: ignore[arg-type]
    return out


# ---------------------------------------------------------------- the run of role 4


@dataclass
class ReviewerRun:
    """What role 4 returned: every raw finding with what ITS call sent, and the counts for the record. `ok` False (every call failed, or
    nothing was asked, or no finding came back) means role 5 asks every item."""

    raw: list[tuple[RawFinding, nine_findings.Sent]] = field(default_factory=list)
    groups: int = 0
    answered: int = 0
    failed: int = 0
    not_asked: int = 0
    usd: float | None = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.answered > 0 and bool(self.raw)

    @property
    def partly(self) -> bool:
        return bool(self.failed or self.not_asked)


def review(
    seam: Seam,
    prefix: Sequence[dict],
    groups: Sequence[Sequence[ChapterText]],
    *,
    max_tokens: int = 8000,
    should_stop: Callable[[], bool] = lambda: False,
    concurrency: int = CONCURRENCY,
) -> ReviewerRun:
    """One call per chapter group, `concurrency` at a time, each through the seam with prefix + that group's blocks. A group not asked
    because `should_stop()` says so (a cap, a stop) is counted `not_asked`; a failed call is counted and its error code kept (codes only).
    The result order follows the groups, so the same inputs give the same findings."""
    run = ReviewerRun(groups=len(groups))

    def one(group: Sequence[ChapterText]) -> tuple[SeamResult | None, list[dict]]:
        if should_stop():
            return None, []
        blocks = [*prefix, *chapter_blocks(group)]
        return seam(
            ROLE_NO, blocks, question_of(group), system=SYSTEM, max_tokens=max_tokens
        ), blocks

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        results = list(pool.map(one, groups))
    for res, blocks in results:
        if res is None:
            run.not_asked += 1
            continue
        if res.usd is not None and run.usd is not None:
            run.usd += res.usd
        elif res.usd is None:
            run.usd = None  # one call's cost is not known: the sum is not known (never shown as 0)
        parsed = parse_findings(res.text) if res.error is None else None
        if parsed is None:
            run.failed += 1
            run.errors.append(res.error or "unreadable_reply")
            continue
        run.answered += 1
        sent = sent_of(res.call_id, blocks, res.model)
        run.raw.extend((r, sent) for r in parsed)
    return run
