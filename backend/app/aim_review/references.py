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
vendor left open (`deferred`) is never touched. Every line keeps "AI, to be checked".
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
KIND_WORDS = "reference paper"
#: The role the held parts of a contract package carry.
PACKAGE_ROLE = "CONTRACT_DOCUMENT"
#: Statuses of a reference in the run's record.
READ, READ_IN_PART, NOT_SENT, FAILED = "read", "read in part", "not sent", "failed"
NOT_HELD, AMBIGUOUS, NOT_READABLE = (
    "not held",
    "held more than once: not chosen",
    "held, not on the list shown",
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


def held_schedules(conn, paper_id: str) -> dict[Key, list[str]]:
    """{Schedule: the held contract papers whose first heading lines say they ARE that Schedule}. Reads page 1 of each held contract
    paper only."""
    out: dict[Key, list[str]] = {}
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
        for key, parent in CC.package_part([(int(row[0]), row[1] or "")]):
            if parent is None and CC.DEPTH[key[0]] == 0:
                out.setdefault(key, []).append(doc_id)
    return out


def resolve(conn, paper_id: str, pages: dict[int, str]) -> Resolution:
    """The reference papers of a paper: each cited Schedule that exactly ONE held contract paper is. The rest are said, not guessed."""
    held = held_schedules(conn, paper_id)
    res = Resolution()
    for key in paper_cites(pages):
        ids = held.get(key, [])
        if not ids:
            res.not_held.append(name_of(key))
        elif len(ids) > 1:
            res.ambiguous.append(name_of(key))
        else:
            res.refs.append(Ref(ids[0], key, name_of(key)))
    return res


def plan_entries(conn, paper_id: str, allowed: frozenset[str]) -> tuple[list[Ref], int]:
    """(the reference papers the caller may read, how many the caller may not read: counted, never named). Read-only; for the plan."""
    from app import agent_review_standards

    pages = agent_review_standards.read_book(conn, str(paper_id)).pages
    res = resolve(conn, str(paper_id), pages)
    readable = [r for r in res.refs if r.doc_id in allowed]
    return readable, len(res.refs) - len(readable)


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


def check(
    conn, mdl, paper, lines: list[dict], allowed_books: frozenset[str], lead: str
) -> tuple[list[dict], set[str]]:
    """Check the open questions that name a reference paper against it. Returns (the run's `references` record, the reference
    document ids that were carried: they are not rule books). Changes `lines` in place. Never raises for a model or gate failure."""
    from app import claude_auto_approve

    try:
        if not claude_auto_approve.is_contract_paper(paper.paper_id):
            return [], set()
        res = resolve(conn, paper.paper_id, paper.pages)
    except sqlite3.Error as exc:
        log.info("reference papers not resolved (%s)", type(exc).__name__)
        return [], set()
    record: list[dict] = [
        {"part": n, "status": NOT_HELD, "reason": "", "questions": 0, "settled": 0} for n in res.not_held
    ] + [{"part": n, "status": AMBIGUOUS, "reason": "", "questions": 0, "settled": 0} for n in res.ambiguous]  # fmt: skip
    carried: set[str] = set()
    for ref in res.refs:
        mine = questions_for(lines, ref)
        if ref.doc_id not in allowed_books:
            record.append(
                _status(
                    ref,
                    NOT_SENT,
                    "not on the list of documents shown before the start",
                    len(mine),
                )
            )
        elif not mine:
            record.append(_status(ref, READ, "no open question names it", 0))
        else:
            carried.add(ref.doc_id)
            settled, read, held, failure = _ask_part(conn, mdl, paper, ref, mine, lead)
            if failure:
                gate = "gate_closed" in failure or ": stop " in failure
                why = "the send gate did not allow it" if gate else failure[:200]
                record.append(
                    _status(ref, NOT_SENT if gate else FAILED, why, len(mine), settled)
                )
            else:
                record.append(
                    _status(
                        ref,
                        READ if read == held else READ_IN_PART,
                        "",
                        len(mine),
                        settled,
                        read,
                        held,
                    )
                )
    return record, carried
