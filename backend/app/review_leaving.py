"""The documents a Claude review of one paper may send, worked out BEFORE the start, for the caller's access scope (owner decision,
12 Nov 2026, #1584: "the screen lists every document that will leave the Mac before the review starts").

`leaving_for` answers `documents.leaving` of `review_engine.plan_for`: the paper, the held rule books the AI reviewer may ask
rules from (cited by the paper, or governing its equipment type), the cited specifications on the approved list and the papers
the user chose for a general review; each with its display title, kind and why. `not_sent` lists what a review cites that will NOT
go, and why. A document the caller may not read is counted, never named (CLAUDE.md rule 5: intersection, never union).

The match is the review's own: `agent_review_rules.library_of`, `standard_ids.cited_standards`, `applicability.find_standard`.
This module only decides what is LISTED. What is sent stays under `claude_approved.refusal` and, with a stored list
(`review_shown`), only what the list names. It reads page text to find citations and returns no text of it.
"""

from __future__ import annotations

import logging
import sqlite3

from . import claude_approved

log = logging.getLogger(__name__)

PAPER, RULE_BOOK, SPECIFICATION, PROJECT_PAPER, CONTRACT = (
    "paper",
    "rule book",
    "specification",
    "project paper",
    "contract",
)
WHY_PAPER = "paper under review"
WHY_CITED = "cited by the paper"
WHY_GOVERNS = "governs the equipment type"
WHY_CHOSEN = "chosen by you for this review"
CONTRACT_WORDS = "a contract goes only with the owner's recorded yes"
NOT_HELD = "not held in the library"
BLOCKED_WORDS = "blocked from the cloud model by the owner's block list"
NOT_APPROVED_BOOK = "not approved for Claude; the owner approves it"
NOT_APPROVED_SPEC = "a specification that is not on the owner's approved list"
NOT_READABLE = "documents you may not read"
LOCAL_WORDS = "Nothing leaves this Mac"


def _title(row) -> str:
    return str(row["filename"] or "")


def _doc_rows(conn, ids) -> dict[str, dict]:
    ids = sorted({str(i) for i in ids if i})
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        "SELECT d.id AS id, d.filename AS filename, d.sha256 AS sha256, c.document_role AS role"
        " FROM documents d LEFT JOIN document_classification c ON c.document_id = d.id"
        f" WHERE d.id IN ({marks})",
        ids,
    ).fetchall()
    return {r["id"]: dict(r) for r in rows}


def _specification_library(conn, paper_id: str) -> list[dict]:
    from . import applicability

    rows = conn.execute(
        "SELECT d.id AS id, d.filename AS filename FROM documents d"
        " JOIN document_classification c ON c.document_id = d.id"
        " WHERE c.document_role IN (?, ?) AND d.id != ?",
        (claude_approved.SPECIFICATION_ROLE, "CONTRACT_DOCUMENT", paper_id),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "filename": r["filename"],
            "document_number": applicability.library_identifier(r["filename"] or ""),
        }
        for r in rows
    ]


def _citations(conn, document_id: str, equipment_type: str | None):
    """(cited names in the paper's own spelling, governing names for its equipment type). Names of standards only."""
    from . import applicability, standard_ids

    text = "\n".join(
        r[0] or ""
        for r in conn.execute(
            "SELECT text FROM pages WHERE document_id = ? ORDER BY page_no",
            (document_id,),
        )
    )
    cited = standard_ids.cited_standards(text)
    governing = (applicability.governing_table().get("equipment_types") or {}).get(
        equipment_type or "", []
    )
    return cited, list(governing)


class _Gate:
    """What the send gate would say about one document, read once."""

    def __init__(self, facts) -> None:
        self.approved = claude_approved.approved_hashes()
        self.enforced = bool(claude_approved.settings.claude_approved_list_enforced)
        self.auto = (
            claude_approved.auto_approve_on()
            and bool(facts.paper_approved)
            and not facts.is_contract
        )
        try:
            self.blocks = claude_approved.blocked_hashes()
            self.marked = claude_approved.marked_name_keys()
            self.unreadable = False
        except claude_approved.BlockListUnreadable:
            self.blocks, self.marked, self.unreadable = frozenset(), frozenset(), True

    def why_not(self, row: dict, kind: str) -> str | None:
        from . import claude_auto_approve, contract_yes

        sha = (row["sha256"] or "").strip().lower()
        if (
            self.unreadable
            or sha in self.blocks
            or claude_approved.name_is_blocked(row["filename"], self.marked)
        ):
            return BLOCKED_WORDS
        if claude_auto_approve.is_contract_paper(
            row["id"]
        ) and not contract_yes.has_yes(row["id"]):
            return CONTRACT_WORDS
        if not self.enforced or sha in self.approved:
            return None
        if (
            kind == RULE_BOOK
            and self.auto
            and row["role"] == claude_approved.STANDARD_ROLE
        ):
            return None  # joins the list when the review starts (`claude_auto_approve`)
        return NOT_APPROVED_BOOK if kind == RULE_BOOK else NOT_APPROVED_SPEC


def leaving_for(
    conn,
    document_id: str,
    allowed: frozenset[str],
    facts,
    *,
    equipment_type: str | None,
    leaves: bool,
    project_ids=(),
) -> dict:
    """`{"leaving": [...], "not_sent": [...], "not_readable": n, "count": {...}, "summary": str}`. Never raises: a fault yields an
    EMPTY leaving list with the reason (the screen then offers no Claude start)."""
    out: dict = {"leaving": [], "not_sent": [], "not_readable": 0}
    if not leaves:
        out["summary"] = LOCAL_WORDS
        return _finish(out)
    try:
        _fill(conn, document_id, allowed, facts, equipment_type, project_ids, out)
    except (sqlite3.Error, ValueError, OSError) as exc:
        log.warning("review leaving list unreadable (%s)", type(exc).__name__)
        out["leaving"], out["not_sent"], out["not_readable"] = [], [], 0
        out["unreadable"] = True
        out["summary"] = (
            "The list of documents that would leave could not be worked out, so no Claude start is offered"
        )
        return _finish(out)
    out["summary"] = (
        f"{len(out['leaving'])} document(s) will be sent to Claude"
        if out["leaving"]
        else LOCAL_WORDS
    )
    return _finish(out)


def _finish(out: dict) -> dict:
    out["count"] = {
        "leaving": len(out["leaving"]),
        "boundary": "documents you may read",
    }
    return out


def _fill(conn, document_id, allowed, facts, equipment_type, project_ids, out) -> None:
    from . import agent_review_rules, applicability

    seen: set[str] = set()

    def put(row: dict, kind: str, why: str) -> None:
        if row["id"] in seen:
            return
        seen.add(row["id"])
        if row["id"] not in allowed:  # counted, never named
            out["not_readable"] += 1
            return
        reason = gate.why_not(row, kind)
        if reason:
            out["not_sent"].append(
                {
                    "id": row["id"],
                    "title": _title(row),
                    "kind": kind,
                    "why": why,
                    "reason": reason,
                }
            )
        else:
            out["leaving"].append(
                {"id": row["id"], "title": _title(row), "kind": kind, "why": why}
            )

    gate = _Gate(facts)
    paper = _doc_rows(conn, [document_id]).get(document_id)
    if paper is None or document_id not in allowed:
        return
    seen.add(document_id)
    out["leaving"].append(
        {"id": document_id, "title": _title(paper), "kind": PAPER, "why": WHY_PAPER}
    )

    cited, governing = _citations(conn, document_id, equipment_type)
    books = agent_review_rules.library_of(conn)
    specs = _specification_library(conn, document_id)
    rows = _doc_rows(conn, [e["id"] for e in books + specs])
    for names, why in ((cited, WHY_CITED), (governing, WHY_GOVERNS)):
        for name in names:
            book = applicability.find_standard(books, name)
            spec = None if book else applicability.find_standard(specs, name)
            hit = book or spec
            if hit is None:
                if why == WHY_CITED and not any(
                    n["name"] == name for n in out["not_sent"] if "name" in n
                ):
                    out["not_sent"].append(
                        {
                            "name": name,
                            "kind": RULE_BOOK,
                            "why": why,
                            "reason": NOT_HELD,
                        }
                    )
                continue
            other = (
                CONTRACT
                if rows[hit["id"]]["role"] == "CONTRACT_DOCUMENT"
                else SPECIFICATION
            )
            put(rows[hit["id"]], RULE_BOOK if book else other, why)
    chosen = _doc_rows(conn, project_ids)
    for pid in project_ids:
        row = chosen.get(pid)
        if row is not None and pid not in seen:
            kind = (
                SPECIFICATION
                if row["role"] == claude_approved.SPECIFICATION_ROLE
                else PROJECT_PAPER
            )
            put(row, kind, WHY_CHOSEN)


def documents_block(ctx, plan, project_ids) -> dict:
    """`documents` of the plan: the older keys (the last review's rule book names) and the list of what would leave.
    `ctx` is `(conn, document_id, allowed, facts, reading)`."""
    from .review_engine import _earlier_books

    conn, document_id, allowed, facts, reading = ctx
    leaves = bool(plan.text_leaves)
    docs: dict = {"paper": leaves, "rule_books": [], "rule_books_note": None}
    if leaves:
        books = [b for b in _earlier_books(conn, document_id) if b["id"] in allowed]
        docs["rule_books"] = sorted(b["filename"] for b in books)
        docs["rule_books_note"] = (
            "named from this paper's last review, only the books you may read; the books are chosen again when the review starts"
            if books
            else "the rule books are chosen when the review starts"
        )
    docs.update(
        leaving_for(
            conn,
            document_id,
            allowed,
            facts,
            equipment_type=getattr(reading, "equipment_type", None),
            leaves=leaves,
            project_ids=tuple(project_ids),
        )
    )
    return docs
