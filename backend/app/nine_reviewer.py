"""Role 4, the reviewer: reads real chapters of the rule books against the paper, with the fact sheet and the project context, and
writes ONE finding per issue (nine-role reviewer, builder B4).

The model call leaves ONLY through the one call seam of the nine-role review (`nine_call.ask`, builder B1): this module builds the BLOCK
list (the same list is the request, the document declaration and the role record) and reads the answer. What a call SENT is read from
`Answer.reads` (the blocks the gate kept), never from the blocks offered: a block the gate held is in `Answer.not_sent` and a quote
from a page that was not sent is unverified. It opens no socket, names no
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

import dataclasses
import hashlib
import json
import re
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from . import nine_call, nine_findings
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
    "words, with clause_page (the page of the book the quote stands on), the clause number as the chapter prints it and book_id as the chapter block names it). The quotes must be from the "
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
    'paper", "paper_page": 1, "paper_quote": "...", "book_id": "...", "clause": "4.1.2", "clause_page": 12, "clause_quote": "...", "paper_figure": "...", '
    '"clause_figure": "...", "condition_quote": "...", "condition_page": 1, "verdict": "met | not_met | not_stated | not_applicable | '
    'cannot_tell", "reasoning": "...", "comment": "...", "fact_ids": ["f:1:2"]}]}. Leave a key empty when you have nothing for it.'
)
PROMPT_VERSION = (
    "nine-reviewer-" + hashlib.sha256((SYSTEM + ANSWER_SHAPE).encode()).hexdigest()[:10]
)
#: the reviewer's words are REGISTERED templates (B1's seam sends no free text): no parameter, so no document word can enter them
SYSTEM_ID = nine_call.template(
    "nine_reviewer_system", SYSTEM.replace("{", "{{").replace("}", "}}")
)
QUESTION_ID = nine_call.template(
    "nine_reviewer_question", ANSWER_SHAPE.replace("{", "{{").replace("}", "}}")
)  # the seam renders with str.format: braces doubled


# ---------------------------------------------------------------- the seam (B1) and the blocks


@dataclass(frozen=True)
class ChapterText:
    """One chapter (or one part of a long one) of a rule book, NAMED not copied: the book, its pages, how many characters it holds and, for a
    part of a long chapter, the character range into the joined text of those pages. The seam loads the stored text itself, so the words
    that go out are the stored words and nothing cleaned. Built by the librarian (role 3); this module only packs them."""

    book_id: str
    chapter_id: str
    part_no: int
    part_of: int
    pages: tuple[int, ...]
    chars: int
    char_from: int | None = None
    char_to: int | None = None


@dataclass(frozen=True)
class ContextPart:
    """One part of the project context, derived from named SOURCES (document ids) and carrying rows of short tokens only (B1's derived
    block). Put only tokens that really come from `sources` into `items`: the checker verifies afterwards."""

    name: str
    sources: tuple[str, ...]
    items: tuple[tuple[str, ...], ...]
    kinds: tuple[str, ...] | None = (
        None  # one declared kind per column (B1: id, code, key, number, clause, standard, enum, unit, source)
    )


FACT_SHEET = "fact_sheet"


def estimate_tokens(chars: int) -> int:
    return -(-int(chars) // CHARS_PER_TOKEN)


def group_chapters(
    chapters: Iterable[ChapterText], limit: int = GROUP_TOKENS
) -> list[list[ChapterText]]:
    """Pack chapters into calls in their reading order (the librarian's rank): a call holds at most `limit` tokens of chapter text; one part
    that is alone over the limit still goes alone (the chapter cutter keeps parts under it)."""
    groups: list[list[ChapterText]] = []
    size = 0
    for c in chapters:
        need = estimate_tokens(c.chars)
        if not groups or size + need > limit:
            groups.append([])
            size = 0
        groups[-1].append(c)
        size += need
    return groups


def token(text: object) -> str:
    """One short one-line token for a derived row (the seam refuses anything longer or with a line break)."""
    one = " ".join(str(text or "").split())
    return (
        one[: nine_call.MAX_CELL_CHARS] or "-"
    )  # the seam's own cell cap; a typed column is checked there, never cut to fit


def _rows(items: Iterable[Iterable[object]]) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(token(c) for c in row) for row in items if row)


def prefix_blocks(
    paper_id: str,
    paper_pages: Sequence[int],
    digest_items: Iterable[Iterable[object]] = (),
    context_parts: Sequence[ContextPart] = (),
    digest_kinds: Sequence[str] | None = None,
) -> list[nine_call.Block]:
    """The part every call shares (cached after the first): the paper's pages (NAMED; the seam loads their stored text), the fact-sheet digest
    (a derived block whose only source is the paper) and each part of the project context as its OWN derived block with ITS sources, so the
    one gate sees where every token came from: a part with a held source is dropped whole and named, the rest goes on."""
    blocks = [
        nine_call.Block("paper", paper_id, (int(n),)) for n in sorted(paper_pages)
    ]
    rows = _rows(digest_items)
    if rows:
        blocks.append(
            nine_call.Block(
                "review_record",
                name=FACT_SHEET,
                sources=(paper_id,),
                items=rows,
                kinds=tuple(digest_kinds) if digest_kinds else None,
            )
        )
    for part in context_parts:
        if part.sources and part.items:
            blocks.append(
                nine_call.Block(
                    "review_record",
                    name=part.name,
                    sources=tuple(part.sources),
                    items=_rows(part.items),
                    kinds=tuple(part.kinds) if part.kinds else None,
                )
            )
    if blocks:
        last = blocks[-1]
        blocks[-1] = dataclasses.replace(last, cache=True)  # the shared part ends here
    return blocks


def context_names(prefix: Sequence[nine_call.Block]) -> tuple[str, ...]:
    """The context parts a prefix OFFERS (derived blocks other than the fact sheet)."""
    return tuple(
        b.name
        for b in prefix
        if b.document_kind == nine_call.DERIVED_KIND and b.name != FACT_SHEET
    )


def chapter_blocks(group: Sequence[ChapterText]) -> list[nine_call.Block]:
    return [
        nine_call.Block(
            "rule_book", c.book_id, tuple(c.pages), c.char_from, c.char_to,
            chapter_id=c.chapter_id, part_no=c.part_no, part_of=c.part_of,
        )
        for c in group
    ]  # fmt: skip


def sent_of(
    answer: nine_call.Answer, offered: Sequence[ChapterText] = ()
) -> nine_findings.Sent:
    """What a call really sent, read from the ANSWER (`Answer.reads`: one entry per block the gate kept), never from the blocks that were
    offered. A document the gate held is not in it, so a quote from its pages is unverified. The CHARACTER RANGE is the one the seam really sent
    (`Answer.ranges`, same order as `reads`); only when the answer carries none does it fall back to the range the part was offered with
    (`offered`, matched by book, chapter and part number). A quote outside that range was not sent."""
    paper: set[int] = set()
    books: dict[str, set[int]] = {}
    blocks: dict[str, list[tuple[tuple[int, ...], int | None, int | None]]] = {}
    refs: list[tuple[str, str, int]] = []
    ranges = tuple(answer.ranges or ())
    for i, r in enumerate(answer.reads):
        pages = {
            int(p) for p in r.pages if isinstance(p, int) and not isinstance(p, bool)
        }
        if r.document_kind == "paper":
            paper |= pages
        elif r.document_kind == "rule_book":
            book = str(r.document_id)
            books.setdefault(book, set()).update(pages)
            part = next(
                (
                    c
                    for c in offered
                    if c.book_id == book
                    and c.chapter_id == str(r.chapter_id or "")
                    and c.part_no == int(r.part_no or 1)
                ),
                None,
            )
            sent_range = (
                ranges[i] if i < len(ranges) else None
            )  # the range the seam really sent
            lo, hi = (
                sent_range
                if sent_range
                else (part.char_from if part else None, part.char_to if part else None)
            )
            blocks.setdefault(book, []).append((tuple(sorted(pages)), lo, hi))
            refs.append((book, str(r.chapter_id or ""), int(r.part_no or 1)))
    return nine_findings.Sent(
        answer.call_id, frozenset(paper), {k: frozenset(v) for k, v in books.items()}, answer.model, tuple(dict.fromkeys(refs)),
        {k: tuple(v) for k, v in blocks.items()},
    )  # fmt: skip


def context_sent(answer: nine_call.Answer) -> set[str]:
    """The names of the context parts a call really sent (a derived block is read once per source: its name is the read's chapter id)."""
    return {
        str(r.chapter_id)
        for r in answer.reads
        if r.document_kind == nine_call.DERIVED_KIND
        and r.chapter_id
        and r.chapter_id != FACT_SHEET
    }


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
        raw["clause_page"] = _int(item.get("clause_page"))
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
    """What role 4 returned: every raw finding with what ITS call really sent, and the counts for the record. `ok` False (every call failed,
    nothing was asked, or no finding came back) means role 5 asks every item. Groups not read (failed, not asked, held by the role budget)
    are listed in `unread`: no finding covers their rules, so role 5 asks those items (the run is never weaker than today's)."""

    raw: list[tuple[RawFinding, nine_findings.Sent]] = field(default_factory=list)
    groups: int = 0
    answered: int = 0
    failed: int = 0
    not_asked: int = 0
    usd: float | None = 0.0
    errors: list[str] = field(default_factory=list)
    budget_stopped: bool = False
    not_sent: list[tuple[str, str]] = field(
        default_factory=list
    )  # (document id, code) the gate held, over every call
    unread: list[list[ChapterText]] = field(default_factory=list)
    context_offered: tuple[
        str, ...
    ] = ()  # the context parts the prefix offered (derived blocks with their sources)
    context_dropped: list[str] = field(
        default_factory=list
    )  # parts a call did NOT send (a source the gate held): named in the record
    no_context_available: bool = False  # role 2 found NOTHING to pass (no project document held): zero parts offered is then not a gap

    NO_CONTEXT_NOT_OFFERED = "project context not passed (none offered)"
    NO_CONTEXT_AVAILABLE = "no project context was available"  # role 2 found nothing to pass: that fact is role 2's own row, not a gap here

    @property
    def context_passed(self) -> bool:
        """Context parts were offered and every one of them went (none held by the gate)."""
        return bool(self.context_offered) and not self.context_dropped

    @property
    def ok(self) -> bool:
        return self.answered > 0 and bool(self.raw)

    @property
    def partly(self) -> bool:
        return bool(
            self.failed
            or self.not_asked
            or self.budget_stopped
            or self.not_sent
            or self.context_dropped
        )

    def state(self) -> tuple[str, str | None]:
        """(role state, why) for the record: "ran" when every group was read and every offered context part went; "ran_partly" with the reason when
        some were not read or a context part was held by the gate (named); "not_run" when no call answered."""
        if self.answered == 0:
            why = (
                "role budget reached before any call"
                if self.budget_stopped
                else (
                    "no call answered: " + ", ".join(sorted(set(self.errors)))
                    if self.errors
                    else "nothing was asked"
                )
            )
            return "not_run", why
        not_offered = not self.context_offered and not self.no_context_available
        if self.partly or not_offered:
            parts = []
            if not_offered:
                parts.append(self.NO_CONTEXT_NOT_OFFERED)
            if self.context_dropped:
                parts.append(
                    f"project context not passed ({len(self.context_dropped)} part(s) held: "
                    + ", ".join(self.context_dropped)
                    + ")"
                )
            if self.budget_stopped:
                parts.append("role budget reached")
            if self.failed:
                parts.append(f"{self.failed} call(s) failed")
            if self.not_asked:
                parts.append(f"{self.not_asked} chapter group(s) not asked")
            if self.not_sent:
                parts.append("not sent, held by the gate: " + self.not_sent_words())
            tail = (
                f"; {len(self.unread)} of {self.groups} chapter group(s) not read"
                if self.unread
                else ""
            )
            return "ran_partly", "; ".join(parts) + tail
        return "ran", None

    def not_sent_words(self) -> str:
        """What the gate held back, as `name (code)`, each once: a document id or a derived block's name (`derived:<name>`) and the code that held
        it. Names and codes only, never a word of a document."""
        pairs = dict.fromkeys(f"{name} ({code})" for name, code in self.not_sent)
        shown = list(pairs)[:6]
        return ", ".join(shown) + (
            f" and {len(pairs) - 6} more" if len(pairs) > 6 else ""
        )

    def produced(self) -> dict[str, int | str]:
        """Counts only, for `produced_json` of the record."""
        return {
            "raw_findings": len(self.raw),
            "chapter_groups": self.groups,
            "answered": self.answered,
            "failed": self.failed,
            "not_asked": self.not_asked,
            "unread_groups": len(self.unread),
            "context_parts": len(self.context_offered),
            "context_parts_held": len(self.context_dropped),
            "context_passed": int(self.context_passed),
            **(
                {
                    "blocks_not_sent": len(self.not_sent),
                    "not_sent": self.not_sent_words()[:200],
                }
                if self.not_sent
                else {}
            ),
            **(
                {"context": self.NO_CONTEXT_AVAILABLE}
                if self.no_context_available and not self.context_offered
                else {}
            ),
        }


def review(
    run_id: str,
    prefix: Sequence[nine_call.Block]
    | Callable[[int, Sequence[ChapterText]], Sequence[nine_call.Block]],
    groups: Sequence[Sequence[ChapterText]],
    *,
    ask: Callable[..., nine_call.Answer] = nine_call.ask,
    engine: str | None = None,
    model: str | None = None,
    max_tokens: int = 8000,
    send: Callable | None = None,
    local_send: Callable[[dict], dict] | None = None,
    env: dict | None = None,
    meter: Any = None,
    gate: nine_call.RoleGate | None = None,
    should_stop: Callable[[], bool] = lambda: False,
    concurrency: int = CONCURRENCY,
    no_context_available: bool = False,
) -> ReviewerRun:
    """One call per chapter group through the seam, `concurrency` at a time, each with prefix + that group's blocks. A group is `not_asked`
    when `should_stop()` says so or the role budget was already reached (`Answer.error_code == "role_budget"`: the role ends ran_partly);
    a failed or refused call is counted and its code kept (codes only). What each call SENT is read from its Answer. Results follow the
    group order, so the same inputs give the same findings."""
    # `prefix` is ONE shared list, or a function of (the group's number, the group) when the facts a request needs differ by chapter or the
    # digest is sent in parts (the caller repeats a group once per part)
    prefix_of = prefix if callable(prefix) else (lambda _i, _g: prefix)
    offered = context_names(prefix_of(0, groups[0])) if groups else ()
    run = ReviewerRun(
        groups=len(groups),
        context_offered=offered,
        no_context_available=no_context_available,
    )
    gate = gate or nine_call.RoleGate.for_role(ROLE_NO)
    stop = {"budget": False}

    def one(numbered: tuple[int, Sequence[ChapterText]]) -> nine_call.Answer | None:
        i, group = numbered
        if should_stop() or stop["budget"]:
            return None
        got = ask(
            run_id, ROLE_NO, [*prefix_of(i, group), *chapter_blocks(group)], (QUESTION_ID, {}), engine=engine, system=(SYSTEM_ID, {}), model=model,
            max_tokens=max_tokens, send=send, local_send=local_send, env=env, meter=meter, gate=gate,
        )  # fmt: skip
        if got.error_code == "role_budget":
            stop["budget"] = True
        return got

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        results = list(pool.map(one, enumerate(groups)))
    for group, res in zip(groups, results, strict=True):
        if res is None:
            run.not_asked += 1
            run.unread.append(list(group))
            continue
        run.not_sent.extend(res.not_sent)
        if res.error_code == "role_budget":
            run.budget_stopped = True
            run.not_asked += 1
            run.unread.append(list(group))
            continue
        if res.usd is not None and run.usd is not None:
            run.usd += res.usd
        elif res.usd is None and res.ok:
            run.usd = None  # an answered call whose cost is not known: the sum is not known (never shown as 0)
        parsed = parse_findings(res.text) if res.ok else None
        if parsed is None:
            run.failed += 1
            run.errors.append(res.error_code or "unreadable_reply")
            run.unread.append(list(group))
            continue
        run.answered += 1
        run.context_dropped.extend(
            n
            for n in offered
            if n not in context_sent(res) and n not in run.context_dropped
        )
        sent = sent_of(res, group)
        run.raw.extend((r, sent) for r in parsed)
    return run
