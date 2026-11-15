"""Role 3 of the nine-role reviewer: the Librarian (SPEC A.2 row 3, C, F). It decides which rule books AND which chapters of them the
reviewer reads, in what order, and what is "chosen, not read" and why. Code first: every candidate chapter is found and ranked by code
(`plan_reading`, pure); ONE optional model call sees only chapter TITLES and may ADD chapters, never remove a code choice
(`titles_for_model`, `apply_model_choice`; the call itself goes through the one seam, supplied by the job as `ask`).

Inputs are plain values so the plan is testable without a database: the books and their cut chapters (`nine_chapters.CutBook`), the
rules chosen for this paper in their rank order (rule choice v2: `agent_review_rule_choice`), the clauses the paper and the project
context name, the equipment's words, the list shown before the start, the starter's access, and the engine's reading budget.

Rules the output keeps:
  * a book outside the starter's access is COUNTED (`books_wanted_not_listed`), never named; a book inside the access but not on the
    shown list is listed with `on_shown_list=False` and every chapter "not read: not on the list shown before the start";
  * every candidate ends as chosen or not read with a reason; nothing is dropped silently;
  * a chapter id the model returns that code did not supply is ignored;
  * no book, layout or word list: the only lists are data files (`governing_standards.json`) and the equipment's own words."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import nine_call
from .nine_chapters import (
    CLAUDE_BOOK_TOKENS,
    CLAUDE_REVIEW_TOKENS,
    LOCAL_REVIEW_TOKENS,
    CutBook,
    tokens_of,
)
from .nine_contract import BookChoice, Chapter, ReadingItem, ReadingList

WHY_RULE = "holds a rule chosen for this paper"
WHY_CITED = "cited by the paper"
WHY_CONTEXT = "named by the project context"
WHY_TITLE = "its title names the equipment"
WHY_LIBRARIAN = "chosen by the librarian"
#: how many titles the one model call may see, and how long a title is cut
MAX_TITLES = 400
TITLE_CHARS = 120

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BookInput:
    """One rule book the review may read. `why` is the book-level reason ("cited by the paper", "governs the equipment type", ...);
    `label`: the book's standard label (as `governing_standards.json` names it), used by the one partial-standard gate."""

    book_id: str
    cut: CutBook
    why: tuple[str, ...] = ()
    label: str = ""


@dataclass(frozen=True)
class RuleRef:
    """A rule chosen for this paper (already ranked by rule choice v2: `rank` 1 is the first)."""

    book_id: str
    clause: str | None
    page: int | None
    rank: int


@dataclass(frozen=True)
class ClauseRef:
    """A clause the paper cites or the project context names. `clause` None = the whole book (a book-level reason only)."""

    book_id: str
    clause: str | None


def _word_hit(text: str, words: Iterable[str]) -> bool:
    low = " " + re.sub(r"[^a-z0-9]+", " ", text.lower()) + " "
    return any(
        re.search(
            r"(?<![a-z0-9])"
            + re.escape(re.sub(r"[^a-z0-9]+", " ", w.lower()).strip())
            + r"(?:e?s)?(?![a-z0-9])",
            low,
        )
        for w in words
        if w.strip()
    )


def _title(cut: CutBook, chapter: Chapter) -> str:
    """The heading line of a chapter, read from the book's own stored text (never stored in a record)."""
    lines = cut._lines
    return (
        lines[chapter.title_line][:TITLE_CHARS]
        if 0 <= chapter.title_line < len(lines)
        else chapter.chapter_id
    )


def _holding(cut: CutBook, ref: RuleRef) -> list[Chapter]:
    """The chapter(s) a chosen rule lies in: by its clause number, else by its page (stored clause ids are not always reliable)."""
    by_page = [
        c
        for c in cut.chapters
        if ref.page is not None and c.page_from <= ref.page <= c.page_to
    ]
    cid = cut.locate(ref.clause) if ref.clause else None
    named = cut.chapter(cid) if cid else None
    if named is not None and (not by_page or named in by_page):
        return [named]
    if len(by_page) == 1:
        return by_page
    return by_page[:3] if by_page else ([named] if named else [])


def plan_reading(
    run_id: str,
    books: Sequence[BookInput],
    *,
    rules: Sequence[RuleRef] = (),
    cited: Sequence[ClauseRef] = (),
    context: Sequence[ClauseRef] = (),
    equipment_words: Sequence[str] = (),
    shown: Iterable[str] = (),
    allowed: Iterable[str] = (),
    equipment: Iterable[str] = (),
    engine: str = "claude",
    wanted_not_listed: int = 0,
) -> ReadingList:
    """The reading list: books with why, chapters with why and rank, chosen or "not read" with the reason. Pure and deterministic."""
    # default DENY: a caller that passes no shown list or no access reads nothing
    shown_set = frozenset(str(s) for s in shown)
    allowed_set = frozenset(str(s) for s in allowed)
    local = engine == "local"
    review_limit = LOCAL_REVIEW_TOKENS if local else CLAUDE_REVIEW_TOKENS
    book_limit = LOCAL_REVIEW_TOKENS if local else CLAUDE_BOOK_TOKENS
    hidden = int(wanted_not_listed)
    listed: list[BookInput] = []
    for b in books:
        if b.book_id not in allowed_set:
            hidden += 1  # counted, never named
            continue
        listed.append(b)

    # 1. every candidate chapter with its reasons
    cand: dict[tuple[str, str], dict] = {}

    def add(
        book: BookInput, chapter: Chapter, why: str, rank: int | None = None
    ) -> None:
        key = (book.book_id, chapter.chapter_id)
        slot = cand.setdefault(
            key, {"book": book, "chapter": chapter, "why": [], "best": 10**9}
        )
        if why not in slot["why"]:
            slot["why"].append(why)
        if rank is not None:
            slot["best"] = min(slot["best"], rank)

    by_id = {b.book_id: b for b in listed}
    for ref in rules:
        book = by_id.get(ref.book_id)
        if book is not None:
            for chapter in _holding(book.cut, ref):
                add(book, chapter, WHY_RULE, ref.rank)
    for refs, why in ((cited, WHY_CITED), (context, WHY_CONTEXT)):
        for ref in refs:
            book = by_id.get(ref.book_id)
            cid = (
                book.cut.locate(ref.clause)
                if (book is not None and ref.clause)
                else None
            )
            chapter = book.cut.chapter(cid) if (book is not None and cid) else None
            if chapter is not None:
                add(book, chapter, why)
    words = [w for w in equipment_words if w]
    for book in listed:
        hits = _partial_hits(book, equipment)
        for chapter in book.cut.chapters:
            if (words and _word_hit(_title(book.cut, chapter), words)) or (
                chapter.chapter_id in hits
            ):
                add(book, chapter, WHY_TITLE)

    # 2. rank: rule chapters first (by their best rule rank), then cited or named, then title matches; then book and reading order
    order = {b.book_id: i for i, b in enumerate(listed)}
    pos = {
        (b.book_id, c.chapter_id): i
        for b in listed
        for i, c in enumerate(b.cut.chapters)
    }

    def key(item) -> tuple:
        why = item["why"]
        tier = (
            0
            if WHY_RULE in why
            else 1
            if (WHY_CITED in why or WHY_CONTEXT in why)
            else 2
        )
        return (
            tier,
            item["best"],
            order[item["book"].book_id],
            pos[(item["book"].book_id, item["chapter"].chapter_id)],
        )

    ranked = sorted(cand.values(), key=key)

    # 3. the budget, walking the rank: a chapter that does not fit its book's or the review's budget is "not read" with that reason
    spent = 0
    per_book: dict[str, int] = {}
    items: dict[str, list[ReadingItem]] = {b.book_id: [] for b in listed}
    for rank, slot in enumerate(ranked, 1):
        book, chapter = slot["book"], slot["chapter"]
        tokens = tokens_of(sum(p.chars for p in chapter.parts))
        reason = None
        if book.book_id not in shown_set:
            reason = "not on the list shown before the start"
        elif not chapter.chars:
            reason = "no stored text"
        elif local and tokens > review_limit:
            reason = "too long for the local model"
        elif (
            spent + tokens > review_limit
            or per_book.get(book.book_id, 0) + tokens > book_limit
        ):
            reason = "over the reading budget"
        chosen = reason is None
        if chosen:
            spent += tokens
            per_book[book.book_id] = per_book.get(book.book_id, 0) + tokens
        items[book.book_id].append(
            ReadingItem(chapter, tuple(slot["why"]), rank, chosen, reason)
        )  # type: ignore[arg-type]
    choices = tuple(
        BookChoice(
            b.book_id,
            b.why,
            b.book_id in shown_set,
            tuple(items[b.book_id]),
        )
        for b in listed
    )
    return ReadingList(run_id, choices, hidden, spent, review_limit)


# ---------------------------------------------------------------- the one optional model step: titles only, can add, never remove


def titles_for_model(
    reading: ReadingList, books: Sequence[BookInput], limit: int = MAX_TITLES
) -> list[tuple[str, str, str]]:
    """(book id, chapter id, title line) of the chapters of the LISTED books that are not yet candidates: all the model may see. Titles come
    from the stored text and are cut at `TITLE_CHARS`; at most `limit`. Books not on the shown list or outside the access are absent."""
    have = {(b.book_id, i.chapter.chapter_id) for b in reading.books for i in b.items}
    ok = {b.book_id for b in reading.books if b.on_shown_list}
    out: list[tuple[str, str, str]] = []
    for book in books:
        if book.book_id not in ok:
            continue
        for chapter in book.cut.chapters:
            if (book.book_id, chapter.chapter_id) not in have:
                out.append(
                    (book.book_id, chapter.chapter_id, _title(book.cut, chapter))
                )
                if len(out) >= limit:
                    return out
    return out


def apply_model_choice(
    reading: ReadingList,
    books: Sequence[BookInput],
    supplied: Sequence[tuple[str, str, str]],
    returned: Iterable[object],
    *,
    engine: str = "claude",
) -> ReadingList:
    """Add the chapters the model marked "applies": only (book id, chapter id) pairs that code supplied are accepted, each as
    "chosen by the librarian", within what is left of the budget. A code choice is never removed. The result is a new reading list."""
    asked = {(b, c) for b, c, _t in supplied}
    wanted: list[tuple[str, str]] = []
    for r in returned:
        pair = tuple(r) if isinstance(r, (list, tuple)) and len(r) == 2 else None
        if (
            pair
            and (str(pair[0]), str(pair[1])) in asked
            and (str(pair[0]), str(pair[1])) not in wanted
        ):
            wanted.append((str(pair[0]), str(pair[1])))
    if not wanted:
        return reading
    by_id = {b.book_id: b for b in books}
    local = engine == "local"
    review_limit = LOCAL_REVIEW_TOKENS if local else CLAUDE_REVIEW_TOKENS
    book_limit = LOCAL_REVIEW_TOKENS if local else CLAUDE_BOOK_TOKENS
    spent = reading.tokens_planned
    per_book = {
        b.book_id: sum(
            tokens_of(sum(p.chars for p in i.chapter.parts))
            for i in b.items
            if i.chosen
        )
        for b in reading.books
    }
    next_rank = 1 + max((i.rank for b in reading.books for i in b.items), default=0)
    choices = []
    for b in reading.books:
        items = list(b.items)
        for book_id, cid in wanted:
            if book_id != b.book_id or book_id not in by_id:
                continue
            chapter = by_id[book_id].cut.chapter(cid)
            if chapter is None:
                continue
            tokens = tokens_of(sum(p.chars for p in chapter.parts))
            reason = None
            if not b.on_shown_list:
                reason = "not on the list shown before the start"
            elif (
                spent + tokens > review_limit
                or per_book.get(book_id, 0) + tokens > book_limit
            ):
                reason = "over the reading budget"
            elif local and tokens > review_limit:
                reason = "too long for the local model"
            if reason is None:
                spent += tokens
                per_book[book_id] = per_book.get(book_id, 0) + tokens
            items.append(
                ReadingItem(
                    chapter, (WHY_LIBRARIAN,), next_rank, reason is None, reason
                )
            )  # type: ignore[arg-type]
            next_rank += 1
        choices.append(BookChoice(b.book_id, b.why, b.on_shown_list, tuple(items)))
    return ReadingList(
        reading.run_id,
        tuple(choices),
        reading.books_wanted_not_listed,
        spent,
        reading.tokens_limit,
    )


def extend_with_model(
    reading: ReadingList,
    books: Sequence[BookInput],
    ask: Callable[[list[tuple[str, str, str]]], Iterable[object] | None] | None,
    *,
    engine: str = "claude",
) -> ReadingList:
    """The librarian's one call. `ask(titles)` is supplied by the job (an adapter over the one call seam) and returns (book id, chapter
    id) pairs or None. No `ask`, no titles, a failed call (None or an exception): the code-only reading list stands."""
    if ask is None:
        return reading
    titles = titles_for_model(reading, books)
    if not titles:
        return reading
    try:
        returned = ask(titles)
    except Exception as exc:  # noqa: BLE001 - any failure of the call leaves the code-only list
        log.warning("librarian title call failed: %s", type(exc).__name__)
        return reading
    return apply_model_choice(reading, books, titles, returned or (), engine=engine)


# ---------------------------------------------------------------- facts for the sheet and the record (counts and ids only)


def produced(reading: ReadingList) -> dict:
    """`agent_review_role.produced_json` of role 3: books, chapters chosen, chapters not read by reason, books wanted but not listed."""
    not_read: dict[str, int] = {}
    chosen = 0
    for b in reading.books:
        for i in b.items:
            if i.chosen:
                chosen += 1
            else:
                not_read[str(i.not_read_why)] = not_read.get(str(i.not_read_why), 0) + 1
    return {
        "books": len(reading.books),
        "chapters_chosen": chosen,
        "chapters_not_read": not_read,
        "books_wanted_not_listed": reading.books_wanted_not_listed,
        "tokens_planned": reading.tokens_planned,
        "tokens_limit": reading.tokens_limit,
    }


QUESTION_ID = nine_call.template(
    "nine_librarian_titles",
    "The derived block lists chapter titles of rule books, one per row as book | chapter | title. Name the chapters, from this list "
    "only, that apply to a datasheet review of the equipment the paper describes and are not covered by the chapters already chosen. "
    'Answer with JSON only: {{"chapters": [["book", "chapter"], ...]}}. Use the book and chapter exactly as written.',
)
#: the titles go as ONE derived block of kind review_record (rows of short tokens), sources = the books the titles come from, so the
#: seam gates every book; the heading pages are not sent as blocks (a title is a short token, a page is a chapter's words).
BLOCK_NAME = "chapter_titles"
TOKEN = nine_call.MAX_TOKEN_CHARS


def titles_block(
    titles: Sequence[tuple[str, str, str]],
) -> tuple[nine_call.Block | None, int]:
    """(the titles as a derived block, rows left out). A title is the RAW prefix of its heading line as it stands in the stored text (60
    characters at most, leading blanks off, nothing normalised), so it occurs verbatim in its source book. A row whose id is longer
    than a token, whose title is empty or holds a control character, or that does not fit the seam's digest size, is left out and
    counted (the caller says it). The book id and the chapter id are ids."""
    rows, used, left = [], 0, 0
    for book, chapter, title in titles:
        t = title.lstrip()[:TOKEN]
        row = (book, chapter, t)
        if not t or any(len(c) > TOKEN or any(ord(ch) < 32 for ch in c) for c in row):
            left += 1
            continue
        cost = sum(len(c) + 3 for c in row)
        if used + cost > nine_call.MAX_DERIVED_CHARS:
            left += 1
            continue
        rows.append(row)
        used += cost
    if not rows:
        return None, left
    block = nine_call.Block(
        nine_call.DERIVED_KIND,
        name=BLOCK_NAME,
        sources=tuple(sorted({r[0] for r in rows})),
        items=tuple(rows),
    )
    return block, left


def seam_ask(run_id: str, *, engine: str | None = None, **seam):
    """The adapter `extend_with_model` takes: ONE call of role 3 through `nine_call.ask`. A refused or failed call: None (the code list stands)."""

    def ask(titles: Sequence[tuple[str, str, str]]):
        block, _left = titles_block(titles)
        if block is None:
            return None
        got = nine_call.ask(
            run_id, 3, [block], (QUESTION_ID, {}), engine=engine, **seam
        )
        return parse_choice(got.text) if got.ok else None

    return ask


def parse_choice(text: str | None) -> list[tuple[str, str]]:
    """The pairs of the model's JSON answer; anything else is an empty list (the code-only list stands)."""
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        found = re.search(r"\{.*\}", text, re.S)
        try:
            data = json.loads(found.group(0)) if found else {}
        except ValueError:
            return []
    rows = data.get("chapters") if isinstance(data, dict) else None
    return (
        [(str(r[0]), str(r[1])) for r in rows if isinstance(r, list) and len(r) == 2]
        if isinstance(rows, list)
        else []
    )


# ---------------------------------------------------------------- the data the librarian reads (no list in code)


def _partial_hits(book: BookInput, equipment: Iterable[str]) -> set[str]:
    """Chapter ids whose title names a governed part of a book the equipment takes only in part: the ONE gate
    (`subject_scope.partial_gate`, plural matching, `no_plural` honoured). A book with no entry for this equipment: none."""
    from . import subject_scope

    equipment = set(equipment)
    if not equipment or not book.label:
        return set()
    table = json.loads(
        (Path(__file__).parent / "reference" / "governing_standards.json").read_text(
            encoding="utf-8"
        )
    )
    kw = {
        "equipment": equipment,
        "standard_labels": {book.book_id: book.label},
        "partial_standards": table.get("partial_standards") or {},
        "plural": True,
    }
    probe = {"id": "", "subject": "", "standard_document_id": book.book_id}
    if not subject_scope.partial_gate([probe], **kw)["items"]:
        return (
            set()
        )  # an empty text names nothing: it is dropped only when the book has an entry
    reqs = [
        {
            "id": c.chapter_id,
            "subject": _title(book.cut, c),
            "standard_document_id": book.book_id,
        }
        for c in book.cut.chapters
    ]
    return {r["id"] for r in subject_scope.partial_gate(reqs, **kw)["kept"]}


__all__ = [
    "WHY_CITED",
    "WHY_CONTEXT",
    "WHY_LIBRARIAN",
    "WHY_RULE",
    "WHY_TITLE",
    "BookInput",
    "ClauseRef",
    "RuleRef",
    "apply_model_choice",
    "extend_with_model",
    "parse_choice",
    "plan_reading",
    "produced",
    "seam_ask",
    "titles_block",
    "titles_for_model",
]
