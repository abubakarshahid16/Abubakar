"""B6C: question understanding - structured, deterministic, retrieval-only.

What a question is ABOUT, decided before retrieval so retrieval searches the
right place. It never answers anything and never reads a prior ANSWER as
evidence: the only conversation context used is which document and clause the
previous turn's evidence came from (metadata), and the earlier USER questions
(chat.resolve_followup).

  * DOCUMENT SCOPE - a document the question names by its designation
    ("in ABC-X-123", "per 45-QRS-006"), or refers to ("this standard",
    "that document") when the previous turn established one. Scope only ever
    NARROWS the caller's permitted documents (CLAUDE.md rule 5).
  * CLAUSE - "clause 6.2.3" is kept; "this / that requirement", "the
    previous clause", "the next clause" are resolved from the previous turn.
  * AMBIGUITY - a name that matches several documents, a reference with no
    context to resolve it, and (after retrieval) the same text found in several
    documents are REPORTED, never silently resolved to one of them.
  * FALLBACK - anything not understood leaves the question exactly as typed.

No hard-coded document, standard or question: designations are read from the
caller's own document filenames.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .db import connect

#: A document designation inside a filename: letters/digits in 2+ hyphen- or
#: dot-joined segments, with at least one digit ("ABC-D-012", "32-XYZ-008").
_DESIGNATION = re.compile(r"[A-Za-z0-9]+(?:[-.][A-Za-z0-9]+)+")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")

_THIS_DOCUMENT = re.compile(
    r"\b(?:this|that|the same|the above|said)\s+"
    r"(?:standard|document|spec(?:ification)?|datasheet|data\s*sheet|sheet)\b", re.I)
_THIS_CLAUSE = re.compile(
    r"\b(?:this|that|the same|the above)\s+(?:clause|requirement|section|paragraph)\b", re.I)
_NEXT_CLAUSE = re.compile(r"\b(?:the\s+)?(?:next|following)\s+(?:clause|section|paragraph)\b", re.I)
_PREV_CLAUSE = re.compile(r"\b(?:the\s+)?(?:previous|preceding)\s+(?:clause|section|paragraph)\b", re.I)
_CLAUSE_REF = re.compile(
    r"\b(?:clause|section|para(?:graph)?|§)\s*((?:[A-Z]\.)?\d+(?:\.\d+)*)", re.I)
_CLAUSE_NUMBER = re.compile(r"^\s*((?:[A-Z]\.)?\d+(?:\.\d+)*)\b")
_WS = re.compile(r"\s+")

#: Near-identical passages from different documents: token Jaccard at or
#: above this is "the same text", the boilerplate case.
DUPLICATE_JACCARD = 0.85


@dataclass(frozen=True)
class PriorContext:
    """What the previous turn's evidence came from - metadata, never text."""
    document_id: str | None = None
    clause: str | None = None


@dataclass(frozen=True)
class Understanding:
    original: str
    retrieval_query: str
    document_id: str | None = None
    scope_ids: frozenset[str] | None = None      # narrowed permitted set, or None
    scope_reason: str | None = None
    clause: str | None = None
    clause_reason: str | None = None
    ambiguous_documents: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "retrieval_query": self.retrieval_query,
            "document_id": self.document_id,
            "scope_reason": self.scope_reason,
            "clause": self.clause,
            "clause_reason": self.clause_reason,
            "scope_ids": sorted(self.scope_ids) if self.scope_ids else None,
            "ambiguous_documents": list(self.ambiguous_documents),
            "notes": list(self.notes),
        }


def _norm(text: str) -> str:
    return _NON_ALNUM.sub(" ", text).strip().upper()


def designation(filename: str) -> str | None:
    """The document's designation from its filename, or None."""
    stem = filename.rsplit(".", 1)[0]
    for m in _DESIGNATION.finditer(stem):
        token = m.group(0)
        if any(ch.isdigit() for ch in token) and any(ch.isalpha() for ch in token):
            return token
    return None


def named_documents(question: str, documents: dict[str, str]) -> dict[str, list[str]]:
    """{designation as named: [document ids carrying it]} for every permitted
    document the question names. `documents` is {document_id: filename}."""
    padded = f" {_norm(question)} "
    found: dict[str, list[str]] = {}
    for doc_id, filename in sorted(documents.items()):
        des = designation(filename)
        if des and f" {_norm(des)} " in padded:
            found.setdefault(des, []).append(doc_id)
    return found


def _step(clause: str, delta: int) -> str | None:
    parts = clause.split(".")
    if not parts[-1].isdigit():
        return None
    n = int(parts[-1]) + delta
    return ".".join(parts[:-1] + [str(n)]) if n >= 1 else None


def understand(
    question: str,
    *,
    allowed_document_ids: frozenset[str],
    documents: dict[str, str],
    conversation_document_id: str | None = None,
    context: PriorContext | None = None,
) -> Understanding:
    """Structured understanding of one question. Deterministic; no model."""
    context = context or PriorContext()
    notes: list[str] = []
    query = _WS.sub(" ", question).strip()
    permitted = {d: f for d, f in documents.items() if d in allowed_document_ids}

    document_id = scope_ids = scope_reason = None
    ambiguous: tuple[str, ...] = ()

    named = named_documents(query, permitted)
    if named:
        ids = sorted({d for group in named.values() for d in group})
        if len(ids) == 1:
            document_id, scope_reason = ids[0], "named in the question"
        else:
            # several documents carry the name (editions, copies) or the
            # question names several: search those, choose none of them
            scope_ids = frozenset(ids)
            ambiguous = tuple(ids)
            scope_reason = "named in the question - more than one document matches"
            notes.append("the name matches more than one document; none was chosen")
    elif _THIS_DOCUMENT.search(query):
        if context.document_id and context.document_id in allowed_document_ids:
            document_id, scope_reason = context.document_id, "the document the previous answer came from"
        elif conversation_document_id and conversation_document_id in allowed_document_ids:
            document_id, scope_reason = conversation_document_id, "the conversation's document"
        else:
            notes.append("'this document' has nothing earlier in the conversation to refer to")

    clause = clause_reason = None
    explicit = _CLAUSE_REF.search(query)
    if explicit:
        clause, clause_reason = explicit.group(1), "named in the question"
    elif context.clause and _NEXT_CLAUSE.search(query):
        clause, clause_reason = _step(context.clause, +1), "the clause after the previous answer's"
    elif context.clause and _PREV_CLAUSE.search(query):
        clause, clause_reason = _step(context.clause, -1), "the clause before the previous answer's"
    elif context.clause and _THIS_CLAUSE.search(query):
        clause, clause_reason = context.clause, "the previous answer's clause"
    elif _NEXT_CLAUSE.search(query) or _PREV_CLAUSE.search(query) or _THIS_CLAUSE.search(query):
        notes.append("the clause referred to has nothing earlier in the conversation to resolve it")

    if clause and not explicit:
        # the reader's words did not carry the number - retrieval needs it,
        # and within the document the previous answer came from
        query = f"{query} clause {clause}"
        if document_id is None and scope_ids is None and context.document_id in allowed_document_ids:
            document_id, scope_reason = context.document_id, "the document the referenced clause is in"

    return Understanding(
        original=question, retrieval_query=query, document_id=document_id,
        scope_ids=scope_ids, scope_reason=scope_reason, clause=clause,
        clause_reason=clause_reason, ambiguous_documents=ambiguous, notes=tuple(notes))


def _tokens(text: str) -> set[str]:
    return set(_norm(text).split())


def duplicated_across_documents(passages: list[dict]) -> list[str]:
    """Document ids whose passage repeats the TOP passage nearly word for word.

    Boilerplate ("all referenced standards shall be of the latest issue")
    reads identically in many documents; the top hit's document is then an
    accident of ranking, not the answer to "which document". Reported so the
    reader can name one - never resolved silently.
    """
    if len(passages) < 2:
        return []
    top = passages[0]
    base = _tokens(top.get("text") or "")
    if not base:
        return []
    same = [top["document_id"]]
    for p in passages[1:]:
        if p["document_id"] in same:
            continue
        other = _tokens(p.get("text") or "")
        if other and len(base & other) / len(base | other) >= DUPLICATE_JACCARD:
            same.append(p["document_id"])
    return same if len(same) > 1 else []


def ambiguous_source(result: dict) -> list[str]:
    """Documents that carry the ANSWER'S OWN TEXT: the top passage's document,
    then every other document whose near-identical chunk retrieval dropped as
    a duplicate of it, then any other shown passage repeating it. Two or more
    means "which document" was decided by ranking, not by the question."""
    primary = result.get("passage") or next(iter(result.get("passages") or []), None)
    if not primary:
        return []
    docs = [primary["document_id"]]
    for dup in result.get("near_duplicates") or []:
        if dup["duplicate_of"] == primary.get("chunk_id") and dup["document_id"] not in docs:
            docs.append(dup["document_id"])
    shown = [primary, *(result.get("supporting") or []), *(result.get("passages") or [])]
    for d in duplicated_across_documents(shown):
        if d not in docs:
            docs.append(d)
    return docs if len(docs) > 1 else []


def document_names(allowed_document_ids: frozenset[str]) -> dict[str, str]:
    """{document_id: filename} for the caller's permitted documents only."""
    if not allowed_document_ids:
        return {}
    marks = ",".join("?" * len(allowed_document_ids))
    return {r[0]: r[1] for r in connect().execute(
        f"SELECT id, filename FROM documents WHERE id IN ({marks})",
        sorted(allowed_document_ids))}


def prior_context(conversation_id: str) -> PriorContext:
    """The document and clause the previous ASSISTANT turn's evidence came
    from - read from its stored payload's first passage. Its answer text is
    never read."""
    row = connect().execute(
        """SELECT payload FROM messages WHERE conversation_id = ? AND role = 'assistant'
           ORDER BY ordinal DESC LIMIT 1""", (conversation_id,)).fetchone()
    if not row or not row["payload"]:
        return PriorContext()
    try:
        payload = json.loads(row["payload"])
    except (TypeError, ValueError):
        return PriorContext()
    passages = payload.get("passages") or ([payload["passage"]] if payload.get("passage") else [])
    if not passages:
        return PriorContext()
    first = passages[0]
    m = _CLAUSE_NUMBER.match(first.get("section") or "")
    return PriorContext(document_id=first.get("document_id"), clause=m.group(1) if m else None)
