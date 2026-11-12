"""The review's own notes as POINTS of the one list (owner, 12 Nov 2026, STATE section 37; `ONE-REVIEWER.md`, PR 4).

The AI review is the only reviewer, so what the old rule check said in its notes belongs on the same list, decided Keep or Remove like any point:

  1. PAGES NOT READ: the run's page record (`outcome_json.page_coverage`, `page_ledger.run_unread_pages`, the one definition): one Question point
     naming the pages and how many of how many; none when every page was read; none (said by the run's own record, never 0) when the run stored no record;
  2. RULE BOOKS NOT HELD: one Question point per rule book the review wanted and the library does not hold (`agent_review_missing_book`);
     its rules were not asked, so nothing is said to be met;
  3. STANDARDS NOT CITED: ONE Question point (the standards listed together) for the standards that apply to the equipment but the paper does not cite
     (`applicability.standards_check`, `required_not_cited`): internal copy only, never a Fail, never in the contractor copy (the copy is drawn from
     the lines and the added points, and these ids are in neither).

They are added ONLY when the paper has an AI review and no rule-check run: a rule-check run already lists the same notes as its own rows, and the
list must not say a thing twice. A check that could not run says so as a point; it is never an empty "all fine". Reads only; nothing is written;
no document text is logged.
"""

from __future__ import annotations

import hashlib
import logging

from . import review_points as rp

log = logging.getLogger(__name__)

PAGES_SHOWN = 30


def _point(point_id: str, name: str, action: str) -> dict:
    """A note in the list's shape: rank 4 (a question), source the AI review, no quote (a note has none), no code word in its words."""
    return {
        "id": point_id,
        "source": rp.SOURCE_AI_REVIEW,
        "source_words": rp.SOURCE_WORDS[rp.SOURCE_AI_REVIEW],
        "engine": rp.ENGINE_AI,
        "rank": 4,
        "tile": "questions",
        "firm": None,
        "other_kind": None,
        "name": name,
        "page": None,
        "rule_book": None,
        "clause": None,
        "action": action,
        "paper_quote": None,
        "clause_quote": None,
        "paper_quote_note": rp.NO_PAPER_QUOTE,
        "clause_quote_note": rp.NO_CLAUSE_QUOTE,
        "route_note": None,
        "view_page": None,
        "shall": True,
        "group_key": None,  # each note is its own question: never folded into a group with another
        "added_by": None,
        "_book_doc": None,
    }


def pages_point(run_id: str, unread: list[int] | None, total: int | None) -> dict | None:
    """Pages the review did not read: None when none were left unread, or when the run's record says nothing about its pages (not known is not zero)."""
    if not unread:
        return None
    shown = ", ".join(str(p) for p in unread[:PAGES_SHOWN])
    more = f" and {len(unread) - PAGES_SHOWN} more" if len(unread) > PAGES_SHOWN else ""
    of = f" of {total}" if total else ""
    return _point(
        f"note:{run_id}:pages",
        "Pages not read",
        f"{len(unread)}{of} pages of this paper were not read by the review: {shown}{more}. Nothing on them was checked: look at them by hand, or ask for a better copy.",
    )


def missing_book_points(run_id: str, names: list[str]) -> list[dict]:
    """One point per rule book the review wanted and the library does not hold."""
    out = []
    for name in names:
        clean = rp._plain(name)
        if not clean:
            continue
        key = hashlib.sha1(clean.lower().encode("utf-8")).hexdigest()[:10]  # noqa: S324 - an id, not a secret
        out.append(
            _point(
                f"note:{run_id}:book:{key}",
                f"Rule book not held: {clean}",
                f"{clean} is not in the library, so its rules were not checked. Nothing is said to be met against it: add the book, or check the paper against it by hand.",
            )
        )
    return out


def not_cited_point(run_id: str, check: dict | None) -> dict | None:
    """ONE point for every standard that applies to this equipment and that the paper does not cite. A question for the engineer, never a Fail."""
    rows = (check or {}).get("required_not_cited") or []
    names = [rp._plain(r.get("identifier")) for r in rows]
    names = list(dict.fromkeys(n for n in names if n))
    if not names:
        return None
    many = len(names) > 1
    return _point(
        f"note:{run_id}:not_cited",
        "Standards not cited",
        f"{', '.join(names)} {'apply' if many else 'applies'} to this kind of equipment, and the paper does not cite {'them' if many else 'it'}. "
        "Ask whether the contractor meant to leave out. This is a question for you, not a finding against the paper.",
    )


def _failed(run_id: str, what: str, exc: Exception) -> dict:
    log.warning("review notes: %s did not run (%s)", what, type(exc).__name__)
    return _point(
        f"note:{run_id}:{what.replace(' ', '_')}",
        f"The {what} did not run",
        f"The {what} could not be made ({type(exc).__name__}), so nothing is said about it here. It is not a clean result: ask for the review to be run again.",
    )


def notes_of_run(run_id: str, paper_id: str, scope, not_held: list[str]) -> list[dict]:
    """The notes of one AI review run as points. Each part stands alone: one that fails becomes a point saying so, the others still show."""
    from . import applicability, comparison, page_ledger

    out: list[dict] = []
    try:
        outcome = comparison.run_outcome(run_id, allowed_document_ids=scope.allowed_document_ids) or {}
        unread = page_ledger.run_unread_pages_of(outcome)
        total = (outcome.get("page_coverage") or {}).get("pages_total")
        if page := pages_point(run_id, unread, total):
            out.append(page)
    except Exception as exc:  # noqa: BLE001 - an unreadable record is said, never "all pages read"
        out.append(_failed(run_id, "pages-read record", exc))
    out.extend(missing_book_points(run_id, not_held))
    try:
        check = applicability.standards_check(paper_id, allowed_document_ids=frozenset(scope.allowed_document_ids))
        if cited := not_cited_point(run_id, check):
            out.append(cited)
    except Exception as exc:  # noqa: BLE001
        out.append(_failed(run_id, "standards-cited check", exc))
    return out
