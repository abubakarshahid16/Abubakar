"""REFERENCE PAPERS of a contract review (order 14, owner's after-live order, item 2).

A contract paper cites other parts of its own package ("Schedule C"). Those parts are held in the library, yet the review used to ask the
vendor "please confirm where in Schedule C". Now: when the paper under review is a contract and cites a Schedule that ONE held
contract paper IS, that paper is a REFERENCE PAPER: read, not a rule book. A question of the review that names that Schedule is
checked against it instead of asked.

HOW A PART IS FOUND. By the contract code's own part reading (`app.contract_checks`): a held paper is "Schedule C" when its own
first heading lines say so; the paper cites "Schedule C" when its text names it. Only a Schedule (no higher part), only when exactly
ONE held contract paper is that Schedule: a part held more than once, or not held, is not chosen and not guessed ("held more than
once" / "not held" are said). Nothing is matched by file name, by shared words, or by a model.

PRIVACY (rule 1). A reference paper is listed in the plan's `documents.leaving` BEFORE the start, with why "cited by the paper; same
package", through the same send gate as any contract (`review_leaving._Gate`: Automatic never sends a contract; the explicit choice of
Claude does, and records it). It is read only if it is on the run's stored list (`allowed_books`); each call declares it
(`claude_approved.carrying`), so the gate that stops a contract without consent stops this call too. A part that was not sent is said
so in the run's `references` and its questions stay as they were. No route is widened here.

THE CHECK. One call per Schedule: the paper (cached block), the questions that name it, and the Schedule's pages (capped; a part
read in part says which pages). The model answers "agrees", "differs" or "not_stated" per question; an answer that quotes the part
counts only if code finds the quote on that page of the part (`steps._verified`). "agrees": the question is answered by the part, the
line becomes an AI "Met" (kept in "All points", not sent; never "by code"). "differs": a sent "AI opinion" that says what the part
states. "not_stated": the question stays, and says the part was read. No quote found: the question stays as it was. A value the
vendor left open (`deferred`) is never touched. Every line keeps the AI mark (`aim_review_gate.AI_MARK`).
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field

from .. import contract_checks as CC

log = logging.getLogger(__name__)

Key = tuple[str, str]

WHY_REFERENCE = "cited by the paper; same package"
#: A held Schedule the paper cites that no recorded link ties to it: OFFERED before the start, unticked; ticking it puts it on the shown list.
WHY_OFFER = "cited by this paper; tick to compare it"
WHY_CHOSEN_REFERENCE = "cited by this paper; chosen by you to compare"
KIND_WORDS = "reference paper"
#: The role the held parts of a contract package carry.
PACKAGE_ROLE = "CONTRACT_DOCUMENT"
#: Statuses of a reference in the run's record.
READ, READ_IN_PART, NOT_SENT, FAILED = "read", "read in part", "not sent", "failed"
NOT_HELD, AMBIGUOUS, NOT_READABLE, NOT_LINKED = (
    "not held",
    "held more than once: not chosen",
    "held, not on the list shown",
    "held, but not linked to this paper: not compared",
)
#: A line's code note when a reference paper settled or changed it (`sendable` reads the label, never this note).
NOTE_CHECKED = "reference_checked"
HIDDEN_COMMENT = "Checked against a part of the contract package that you may not open."
MAX_PART_CHARS = 100_000
MAX_QUESTIONS = 40
REF_MAX_TOKENS = 8000
MIN_QUOTE = 12  # a quote shorter than this proves nothing about a part


@dataclass(frozen=True)
class Ref:
    doc_id: str
    key: Key
    name: str


@dataclass
class Resolution:
    refs: list[Ref] = field(default_factory=list)
    not_held: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    #: A held contract paper IS the Schedule, but no recorded link ties it to this paper (same recorded project, or on the run's shown list):
    #: said, never compared.
    unlinked: list[str] = field(default_factory=list)
    #: Of `unlinked`, the ones held ONCE for that Schedule letter: the engineer may choose them at the start (the plan offers them).
    offers: list[Ref] = field(default_factory=list)


def name_of(key: Key) -> str:
    return CC._name((key, None))


def paper_cites(pages: dict[int, str]) -> list[Key]:
    """The Schedules the paper names (a Schedule: no higher part), in order of first mention, never the paper's own part."""
    own = {k for k, _p in CC.package_part(sorted(pages.items()))}
    out: list[Key] = []
    for _page, line in CC.lines_of(sorted(pages.items())):
        for (key, parent), _at in CC.parts(line):
            if (
                parent is None
                and CC.DEPTH[key[0]] == 0
                and key not in own
                and key not in out
            ):
                out.append(key)
    return out


def project_of(conn, doc_id: str) -> str | None:
    """The project RECORDED for a document (the classification's `project`), blank-normalised; None when none is recorded. This is the
    link between the parts of one package: never a likeness of names or numbers."""
    row = conn.execute(
        "SELECT project FROM document_classification WHERE document_id = ?",
        (str(doc_id),),
    ).fetchone()
    text = " ".join(str(row[0] or "").split()).casefold() if row else ""
    return text or None


def held_schedules(
    conn, paper_id: str, shown: frozenset[str] = frozenset()
) -> tuple[dict[Key, list[str]], dict[Key, list[str]]]:
    """({Schedule: the held contract papers that ARE that Schedule AND are tied to the paper by a RECORDED link: the same recorded
    project, or the engineer's choice at the start (the run's shown list, `shown`)}, {Schedule: those with neither link}). A part counts
    as a Schedule when its first heading lines say so (page 1 only). Never a likeness of names or numbers."""
    linked: dict[Key, list[str]] = {}
    other: dict[Key, list[str]] = {}
    mine = project_of(conn, paper_id)
    ids = [
        r[0]
        for r in conn.execute(
            "SELECT d.id FROM documents d JOIN document_classification c ON c.document_id = d.id"
            " WHERE c.document_role = ? AND d.id != ? ORDER BY d.id",
            (PACKAGE_ROLE, str(paper_id)),
        )
    ]
    for doc_id in ids:
        row = conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no LIMIT 1",
            (doc_id,),
        ).fetchone()
        if row is None:
            continue
        tied = doc_id in shown or (
            mine is not None and project_of(conn, doc_id) == mine
        )
        home = linked if tied else other
        for key, parent in CC.package_part([(int(row[0]), row[1] or "")]):
            if parent is None and CC.DEPTH[key[0]] == 0:
                home.setdefault(key, []).append(doc_id)
    return linked, other


def resolve(
    conn, paper_id: str, pages: dict[int, str], shown: frozenset[str] = frozenset()
) -> Resolution:
    """The reference papers of a paper: each cited Schedule that exactly ONE held contract paper is AND a recorded link ties to the paper (the same
    recorded project, or the run's shown list: the engineer's choice at the start). The rest are said, not guessed."""
    held, elsewhere = held_schedules(conn, paper_id, shown)
    res = Resolution()
    for key in paper_cites(pages):
        ids = held.get(key, [])
        if not ids:
            (res.unlinked if elsewhere.get(key) else res.not_held).append(name_of(key))
            if len(elsewhere.get(key, [])) == 1:
                res.offers.append(Ref(elsewhere[key][0], key, name_of(key)))
        elif len(chosen := pick(conn, ids, shown)) == 1:
            res.refs.append(Ref(chosen[0], key, name_of(key)))
        else:  # still tied: said, never merged; each offered on the plan so the engineer chooses one
            res.ambiguous.append(name_of(key))
            res.offers += [Ref(i, key, f"{name_of(key)} ({TIED})") for i in chosen]
    return res


#: The words a plan offer carries when several held papers are one cited Schedule and code could not choose.
TIED = "held more than once: choose one"
#: A held paper whose recorded title or file name says it is an attachment of a part, not the part itself.
_LOWER_WORDS = re.compile(
    r"\b(attachment|annex|appendix|exhibit|enclosure)s?\b", re.IGNORECASE
)


def pick(conn, ids: list[str], shown: frozenset[str] = frozenset()) -> list[str]:
    """Several held papers are one cited Schedule: [the one chosen] or the papers still tied (never merged, never guessed).
    In order: the engineer's choice (exactly one of them on the run's shown list); the main schedule over papers that are its
    attachments (a lower part heading their first page, or named so in their recorded title or file name); the highest
    RECORDED revision (all numbers, or all letters; a mix or a missing one is no order)."""
    mine = [i for i in ids if i in shown]
    if len(mine) == 1:
        return mine
    main = [i for i in ids if not _is_lower_part(conn, i)]
    ids = main or list(ids)
    revs = {i: _revision(conn, i) for i in ids}
    if (
        len(ids) > 1
        and all(r is not None for r in revs.values())
        and len({type(r) for r in revs.values()}) == 1
    ):
        top = max(revs.values())
        ids = [i for i in ids if revs[i] == top]
    return ids


def _is_lower_part(conn, doc_id: str) -> bool:
    row = conn.execute(
        "SELECT d.filename, c.title FROM documents d LEFT JOIN document_classification c ON c.document_id = d.id"
        " WHERE d.id = ?",
        (str(doc_id),),
    ).fetchone()
    if row and any(_LOWER_WORDS.search(str(x or "")) for x in row):
        return True
    first = conn.execute(
        "SELECT text FROM pages WHERE document_id = ? ORDER BY page_no LIMIT 1",
        (str(doc_id),),
    ).fetchone()
    opening = [
        ln.strip() for ln in str((first or [""])[0] or "").splitlines() if ln.strip()
    ]
    heads = [CC._heading_part(ln) for ln in opening[: CC.HEADING_LINES * CC.LIST_SPAN]]
    return any(h and CC.DEPTH.get(h[0][0], 0) > 0 for h in heads)


def _revision(conn, doc_id: str) -> int | tuple[int, str] | None:
    """The RECORDED revision as a number ("Rev. 2" -> 2) or a letter code ordered like a spreadsheet column, by length then
    letters ("Z" < "AA": (1, "Z") < (2, "AA")); None when none is recorded or unreadable."""
    row = conn.execute(
        "SELECT revision FROM document_classification WHERE document_id = ?",
        (str(doc_id),),
    ).fetchone()
    text = re.sub(
        r"(?i)^\s*(rev(ision)?\.?)\s*", "", str((row or [""])[0] or "")
    ).strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    return (len(text), text.upper()) if re.fullmatch(r"[A-Za-z]{1,2}", text) else None


def plan_entries(conn, paper_id: str, allowed: frozenset[str]) -> tuple[list[Ref], int]:
    """(the reference papers the caller may read, how many the caller may not read: counted, never named). Read-only; for the plan."""
    from app import agent_review_standards

    pages = agent_review_standards.read_book(conn, str(paper_id)).pages
    res = resolve(conn, str(paper_id), pages)
    readable = [r for r in res.refs if r.doc_id in allowed]
    return readable, len(res.refs) - len(readable)


def plan_offers(conn, paper_id: str, allowed: frozenset[str]) -> list[Ref]:
    """The held Schedules the paper cites that no recorded link ties to it and that the caller may read: offered before the start, never
    compared unless the engineer ticks them (they then join the shown list). A part the caller may not read is not named. Read-only."""
    from app import agent_review_standards

    pages = agent_review_standards.read_book(conn, str(paper_id)).pages
    return [
        r for r in resolve(conn, str(paper_id), pages).offers if r.doc_id in allowed
    ]


# ------------------------------------------------------------------ the check


REF_TASK = """TASK S6 - CHECK THE QUESTIONS AGAINST A PART OF THE SAME CONTRACT. Above is the paper under review. Below is %(name)s, another
part of the same contract package%(range)s. Each QUESTION asks the vendor to confirm something that the paper leaves to %(name)s or
says is in it. For each question decide from THE PART only:
 "agrees": the part states what the question asks about, and it agrees with the paper's own words;
 "differs": the part states it differently from the paper (or the paper's own words contradict the part);
 "not_stated": the part, as read, does not state it.
For "agrees" and "differs" give "page" (the part's page) and "quote": 5 to 30 words copied EXACTLY from that page of THE PART, and "comment":
what the part states, at most 35 words. A value left open there (TBA, TBD, By Contractor, blank) is "not_stated". Never invent a figure.
Reply with ONE JSON object only: {"checks": [{"n": n, "result": "agrees"|"differs"|"not_stated", "page": p, "quote": "...", "comment": "..."}]}
THE QUESTIONS:
%(items)s
THE PART (%(name)s):
%(part)s"""


def _part_text(pages: dict[int, str]) -> tuple[str, int, int]:
    """(the part's text with page markers, pages read, pages held), in page order, cut at MAX_PART_CHARS on a page boundary."""
    out, used = [], 0
    read = 0
    for n in sorted(pages):
        block = f"[page {n}]\n{pages[n]}\n"
        if used + len(block) > MAX_PART_CHARS and read:
            break
        out.append(block)
        used += len(block)
        read += 1
    return "".join(out), read, len(pages)


def _names_in(line: dict) -> set[Key]:
    text = " ".join(str(line.get(k) or "") for k in ("field", "comment", "quote"))
    return {(w, lab) for w, lab, _i in CC.labels(text)}


def eligible(line: dict) -> bool:
    """A line a reference paper may settle: an open Question that is not a vendor-deferred value and was judged."""
    note = str(line.get("code") or "")
    return (
        line.get("label") == "Question"
        and not line.get("deferred")
        and "not_judged" not in note
    )


def questions_for(lines: list[dict], ref: Ref) -> list[dict]:
    return [ln for ln in lines if eligible(ln) and ref.key in _names_in(ln)]


def _apply(
    line: dict, ref: Ref, answer: dict, part_pages: dict[int, str], partial: str
) -> str:
    """Apply one verified answer to its line; return what happened: agrees / differs / not_stated / unverified / skipped."""
    from . import steps as S

    result = str(answer.get("result") or "")
    comment = re.sub(r"\s+", " ", str(answer.get("comment") or "")).strip()[:400]
    note = str(line.get("code") or "")
    mark = f"{NOTE_CHECKED}: {ref.name}"
    named = [b for b in (line.get("named_books") or []) if isinstance(b, dict)]
    named.append({"id": ref.doc_id, "name": ref.name})
    if result == "not_stated":
        line["comment"] = (
            f"{ref.name} was read{partial} and does not state this. {line.get('comment') or ''}".strip()
        )
        line["named_books"] = named
        line["code"] = "; ".join(x for x in (note, mark) if x)
        return "not_stated"
    if result not in ("agrees", "differs"):
        return "skipped"
    quote = str(answer.get("quote") or "")
    page = answer.get("page") if isinstance(answer.get("page"), int) else None
    got = S._verified({"quote": quote, "page": page}, part_pages)
    if len(quote) < MIN_QUOTE or not got["verified"] or not comment:
        return "unverified"  # the part's words were not found on its page: the question stays as it was
    line["comment"] = f"{ref.name}, page {got['page']}: {comment}"
    line["named_books"] = named
    line["code"] = "; ".join(x for x in (note, mark) if x)
    if result == "agrees":
        line["label"], line["ask"] = "Met", ""
    else:
        line["label"], line["ask"] = "AI opinion", ""
    return result


def _status(
    ref: Ref,
    status: str,
    reason: str = "",
    checked: int = 0,
    settled: int = 0,
    read: int = 0,
    held: int = 0,
) -> dict:
    return {
        "id": ref.doc_id, "part": ref.name, "status": status, "reason": reason,
        "questions": checked, "settled": settled, "pages_read": read, "pages_held": held,
    }  # fmt: skip


def _ask_part(
    conn, mdl, paper, ref: Ref, mine: list[dict], lead: str
) -> tuple[int, int, int, str]:
    """One reference paper's questions asked in batches. Returns (settled, pages read, pages held, failure words or "")."""
    from app import agent_review_standards

    from . import steps as S
    from .engine import StepFailed

    part_pages = agent_review_standards.read_book(conn, ref.doc_id).pages
    text, read, held = _part_text(part_pages)
    partial = "" if read == held else f" (pages 1 to {read} of {held})"
    settled = 0
    for i in range(0, len(mine), MAX_QUESTIONS):
        by_n = dict(enumerate(mine[i : i + MAX_QUESTIONS], 1))
        items = "\n".join(
            S._dumps({"n": n, "field": ln.get("field"), "page": ln.get("page"), "paper_quote": ln.get("quote"),
                      "question": ln.get("comment")}) for n, ln in by_n.items()
        )  # fmt: skip
        try:
            out = mdl.ask(
                step="aim_reference",
                model=lead,
                system="",
                cached=S.paper_block(paper),
                prompt=REF_TASK
                % {
                    "name": ref.name,
                    "range": f": pages 1 to {read} of {held} only" if partial else "",
                    "items": items,
                    "part": text,
                },
                carries={paper.paper_id, ref.doc_id},
                max_tokens=REF_MAX_TOKENS,
            )
        except StepFailed as exc:
            return settled, read, held, str(exc)
        answers = out.get("checks") if isinstance(out, dict) else None
        for ans in answers if isinstance(answers, list) else []:
            n = ans.get("n") if isinstance(ans, dict) else None
            done = n in by_n and _apply(by_n[n], ref, ans, part_pages, partial)
            settled += done in ("agrees", "differs")
    return settled, read, held, ""


# ------------------------------------------------------------------ the Form against the cited Schedule (v2)

MAX_CITES = 40  # citing sentences compared per Schedule
CITE_CHARS = 500
WINDOW_CHARS = 60_000  # one window of the Schedule per call, the size the judge uses for a long paper
MAX_WINDOWS = 6

COMPARE_TASK = """TASK S7 - COMPARE THE PAPER UNDER REVIEW WITH %(name)s. Above is the paper. Below are sentences of the paper that point to
%(name)s, and part of %(name)s%(range)s. For each sentence decide whether what the paper states about that matter AGREES with what
%(name)s states, or DIFFERS (the two cannot both hold: a different value, period, order, party, condition or wording of a duty), or the
matter is not on these pages of %(name)s ("not_here": say nothing else about it). A sentence that only names %(name)s and states nothing
to compare is "not_here". Never call a value the paper or the schedule leaves open (TBA, TBD, By Contractor, blank) a difference.
For "agrees" and "differs" give BOTH sides, each as words copied EXACTLY (5 to 30 words): "form_quote" and "form_page" from the paper,
"part_quote" and "part_page" from %(name)s, and "comment": what differs or agrees, at most 35 words.
Reply with ONE JSON object only: {"compare": [{"n": n, "result": "agrees"|"differs"|"not_here", "form_quote": "...", "form_page": p,
 "part_quote": "...", "part_page": q, "comment": "..."}]}
THE PAPER'S SENTENCES:
%(items)s
%(name)s (pages %(first)d to %(last)d):
%(part)s"""


@dataclass(frozen=True)
class Cite:
    n: int
    page: int
    text: str


def _plainly_cites(line: str, key: Key) -> bool:
    """The line names the Schedule ITSELF, not only as the higher part of a sub-part ("Attachment II of Schedule C" points to the
    attachment). Every labelled part the contract code reads in the line counts once; the ones that are another part's higher part are taken off."""
    found = CC.parts(line)
    named = sum(1 for (k, parent), _at in found if k == key and parent is None)
    as_parent = sum(1 for (_k, parent), _at in found if parent == key)
    return named > as_parent


def citing_sentences(pages: dict[int, str], ref: Ref) -> list[Cite]:
    """The paper's own sentences that point to the Schedule, found by code: a line that names it as a Schedule (the contract code's
    part reading), with the next line of the page when the sentence wraps. A bare heading is not a sentence. In page order, no
    sentence twice, at most MAX_CITES."""
    out: list[Cite] = []
    seen: set[str] = set()
    for page in sorted(pages):
        lines = [ln.strip() for ln in pages[page].splitlines() if ln.strip()]
        for i, line in enumerate(lines):
            if not _plainly_cites(line, ref.key):
                continue
            if CC._heading_part(line) and len(line.split()) < 6:
                continue  # a heading naming the part, not a sentence about it
            text = (line + (" " + lines[i + 1] if i + 1 < len(lines) else ""))[
                :CITE_CHARS
            ]
            key = re.sub(
                r"\W+", "", line.lower()
            )  # the cited line itself: the same sentence on another page is one
            if key in seen:
                continue
            seen.add(key)
            out.append(Cite(len(out) + 1, page, text))
            if len(out) >= MAX_CITES:
                return out
    return out


def windows_of(pages: dict[int, str]) -> list[dict[int, str]]:
    """The Schedule's pages in order, cut into windows of at most WINDOW_CHARS (a page is never split); at most MAX_WINDOWS."""
    out: list[dict[int, str]] = []
    cur: dict[int, str] = {}
    used = 0
    for n in sorted(pages):
        size = len(pages[n]) + 12
        if cur and used + size > WINDOW_CHARS:
            out.append(cur)
            cur, used = {}, 0
        cur[n] = pages[n]
        used += size
    if cur:
        out.append(cur)
    return out[:MAX_WINDOWS]


def _window_text(window: dict[int, str]) -> str:
    return "".join(f"[page {n}]\n{t}\n" for n, t in sorted(window.items()))


def _both_sides(
    answer: dict, paper_pages: dict[int, str], part_pages: dict[int, str]
) -> dict | None:
    """The answer's two quotes, each found by code on its own page of its own paper; None when either is missing or not found."""
    from . import steps as S

    form = S._verified(
        {"quote": answer.get("form_quote"), "page": answer.get("form_page")},
        paper_pages,
    )
    part = S._verified(
        {"quote": answer.get("part_quote"), "page": answer.get("part_page")}, part_pages
    )
    comment = re.sub(r"\s+", " ", str(answer.get("comment") or "")).strip()[:300]
    if not (form["verified"] and part["verified"] and comment):
        return None
    if min(len(str(form["quote"])), len(str(part["quote"]))) < MIN_QUOTE:
        return None
    return {"form": form, "part": part, "comment": comment}


def differs_line(ref: Ref, found: dict, n: int) -> dict:
    """The sent AI opinion of one difference: both quotes and both pages. Never a Fail or Not met, never "by code"."""
    form, part = found["form"], found["part"]
    return {
        "item_id": f"R-{ref.key[1]}-{n:02d}", "finding_no": 1, "label": "AI opinion", "field": f"The Form against {ref.name}",
        "page": form["page"], "quote": form["quote"], "quote_unverified": "",
        "comment": f"Form page {form['page']} says: \u201c{form['quote']}\u201d; {ref.name} page {part['page']} says: \u201c{part['quote']}\u201d. {found['comment']}",
        "standard": ref.name, "book_document_id": "", "clause": "", "source": "held contract paper (same package)",
        "topic": f"The Form against {ref.name}", "code": f"{NOTE_CHECKED}: {ref.name}", "numbers": None,
        "named_books": [{"id": ref.doc_id, "name": ref.name}], "code_compare": None, "deferred": False, "ask": "",
    }  # fmt: skip


def _compare(conn, mdl, paper, ref: Ref, lead: str) -> tuple[list[dict], dict, str]:
    """The Form's sentences that point to the Schedule against the whole Schedule, window by window. Returns (the new lines: one AI
    opinion for each verified difference, stats {sentences, agrees, differs, windows}, failure words or "")."""
    from app import agent_review_standards

    from . import steps as S
    from .engine import StepFailed

    cites = citing_sentences(paper.pages, ref)
    stats = {"sentences": len(cites), "agrees": 0, "differs": 0, "windows": 0}
    if not cites:
        return [], stats, ""
    part_pages = agent_review_standards.read_book(conn, ref.doc_id).pages
    items = "\n".join(
        S._dumps({"n": c.n, "page": c.page, "sentence": c.text}) for c in cites
    )
    best: dict[int, tuple[str, dict]] = {}
    windows = windows_of(part_pages)
    for w in windows:
        first, last = min(w), max(w)
        try:
            out = mdl.ask(
                step="aim_reference", model=lead, system="", cached=S.paper_block(paper),
                prompt=COMPARE_TASK % {"name": ref.name, "range": "" if len(windows) == 1 else f" (window {stats['windows'] + 1} of {len(windows)})",
                                       "items": items, "first": first, "last": last, "part": _window_text(w)},
                carries={paper.paper_id, ref.doc_id}, max_tokens=REF_MAX_TOKENS,
            )  # fmt: skip
        except StepFailed as exc:
            return [], stats, str(exc)
        stats["windows"] += 1
        answers = out.get("compare") if isinstance(out, dict) else None
        for ans in answers if isinstance(answers, list) else []:
            n = ans.get("n") if isinstance(ans, dict) else None
            result = str(ans.get("result") or "") if isinstance(ans, dict) else ""
            if (
                not isinstance(n, int)
                or n < 1
                or n > len(cites)
                or result not in ("agrees", "differs")
            ):
                continue
            found = _both_sides(ans, paper.pages, part_pages)
            if found is None:
                continue  # a quote code cannot find on its page: the answer is dropped, nothing changes
            if (
                result == "differs" or n not in best
            ):  # a verified difference wins over an agreement from another window
                best[n] = (result, found)
    new: list[dict] = []
    for n in sorted(best):
        result, found = best[n]
        stats["agrees" if result == "agrees" else "differs"] += 1
        if result == "differs":
            new.append(differs_line(ref, found, n))
    return new, stats, ""


def _check_ref(conn, mdl, paper, ref: Ref, lines: list[dict], lead: str) -> dict:
    """What the review does with ONE reference paper that is on the run's list: its open questions, then the Form against it."""
    mine = questions_for(lines, ref)
    settled = read = held = 0
    if mine:
        settled, read, held, failure = _ask_part(conn, mdl, paper, ref, mine, lead)
        if failure:
            return _failed(ref, failure, len(mine), settled)
    new, stats, failure = _compare(conn, mdl, paper, ref, lead)
    if failure:
        return _failed(ref, failure, len(mine), settled)
    lines.extend(new)
    status = READ_IN_PART if held and read != held else READ
    out = _status(
        ref,
        status,
        ""
        if (mine or stats["sentences"])
        else "no open question and no sentence of the Form names it",
        len(mine),
        settled,
        read,
        held,
    )
    return {
        **out,
        "compared": stats["sentences"],
        "agrees": stats["agrees"],
        "differs": stats["differs"],
    }


def _failed(ref: Ref, failure: str, questions: int, settled: int) -> dict:
    """A call that failed: "failed" only when nothing was settled; after settled questions it is "read in part" and says how many
    (those lines are already decided and stay so)."""
    gate = "gate_closed" in failure or ": stop " in failure
    why = "the send gate did not allow it" if gate else failure[:200]
    if settled:
        return _status(
            ref,
            READ_IN_PART,
            f"{settled} of {questions} questions settled before a call stopped ({why})",
            questions,
            settled,
        )
    return _status(ref, NOT_SENT if gate else FAILED, why, questions, settled)


def check(
    conn, mdl, paper, lines: list[dict], allowed_books: frozenset[str], lead: str
) -> tuple[list[dict], set[str]]:
    """Check a contract against its reference papers. Returns (the run's `references` record, the reference document ids that were
    carried: they are not rule books). Changes `lines` in place: an open question that a Schedule answers is settled or marked read, and a
    sentence of the Form that DIFFERS from the Schedule it points to becomes a new sent AI opinion. Never raises for a model or gate failure."""
    from app import claude_auto_approve

    try:
        if not claude_auto_approve.is_contract_paper(paper.paper_id):
            return [], set()
        res = resolve(conn, paper.paper_id, paper.pages, allowed_books)
    except sqlite3.Error as exc:
        log.info("reference papers not resolved (%s)", type(exc).__name__)
        return [], set()
    record: list[dict] = [
        {"part": n, "status": NOT_HELD, "reason": "", "questions": 0, "settled": 0} for n in res.not_held
    ] + [{"part": n, "status": AMBIGUOUS, "reason": "", "questions": 0, "settled": 0} for n in res.ambiguous]  # fmt: skip
    record += [{"part": n, "status": NOT_LINKED, "reason": "", "questions": 0, "settled": 0} for n in res.unlinked]  # fmt: skip
    carried: set[str] = set()
    for ref in res.refs:
        if ref.doc_id not in allowed_books:
            record.append(
                _status(
                    ref,
                    NOT_SENT,
                    "not on the list of documents shown before the start",
                    len(questions_for(lines, ref)),
                )
            )
            continue
        carried.add(ref.doc_id)
        record.append(_check_ref(conn, mdl, paper, ref, lines, lead))
    return record, carried
