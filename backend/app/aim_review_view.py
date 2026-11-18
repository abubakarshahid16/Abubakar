"""What the general review's results page says (order 14, piece C): ONE assembly of a stored general run into the page's JSON.

The page, the Excel file and the completeness check all read THIS dict, so they cannot disagree about what a line says. Reads only:
the stored run and its lines (`aim_review_store`), the titles of the rule books (`documents`), nothing else. No model, no network, no
write. Every count states its boundary; a null renders as nothing (never 0); a rule book the caller may not read is counted, never
named. The labels the person SEES are the stored `shown_label` (written by `aim_review_store`, the one home of that table).
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import (
    aim_review,
    aim_review_gate,
    aim_review_measured,
    aim_review_store,
    review_shown,
)

#: The boundary every count carries.
BOUNDARY = "this paper, this review"
#: The sentence when rule books apply that were not on the list the person saw (the same words the older reviews use).
#: The sentence's one home is `review_shown` (the rule check's notes say it too).
UNLISTED_SENTENCE = review_shown.FOUND_DURING_REVIEW_WORDS
NOT_FINISHED_WORDS = "This general review has not finished, so it has no file yet."
#: Run states that have lines to show: "done" (finished) and "stopped" (ended early; the lines so far are kept).
_SHOWN_STATUS = {"done": "completed", "completed": "completed", "stopped": "stopped"}


class NotFinished(Exception):
    """The run is queued or running (or failed with nothing stored): there is nothing to count yet."""


def _json(text, default):
    try:
        got = json.loads(text) if text else default
    except ValueError:
        return default
    return got if isinstance(got, type(default)) else default


def _blank(value) -> Any:
    """A stored null or empty text is None (rendered as nothing), never "0" or "None"."""
    return None if value is None or value == "" else value


#: What a line says instead of the rule book's name, clause and id when the viewer may not read that book (rule 5).
HIDDEN_BOOK_WORDS = "a rule book you may not open"


def book_hidden(conn, row: dict, scope) -> bool:
    """THE one decision "this line's rule book is hidden from this viewer" (rule 5; REVIEW.md: decide it in ONE function from the
    stored document and the viewer's read set). True when the line names a book id the viewer cannot open: its own book, or a
    book its words name (an always-on line's `named_books`): the viewer's read set does not hold it, or the book is no longer
    in the library (then no stored id is served either, only the fixed words: review fix check). No book id, or no viewer
    (`scope` None: the app's own counting), hides nothing."""
    if scope is None:
        return False
    ids = [str(row.get("book_document_id") or "")] + [
        str(b.get("id") or "") for b in _named_books(row)
    ]
    for doc_id in (i for i in ids if i):
        held = conn.execute(
            "SELECT 1 FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if held is None or not scope.may_read(doc_id):
            return True
    return False


def _named_books(row: dict) -> list[dict]:
    named = row.get("named_books")
    if named is None:
        named = _json(row.get("named_books_json"), [])
    return [b for b in named or [] if isinstance(b, dict)]


def line_view(row: dict, n: int, hidden: bool = False) -> dict:
    """One stored line as the page and the file show it. `n` is the 1-based position in line order. `hidden` (from `book_hidden`):
    the book's name, clause and id are not served, and the name is not left in the comment either; the line is still counted."""
    if hidden:
        comment = str(row.get("comment") or "")
        names = [str(row.get("standard") or "")] + [
            str(b.get("name") or "") for b in _named_books(row)
        ]
        for name in sorted(
            {n for n in names if n}, key=len, reverse=True
        ):  # the longest name first
            comment = comment.replace(name, HIDDEN_BOOK_WORDS)
        row = {
            **row,
            "standard": HIDDEN_BOOK_WORDS,
            "clause": "",
            "book_document_id": None,
            "comment": comment,
            # code's note may hold the rule's words or numbers: only its state words stay (they decide whether the line is sent
            # and how it groups, the same for every viewer); the comparison's words are not served either (`compared`)
            "code_note": _state_words(row.get("code_note")),
        }
    page = row.get("page")
    return {
        "n": n,
        "field": row.get("field") or "",
        "page": page if isinstance(page, int) else None,
        "label": row.get("label") or "",
        "shown_label": row.get("shown_label") or "",
        "comment": row.get("comment") or "",
        "quote": row.get("quote") or "",
        "item_id": row.get("item_id") or "",
        "standard": row.get("standard") or "",
        "clause": row.get("clause") or "",
        "source": row.get("source") or "",
        "topic": row.get("topic") or "",
        "code_note": "; ".join(
            x
            for x in str(row.get("code_note") or "").split("; ")
            if not x.startswith("same point as line")
        ),
        "quote_unverified": bool(row.get("quote_unverified")),
        "book_document_id": _blank(row.get("book_document_id")),
        "compared": "" if hidden else _compared(row),
        "compare_kind": _compare_kind(row),
        # recorded state (18 Nov 2026): what a Question asks ("" when not recorded: an older run), whether its value is left
        # open, and the judge's numbers (none for a book the viewer may not open: rule 5)
        "ask": row.get("ask") or "",
        "deferred": bool(row.get("deferred")),
        "numbers": None if hidden else _numbers(row),
    }


def _numbers(row: dict) -> dict | None:
    """The judge's numbers as stored (value, unit, operator, limit), or None."""
    nums = row.get("numbers")
    if nums is None:
        nums = _json(row.get("numbers_json"), None)
    return nums if isinstance(nums, dict) and nums else None


#: The code-note words that are STATE, not text: whether a line is sent (`aim_review.NOT_SENT_NOTES`) and its provisional kind.
_STATE_WORDS = frozenset(aim_review.NOT_SENT_NOTES) | {
    aim_review.PROVISIONAL_FAILS,
    aim_review.PROVISIONAL_UNCHECKED,
}


def _state_words(code_note) -> str:
    """A code note cut to its state words ("edited: repeats line 3" -> "edited"); every other part is dropped."""
    words = (x.split(":", 1)[0].strip() for x in str(code_note or "").split(";"))
    return "; ".join(dict.fromkeys(w for w in words if w in _STATE_WORDS))


def _note_words(code_note) -> set[str]:
    """The words a code note's parts start with ("edited: repeats line 3; answered: ..." -> {"edited", "answered"})."""
    return {x.split(":", 1)[0].strip() for x in str(code_note or "").split(";")}


def _provisional_kind(code_note) -> str:
    """The provisional part of a code note ("provisional_unchecked", "provisional_fails", ...), or ""."""
    parts = (x.strip() for x in str(code_note or "").split(";"))
    return next((x for x in parts if x.startswith(aim_review.PROVISIONAL)), "")


def _compared(row: dict) -> str:
    """The words of code's comparison at this place ("25 bar <= 20 bar: false"), or ""."""
    cmp_ = row.get("code_compare")
    if cmp_ is None:
        cmp_ = _json(row.get("code_compare_json"), {})
    return str(cmp_.get("why") or "") if isinstance(cmp_, dict) else ""


def _compare_kind(row: dict) -> str:
    """What code's comparison at this place read its values from (`code_compare.read_from`), or "": part of the key of a comment
    (`_keys`), so lines code compared differently never share one comment."""
    cmp_ = row.get("code_compare")
    if cmp_ is None:
        cmp_ = _json(row.get("code_compare_json"), {})
    return str(cmp_.get("read_from") or "") if isinstance(cmp_, dict) else ""


# ------------------------------------------------------------------ comments: one per point, every place listed


def _place(p: dict) -> str:
    where = f"page {p['page']}" if p.get("page") is not None else "no page"
    quote = f': "{p["quote"]}"' if p.get("quote") else ""
    numbers = f" ({p['compared']})" if p.get("compared") else ""
    return f"{where}{quote}{numbers}"


def _field_key(field) -> str:
    """A field name folded for comparison: case, spacing and punctuation do not make another field."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", str(field or "").lower()).split())


def _keys(sent: list[dict]) -> dict[int, tuple]:
    """{line number: the key of its comment}. ONE comment per CHECK: the lines of one checklist item that show the same label,
    the same compare kind and the same provisional kind (a provisional figure never joins an ordinary Question), across tags,
    lines, sheets and pages (the repeats a strict judge marks WEAK). Lines of DIFFERENT
    items are never merged, whatever their label or rule book (18 Nov 2026: long lists of different points buried findings a
    senior engineer would raise one by one), so a code-compared Fail never joins a Question. A line with no item stays alone.
    Every sent line is in exactly one comment, which keeps each place's own words; every line stays a point."""
    return {
        p["n"]: ("item", p.get("item_id") or f"line-{p['n']}", p["shown_label"], p.get("compare_kind") or "",
                 _provisional_kind(p.get("code_note")))
        for p in sent
    }  # fmt: skip


def group_comments(points: list[dict]) -> list[dict]:
    """THE comments of a run (the page, the file and the completeness check read this one list): the SENT lines grouped by
    `_keys`, in line order of each group's first line. One line: that line as it is. Several: one comment that keeps every
    member's own words (`_same_point`), or the places of one field said in the same words (`_places_of`).
    Each comment names the lines it covers."""
    sent = [p for p in points if aim_review.sendable(p)]
    keys = _keys(sent)
    groups: dict[tuple, list[dict]] = {}
    for p in sent:
        groups.setdefault(keys[p["n"]], []).append(p)
    out = []
    for members in groups.values():
        members = sorted(
            members, key=lambda m: (m["page"] is None, m["page"] or 0, m["n"])
        )
        if len(members) == 1:
            pages = [members[0]["page"]] if members[0]["page"] is not None else []
            out.append({**members[0], "lines": [members[0]["n"]], "pages": pages})
        elif (
            len({_field_key(m.get("field")) for m in members}) > 1
            or len({m.get("comment") or "" for m in members}) > 1
        ):
            out.append(
                _same_point(members)
            )  # LOSSLESS: each place's own words, field, page, quote and value
        else:
            out.append(
                _places_of(members)
            )  # one field, the same words: said once, every place listed
    return sorted(out, key=lambda g: g["n"])


def _places_of(members: list[dict]) -> dict:
    """ONE comment for the places of one point in one field: the point said once, every place with its quote and numbers."""
    first = members[0]
    pages = sorted({m["page"] for m in members if m["page"] is not None})
    places = "; ".join(_place(m) for m in members)
    return {
        **first,
        "n": min(m["n"] for m in members),
        "lines": sorted(m["n"] for m in members),
        "pages": pages,
        "comment": f"{first['comment']}\nThe same point at {len(members)} places (pages {', '.join(map(str, pages)) or 'none'}): {places}.",
        "quote": " | ".join(f"page {m['page']}: {m['quote']}" if m["page"] is not None else m["quote"]
                            for m in members if m["quote"]),
        "code_note": "; ".join(dict.fromkeys(m["code_note"] for m in members if m["code_note"])),
        "quote_unverified": any(m["quote_unverified"] for m in members),
        **_state(members),
    }  # fmt: skip


def _state(members: list[dict]) -> dict:
    """A merged comment's own state, never one member's: what it asks by the safe rule (any concern -> concern; else any value left
    open -> open; "confirm" only when every member says confirm; else unknown ""), left open when any member is, the judge's
    numbers only when every member has the same, and every member's comparison with its page. Each point keeps its own on
    "All points"."""
    asks = {m.get("ask") or "" for m in members}
    ask = (
        "concern"
        if "concern" in asks
        else "open"
        if "open" in asks
        else "confirm"
        if asks == {"confirm"}
        else ""
    )
    nums = [m.get("numbers") for m in members]
    compared = " | ".join(
        f"page {m['page']}: {m['compared']}"
        if m.get("page") is not None
        else m["compared"]
        for m in members
        if m.get("compared")
    )
    return {
        "ask": ask,
        "deferred": any(m.get("deferred") for m in members),
        "numbers": nums[0] if all(n == nums[0] for n in nums) else None,
        "compared": compared,
    }


def _member(m: dict) -> str:
    where = f"page {m['page']}" if m.get("page") is not None else "no page"
    quote = f' (quote: "{m["quote"]}")' if m.get("quote") else ""
    numbers = f" ({m['compared']})" if m.get("compared") else ""
    return f"{m.get('field') or 'no field'} ({where}): {m.get('comment') or ''}{quote}{numbers}"


def _same_point(members: list[dict]) -> dict:
    """ONE comment for the editor's group, LOSSLESS: the first member's words, then every other member's field, page, own
    comment in full and quote. Lines stay one per place (All points keeps each)."""
    members = sorted(members, key=lambda m: m["n"])
    first, others = members[0], members[1:]
    pages = sorted({m["page"] for m in members if m["page"] is not None})
    return {
        **first,
        "lines": [m["n"] for m in members],
        "pages": pages,
        "comment": f"{first['comment']}\nThe same point at {len(others)} more place{'' if len(others) == 1 else 's'}: "
        + "; ".join(_member(m) for m in others),
        "quote": " | ".join(f"page {m['page']}: {m['quote']}" if m["page"] is not None else m["quote"]
                            for m in members if m["quote"]),
        "code_note": "; ".join(dict.fromkeys(m["code_note"] for m in members if m["code_note"])),
        "quote_unverified": any(m["quote_unverified"] for m in members),
        **_state(members),
    }  # fmt: skip


def _titles(conn, ids: list[str], scope) -> tuple[dict[str, str], int]:
    """({document id: title} of the books the caller may read, how many the caller may not read)."""
    out: dict[str, str] = {}
    hidden = 0
    for doc_id in ids:
        row = conn.execute(
            "SELECT filename FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if row is None or (scope is not None and not scope.may_read(doc_id)):
            hidden += 1
        else:
            out[doc_id] = str(row["filename"] or "")
    return out, hidden


def _books(conn, run: dict, scope) -> tuple[list[dict], int]:
    items = _json(run.get("books_json"), [])
    ids, why = [], {}
    for it in items:
        doc_id = str(it.get("id") or "") if isinstance(it, dict) else str(it or "")
        if doc_id:
            ids.append(doc_id)
            why[doc_id] = str(it.get("why") or "") if isinstance(it, dict) else ""
    titles, hidden = _titles(conn, ids, scope)
    return [
        {"id": i, "title": titles[i], "why": why[i]} for i in ids if i in titles
    ], hidden


def _checklist(conn, run: dict, points: list[dict]) -> dict:
    """The checklist the run judged. `items` counts the saved checklist's items (else the distinct items the run judged: one item
    may give several lines); `always_items` counts the items every review checks besides the checklist (`aim_review.always`),
    which are not part of the saved checklist."""
    from .aim_review import always

    always_ids = {p["item_id"] for p in points if always.is_always(p.get("item_id"))}
    judged = {p["item_id"] for p in points if p.get("item_id")} - always_ids
    key = _blank(run.get("checklist_key"))
    row = None
    if key and run.get("checklist_sha256"):
        row = conn.execute(
            f"SELECT items, built_from FROM {aim_review_store.CHECKLISTS} WHERE key = ? AND sha256 = ?",
            (key, run["checklist_sha256"]),
        ).fetchone()
    reused = run.get("checklist_reused")
    return {
        "key": key,
        "items": row["items"]
        if row and row["items"] is not None
        else (len(judged) or None),
        "always_items": len(always_ids),
        "reused": None if reused is None else bool(reused),
        "built_from": row["built_from"] if row else None,
    }


def _latest_old(conn, paper_id: str) -> str | None:
    """The start time of the paper's newest finished review of the EARLIER engines (general runs are not in it)."""
    from . import review_points_service

    ids = [i for i in review_points_service.runs_of_paper(conn, paper_id) if i]
    if not ids:
        return None
    marks = ",".join("?" for _ in ids)
    row = conn.execute(
        f"SELECT MAX(COALESCE(started_at, created_at)) FROM review_runs WHERE id IN ({marks})",
        ids,
    ).fetchone()
    return row[0] if row and row[0] else None


def is_latest(conn, paper_id: str, run: dict) -> bool:
    """True when no finished earlier-engine review of the paper is newer than this general run: the page then draws the general
    results; otherwise it draws the older sections under `aim_review_gate.EARLIER_VERSION`."""
    old = _latest_old(conn, paper_id)
    return old is None or str(run.get("created_at") or "") >= str(old)


def _cost_note(run: dict) -> str | None:
    """The words of a run whose cost was not read from the ledger (the method's own words), else None."""
    from .aim_review.engine import COST_NOT_READ

    calls = _json(run.get("calls_json"), [])
    return (
        COST_NOT_READ
        if any(isinstance(c, dict) and c.get("code") == COST_NOT_READ for c in calls)
        else None
    )


def resolve(conn, paper_id: str, run_id: str | None = None) -> dict | None:
    """The general run to show: the one asked for (it must be a general run OF THIS paper), else the paper's latest ENDED one
    (finished or stopped early: a stopped run is shown as stopped, review R1 N1)."""
    if run_id:
        run = aim_review_store.run(conn, run_id)
        return run if run and run.get("paper_document_id") == paper_id else None
    return aim_review_store.latest_run(conn, paper_id, ended=True)


def build(conn, run: dict, scope=None) -> dict:
    """The page's JSON for ONE stored general run, without the completeness answer (that needs the built file). Raises
    `NotFinished` for a run that has not ended."""
    status = _SHOWN_STATUS.get(str(run.get("status") or ""))
    if status is None:
        raise NotFinished(NOT_FINISHED_WORDS)
    rows = aim_review_store.lines(conn, run["run_id"])
    points = [
        line_view(r, i, book_hidden(conn, r, scope)) for i, r in enumerate(rows, 1)
    ]
    # a Question whose only content is "not judged" stays on "All points" (counted there), never a comment (ASK A -> C); the sent
    # lines of one point make ONE comment listing every place (`group_comments`)
    comments = group_comments(points)
    by_label = {
        label: sum(1 for p in points if p["label"] == label)
        for label in aim_review.LABELS
    }
    by_shown: dict[str, int] = {}
    for p in points:
        by_shown[p["shown_label"]] = by_shown.get(p["shown_label"], 0) + 1
    identity = _json(run.get("identity_json"), {})
    books, hidden = _books(conn, run, scope)
    unlisted = _json(run.get("unlisted_json"), [])
    usd = run.get("usd")
    return {
        "paper_document_id": run["paper_document_id"],
        "run_id": run["run_id"],
        "method": run.get("method_version") or aim_review.METHOD_VERSION,
        "mark": aim_review_gate.AI_MARK,
        "status": status,
        "stop_reason": _blank(run.get("stop_reason")),
        "identity": {
            k: _blank(identity.get(k)) for k in ("kind", "equipment_type", "subject")
        },
        # the measured score of this paper's kind ("below target" says so); None when the run names no kind (piece G)
        "measured": aim_review_measured.for_run(
            {k: _blank(identity.get(k)) for k in ("kind", "equipment_type")}
        ),
        "counts": {
            "points": len(points),
            "comments": len(comments),
            # points kept off the comments, counted apart (each stays on "All points"): taken off by the editor as a repeat or
            # contradicted, or answered by the paper on some page (the whole-paper check)
            "not_sent": {
                note: sum(1 for p in points if note in _note_words(p["code_note"]))
                for note in (aim_review.EDITED, aim_review.ANSWERED)
            },
            "by_label": by_label,
            "by_shown_label": by_shown,
            "boundary": BOUNDARY,
        },
        "comments": comments,
        "points": points,
        "books": books,
        "books_not_readable": hidden,
        "points_from_books_not_readable": sum(
            1 for p in points if p["standard"] == HIDDEN_BOOK_WORDS
        ),
        "not_held": [
            {"name": str(d.get("name") or ""), "why": str(d.get("why") or "")}
            for d in _json(run.get("not_held_json"), [])
            if isinstance(d, dict)
        ],
        "unlisted_books": {
            "count": len(unlisted),
            "sentence": UNLISTED_SENTENCE.format(n=len(unlisted)) if unlisted else None,
        },
        "checklist": _checklist(conn, run, points),
        "calls": [c for c in _json(run.get("calls_json"), []) if isinstance(c, dict)],
        # the contract's {"usd": ...}; a run whose ledger could not be read also says so (null cost, never 0)
        "cost": {"usd": None if usd is None else float(usd)}
        | ({"note": _cost_note(run)} if usd is None and _cost_note(run) else {}),
        "seconds": run.get("seconds"),
        "created_at": run.get("created_at"),
        "finished_at": run.get("finished_at"),
    }


def served(conn, paper_id: str, scope, run_id: str | None = None) -> dict | None:
    """The full answer of `GET .../general`: `build` plus the completeness answer (page, database, rows of the built file) and
    `is_latest`. None when the paper has no such general run. Raises `NotFinished`."""
    from . import aim_review_completeness

    run = resolve(conn, paper_id, run_id)
    if run is None:
        return None
    view = build(conn, run, scope)
    view["completeness"] = aim_review_completeness.report_for(conn, run, view)
    view["is_latest"] = is_latest(conn, paper_id, run)
    return view
