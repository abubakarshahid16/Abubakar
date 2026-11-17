"""THE CONTRACT RULE BOOK of a contract paper (order 14 LPD, P3; owner, 17 Nov 2026): when a CONTRACT paper is reviewed, the
GENERAL TERMS paper of its own package serves as its contract rule book, together with the contract checklist CT-01 to CT-08
(`reference/contract_checks.json`, an AI draft that no engineer has signed). Behind `contract_rule_book_enabled` (default off).

  * `package_papers(conn, doc_id, viewer)`: the other papers of the SAME contract package, by THE one finder of order 14 LPC
    (`contract_package.package_papers`: the same labelled cover number, role or kind contract, only papers the viewer may read).
  * `rule_book_of`: two signals must agree, and a false "no" is always safe (none is used; the run says none was recognised):
    (A) the paper's own title, labels, numbers, revision, version and year taken off, is EXACTLY the general terms phrase (any other
    word anywhere is a no; its page-1 heading lines decide by the same rule only when no title names the general terms);
    (B) when the paper under review lists its general terms under a label ("Schedule X  General Terms and Conditions"), the
    candidate's own label is that label. With no such entry, (A) decides alone and only when exactly one paper passes it. Never a
    document id, a file name or a layout of one paper (CLAUDE.md rule 13).
  * `checklist_items`: CT-01 to CT-08 as items of the general review's part 2 (the path a procedure's checklist takes).
  * `code_lines`: what code decides of CT-01 to CT-03 (`contract_checks.run_all`) as lines of part 2, each a Query for the engineer.
  * `mark`: every line that comes from the rule book or the checklist says "AI draft, engineer to confirm" and is internal only. The
    general review never writes Pass or Fail (`agent_general_review.finalize_line`) and its lines never reach the contractor copy.

What may leave the machine is decided elsewhere and unchanged: the plan lists the rule book before the start (`review_leaving`), a run
with a stored list sends only what the list names, and a contract goes to Claude only on an explicit Claude start (rule 1). Reads
only; no model, no network.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Mapping
from typing import Any

from . import contract_checks
from .agent_general_review import CLASS_QUERY

DRAFT = contract_checks.RULE_STATE  # "AI draft, engineer to confirm"
CONTRACT_KIND = "contract"
SOURCE_BOOK = "contract rule book"
SOURCE_CHECKLIST = "contract checklist"
SUB_CODE = "contract check by code"
WHY_LISTED = f"the general terms of this contract's package, used as its contract rule book ({DRAFT})"
NONE_FOUND = "no general terms paper recognised in this package"
SEVERAL = "{n} papers of this contract's package say general terms: none is used, the engineer names it"
NOT_LISTED = "the general terms paper was not on the list shown before the start, so it was not sent and not used"
NO_YES = "the general terms paper is a contract: it goes to Claude only on an explicit Claude start"
HEAD_LINES = 6  # the heading lines of page 1: a title, a header and a number; never the body, which may cite another paper

#: THE general terms, as the whole of what a title says once its labels, numbers, revision, version and year are taken off. Nothing
#: else may be left anywhere in the title (lead decision, round 3 of #1880: no list of qualifiers, no split into parts).
_IS_GENERAL_TERMS = re.compile(
    r"^(?:the )?general (?:terms(?: (?:and )?conditions?)?|conditions?(?: of (?:the )?contract)?)$"
)
#: The title speaks of the general terms at all ("general terms", "general conditions"): then it decides, yes or no.
_NAMES_GENERAL_TERMS = re.compile(r"\bgeneral (?:terms?|conditions?)\b")
#: The tokens that only label, number or date a paper: a label word with its id, a revision or version with its id.
_LABEL_WORDS = frozenset(
    {"schedule", "annex", "appendix", "exhibit", "attachment", "att", "enclosure", "part", "section", "volume", "vol",
     "book", "chapter"}
)  # fmt: skip
_REVISION_WORDS = frozenset({"rev", "revision", "version", "ver"})
_ID = re.compile(r"^(?:[a-z]{1,2}|[ivxl]{1,6}|\d{1,4}[a-z]?)$")
_NUMBER_ONLY = re.compile(
    r"^(?:\d{1,4}[a-z]?|v\d{1,3})$"
)  # a number, a year, a version
YES, NO, SILENT = "yes", "no", "silent"


def enabled() -> bool:
    from .config import settings

    return bool(getattr(settings, "contract_rule_book_enabled", False))


# ------------------------------------------------------------------------------------------------ the package (the one finder)


def _head(conn: sqlite3.Connection, doc: str) -> str:
    row = conn.execute(
        "SELECT text FROM pages WHERE document_id = ? ORDER BY page_no LIMIT 1", (doc,)
    ).fetchone()
    lines = [
        ln.strip()
        for ln in str((row[0] if row else "") or "").splitlines()
        if ln.strip()
    ]
    return "\n".join(lines[:HEAD_LINES])


def package_papers(
    conn: sqlite3.Connection, doc_id: str, viewer: Iterable[str]
) -> list[str]:
    """The ids of the other papers of the paper's contract package that `viewer` may read: `contract_package.package_papers`, the
    ONE package finder (a filter only narrows, rule 5)."""
    from . import contract_package

    return [
        str(p["document_id"])
        for p in contract_package.package_papers(conn, doc_id, frozenset(viewer))
    ]


# ------------------------------------------------------------------------------------------------ the rule book


def _titles(conn: sqlite3.Connection, doc: str) -> list[str]:
    """The paper's own titles: its stored title and its file name (without the extension)."""
    out = []
    for sql in (
        "SELECT title FROM document_classification WHERE document_id = ?",
        "SELECT filename FROM documents WHERE id = ?",
    ):
        try:
            row = conn.execute(sql, (doc,)).fetchone()
        except sqlite3.Error:
            row = None
        text = str((row[0] if row else "") or "")
        out.append(re.sub(r"\.[A-Za-z0-9]{2,5}$", "", text))
    return out


def strip_labels(text: str) -> str:
    """The words of a title or a list entry with ONLY its labels, numbers, revision, version and year taken off, folded."""
    words = re.sub(
        r"[^a-z0-9]+", " ", str(text or "").lower().replace("&", " and ")
    ).split()
    out, i = [], 0
    while i < len(words):
        w = words[i]
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if (w in _LABEL_WORDS or w in _REVISION_WORDS) and _ID.match(nxt):
            i += 2
            continue
        if _NUMBER_ONLY.match(w):
            i += 1
            continue
        out.append(w)
        i += 1
    return " ".join(out)


def title_state(text: str) -> str:
    """YES when, labels and numbers taken off, the title is EXACTLY the general terms; NO when it names the general terms with any
    other word anywhere (a supplement, an amendment, a summary of them...); SILENT when it does not name them. A false NO is safe:
    the paper is then not used and the run says none was recognised."""
    left = strip_labels(text)
    if _IS_GENERAL_TERMS.match(left):
        return YES
    return NO if _NAMES_GENERAL_TERMS.search(left) else SILENT


def _combined(states: Iterable[str]) -> str:
    """NO wins (the safe side), then YES, else SILENT."""
    states = list(states)
    return NO if NO in states else (YES if YES in states else SILENT)


def says_general_terms(conn: sqlite3.Connection, doc: str) -> str:
    """Signal (A): is the paper, by its own titles, the general terms? Its titles decide when they name the general terms at all;
    only when they are silent do its page-1 heading lines decide, by the same strict rule. YES, NO or SILENT."""
    title = _combined(title_state(x) for x in _titles(conn, doc))
    if title != SILENT:
        return title
    return _combined(title_state(x) for x in _head(conn, doc).splitlines())


def named_general_terms(conn: sqlite3.Connection, paper: str) -> frozenset:
    """Signal (B): the labels the paper under review gives its general terms in its own list of contract documents: a labelled
    reference ("Schedule X") whose listed name (the rest of its line, else the next line) BEGINS with the general terms phrase.
    Only a pointer: the paper so labelled must also pass (A)."""
    lines = contract_checks.lines_of(_pages(conn, paper))
    out = set()
    for i, (_p, line) in enumerate(lines):
        for word, label, at in contract_checks.labels(line):
            rest = strip_labels(line[at:])
            if not rest and i + 1 < len(lines):
                rest = strip_labels(lines[i + 1][1])
            if re.match(r"(?:the )?general (?:terms|conditions?)\b", rest):
                out.add((word, label.upper()))
    return frozenset(out)


def rule_book_of(
    conn: sqlite3.Connection, paper: str, viewer: Iterable[str], kind: str | None
) -> dict:
    """`{"id": doc id or None, "why": words}`. The general terms paper of the paper's package when the switch is on and the paper is
    a contract: a paper of its package (the one finder) that passes (A), its own title is exactly the general terms; when the paper
    under review lists its general terms under a label (B), that paper's own label must be it too. Exactly one, else none."""
    if not enabled() or str(kind or "") != CONTRACT_KIND:
        return {"id": None, "why": "not used"}
    from . import contract_package

    package = contract_package.package_papers(conn, paper, frozenset(viewer))
    passes = [p for p in package if says_general_terms(conn, p["document_id"]) == YES]
    named = named_general_terms(conn, paper)
    if named:  # the two signals must agree: the paper's own label for its general terms, and the strict title
        passes = [
            p
            for p in passes
            if {(w, lab.upper()) for (w, lab), _up in p["parts"]} & named
        ]
    pick = [str(p["document_id"]) for p in passes]
    if len(pick) == 1:
        return {"id": pick[0], "why": WHY_LISTED}
    return {"id": None, "why": SEVERAL.format(n=len(pick)) if pick else NONE_FOUND}


def may_carry(
    conn: sqlite3.Connection, run_id: str, book: str, local: bool
) -> str | None:
    """None when the run may carry the rule book, else why not. A local run sends nothing. A Claude run: only when the list shown
    before the start names it, or (no list stored, an older route) the owner's recorded yes for that contract. The send gate
    (`claude_approved.refusal`) still asks its own questions at send time."""
    if local:
        return None
    from . import review_shown

    shown = review_shown.shown_ids(conn, run_id)
    if shown is not None:
        return None if book in shown else NOT_LISTED
    from . import contract_yes

    return None if contract_yes.has_yes(book) else NO_YES


# ------------------------------------------------------------------------------------------------ the checklist CT-01..CT-08


def checklist_items() -> list[dict]:
    """CT-01 to CT-08 as items of part 2 (the shape `agent_general_review.checklist_items` gives a procedure's checklist)."""
    out = []
    for it in contract_checks.checklist().get("items") or []:
        ct, title = str(it["id"]), " ".join(str(it.get("title") or "").split())
        q = f"Topic: {ct} {title}"
        if it.get("not_code"):
            q += f". Ask the engineer when: {' '.join(str(it['not_code']).split())}"
        out.append(
            {
                "item_id": ct,
                "source": SOURCE_CHECKLIST,
                "topic": f"{ct} {title} ({DRAFT})",
                "question": q,
                "clause_refs": [],
                "draft": DRAFT,
            }
        )
    return out


def checklist_ids() -> frozenset[str]:
    return frozenset(i["item_id"] for i in checklist_items())


def _pages(conn: sqlite3.Connection, doc: str) -> contract_checks.Pages:
    return [
        (int(p), t or "")
        for p, t in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (doc,),
        )
    ]


def code_lines(
    conn: sqlite3.Connection, paper: str, package: Iterable[str]
) -> list[dict]:
    """What code decides of CT-01 to CT-03 on the paper and the held papers of its package (`contract_checks.run_all`, never
    `complete`: the package held may not be the whole contract). One Query for the engineer per result to look at; a consistent
    result is coverage, not a line. A quote is carried only when code verified it on its page."""
    results = contract_checks.run_all(
        _pages(conn, paper), {d: _pages(conn, d) for d in package}
    )
    out = []
    for r in results:
        if not r.is_row:
            continue
        q = next((x for x in r.quotes if x.verified), None)
        out.append(
            {
                "part": 2,
                "document": paper,
                "item_id": r.ct,
                "checklist_item": r.ct,
                "topic": f"{r.ct} {r.topic} ({DRAFT})",
                "verdict_class": CLASS_QUERY,
                "subkind": SUB_CODE,
                "text": f"{r.ct} {r.topic}: {r.outcome}: {r.value}. {r.message}",
                "reason": r.outcome,
                **(
                    {
                        "quote_a": {"document": paper, "page": q.page, "text": q.text},
                        "quotes_verified_by_code": True,
                    }
                    if q
                    else {}
                ),
            }
        )
    return out


# ------------------------------------------------------------------------------------------------ the label


def source_of(line: Mapping, books: Iterable[str], items: Iterable[str]) -> str | None:
    """Which draft a line comes from: the rule book (a finding against that paper), the checklist (one of its items), or None."""
    if line.get("other_document") and str(line["other_document"]) in set(books):
        return SOURCE_BOOK
    item = str(line.get("checklist_item") or line.get("item_id") or "")
    return SOURCE_CHECKLIST if item and item in set(items) else None


def mark(line: Mapping, books: Iterable[str], items: Iterable[str]) -> dict[str, Any]:
    """A line from the contract rule book or the checklist says so, and that it is an AI draft for the engineer to confirm, in its
    own text (the words every file prints) and its record. Internal only. Any other line comes back unchanged."""
    out = dict(line)
    src = source_of(out, books, items)
    if src is None:
        return out
    out["rule_state"], out["draft_source"], out["internal_only"] = DRAFT, src, True
    if src == SOURCE_CHECKLIST and not out.get(
        "checklist_item"
    ):  # its CT id stays on the line after the line id is given
        out["checklist_item"] = str(out.get("item_id"))
    head = f"{src} ({DRAFT})"
    if not str(out.get("text") or "").startswith(head):
        out["text"] = f"{head}: {out.get('text') or ''}"
    return out


# ------------------------------------------------------------------------------------------------ one call for the run


def for_run(
    conn: sqlite3.Connection,
    run_id: str,
    paper: str,
    kind: str | None,
    scope: Iterable[str],
    project: Iterable[str],
    local: bool,
) -> dict:
    """What a general review of `paper` adds: `{"book": id or None, "items": [...], "code_lines": [...], "lines": [...]}`. Switch
    off, or not a contract: nothing (the run is exactly as before). The rule book joins the project papers only when the caller may
    read it, it passes the project-paper checks (`agent_general_review.check_project_papers`: not blocked, not a rule book, has
    text) and the run may carry it (`may_carry`); otherwise one "Not reviewed" line says why it was not used."""
    from .agent_general_review import CLASS_NOT_REVIEWED, check_project_papers

    none: dict = {
        "book": None,
        "accepted": [],
        "items": [],
        "code_lines": [],
        "lines": [],
    }
    if not enabled() or str(kind or "") != CONTRACT_KIND:
        return none
    scope = frozenset(str(d) for d in scope)
    found = rule_book_of(conn, paper, scope, kind)
    book, why, accepted = found["id"], found["why"], []
    if book and book not in set(project):
        accepted, problems = check_project_papers(conn, paper, [book], scope)
        why = "; ".join(problems) if problems else may_carry(conn, run_id, book, local)
        book = book if accepted and not why else None
    out = {
        **none,
        "book": book,
        "accepted": [{**a, "rule_book": DRAFT} for a in accepted] if book else [],
        "items": checklist_items(),
        "code_lines": code_lines(conn, paper, package_papers(conn, paper, scope)),
    }
    if book is None:
        out["lines"] = [
            {"part": 4, "verdict_class": CLASS_NOT_REVIEWED, "subkind": None, "document": paper,
             "text": f"not reviewed: contract rule book not used: {why}"}
        ]  # fmt: skip
    return out
