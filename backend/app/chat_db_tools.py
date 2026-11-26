"""DATABASE ANSWERS IN CHAT (owner, 25 Nov 2026: "Yes, allow it"; recorded on #1584): three tools Chat in Claude mode may call,
whose answers go to Claude. Behind ONE switch, `CHAT_DATABASE_TOOLS_ENABLED`, default OFF.

  * `list_documents(kind or role)`: title, kind, role and id of the documents the caller may read;
  * `latest_review(paper)`: the latest general review of a paper: its counts and its top comments, with page;
  * `tq_open_items(query)`: Chat does not read technical queries yet: it says so and names the Technical Queries page.

RULES (each one tested):
  * ONLY DOCUMENTS THE CALLER MAY READ (rule 5: the caller's grants narrow, never widen). A document outside them is counted,
    never named; a review's rule book the caller may not read shows as "a rule book you may not open".
  * THE CLIENT'S REGISTER AND THE BLOCK LIST STAY BLOCKED: a file named like the register, a name the owner marked, or a blocked
    checksum is never named and its review is never given; it is counted as "withheld". There is NO deliverables-status tool.
    A block file that cannot be read withholds everything (fail closed).
  * NO DOCUMENT TEXT: titles, kinds, roles, ids, counts, and a review's own comments with page (a comment's quote of the paper
    is left out). Whole document text still needs Chat's per-request selection.
  * The tools are offered only on the Claude-first lane, so every answer reaches Claude only through `reader_transport` under
    the `claude_spend` caps, as every chat call does; Local only and the local Chat engine never call them. Each call is logged
    with the tool name, ids and counts only.
"""

from __future__ import annotations

import logging
import re

from .db import connect

log = logging.getLogger(__name__)

LIST_DOCUMENTS = {
    "name": "list_documents",
    "description": (
        "List the documents in the user's library that they may read, by kind (e.g. datasheet, contract, procedure, "
        "standard) or by role (e.g. CONTRACTOR_SUBMITTAL, COMPANY_STANDARD, CONTRACT_DOCUMENT): title, kind, role and id. "
        "Gives no document text."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "description": "Optional: a kind of paper."},
            "role": {"type": "string", "description": "Optional: a document role."},
        },
    },
}
LATEST_REVIEW = {
    "name": "latest_review",
    "description": (
        "The latest finished review of one paper (by document id): how many points and comments, by label, and its top "
        "comments with page, standard and clause. Gives no document text."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"document_id": {"type": "string"}},
        "required": ["document_id"],
    },
}
TQ_OPEN_ITEMS = {
    "name": "tq_open_items",
    "description": "The open items of a technical query, by its number or id.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
}
TOOLS = (LIST_DOCUMENTS, LATEST_REVIEW, TQ_OPEN_ITEMS)
NAMES = frozenset(t["name"] for t in TOOLS)

#: At most this many documents and top comments go to Claude in one answer.
MAX_DOCUMENTS, TOP_COMMENTS = 100, 10
#: Chat does not read technical queries (their mail and drafts stay on the Technical Queries page, under their own lane and
#: grants): the tool says so, with no query's id, subject or text.
TQ_NOT_HERE = "Chat does not read technical queries yet; open the Technical Queries page to see their open items"


#: A question about the library's RECORDS rather than a document's words: which papers there are, their latest review, the
#: open items of a technical query. Only these leave the local path without a document selection, and only with the switch on.
#: NARROW ON PURPOSE (review of update 12, N9): a request for a LIST of the library's papers (a plural kind right after "list",
#: "show me", "which", "what" or "how many", two words between at most), or a paper's review results. A question about a value
#: in a paper ("what is the design pressure in the datasheet") is not a records question: it stays on the document path.
_KINDS = r"(?:documents|papers|files|contracts|datasheets|procedures|specifications|submittals|standards)"
_RECORDS = re.compile(
    r"\b(?:list|show me|which|what|how many)\s+(?:\w+\s+){0,2}" + _KINDS + r"\b"
    r"|\blatest review\b|\breview (?:results?|comments)\b|\bopen items?\b|\btechnical quer(?:y|ies)\b",
    re.IGNORECASE,
)
#: A question that points at ONE paper ("in the datasheet", "does this contract ...") asks that paper's words, never the records.
_ONE_PAPER = re.compile(
    r"\b(?:in|of|from|does|do|did)\s+(?:the|this|that|my|our)\s+"
    r"(?:paper|datasheet|document|file|contract|procedure|specification|submittal|drawing)\b",
    re.IGNORECASE,
)


def asks_the_records(question: str) -> bool:
    """True when the switch is on and the question asks the library's records (`_RECORDS`), not a document's words
    (`_ONE_PAPER`)."""
    q = question or ""
    return enabled() and bool(_RECORDS.search(q)) and not _ONE_PAPER.search(q)


def enabled() -> bool:
    from .config import settings

    return bool(getattr(settings, "chat_database_tools_enabled", False))


def _withheld(rows: list[dict]) -> set[str]:
    """The ids of rows that are the register, marked by name, or blocked by checksum. A block file that cannot be read
    withholds every row (fail closed)."""
    from . import claude_approved

    try:
        marked = claude_approved.marked_name_keys()
        hashes = claude_approved.blocked_hashes()
    except claude_approved.BlockListUnreadable:
        return {r["id"] for r in rows}
    return {
        r["id"]
        for r in rows
        if claude_approved.name_is_blocked(r.get("filename"), marked)
        or str(r.get("sha256") or "").strip().lower() in hashes
    }


def _documents(allowed: frozenset[str]) -> tuple[list[dict], int]:
    """(readable rows that may be named, how many were withheld by the register or the block list)."""
    if not allowed:
        return [], 0
    ids = sorted(allowed)
    marks = ",".join("?" * len(ids))
    kinds = (
        "LEFT JOIN document_kinds k ON k.document_id = d.id"
        if connect()
        .execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'document_kinds'"
        )
        .fetchone()
        else "LEFT JOIN (SELECT NULL AS document_id, NULL AS kind) k ON 0"
    )
    rows = [
        dict(r)
        for r in connect()
        .execute(
            "SELECT d.id, d.filename, d.sha256, c.document_role AS role, c.title AS title, k.kind AS kind FROM documents d"
            f" LEFT JOIN document_classification c ON c.document_id = d.id {kinds}"
            f" WHERE d.id IN ({marks}) ORDER BY d.filename",
            ids,
        )
        .fetchall()
    ]
    gone = _withheld(rows)
    return [r for r in rows if r["id"] not in gone], len(gone)


def _total(conn) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])


def list_documents(input: dict, *, allowed: frozenset[str]) -> dict:
    kind = " ".join(str(input.get("kind") or "").lower().replace("_", " ").split())
    role = str(input.get("role") or "").strip().upper()
    rows, withheld = _documents(allowed)
    picked = [
        r
        for r in rows
        if (
            not kind
            or " ".join(str(r.get("kind") or "").lower().replace("_", " ").split())
            == kind
        )
        and (not role or str(r.get("role") or "").upper() == role)
    ]
    not_readable = max(0, _total(connect()) - len(allowed))
    out = {
        "documents": [
            {
                "id": r["id"],
                "title": r.get("title") or r["filename"],
                "kind": r.get("kind"),
                "role": r.get("role"),
            }
            for r in picked[:MAX_DOCUMENTS]
        ],
        "count": len(picked),
        "shown": min(len(picked), MAX_DOCUMENTS),
        "boundary": "documents you may read",
        "not_readable_count": not_readable,
        "withheld_count": withheld,
    }
    log.info(
        "chat database tool list_documents: %d of %d readable listed",
        out["shown"],
        len(rows),
    )
    return out


class _Viewer:
    """The caller's read set, as the review page's `scope` (only `may_read` is asked)."""

    is_admin = False

    def __init__(self, allowed: frozenset[str]) -> None:
        self.allowed = allowed

    def may_read(self, doc_id) -> bool:
        return str(doc_id) in self.allowed


def latest_review(input: dict, *, allowed: frozenset[str]) -> dict:
    """The paper's FACE review (`aim_review_face`, the same review its Reviews list row opens: newest signed, else newest
    finished on Claude, else newest finished), with its engine named (review of update 12, N9: a local rough draft is said)."""
    from . import aim_review_runs, aim_review_store, aim_review_view

    paper = str(input.get("document_id") or "")
    rows, _withheld_count = _documents(frozenset({paper}) & allowed)
    if not rows:
        return {"found": False, "note": "no readable paper with that id"}
    conn = connect()
    faces = aim_review_runs.entries(conn, allowed, paper, newest_only=True)
    face = next((f for f in faces if f.get("status") == "completed"), None)
    run = aim_review_store.run(conn, face["review_run_id"]) if face else None
    if run is None:
        return {"found": False, "note": "this paper has no finished review"}
    view = aim_review_view.build(conn, run, _Viewer(allowed))
    comments = [
        {
            "label": c.get("shown_label") or c.get("label"),
            "page": c.get("page"),
            "comment": c.get("comment"),
            "standard": c.get("standard"),
            "clause": c.get("clause"),
        }
        for c in view.get("comments") or []
    ][:TOP_COMMENTS]
    out = {
        "found": True,
        "document_id": paper,
        "run_id": run["run_id"],
        "status": view.get("status"),
        "finished_at": view.get("finished_at"),
        "counts": {
            k: view["counts"].get(k) for k in ("points", "comments", "by_shown_label")
        },
        "top_comments": comments,
        "mark": view.get("mark"),
        "engine": face.get("engine"),
        "engine_words": face.get("engine_words"),
    }
    log.info(
        "chat database tool latest_review: paper %s run %s, %d comments",
        paper,
        run["run_id"],
        len(comments),
    )
    return out


def tq_open_items(input: dict, *, allowed: frozenset[str]) -> dict:
    del input, allowed
    log.info("chat database tool tq_open_items: %s", TQ_NOT_HERE)
    return {"found": False, "note": TQ_NOT_HERE}


RUNS = {
    "list_documents": list_documents,
    "latest_review": latest_review,
    "tq_open_items": tq_open_items,
}


def run(name: str, input: dict, *, allowed: frozenset[str]):
    """One database tool call as a `chat_tools.ToolRun` (its result travels as the tool's note, JSON)."""
    import json

    from .chat_tools import ToolRun

    result = RUNS[name](
        input if isinstance(input, dict) else {}, allowed=frozenset(allowed)
    )
    return ToolRun(
        name,
        input,
        "Looked in the library's records",
        True,
        note=json.dumps(result, ensure_ascii=False),
    )
