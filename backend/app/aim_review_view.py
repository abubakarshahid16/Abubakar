"""What the general review's results page says (order 14, piece C): ONE assembly of a stored general run into the page's JSON.

The page, the Excel file and the completeness check all read THIS dict, so they cannot disagree about what a line says. Reads only:
the stored run and its lines (`aim_review_store`), the titles of the rule books (`documents`), nothing else. No model, no network, no
write. Every count states its boundary; a null renders as nothing (never 0); a rule book the caller may not read is counted, never
named. The labels the person SEES are the stored `shown_label` (written by `aim_review_store`, the one home of that table).
"""

from __future__ import annotations

import json
from typing import Any

from . import aim_review, aim_review_gate, aim_review_store, review_shown

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


def line_view(row: dict, n: int) -> dict:
    """One stored line as the page and the file show it. `n` is the 1-based position in line order."""
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
        "code_note": row.get("code_note") or "",
        "quote_unverified": bool(row.get("quote_unverified")),
        "book_document_id": _blank(row.get("book_document_id")),
    }


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


def _checklist(conn, run: dict, n_lines: int) -> dict:
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
        else (n_lines or None),
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
    results; otherwise it draws the older sections under "Earlier version"."""
    old = _latest_old(conn, paper_id)
    return old is None or str(run.get("created_at") or "") >= str(old)


def resolve(conn, paper_id: str, run_id: str | None = None) -> dict | None:
    """The general run to show: the one asked for (it must be a general run OF THIS paper), else the paper's latest finished one."""
    if run_id:
        run = aim_review_store.run(conn, run_id)
        return run if run and run.get("paper_document_id") == paper_id else None
    return aim_review_store.latest_run(conn, paper_id)


def build(conn, run: dict, scope=None) -> dict:
    """The page's JSON for ONE stored general run, without the completeness answer (that needs the built file). Raises
    `NotFinished` for a run that has not ended."""
    status = _SHOWN_STATUS.get(str(run.get("status") or ""))
    if status is None:
        raise NotFinished(NOT_FINISHED_WORDS)
    rows = aim_review_store.lines(conn, run["run_id"])
    points = [line_view(r, i) for i, r in enumerate(rows, 1)]
    comments = [p for p in points if p["label"] in aim_review.SENDABLE]
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
        "counts": {
            "points": len(points),
            "comments": len(comments),
            "by_label": by_label,
            "by_shown_label": by_shown,
            "boundary": BOUNDARY,
        },
        "comments": comments,
        "points": points,
        "books": books,
        "books_not_readable": hidden,
        "not_held": [
            {"name": str(d.get("name") or ""), "why": str(d.get("why") or "")}
            for d in _json(run.get("not_held_json"), [])
            if isinstance(d, dict)
        ],
        "unlisted_books": {
            "count": len(unlisted),
            "sentence": UNLISTED_SENTENCE.format(n=len(unlisted)) if unlisted else None,
        },
        "checklist": _checklist(conn, run, len(points)),
        "calls": [c for c in _json(run.get("calls_json"), []) if isinstance(c, dict)],
        "cost": {"usd": None if usd is None else float(usd)},
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
