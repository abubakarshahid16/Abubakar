"""A technical query arrives READY: what the contractor asks, what the contract and standards say, and a proposed reply are made by the
system with no click in the middle (owner, 26 Nov 2026 21:29 and 21:36: "if I have to open the email and check, then what is the point of
telling the app to do that"). One human step stays, at the end: the approval (and sending stays off).

- The wording the system works from (`working`): an engineer's confirmed question, else an engineer's own saved wording, else the system's
  proposal. Confirming is an approval flag; it is never needed before evidence or a draft.
- After the evidence is prepared (the evidence job), the LOCAL model writes a draft from the passages (`write_draft`). Passages an engineer
  kept come first; when none is kept, the passages the system found for this wording may be cited, and the draft says so in one line.
  Nothing is approved or sent by this: approval still needs every found passage kept or rejected and a kept, current citation.
- Changing the wording (`edit`, or confirming another one) queues the same job again (`refresh`), so evidence and draft never stay behind
  the question; `ready` tells the screen what is there and whether it was made for the current wording.
- Claude is never used here. A Claude draft stays the engineer's own request with its consent record (api/technical_queries.py).
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from .db import connect

log = logging.getLogger(__name__)

#: `query_drafts.prompt_version` of a draft the system wrote by itself after preparing the evidence. 2 = the query-reply prompt (no
#: "Yes." / "No." opening; each numbered request answered, or "Not found in the documents searched") and the relevance floor; a query whose
#: latest draft is an older system draft, with no decision on it, is drafted again at the next start (builder C's walk, 26 Nov 2026).
SYSTEM_DRAFT = "system-draft-2"
#: A passage the SYSTEM found is a draft's source only at or above this reranker score: the answer lane's own calibration (answer.py:
#: answerable questions -1.19 .. 7.36, plausible but wrong -10.32 .. -4.73). Measured on a copy of live (32 drafts): 29 of 82 cited
#: passages were below it; with it, 23 of 32 queries keep a source (median 7). A passage an engineer KEPT always counts.
RELEVANCE_FLOOR = -1.19
#: The passages a system draft is written from when no engineer has kept one: the best found for this wording.
MAX_DRAFT_PASSAGES = 8
#: The states in which the wording may change and evidence and draft refresh (as `technical_queries.prepare_evidence` accepts); a query
#: awaiting review on a MODEL-written draft is refreshed too (its draft is replaced by a new version), never one on an engineer's own draft.
PREPARABLE = ("received", "triage", "drafting", "changes_requested")

NO_QUESTION = "no question was found to answer: write it in the question box and the draft follows"
NO_PASSAGE = "no passage was found in the contract documents and standards you may read"
TOO_WEAK = "no passage found answers the question closely enough: keep a source by hand, then press Generate draft"
MODEL_DOWN = "the local drafting model is unavailable; the draft is written on the next preparation"
OUTSIDE = "the draft cited passages outside the query's evidence, so it was not kept"
TYPED_KEPT = "an engineer's own draft is kept; press Generate draft for a new one"
FOUND_NOT_KEPT = "Written by the local model from passages the system found; no engineer has kept them yet."


def key(text: str | None) -> str | None:
    """A short fingerprint of a wording (which wording found a passage, which one a draft answers)."""
    text = (text or "").strip()
    return hashlib.sha256(text.encode()).hexdigest()[:16] if text else None


def working(item: dict[str, Any]) -> tuple[str, str]:
    """(the wording the system works from, where it comes from: confirmed, edited, proposed or none)."""
    for column, source in (
        ("confirmed_question", "confirmed"),
        ("edited_question", "edited"),
        ("proposed_question", "proposed"),
    ):
        text = (item.get(column) or "").strip()
        if text:
            return text, source
    return "", "none"


def draft_passages(
    item: dict[str, Any], allowed, attachment_documents, *, unrestricted: bool = False
) -> list[dict[str, Any]]:
    """The passages a draft is written from: the kept, current ones the caller may read; when none is kept, the best the system found FOR
    THE CURRENT WORDING (not rejected, source not superseded), at most MAX_DRAFT_PASSAGES. A contractor's own attachment is never one."""
    question, _source = working(item)
    readable = [
        e for e in item.get("evidence", [])
        if e["document_id"] not in attachment_documents and (unrestricted or e["document_id"] in allowed)
    ]  # fmt: skip
    kept = [
        e
        for e in readable
        if e["evidence_state"] == "verified" and e["supersession_state"] == "current"
    ]
    if kept:
        return kept
    found = [
        e for e in readable
        if e["evidence_state"] in ("verified", "proposed") and e["supersession_state"] != "superseded"
        and (e["evidence_state"] == "verified" or (e.get("found_for") == key(question) and close_enough(e)))
    ]  # fmt: skip
    return found[:MAX_DRAFT_PASSAGES]


def close_enough(row: dict[str, Any]) -> bool:
    """A system-found passage scores at or above RELEVANCE_FLOOR (a passage with no score, a clause the form itself cites, counts)."""
    score = row.get("rank_score")
    return score is None or float(score) >= RELEVANCE_FLOOR


def none_usable_note(item: dict[str, Any]) -> str:
    """Why no passage can carry a draft: nothing was found, or what was found is too far from the question."""
    question, _source = working(item)
    found = any(e.get("found_for") == key(question) for e in item.get("evidence", []))
    return TOO_WEAK if question and found else NO_PASSAGE


def citations_of(
    result: dict[str, Any], passages: list[dict[str, Any]]
) -> list[dict[str, Any]] | None:
    """The draft's citations as evidence rows of the query (label, evidence id, document, page, quote), or None when one cited passage is
    not one of `passages` (the draft is then not kept). One home for the generate-draft route and the system draft."""
    shown = result.get("passages") or []
    cited = result.get("cited") or []
    out = []
    for index in cited:
        if not isinstance(index, int) or index < 1 or index > len(shown):
            return None
        passage = shown[index - 1]
        match = next(
            (
                e for e in passages
                if e["document_id"] == passage.get("document_id") and e["page_start"] is not None
                and passage.get("page_start") is not None and e["page_start"] <= passage.get("page_end", 0)
                and e["page_end"] >= passage["page_start"] and e["exact_quote"] in (passage.get("text") or "")
            ),
            None,
        )  # fmt: skip
        if match is None:
            return None
        out.append({"label": f"S{index}", "evidence_id": match["id"], "document_id": match["document_id"], "page": match["page_start"],
                    "exact_quote": match["exact_quote"]})  # fmt: skip
    if not cited and not result.get("not_found"):
        return None
    return out


def marks(item: dict[str, Any], cited_ids=None) -> list[str]:
    """Honest one-line marks instead of gates (owner 21:36, item 5): where the system is unsure, it says so on the item."""
    _question, source = working(item)
    out = []
    if source == "proposed":
        out.append(
            "The question was proposed by the system; no engineer has confirmed it yet."
        )
    elif source == "edited":
        out.append("The question is an engineer's wording, not confirmed yet.")
    rows = [
        e for e in item.get("evidence", []) if cited_ids is None or e["id"] in cited_ids
    ]
    if cited_ids is not None and any(e["evidence_state"] != "verified" for e in rows):
        out.append(FOUND_NOT_KEPT)
    unknown = sorted(
        {
            e.get("source_name") or e["document_id"]
            for e in rows
            if e["supersession_state"] == "unknown"
        }
    )
    if cited_ids is not None and unknown:
        out.append(
            f"The revision of {', '.join(unknown)} is not confirmed yet (Documents, Details, Save metadata)."
        )
    return out


def _note(query_id: str, note: str | None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE technical_queries SET draft_note=? WHERE id=?", (note, query_id)
        )


def write_draft(
    query_id: str, allowed, user_id, is_admin: bool, unrestricted: bool
) -> str | None:
    """After the evidence is prepared: the local model writes a draft for the current wording. Returns None when a draft was written, else
    the plain reason, which is also stored as the query's draft note (shown on the page). Never Claude; nothing is approved or sent."""
    from . import technical_queries as tq
    from . import verified_passages

    item = tq.get(query_id, user_id, is_admin, unrestricted)
    if item is None or item["status"] not in PREPARABLE:
        return None
    if any(not d.get("model") for d in item.get("drafts", [])):
        _note(query_id, TYPED_KEPT)
        return TYPED_KEPT
    question, _source = working(item)
    if not question:
        _note(query_id, NO_QUESTION)
        return NO_QUESTION
    with connect() as conn:
        attachment_documents = tq.query_attachment_document_ids(conn)
    passages = draft_passages(
        item, frozenset(allowed), attachment_documents, unrestricted=unrestricted
    )
    if not passages:
        note = none_usable_note(item)
        _note(query_id, note)
        return note
    from .answer import query_reply

    try:
        with (
            query_reply()
        ):  # the query-reply prompt: each request answered, no "Yes." / "No." opening
            result = verified_passages.answer(question, evidence=passages, tier="generated",
                                              allowed_document_ids=frozenset(p["document_id"] for p in passages), model="local")  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - logged by its class; the page says the draft waits for the model
        log.info("technical query: system draft not written (%s)", type(exc).__name__)
        _note(query_id, MODEL_DOWN)
        return MODEL_DOWN
    if result.get("answer_type") != "generated" or not result.get("answer"):
        reason = "the passages were not enough for a grounded draft" + (
            f": {result['reason']}" if result.get("reason") else ""
        )
        _note(query_id, reason)
        return reason
    citations = citations_of(result, passages)
    if citations is None:
        _note(query_id, OUTSIDE)
        return OUTSIDE
    unresolved = ([result["reason"]] if result.get("reason") else []) + marks(
        item, {c["evidence_id"] for c in citations}
    )
    tq.add_draft(query_id, result["answer"], [], unresolved, None, user_id, is_admin, unrestricted, citations=citations,
                 model=result.get("model"), prompt_version=SYSTEM_DRAFT, question=question)  # fmt: skip
    _note(query_id, None)
    return None


def refresh(
    query_id: str, allowed, user_id, is_admin: bool, unrestricted: bool
) -> bool:
    """Queue the evidence job (which writes the draft at its end) for the current wording. A query awaiting review on a MODEL-written draft
    goes back to drafting first (its draft answers an older wording); one on an engineer's own draft, or approved and later, is left as it
    is. True when a job was queued."""
    from . import technical_queries as tq
    from . import technical_query_jobs

    item = tq.get(query_id, user_id, is_admin, unrestricted)
    if item is None or not (reopen(item) or item["status"] in PREPARABLE):
        return False
    technical_query_jobs.enqueue(query_id, allowed, user_id, is_admin, unrestricted)
    return True


def reopen(item: dict[str, Any]) -> bool:
    """A query awaiting review on a MODEL-written draft goes back to drafting, so a new draft (or new evidence) can replace it; one on an
    engineer's own typed draft, or decided, is left as it is. True when it was reopened."""
    from . import technical_queries as tq

    drafts = item.get("drafts") or []
    if item["status"] != "awaiting_review" or not drafts or not drafts[-1].get("model"):
        return False
    with connect() as conn:
        conn.execute("UPDATE technical_queries SET status='drafting',updated_at=? WHERE id=? AND status='awaiting_review'",
                     (tq.now(), item["id"]))  # fmt: skip
    item["status"] = "drafting"
    return True


def approve_question(conn, item: dict[str, Any], actor_user_id) -> None:
    """Approving a draft confirms the wording it answers when no engineer has confirmed one (the approver is the one human step; owner 26
    Nov 2026 21:36); a draft written for an older wording is never approved (it is being refreshed)."""
    from . import technical_queries as tq

    latest = (item.get("drafts") or [None])[-1] or {}
    question, _source = working(item)
    answered = (latest.get("question") or "").strip()
    if answered and answered != question:
        raise ValueError(
            "the draft answers an older wording of the question; a new draft is being written for the current one"
        )
    if not (item.get("confirmed_question") or "").strip() and (answered or question):
        text = answered or question
        conn.execute("UPDATE technical_queries SET confirmed_question=?,confirmed_question_by=?,confirmed_question_at=? WHERE id=?",
                     (text, actor_user_id, tq.now(), item["id"]))  # fmt: skip
        tq._event(
            conn,
            item["id"],
            "question_confirmed",
            actor_user_id,
            f"chars={len(text)}; with the approval",
        )


def edit(
    query_id: str,
    question: str,
    allowed,
    user_id,
    is_admin: bool,
    unrestricted: bool,
    actor_user_id,
) -> dict[str, Any] | None:
    """An engineer saves their own wording WITHOUT confirming it; evidence and draft refresh from it."""
    from . import technical_queries as tq

    current = tq.get(query_id, user_id, is_admin, unrestricted)
    if current is None:
        return None
    text = (question or "").strip()
    if not text:
        raise ValueError("the question cannot be empty")
    if len(text) > tq.MAX_CONFIRMED_QUESTION:
        raise ValueError(
            f"the question is longer than {tq.MAX_CONFIRMED_QUESTION} characters"
        )
    drafts = current.get("drafts") or []
    if current["status"] not in (*PREPARABLE, "awaiting_review"):
        raise ValueError("the question cannot be changed once the response is approved")
    with connect() as conn:
        conn.execute(
            "UPDATE technical_queries SET edited_question=?,updated_at=? WHERE id=?",
            (text, tq.now(), query_id),
        )
        tq._event(
            conn, query_id, "question_edited", actor_user_id, f"chars={len(text)}"
        )
    if text != (current.get("evidence_question") or "") or not drafts:
        refresh(query_id, allowed, user_id, is_admin, unrestricted)
    return tq.get(query_id, user_id, is_admin, unrestricted)


def ready(item: dict[str, Any]) -> dict[str, Any]:
    """For the screen: what is there, and whether it was made for the current wording."""
    question, source = working(item)
    job = item.get("evidence_job") or {}
    busy = job.get("state") in ("queued", "running")
    now_key = key(question)
    has_evidence = any(
        (now_key is not None and e.get("found_for") == now_key)
        or e["evidence_state"] == "verified"  # no wording: none found for it
        for e in item.get("evidence", [])
    )
    drafts = item.get("drafts") or []
    latest = drafts[-1] if drafts else None
    try:
        cited = {
            c.get("evidence_id")
            for c in json.loads((latest or {}).get("citations_json") or "[]")
            if isinstance(c, dict)
        }
    except ValueError:
        cited = set()
    return {
        "question": question,
        "question_source": source,
        "evidence": "refreshing"
        if busy
        else "failed"
        if job.get("state") == "failed"
        else "ready"
        if has_evidence
        else "none",
        "evidence_fresh": bool(question)
        and (item.get("evidence_question") or "") == question,
        "draft": "refreshing"
        if busy
        else "ready"
        if latest
        else "not_written"
        if item.get("draft_note")
        else "none",
        "draft_fresh": bool(latest) and (latest.get("question") or "") == question,
        "draft_note": None if busy else item.get("draft_note"),
        "marks": marks(item, cited if latest else None),
    }


def backlog(conn) -> list[str]:
    """The queries that are not ready and can be made ready: never prepared (or prepared under older question rules), or prepared with no
    draft and no stored reason why none was written. Oldest first."""
    from . import technical_query_jobs

    ids = technical_query_jobs.unprepared(conn)
    seen = set(ids)
    for row in conn.execute(
        f"SELECT q.id FROM technical_queries q WHERE q.status IN ({','.join('?' * len(PREPARABLE))}) AND q.draft_note IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM query_drafts d WHERE d.query_id=q.id) AND NOT EXISTS (SELECT 1 FROM query_evidence_jobs j "
        "WHERE j.query_id=q.id AND j.state IN ('queued','running')) ORDER BY q.received_at",
        PREPARABLE,
    ):
        if row[0] not in seen:
            ids.append(row[0])
            seen.add(row[0])
    for qid in stale_system_drafts(conn):
        if qid not in seen:
            ids.append(qid)
            seen.add(qid)
    return ids


def stale_system_drafts(conn) -> list[str]:
    """The queries awaiting review whose latest draft is a SYSTEM draft of an older version (no engineer typed it, no decision names it):
    they are drafted again with the current prompt and floor. Oldest first."""
    out = []
    for row in conn.execute(
        "SELECT q.id, (SELECT d.prompt_version FROM query_drafts d WHERE d.query_id=q.id ORDER BY d.version DESC LIMIT 1) AS pv, "
        "(SELECT d.model FROM query_drafts d WHERE d.query_id=q.id ORDER BY d.version DESC LIMIT 1) AS model FROM technical_queries q "
        "WHERE q.status='awaiting_review' AND NOT EXISTS (SELECT 1 FROM query_decisions x WHERE x.query_id=q.id) "
        "AND NOT EXISTS (SELECT 1 FROM query_evidence_jobs j WHERE j.query_id=q.id AND j.state IN ('queued','running')) ORDER BY q.received_at"
    ):
        if (
            row["model"]
            and (row["pv"] or "").startswith("system-draft-")
            and row["pv"] != SYSTEM_DRAFT
        ):
            out.append(row["id"])
    return out


def queue_backlog() -> int:
    """At server start: every query in the backlog is queued with its owner's read scope (the mailbox owner for an imported query), one at
    a time on the evidence job's one thread, so nobody has to press "Prepare evidence for all". A query with no owner is left for the
    button. Returns how many were queued."""
    from . import access, technical_query_jobs

    with connect() as conn:
        rows = [(qid, conn.execute("SELECT owner_user_id FROM technical_queries WHERE id=?", (qid,)).fetchone()[0])
                for qid in backlog(conn)]  # fmt: skip
    queued = 0
    for query_id, owner in rows:
        if not owner:
            continue
        try:
            scope = access.scope_for_user(owner)
            with (
                connect() as conn
            ):  # an older system draft: back to drafting, so the job may prepare and draft again
                conn.execute(
                    "UPDATE technical_queries SET status='drafting' WHERE id=? AND status='awaiting_review'",
                    (query_id,),
                )
            technical_query_jobs.enqueue(query_id, scope.readable_with_attachments, scope.user_id, scope.is_admin, scope.unrestricted,
                                         start_thread=False)  # fmt: skip
            queued += 1
        except Exception as exc:  # noqa: BLE001 - logged by class; the button still works
            log.info("technical query: not queued at start (%s)", type(exc).__name__)
    return queued
