"""Two guards on a Pass of a rule WITHOUT numbers (order 13, W2 finding and review R39). Pure functions, no I/O, no model call.

A Pass of such a rule used to rest on two verified quotes and a second reader: the code compared no value and did not check that the
quote answers the rule's own FIELD or the rule's CONDITION. The guards run on EVERY Pass answer of such a rule, whatever the gate
decided (`agent_review_decide`), and on the second reader's own quotes (`agent_review_two_reader_run`); a line a guard objects to
carries `pass_guard = {"ok": False, "code", "why"}` and can end neither as "Proven by code: Pass" nor as "AI verdict: met"
(`agent_review_two_reader.textual_pass_agreed`, `is_candidate`, `agrees` read it). A guard only ever takes confidence away; a Fail,
a Query and a number rule (the code compares the figures) are never touched. The reasons state only what the code saw.

A. FIELD (`belongs`). The rule's field is the label's field and the item's field roles, in the registry's words
   (`agent_review_absence.field_words`: its label patterns and spellings; ALL of a spelling's words, no single shared word). A field the
   registry does not know needs every content word of its name. The verified quote's OWN line must carry them; or the line DIRECTLY ABOVE
   it must (never below), when that line is a short label line with no digit and the quote's own line carries no other known field's
   words. A single generic word (`GENERIC`: type, material, service, size, fluid, code, flow) counts only when the line is exactly that
   label. The AI's own field label is never evidence.
B. CONDITION. When the clause quote or the requirement holds a condition (`agent_review_verdict.is_conditional`, one home), the answer
   must carry a condition quote (`condition_quote`, `condition_page`) that is verified on its page, holds a content word of the
   condition itself (not just "service"), and is not the value quote nor overlaps it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from . import agent_bind
from . import agent_review_absence as absence
from . import agent_review_verdict as verdict
from .reader_api import _fold

CODE_FIELD_UNKNOWN = "pass_field_unknown"
CODE_FIELD_NOT_QUOTED = "pass_field_not_quoted"
CODE_CONDITION_NOT_QUOTED = "pass_condition_not_quoted"
CODES = (CODE_FIELD_UNKNOWN, CODE_FIELD_NOT_QUOTED, CODE_CONDITION_NOT_QUOTED)
FIELD_UNKNOWN_WHY = "the rule's field is not known to the code, so the quoted line could not be matched to it"
FIELD_LINE_WHY = "the field's words are not on the quoted line or the line above it"
CONDITION_NOT_QUOTED_WHY = (
    "the AI reviewer holds no verified quote for the condition the rule applies under"
)
CONDITION_WORD_WHY = "the quote given for the condition holds no word of the condition, or repeats the value quote"
#: a one-word label that names no field by itself (matched only as the whole label line)
GENERIC = frozenset({"type", "material", "service", "size", "fluid", "code", "flow"})
#: a label line above a value is short and has no digit
MAX_LABEL_WORDS = 6
_TRIGGERS = frozenset(
    {
        "if",
        "when",
        "where",
        "unless",
        "provided",
        "that",
        "in",
        "case",
        "except",
        "only",
        "otherwise",
        "for",
        "to",
    }
)
_HEADS = frozenset({"service", "duty"})


def field_names(item: Mapping) -> list[str]:
    """The rule's own field names: the label's field, then the item's field roles."""
    label = (
        item.get("rule_label") if isinstance(item.get("rule_label"), Mapping) else {}
    )
    names = [
        str(label.get("field") or "").strip(),
        *[str(r).strip() for r in item.get("field_roles") or []],
    ]
    return [n for n in dict.fromkeys(names) if n]


def _is_the_label(folded: str, text: str) -> bool:
    return folded.strip(" :.-") == text.strip()


def _hit(folded: str, words: absence.FieldWords) -> bool:
    """The folded line carries the field's words by the registry's patterns or spellings; a single generic word only as the whole line."""
    for p in words.patterns:
        m = p.search(folded)
        if m:
            text = m.group(0).strip()
            if text and not (
                len(text.split()) == 1
                and text in GENERIC
                and not _is_the_label(folded, text)
            ):
                return True
    undotted = " ".join(
        folded.replace(".", " ").split()
    )  # the spellings are written without full stops ("c a" for "C.A.", "max allowable ..." for "max. allowable ...")
    for sp in words.spellings:
        generic_alone = (
            len(sp.split()) == 1 and sp in GENERIC and not _is_the_label(folded, sp)
        )
        if (
            re.search(rf"(?<!\w){re.escape(sp)}(?!\w)", folded)
            or re.search(rf"(?<!\w){re.escape(sp)}(?!\w)", undotted)
        ) and not generic_alone:
            return True
    return False


@lru_cache(maxsize=1)
def _all_fields() -> tuple[tuple[str, absence.FieldWords], ...]:
    roles = absence.registry()["roles"]
    out = []
    for role in sorted(roles):
        words = absence.field_words([(role, "registry")])
        if words is not None:
            out.append((role, words))
    return tuple(out)


#: words a label line may add to the field's own words: a unit column header
UNIT_HEADERS = frozenset({"unit", "units", "uom"})
NEGATIONS = frozenset(
    {"not", "no", "non", "without", "never", "none", "nor", "neither", "nil"}
)


def _label_only(folded: str, names: list[str]) -> bool:
    """The line is ONLY the field's label: its longest registry match (or all content words of a field the registry does not know)
    and nothing else but punctuation, a parenthesised unit or a unit column header. A row that holds a text value is not a label line."""
    words = absence.field_words([(n, "rule label") for n in names])
    if words is not None:
        found = [m.group(0) for p in words.patterns for m in p.finditer(folded)]
        found += [
            sp
            for sp in words.spellings
            if re.search(rf"(?<!\w){re.escape(sp)}(?!\w)", folded)
        ]
        if not found:
            return False
        rest = folded.replace(max(found, key=len).strip(), " ", 1)
    else:
        want = agent_bind.content_words(" ".join(n.replace("_", " ") for n in names))
        have = agent_bind.content_words(folded)
        return bool(want) and want <= have and have - want <= UNIT_HEADERS
    rest = re.sub(r"\([^)]*\)", " ", rest)
    return all(t in UNIT_HEADERS for t in re.findall(r"[a-z0-9]+", rest))


def _carries(folded: str, names: list[str]) -> bool:
    words = absence.field_words([(n, "rule label") for n in names])
    if words is not None:
        return _hit(folded, words)
    want = agent_bind.content_words(" ".join(n.replace("_", " ") for n in names))
    if len(want) == 1 and next(iter(want)) in GENERIC:
        return _is_the_label(folded, next(iter(want)))
    return bool(want) and want <= agent_bind.content_words(folded)


def _other_field_words(folded: str, names: list[str]) -> bool:
    """The line carries the words of a registry field that is NOT the rule's own."""
    own = absence.field_words([(n, "rule label") for n in names])
    own_role = own.role if own is not None else None
    return any(role != own_role and _hit(folded, w) for role, w in _all_fields())


def _page_lines(page_text: Any) -> list[tuple[int, int, str]]:
    """(start, end, folded) of every non-empty page line in the folded page text (lines joined by one space, as `_fold` does)."""
    out, pos = [], 0
    for raw in str(page_text or "").splitlines():
        folded = _fold(raw)
        if folded:
            out.append((pos, pos + len(folded), folded))
            pos += len(folded) + 1
    return out


def _own_and_above(page_text: Any, quote: Any) -> tuple[list[str], str | None]:
    """(the folded lines the verified quote lies on, the folded line directly above the first of them or None)."""
    q = _fold(str(quote or "")).strip()
    pieces = _page_lines(page_text)
    i = " ".join(p[2] for p in pieces).find(q) if q else -1
    if i < 0:
        return [], None
    hit = [k for k, (a, b, _f) in enumerate(pieces) if a < i + len(q) and i < b]
    above = pieces[hit[0] - 1][2] if hit[0] > 0 else None
    return [pieces[k][2] for k in hit], above


def belongs(
    item: Mapping, quote: Any, page_text: Any
) -> tuple[bool, str | None, str | None]:
    """(ok, reason code, reason): the strict test of guard A. Not established = not ok, with the reason in plain words."""
    names = field_names(item)
    if not names:
        return False, CODE_FIELD_UNKNOWN, FIELD_UNKNOWN_WHY
    own, above = _own_and_above(page_text, quote)
    if own and any(_carries(line, names) for line in own):
        return True, None, None
    if (
        own
        and above
        and not re.search(r"\d", above)
        and len(above.split()) <= MAX_LABEL_WORDS
        and _carries(above, names)
        and _label_only(above, names)
        and not any(_other_field_words(line, names) for line in own)
    ):
        return True, None, None
    return False, CODE_FIELD_NOT_QUOTED, FIELD_LINE_WHY


def condition_terms(*texts: Any) -> set[str]:
    """The content words of the conditions the detector (`verdict._CONDITIONAL`, one home) finds in the texts: for a conditional
    word the words after it up to the next punctuation; for a "for / in / to ... service" form the words of the form itself. The bare
    trigger words and the heads "service" and "duty" are not terms."""
    terms: set[str] = set()
    for text in texts:
        t = str(text or "")
        for m in verdict._CONDITIONAL.finditer(t):
            span = m.group(0)
            if re.match(r"(?:for|in|to)\s", span, re.IGNORECASE):
                words = span
            else:
                words = " ".join(
                    re.split(r"[.;:,()]", t[m.end() :], maxsplit=1)[0].split()[:8]
                )
            terms |= {
                w
                for w in agent_bind.content_words(words)
                if w not in _TRIGGERS and w not in _HEADS
            }
    return terms


def _spans(page_text: Any, quote: Any) -> list[tuple[int, int]]:
    q, fp = _fold(str(quote or "")).strip(), _fold(str(page_text or ""))
    out, i = [], fp.find(q) if q else -1
    while i >= 0:
        out.append((i, i + len(q)))
        i = fp.find(q, i + 1)
    return out


def _negated(quote: str, terms: set[str]) -> bool:
    """A negation word within five words before, or three after, a word of the condition ("not expected to be sour")."""
    tokens = re.findall(r"[a-z0-9']+", _fold(quote))
    for i, tok in enumerate(tokens):
        if terms & agent_bind.content_words(tok) and any(
            t in NEGATIONS or t.endswith("n't") for t in tokens[max(0, i - 5) : i + 4]
        ):
            return True
    return False


def condition_ok(answer: Mapping, pages: Mapping[int, str], terms: set[str]) -> bool:
    """The condition quote is verified on its page, holds a word of the condition, and is not the value quote nor overlaps it."""
    cq = answer.get("condition_quote")
    ok, _why = verdict.check_paper_quote(cq, answer.get("condition_page"), pages)
    if not (ok and terms and terms & agent_bind.content_words(str(cq))):
        return False
    if _negated(
        str(cq), terms
    ):  # a quote saying the condition does NOT hold is no quote of the condition
        return False
    vq, fc, fv = (
        answer.get("paper_quote"),
        _fold(str(cq)).strip(),
        _fold(str(answer.get("paper_quote") or "")).strip(),
    )
    if fc == fv or fc in fv or fv in fc:
        return False
    cp, vp = (
        verdict._page_no(answer.get("condition_page")),
        verdict._page_no(answer.get("paper_page")),
    )
    if cp is not None and cp == vp:
        a, b = _spans(pages.get(cp), cq), _spans(pages.get(vp), vq)
        if any(x[0] < y[1] and y[0] < x[1] for x in a for y in b):
            return False
    return True


def verdict_of(
    item: Mapping, answer: Mapping, pages: Mapping[int, str], requirement: str | None
) -> dict | None:
    """The guards' result for one Pass answer: None for a number rule (not this guard's), {"ok": True}, or {"ok": False, "code", "why"}."""
    if verdict.is_number_item(item):
        return None
    page = verdict._page_no(answer.get("paper_page"))
    ok, code, why = belongs(
        item, answer.get("paper_quote"), pages.get(page) if page else None
    )
    if not ok:
        return {"ok": False, "code": code, "why": why}
    whole = item.get(
        "clause_condition_text"
    )  # local engine: the conditions of the WHOLE clause, read before it was trimmed
    if verdict.is_conditional(answer.get("clause_quote"), requirement, whole):
        terms = condition_terms(answer.get("clause_quote"), requirement, whole)
        if not (answer.get("condition_quote") and condition_ok(answer, pages, terms)):
            quoted = bool(answer.get("condition_quote"))
            return {
                "ok": False,
                "code": CODE_CONDITION_NOT_QUOTED,
                "why": CONDITION_WORD_WHY if quoted else CONDITION_NOT_QUOTED_WHY,
            }
    return {"ok": True}


def check(
    item: Mapping, answer: Mapping, pages: Mapping[int, str], requirement: str | None
) -> tuple[str, str] | None:
    """(reason code, reason) when a Pass of a rule without numbers must not stand, else None."""
    got = verdict_of(item, answer, pages, requirement)
    return None if got is None or got["ok"] else (str(got["code"]), str(got["why"]))


# ---------------------------------------------------------------- C. THE CLAUSE QUOTE IN THE RULE BOOK (c11, 15 Nov 2026; audit V1 defect 3)
# Before this, a clause quote was "verified" when it stood in the text the reader had been GIVEN: for a rule the stored requirement
# row (`standard_requirements.source_text`), which is on its cited page only part of the time. That shows the reader copied what it
# was handed, not that the words are in the book. Here the quote is searched in the book's stored pages by the same fold as the paper
# quote (`reader_api._fold`: whitespace, case) plus the two things a printed page needs: a word split by a hyphen at a line end is
# joined, and a quote that runs over a page break is found in the two pages together. Never the requirement row.
#   locate(quote, book, page_hint) -> Located(found, page, where, why)   pure; `page_hint` = the stated page(s), first the stated one
#   judge(book_of, item, quote, held_source, held_ok) -> (verified, Located)
# The reader of the stored pages (`agent_review_standards.BookPages` / `verify`) lives beside the other readers of book text.

MIN_QUOTE_CHARS = 8  # a shorter quote proves nothing (the paper quote's own floor is `agent_tools.MIN_QUOTE_CHARS`; this is checked too)
WHERE_STATED = "the stated page"
WHERE_NEXT = "the page after the stated page"
WHERE_OTHER = "another page of the book"
WHERE_CUT = "the clause text cut from the book"  # the book's own text, but its pages were NOT searched for this quote
OFF_PAGE_MIN = 20  # a quote shorter than this is searched on the stated page only: elsewhere it would match by chance
NOT_HELD = "the rule book's pages are not held"
NOT_RESOLVABLE = "not searched: the rule book is not resolvable"
CUT_WHY = "not on a single page of the book: read from the clause text cut from it"
NOT_FOUND = "the quote is not in the rule book's stored pages"
NO_QUOTE = "no clause quote"
TOO_SHORT = "clause quote too short"


@dataclass(frozen=True)
class Located:
    """`found`: the quote stands in the book's stored text. `page`: the page it starts on (the TRUE page). `where`: how that page
    relates to the stated one. `why`: when not found, the reason in plain words."""

    found: bool
    page: int | None = None
    where: str | None = None
    why: str | None = None
    scanned: bool = False  # the text of that page is the recognised text of a scan (`page_ocr`), not a text layer

    def to_json(self) -> dict:
        return {
            "found": self.found,
            "page": self.page,
            "where": self.where,
            "why": self.why,
            **({"scanned": True} if self.scanned else {}),
        }


def _joined(text: str) -> str:
    """A word split by a hyphen at a line end is one word again."""
    return re.sub(r"-[ \t]*\n[ \t]*", "", text or "")


class Book:
    """The stored page text of one rule book, folded once per form (a run asks for many quotes of a few books)."""

    def __init__(self, pages: Mapping[int, str], ocr: Iterable[int] = ()) -> None:
        self.pages = {
            int(n): str(t or "") for n, t in pages.items() if str(t or "").strip()
        }
        self.ocr = frozenset(
            int(n) for n in ocr
        )  # the pages whose text is recognised text
        self._plain: dict[int, str] = {}
        self._hyph: dict[int, str] = {}

    def plain(self, n: int) -> str:
        if n not in self._plain:
            self._plain[n] = _fold(self.pages.get(n, ""))
        return self._plain[n]

    def hyph(self, n: int) -> str:
        if n not in self._hyph:
            self._hyph[n] = _fold(_joined(self.pages.get(n, "")))
        return self._hyph[n]

    def has_text(self) -> bool:
        return bool(self.pages)


def _on_page(plain: str, hyph: str, book: Book, n: int) -> bool:
    return plain in book.plain(n) or (hyph != "" and hyph in book.hyph(n))


def _over_break(plain: str, hyph: str, book: Book, n: int) -> bool:
    """The quote STARTS on page n and runs over the break into page n+1 (a quote that stands wholly on n+1 is not this)."""
    if n + 1 not in book.pages:
        return False
    for q, first, second in (
        (plain, book.plain(n), book.plain(n + 1)),
        (hyph, book.hyph(n), book.hyph(n + 1)),
    ):
        at = f"{first} {second}".find(q) if q else -1
        if 0 <= at < len(first) < at + len(q):
            return True
    return False


def _hints(page_hint: Any) -> list[int]:
    if isinstance(page_hint, bool):
        return []
    if isinstance(page_hint, int):
        return [page_hint]
    if isinstance(page_hint, Iterable) and not isinstance(page_hint, str | bytes):
        return [p for p in page_hint if isinstance(p, int) and not isinstance(p, bool)]
    return []


def locate(quote: Any, book: Book, page_hint: Any = None) -> Located:
    """Where the quote stands in the book's own stored pages: the stated page(s) first, the page after, then every page. The
    answer carries the true page. Pure on its inputs."""
    text = " ".join(str(quote or "").split())
    if not text:
        return Located(False, why=NO_QUOTE)
    if len(text) < MIN_QUOTE_CHARS:
        return Located(False, why=TOO_SHORT)
    if not book.has_text():
        return Located(False, why=NOT_HELD)
    plain = _fold(text)
    hyph = _fold(
        _joined(str(quote))
    )  # the same quote with a line-end hyphen joined; compared with the page joined the same way
    hints = [p for p in _hints(page_hint) if p in book.pages]
    stated = hints[0] if hints else None
    short = len(text) < OFF_PAGE_MIN  # a short quote counts on the stated page only
    near = [p for p in hints if not short or p == stated]
    far = [] if short else sorted(n for n in book.pages if n not in hints)

    def found(n: int) -> Located:
        return Located(
            True, n, WHERE_STATED if n == stated else WHERE_OTHER, scanned=n in book.ocr
        )

    for p in near:
        if _on_page(plain, hyph, book, p):
            return found(p)
    for p in near:
        if _over_break(plain, hyph, book, p):
            return found(p)
    for n in far:
        if _on_page(plain, hyph, book, n):
            return found(n)
    for n in far:
        if _over_break(plain, hyph, book, n):
            return found(n)
    return Located(False, why=NOT_FOUND)


#: held-text sources that are the book's OWN text, cut out by code from its stored pages (`agent_review_standards._Standards.clause`,
#: `.table_clause`); the stored requirement row ("rule_quote") is NOT one of them.
BOOK_OWN_SOURCES = frozenset({"clause_span", "table_page"})


def judge(
    book_of: Callable[[Any], Book],
    item: Mapping,
    quote: Any,
    held_source: str | None,
    held_ok: bool,
) -> tuple[bool, Located]:
    """(verified, where) for the clause quote of one item. `held_ok`: the quote stands in the text the reader was given. A quote is
    verified when it stands in the book's own stored pages (`locate`; the true page is returned). The clause text cut from the book by
    code (`BOOK_OWN_SOURCES`) is the book's own text too: a quote in it that no single page holds (a long clause) stands on the clause's
    start page. The stored requirement row is never a check."""
    doc = item.get("standard_document_id")
    hints = [
        p
        for p in (item.get("clause_page"), item.get("rule_page"))
        if isinstance(p, int) and not isinstance(p, bool)
    ]
    got = locate(quote, book_of(doc) if doc else Book({}), hints)
    if not doc:
        got = Located(
            False, why=NOT_RESOLVABLE
        )  # no book to search: said so, never "found" on a page nobody looked at
    if got.found:
        return True, got
    if (
        held_ok and held_source in BOOK_OWN_SOURCES
    ):  # the clause text cut from the book: its own text, but the PAGES were not searched
        return True, Located(
            True, None, WHERE_CUT, NOT_RESOLVABLE if not doc else CUT_WHY
        )
    return False, got
