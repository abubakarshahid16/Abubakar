"""Role 4, step "findings": a reviewer's raw finding becomes ONE line of today's table through today's one exit (builder B4).

A finding is not a verdict. Code turns each joined finding into what the app already judges, an ITEM plus a first-reader ANSWER, and
hands it to `Runner.decide` (number lines by `compare_figures`, text lines to the second reader, holds, the context check of a Fail),
then `Runner.emit` (the one exit, `agent_review_wording.final_cap`). Nothing here writes a class, a word, a verdict of a line or
`decided_by`: there is no second way to make a decision.

What code does, in order (SPEC D):
  1. VERIFY both quotes. The paper quote must stand on a paper page that was SENT in that call. The clause quote must be found in the
     rule book's own stored pages by `agent_review_standards.verify` (#1822) AND on a page that was sent in that call (a page the
     reviewer was not given cannot support a quote it "remembers"). A finding with an unverified quote is KEPT, as a Query that says why.
  2. MATCH the verified clause quote to ONE stored rule row of the same book (`nine_match`): one match = the line `R-<rule id>` with that
     rule's CURRENT tier; none or two = an `F-<hash>` item with no tier ("read from the chapter; no approved rule row behind it": an
     opinion at most). A match never gives a better tier than the rule has.
  3. JOIN raw findings of different calls by (book, clause number, field key, tag); field key = the registry role of the label, else
     the folded printed label. Same key and same verdict: one finding, its members listed. Same key and DIFFERENT verdicts: never a
     winner, ONE Query "the readers disagree on this field" (the wording #1819 uses).
  4. BUILD the synthetic item (the requirement text is the verified clause sentence, `widen_to_sentence`; its entry goes into the
     run's `ClauseCache` as the book's own text) and the answer; `decide_all` calls `Runner.decide` and `Runner.emit`.

Findings carry `field_roles` and `paper_page`, so the score script reads them unchanged. Pure functions except `decide_all`, which only
calls the runner. No model, no network, no document text written to a log.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from . import agent_review_absence as absence
from . import agent_review_pass_guards as guards
from . import agent_review_standards as standards
from . import agent_review_verdict as verdict
from . import datasheet_roles, nine_match
from .crs_comments import DISAGREE
from .nine_contract import AiVerdict, Finding, FindingOrigin, RawFinding
from .reader_api import _fold

#: the reason a chapter finding with no approved rule row behind it carries (an opinion at most)
NO_RULE_WHY = "read from the chapter; no approved rule row behind it"
PAPER_NOT_SENT = "the paper quote is not on a paper page that was sent in that call"
CLAUSE_NOT_SENT = "the clause quote is not on a page of the book that was sent in that call"
CLAUSE_NOT_FOUND = "the clause quote is not in the rule book's stored pages"
CLAUSE_AMBIGUOUS = "the clause quote is in more than one of the books sent in that call"
NO_BOOK = "the call sent no rule book page to find the clause quote in"
MAX_CLAUSE_ENTRY_CHARS = 8000

#: the answer shape of today's first reader, per reviewer verdict: (verdict word of the ANSWER, reason code)
ANSWER_OF = {
    "met": ("Pass", "met"),
    "not_met": ("Fail", "not_met"),
    "not_stated": ("Fail", "absent"),
    "not_applicable": ("Query", "not_applicable"),
    "cannot_tell": ("Query", "other"),
}
VERDICTS = tuple(ANSWER_OF)


# ---------------------------------------------------------------- what one call sent


@dataclass(frozen=True)
class Sent:
    """What ONE reviewer call put in front of the model (derived by the caller from the blocks it sent, the same list the record is
    written from): the paper pages and, per rule book, the pages of the chapter parts. A quote counts only on these."""

    call_id: str
    paper_pages: frozenset[int]
    book_pages: Mapping[str, frozenset[int]]
    model: str | None = None
    read_refs: tuple[tuple[str, str, int], ...] = ()  # (book id, chapter id, part no) in this call


@dataclass(frozen=True)
class Checked:
    """A raw finding after code looked at its quotes. `*_ok` are written by code only."""

    raw: Mapping
    call: Sent
    book_id: str | None
    paper_ok: bool
    paper_why: str | None
    clause_ok: bool
    clause_page: int | None
    clause_why: str | None


# ---------------------------------------------------------------- 1. verify


def verdict_of(raw: Mapping) -> AiVerdict | None:
    """The finding's verdict word, folded; None when it is none of the five (such a finding says nothing and is dropped by the caller)."""
    word = str(raw.get("verdict") or "").strip().lower().replace(" ", "_").replace("-", "_")
    return word if word in ANSWER_OF else None  # type: ignore[return-value]


def verify_sent(book_id: str, quote: Any, hint: Any, sent_pages: frozenset[int], books: standards.BookPages) -> tuple[int | None, str | None]:
    """(page, why not): the clause quote found by `agent_review_standards.verify` AND standing on a page that was sent. When the first place
    it was found is a page that was not sent, it is searched again among the sent pages only: the same text can stand on both."""
    got = standards.verify(book_id, quote, hint, books)
    if not got.found:
        return None, got.why or CLAUSE_NOT_FOUND
    if got.page in sent_pages:
        return got.page, None
    book = books.book(book_id)
    only = guards.Book({n: t for n, t in book.pages.items() if n in sent_pages}, ocr=book.ocr & sent_pages)
    again = guards.locate(quote, only, [p for p in (hint if isinstance(hint, Iterable) else [hint]) if isinstance(p, int)])
    return (again.page, None) if again.found else (None, CLAUSE_NOT_SENT)


def check_raw(raw: Mapping, call: Sent, paper_pages: Mapping[int, str], books: standards.BookPages) -> Checked:
    """Verify one raw finding. The paper quote is checked on the paper pages that were sent; the clause quote in the book's own pages
    on a page that was sent, the book being the raw finding's `book_id` when it names one, else the only book of the call that holds it."""
    sent_paper = {n: t for n, t in paper_pages.items() if n in call.paper_pages}
    paper_ok, paper_why = verdict.check_paper_quote(raw.get("paper_quote"), raw.get("paper_page"), sent_paper)
    if not paper_ok and raw.get("paper_page") not in call.paper_pages and str(raw.get("paper_quote") or "").strip():
        paper_why = PAPER_NOT_SENT
    quote = raw.get("clause_quote")
    named = str(raw.get("book_id") or "") or None
    wanted = [named] if named in call.book_pages else ([] if named else sorted(call.book_pages))
    if not str(quote or "").strip():
        return Checked(raw, call, None, paper_ok, paper_why, False, None, "no clause quote")
    if not wanted:
        return Checked(raw, call, None, paper_ok, paper_why, False, None, NO_BOOK)
    hits: list[tuple[str, int]] = []
    last_why: str | None = None
    for book_id in wanted:
        page, why = verify_sent(book_id, quote, sorted(call.book_pages[book_id]), call.book_pages[book_id], books)
        if page is not None:
            hits.append((book_id, page))
        else:
            last_why = why
    if len(hits) == 1:
        return Checked(raw, call, hits[0][0], paper_ok, paper_why, True, hits[0][1], None)
    if len(hits) > 1:
        return Checked(raw, call, None, paper_ok, paper_why, False, None, CLAUSE_AMBIGUOUS)
    return Checked(raw, call, named if len(wanted) == 1 else None, paper_ok, paper_why, False, None, last_why or CLAUSE_NOT_FOUND)


# ---------------------------------------------------------------- 3. join


def field_key(label: str | None, rules: Mapping | None = None, prefer: frozenset = frozenset()) -> tuple[str, tuple[str, ...]]:
    """(the key, the registry roles): the registry role of the printed label (`datasheet_roles`), else the folded label itself."""
    text = str(label or "").strip()
    if not text:
        return "", ()
    rules = rules or absence.registry()
    role = datasheet_roles.role_of(text, rules, prefer)
    return (role, (role,)) if role else (_fold(text), ())


def finding_id(book_id: str | None, clause: str | None, key: str, tag: str | None) -> str:
    """"F-<12 hex>" of (book, clause number, field key, tag): stable, so a finding keeps its id from run to run."""
    raw = "\x00".join(str(x or "") for x in (book_id, _fold(str(clause or "")), key, tag))
    return "F-" + hashlib.sha256(raw.encode()).hexdigest()[:12]


@dataclass
class Joined:
    """One issue after the join, before it becomes an item: the representative checked raw finding, who else said it, the verdict."""

    key: tuple[str, str, str, str]
    book_id: str | None
    clause: str | None
    field_label: str | None
    field_roles: tuple[str, ...]
    tag: str | None
    ai_verdict: AiVerdict
    contradiction: bool
    lead: Checked
    members: list[Checked] = field(default_factory=list)


def _quality(c: Checked) -> int:
    """Which member leads: both quotes verified first, then the paper quote, then the clause quote."""
    return 2 * int(c.clause_ok) + int(c.paper_ok) * 3


def join(
    checked: Iterable[Checked],
    *,
    fact_tags: Mapping[str, str | None] | None = None,
    rules: Mapping | None = None,
    prefer_roles: frozenset = frozenset(),
) -> list[Joined]:
    """Raw findings of every call, joined by (book, clause number, field key, tag). Same verdict: ONE finding (the best-verified member
    leads, all members listed). Different verdicts: NEVER a winner: one finding whose verdict is "cannot_tell" and whose
    `contradiction` is True (a Query that says the readers disagree)."""
    groups: dict[tuple[str, str, str, str], list[Checked]] = {}
    keyed: dict[int, tuple[str, tuple[str, ...], str | None]] = {}
    for c in checked:
        word = verdict_of(c.raw)
        if word is None:
            continue
        key, roles = field_key(str(c.raw.get("field_label") or ""), rules, prefer_roles)
        tag = next((fact_tags[f] for f in (c.raw.get("fact_ids") or []) if fact_tags and f in fact_tags and fact_tags[f]), None)
        k = (str(c.book_id or ""), _fold(str(c.raw.get("clause") or "")), key, str(tag or ""))
        groups.setdefault(k, []).append(c)
        keyed[id(c)] = (key, roles, tag)
    out: list[Joined] = []
    for k, members in groups.items():
        lead = max(members, key=_quality)
        words = {verdict_of(m.raw) for m in members}
        _key, roles, tag = keyed[id(lead)]
        single = next(iter(words)) if len(words) == 1 else "cannot_tell"
        out.append(
            Joined(
                key=k, book_id=lead.book_id, clause=str(lead.raw.get("clause") or "") or None,
                field_label=str(lead.raw.get("field_label") or "") or None, field_roles=roles, tag=tag,
                ai_verdict=single, contradiction=len(words) > 1, lead=lead, members=members,
            )
        )  # fmt: skip
    return out


# ---------------------------------------------------------------- 2 and 4. match, item, answer


def clause_sentence(quote: str, page_text: str) -> str:
    """The text the item holds as the requirement: the ONE whole sentence of the book's page that holds the verified quote when there is
    exactly one (`verdict.widen_to_sentence`), else the quote itself. Always contains the quote."""
    got = verdict.widen_to_sentence(quote, page_text)
    return (got or quote)[:MAX_CLAUSE_ENTRY_CHARS] if _fold(quote) in _fold(got or quote) else quote[:MAX_CLAUSE_ENTRY_CHARS]


@dataclass
class Built:
    """What `decide_all` needs for one finding: the finding (contract shape), the item, the answer, the ClauseCache entry (ref -> entry)."""

    finding: Finding
    item: dict
    answer: dict
    cache: dict[str, dict]


def build(
    j: Joined,
    *,
    rules: Iterable[Mapping],
    plan_items: Mapping[str, dict],
    tier_lookup: Callable[[Mapping], str | None] | None,
    book_text: Callable[[str, int], str],
    book_label: Callable[[str | None], str | None] = lambda _b: None,
    origin: FindingOrigin = "reviewer",
) -> Built:
    """The finding as today's item plus first-reader answer. `rules`: stored rule rows of the books sent (`id`, `standard_document_id`,
    `source_text`). `plan_items`: the plan's items by id ("R-..."): a matched rule keeps ITS item (comparator, value, unit, tier) and only
    the clause entry is the verified sentence. An unmatched finding is an `F-` item that names no tier: `rule_tier` "not approved", so
    the exit caps it at an opinion."""
    lead, raw = j.lead, j.lead.raw
    fid = finding_id(j.book_id, j.clause, j.key[2], j.tag)
    cache: dict[str, dict] = {}
    ref = None
    matched = nine_match.Match(None, None, None, nine_match.WHY_NO_QUOTE, 0)
    if lead.clause_ok and lead.clause_page is not None and j.book_id:
        text = clause_sentence(str(raw.get("clause_quote")), book_text(j.book_id, lead.clause_page))
        ref = f"N-{fid}"
        cache[ref] = {
            "standard_document_id": j.book_id, "standard": book_label(j.book_id), "clause": j.clause, "page": lead.clause_page,
            "source": "clause_span", "text": text, "truncated": False,
        }  # fmt: skip
        matched = nine_match.match(j.book_id, str(raw.get("clause_quote")), rules, tier_lookup)
    base = plan_items.get(matched.item_id or "") if matched.matched else None
    if base is not None:
        item = {**base, "clause_quote_ref": ref, "clause": base.get("clause") or j.clause, "clause_page": lead.clause_page}
        item["page_hint"] = [p for p in (raw.get("paper_page"),) if isinstance(p, int)]
        item["page_hint_source"] = "nine reviewer"
        item_id, tier = str(base.get("item_id")), matched.tier
    else:
        item_id, tier = fid, None
        item = {
            "item_id": fid, "source": "rule", "rule_version_id": None, "standard": book_label(j.book_id), "standard_document_id": j.book_id,
            "clause": j.clause, "clause_page": lead.clause_page, "rule_kind": None, "rule_row_found": False,
            "field_roles": list(j.field_roles), "question": str(raw.get("issue") or "")[:400], "page_hint": [p for p in (raw.get("paper_page"),) if isinstance(p, int)],
            "page_hint_source": "nine reviewer", "clause_quote_ref": ref, "rule_quote_ref": None, "rule_tier": verdict.RULE_NOT_APPROVED,
            "rule_unapproved_why": NO_RULE_WHY,
        }  # fmt: skip
    if matched.matched and base is None:
        tier = None  # a rule the plan did not carry cannot be decided as that rule: it stays an F- item with no tier
    item["field_roles"] = list(j.field_roles) or list(item.get("field_roles") or [])
    answer_word, reason = ANSWER_OF[j.ai_verdict]
    answer: dict[str, Any] = {
        "item_id": item_id, "field_label": j.field_label or "", "paper_page": raw.get("paper_page"), "paper_quote": raw.get("paper_quote") or "",
        "clause_quote": raw.get("clause_quote") or "", "paper_figure": raw.get("paper_figure") or "", "clause_figure": raw.get("clause_figure") or "",
        "condition_quote": raw.get("condition_quote") or "", "condition_page": raw.get("condition_page"), "reasoning": raw.get("reasoning") or "",
        "comment": raw.get("comment") or "", "verdict": answer_word, "reason_code": reason,
    }  # fmt: skip
    if j.ai_verdict == "not_stated":
        answer["pages_searched"] = sorted(lead.call.paper_pages)  # only pages the reviewer was given
    if j.contradiction:
        answer["reasoning"] = DISAGREE
        answer["comment"] = DISAGREE
    finding = Finding(
        finding_id=fid, item_id=item_id, origin=origin, book_id=j.book_id, clause=j.clause, clause_page=lead.clause_page,
        field_label=j.field_label, field_roles=tuple(j.field_roles), tag=j.tag, paper_page=raw.get("paper_page") if isinstance(raw.get("paper_page"), int) else None,
        paper_quote=str(raw.get("paper_quote") or "") or None, clause_quote=str(raw.get("clause_quote") or "") or None,
        ai_verdict=j.ai_verdict, matched_rule_id=matched.rule_id if base is not None else None, rule_tier=tier,
        members=tuple(m.call.call_id for m in j.members), contradiction=j.contradiction,
        read_refs=tuple(dict.fromkeys(r for m in j.members for r in m.call.read_refs)),
    )  # fmt: skip
    return Built(finding, item, answer, cache)


# ---------------------------------------------------------------- the exit: today's runner


def register(runner: Any, built: Built) -> None:
    """Make the finding's item known to the runner (its exit looks an item up by id) and its clause entry known to the run's cache."""
    runner.items_by_id[str(built.item["item_id"])] = built.item
    runner.clauses._data.update(built.cache)  # the run's ClauseCache: the verified sentence is the book's own text


def decide_all(runner: Any, built: Iterable[Built], paper_pages: Mapping[int, str], model: str | None, usd_share: float = 0.0) -> list[dict]:
    """Every finding through the runner's own path: `decide` (gate, holds, context check), the silent-line step, then `emit` (the one
    exit, `final_cap`). Returns the stored lines. This module never sets a class, a word or a decision."""
    lines: list[dict] = []
    box = runner._box()
    for b in built:
        register(runner, b)
        line = runner.decide(b.item, b.answer, paper_pages, model, None, box, usd_share)
        line = runner.reread_silent_line(b.item, line, model, box)
        runner.emit(line)
        lines.append(runner.lines[str(b.item["item_id"])])
    return lines


def not_reviewed_reason(c: Checked) -> str | None:
    """Why a finding's quotes were not both verified (for the record); None when both were."""
    return None if c.paper_ok and c.clause_ok else (c.paper_why if not c.paper_ok else c.clause_why)


def process(
    raws: Iterable[tuple[RawFinding, Sent]],
    *,
    paper_pages: Mapping[int, str],
    books: standards.BookPages,
    rules: Iterable[Mapping],
    plan_items: Mapping[str, dict],
    tier_lookup: Callable[[Mapping], str | None] | None,
    book_label: Callable[[str | None], str | None] = lambda _b: None,
    fact_tags: Mapping[str, str | None] | None = None,
    registry: Mapping | None = None,
    prefer_roles: frozenset = frozenset(),
) -> list[Built]:
    """Verify, join, match and build, in that order: raw findings with the call each came from -> the items and answers `decide_all` takes."""
    rules = list(rules)
    checked = [check_raw(raw, sent, paper_pages, books) for raw, sent in raws]
    joined = join(checked, fact_tags=fact_tags, rules=registry, prefer_roles=prefer_roles)

    def text_of(book_id: str, page: int) -> str:
        return books.book(book_id).pages.get(page, "")

    return [
        build(j, rules=rules, plan_items=plan_items, tier_lookup=tier_lookup, book_text=text_of, book_label=book_label)
        for j in joined
    ]
