"""RECORDS ANSWERS IN CHAT, BY CODE, ON BOTH ENGINES (lead-4, 26 Nov 2026, goal G7; the owner allowed database answers in Chat on
#1584, 25 Nov 2026). A practice-copy proof found that "which reviews are signed", "how many comments on the valve review" and
"list the queries waiting for evidence" fell to general knowledge or to a rule book on the local engine, and reached no tool on
Claude. They are questions about the app's own RECORDS, so code answers them from the database, with a count and its boundary,
and no model writes a word of it (the answer never goes to Claude either).

  * signed reviews: the general reviews of the papers the reader may read whose latest sign-off stands;
  * a paper's review: the review its Reviews list row opens (`aim_review_runs.entries`, its FACE), with its counts, engine and,
    for the local model, the rough-draft label; a newer unsigned review is named;
  * technical queries waiting for their evidence: the queries the reader may see (`technical_queries._visible_where`: their own
    or assigned to them; an administrator sees all) whose newest evidence job is queued or running;
  * a list of papers BY KIND ("list the datasheets"): the papers of that kind the reader may read (always on: it replaces a count
    of submittals that answered the question wrongly);
  * any other records-shaped question: "I cannot answer that from the records", with what can be answered; never an essay.

Rule 5: every answer is drawn from the reader's own read set (`allowed`), never wider; a paper outside it is not named. The
client's register and the block list stay withheld (`chat_db_tools._documents`). No document text: file names, kinds, counts.
Reviews, queries and the "cannot answer" line are behind `CHAT_DATABASE_TOOLS_ENABLED` (off: Chat behaves exactly as before)."""

from __future__ import annotations

import re

from . import chat_db_tools
from .db import connect

BOUNDARY = "of the papers you may read"
TQ_BOUNDARY = "of the technical queries you may see (your own or assigned to you; an administrator sees all)"
CANNOT = "I cannot answer that from the records."
CAN = (
    "From the records I can answer: which reviews are signed; how many comments a paper's review has; which technical queries "
    "are waiting for their evidence; and a list of papers by kind (datasheets, procedures, studies)."
)
REASON = "read from the app's records, not from document text"
#: At most this many lines are listed; the rest are counted ("and N more").
MAX_LINES = 30
SIGNED, PAPER_REVIEW, WAITING_EVIDENCE, LIST_KIND, UNANSWERED = (
    "signed_reviews",
    "paper_review",
    "queries_waiting_for_evidence",
    "papers_by_kind",
    "cannot_answer",
)
#: The plural a reader types -> the kind the app records (`document_kinds.kind`). Roles (standards, contracts, submittals,
#: specifications) keep the library count they already have.
KINDS = {
    "datasheets": "datasheet", "data sheets": "datasheet", "procedures": "procedure", "studies": "study",
    "hazops": "study", "hazop studies": "study", "drawings": "drawing", "calculations": "calculation",
}  # fmt: skip
_KIND_WORDS = "|".join(
    sorted((re.escape(k).replace(r"\ ", r"\s+") for k in KINDS), key=len, reverse=True)
)
_LIST_KIND = re.compile(
    rf"\b(?:list|show(?:\s+me)?|which|what|how\s+many)\b(?:\s+\w+){{0,3}}?\s+({_KIND_WORDS})\b",
    re.I,
)
_QUERIES = r"\b(?:technical\s+quer(?:y|ies)|quer(?:y|ies)|tqs?|cfcs?)\b"
_EVIDENCE = re.compile(rf"{_QUERIES}.*\bevidence\b|\bevidence\b.*{_QUERIES}", re.I)
_REVIEWS = r"\b(?:reviews?|sign-?offs?)\b"
_SIGNED = re.compile(
    rf"\b(?:signed|sign-?offs?|signed[- ]off)\b.*{_REVIEWS}|{_REVIEWS}.*\b(?:signed|signed[- ]off)\b",
    re.I,
)
_COUNTED = re.compile(
    r"\b(?:how\s+many|number\s+of|count(?:\s+of)?)\b.*\b(?:comments?|points?|questions?|confirmations?)\b.*\breview\b"
    r"|\breview\b.*\b(?:results?|comments|counts?|findings?)\b|\b(?:latest|last|newest)\s+review\b",
    re.I,
)
_RECORDS_SHAPED = re.compile(
    rf"\b(?:how\s+many|which|list|show(?:\s+me)?|what|status\s+of)\b.*(?:\breviews\b|\bsign-?offs?\b|{_QUERIES})",
    re.I,
)
#: Words of a question that never name a paper.
_STOP = frozenset(
    re.findall(
        r"\w+",
        "the a an of on in for to and or is are was were be how many what which show me list review reviews comments comment "
        "points point questions question confirmations count number has have had does do did its it this that latest last "
        "newest paper papers document results result findings",
    )
)


def kind_of(question: str) -> str | None:
    """Which records answer the question asks for, or None (not a records question: Chat goes on as before)."""
    q = question or ""
    if _LIST_KIND.search(q):
        return LIST_KIND
    if not chat_db_tools.enabled():
        return None
    if _EVIDENCE.search(q):
        return WAITING_EVIDENCE
    if _SIGNED.search(q):
        return SIGNED
    if _COUNTED.search(q):
        return PAPER_REVIEW
    if _RECORDS_SHAPED.search(q) and not chat_db_tools._ONE_PAPER.search(q):
        return UNANSWERED
    return None


def _listed(lines: list[str]) -> str:
    shown = lines[:MAX_LINES]
    more = len(lines) - len(shown)
    return "\n".join(f"- {x}" for x in shown) + (f"\n- and {more} more" if more else "")


def _day(stamp) -> str:
    return str(stamp or "")[:10] or "date not recorded"


def _counts(entry: dict) -> str:
    c = entry.get("general_counts") or {}
    parts = [f"{c[k]} {w}" for k, w in (("points", "points"), ("comments", "comments"), ("confirmations", "to confirm")) if c.get(k) is not None]  # fmt: skip
    return ", ".join(parts) or "counts not recorded"


def _faces(allowed: frozenset[str]) -> list[dict]:
    from . import aim_review_runs

    conn = connect()
    return [
        e
        for e in aim_review_runs.entries(conn, allowed, newest_only=True)
        if e.get("status") == "completed"
    ]


def signed_reviews(allowed: frozenset[str]) -> str:
    from . import aim_review_runs

    entries = [
        e
        for e in aim_review_runs.entries(connect(), allowed)
        if e.get("status") == "completed"
    ]
    signed = [e for e in entries if e.get("general_signoff") == "signed"]
    head = f"{len(signed)} of {len(entries)} finished reviews {'is' if len(signed) == 1 else 'are'} signed, {BOUNDARY}."
    lines = [
        f"{e.get('submittal_filename') or 'a paper'}: review {e['review_run_id'][:8]} ({e.get('engine_words')}), finished "
        f"{_day(e.get('completed_at'))}; {_counts(e)}"
        for e in signed
    ]
    return head + ("\n" + _listed(lines) if lines else "")


def _named(question: str, faces: list[dict]) -> list[dict]:
    """The reviewed papers the question names: the most question words found in a paper's file name or equipment tags."""
    words = {
        w
        for w in re.findall(r"[a-z0-9]+", (question or "").lower())
        if len(w) > 2 and w not in _STOP
    }
    if not words:
        return []

    def score(e: dict) -> int:
        own = " ".join(
            [
                str(e.get("submittal_filename") or ""),
                *(str(t) for t in e.get("equipment_tags") or []),
            ]
        ).lower()
        return sum(1 for w in words if re.search(rf"\b{re.escape(w)}", own))

    best = max((score(e) for e in faces), default=0)
    return [e for e in faces if best and score(e) == best]


def paper_review(question: str, allowed: frozenset[str]) -> str:
    faces = _faces(allowed)
    named = _named(question, faces)
    if not named:
        return (
            f"{CANNOT} No reviewed paper {BOUNDARY} matches the words of the question ({len(faces)} reviewed papers "
            f"{BOUNDARY}); name the paper by its file name or equipment."
        )
    out = []
    for e in named:
        tags = ", ".join(str(t) for t in e.get("equipment_tags") or [])
        state = (
            "signed by an engineer"
            if e.get("general_signoff") == "signed"
            else "AI, to be checked (not signed)"
        )
        line = (
            f"{e.get('submittal_filename') or 'a paper'}{f' ({tags})' if tags else ''}: the review its Reviews list row opens is "
            f"{e['review_run_id'][:8]} ({e.get('engine_words')}), finished {_day(e.get('completed_at'))}, {state}; {_counts(e)}."
        )
        out.append(line + (f" {e['newer_note']}." if e.get("newer_note") else ""))
    head = f"{len(named)} reviewed paper{'s' if len(named) > 1 else ''} {BOUNDARY} match{'' if len(named) > 1 else 'es'}:"
    return head + "\n" + _listed(out)


def queries_waiting(user_id: str | None, is_admin: bool) -> str:
    from . import technical_queries

    if not technical_queries.enabled():
        return f"{CANNOT} Technical queries are switched off in this app, so there is no record of them to read."
    from . import technical_query_jobs

    conn = connect()
    where, args = technical_queries._visible_where(user_id, is_admin, False)
    rows = conn.execute(f"SELECT id, ref_type, ref_number, status FROM technical_queries{where} ORDER BY received_at", args).fetchall()  # fmt: skip
    states = {
        r["id"]: (technical_query_jobs.latest(conn, r["id"]) or {}).get("state")
        for r in rows
    }
    waiting = [r for r in rows if states[r["id"]] in ("queued", "running")]
    failed = sum(1 for s in states.values() if s == "failed")
    by = {
        s: sum(1 for r in waiting if states[r["id"]] == s)
        for s in ("queued", "running")
    }
    head = (
        f"{len(waiting)} of {len(rows)} technical queries are waiting for their evidence ({by['queued']} queued, {by['running']} "
        f"being prepared), {TQ_BOUNDARY}."
        + (f" The evidence of {failed} could not be prepared." if failed else "")
    )
    lines = [
        f"{(str(r['ref_type'] or '') + ' ' + str(r['ref_number'] or '')).strip() or 'query ' + str(r['id'])[:8]}: {str(r['status']).replace('_', ' ')}, evidence {states[r['id']]}"
        for r in waiting
    ]  # fmt: skip
    return head + ("\n" + _listed(lines) if lines else "")


def papers_by_kind(question: str, allowed: frozenset[str]) -> str:
    said = " ".join(_LIST_KIND.search(question).group(1).lower().split())
    kind = KINDS[said]
    rows, withheld = chat_db_tools._documents(allowed)
    picked = [r for r in rows if str(r.get("kind") or "").lower() == kind]
    unknown = sum(1 for r in rows if not r.get("kind"))
    head = f"{len(picked)} {said if len(picked) != 1 else kind} {BOUNDARY} (the kind as the app recorded it)."
    tail = f" {unknown} papers {BOUNDARY} have no kind recorded yet." if unknown else ""
    tail += f" {withheld} withheld by the block list." if withheld else ""
    lines = [f"{r.get('title') or r['filename']}" + (f" ({r['filename']})" if r.get("title") and r["title"] != r["filename"] else "") for r in picked]  # fmt: skip
    return head + tail + ("\n" + _listed(lines) if lines else "")


def result(
    question: str, *, allowed: frozenset[str], user_id: str | None, is_admin: bool
) -> dict | None:
    """The whole Chat answer for a records question, or None (not one: Chat goes on exactly as before)."""
    kind = kind_of(question)
    if kind is None:
        return None
    text = {
        LIST_KIND: lambda: papers_by_kind(question, allowed),
        SIGNED: lambda: signed_reviews(allowed),
        PAPER_REVIEW: lambda: paper_review(question, allowed),
        WAITING_EVIDENCE: lambda: queries_waiting(user_id, is_admin),
        UNANSWERED: lambda: f"{CANNOT} {CAN}",
    }[kind]()
    return {
        "question": question, "retrieval_mode": "metadata", "reranked": False, "timings": {}, "candidates_considered": 0,
        "answer_type": "metadata", "answer": text, "reason": REASON, "input_kind": "records_question", "records": kind,
        "examples": [], "passages": [], "seconds": 0.0, "paper_coverage": None,
    }  # fmt: skip
