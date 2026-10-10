"""Web search for standard IDENTIFIERS, behind a content filter and a
per-query approval (W5b-12, #560; owner decision 2026-10-08).

Standard editions and supersession cannot be checked from the library alone.
This lane may ask the public web about a standard's identifier, edition year,
supersession, free availability and publisher page - and nothing else.

THE FILTER (`check`) WHITELISTS, IT DOES NOT SCRUB. A query is sent whole or
not at all: every token must be part of a public standard identifier
(`web_standards.is_public_identifier`: a standards body and its designator,
company and project identifiers refused), an edition year, or a word from the
closed `ALLOWED_WORDS` list. Anything else blocks the WHOLE query with a named
reason - a quoted sentence, a value, a name, a document number, or a word not
on the list - and nothing is sent. A refused query is never shortened into a
sendable one, because a shortened query is one nobody approved.

PER-QUERY APPROVAL. `approve` re-checks the query and stores it; `search`
takes only an approval id, re-checks the stored query, and claims the approval
atomically so it is used once. Per-publisher trust ("approved per query at
first, per publisher once trusted") is NOT built yet.

THE SOCKET IS THE MARKET LANE'S (`market_transport`), not a new one. OFF BY
DEFAULT: `STANDARD_LOOKUP_ENABLED`, AND both market flags
(`market_providers.live_enabled`). Off: `search` refuses before anything is
claimed or sent. CLAUDE.md rule 1 names this lane.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import settings

#: What a query may say besides identifiers and edition years.
ALLOWED_WORDS = frozenset({
    "edition", "editions", "latest", "current", "newest", "year", "revision", "revised",
    "superseded", "supersedes", "supersession", "replaced", "replaces", "replacement",
    "withdrawn", "withdrawal", "status", "free", "freely", "available", "availability",
    "download", "publisher", "published", "publication", "page", "official", "part", "of",
    "by", "the", "is", "was", "what", "which", "has", "been", "and", "or", "still", "valid",
})

#: A standards body. A designator is allowed only right after one.
_BODIES = frozenset({"api", "asme", "astm", "iso", "iec", "nfpa", "ansi", "nace", "mss", "aws",
                     "awwa", "bs", "en", "din", "ieee", "ul", "norsok", "ped", "asce"})
#: Series letters that may sit between a body and its number ("API RP 14C").
_SERIES = frozenset({"rp", "std", "spec", "sp", "tr", "ts", "mr", "pas", "b", "a", "bpvc"})
_DESIGNATOR = re.compile(r"^[A-Za-z]{0,3}-?\d{1,6}(?:[-.:/]\d{1,4}[A-Za-z]?)*[A-Za-z]{0,2}$")
_YEAR = re.compile(r"^(19|20)\d\d$")
_QUOTES = re.compile(r"[\"'`‘’“”«»]")
_DOCUMENT_NUMBER = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+){2,}$|^[A-Za-z]+-?\d+[A-Za-z]*-\w+$")
_HAS_DIGIT = re.compile(r"\d")

BLOCKED_QUOTED = "quoted_sentence"
BLOCKED_VALUE = "value"
BLOCKED_NAME = "name"
BLOCKED_DOCUMENT_NUMBER = "document_number"
BLOCKED_WORD = "word_not_allowed"
BLOCKED_NO_IDENTIFIER = "no_standard_identifier"
BLOCKED_EMPTY = "empty"
BLOCKED_TOO_LONG = "too_long"
MAX_TOKENS = 12


@dataclass(frozen=True)
class Check:
    sendable: str | None          # the query exactly as it would be sent, or None
    blocked: str | None           # the named reason when sendable is None
    identifiers: tuple[str, ...] = ()


def check(query: str | None) -> Check:
    """Is this query allowed to leave the machine? Whole or not at all."""
    from .web_standards import is_public_identifier

    text = " ".join((query or "").split())
    if not text:
        return Check(None, BLOCKED_EMPTY)
    if _QUOTES.search(text):
        return Check(None, BLOCKED_QUOTED)
    tokens = [t.strip(",;?!()") for t in text.split()]
    tokens = [t for t in tokens if t]
    if len(tokens) > MAX_TOKENS:
        return Check(None, BLOCKED_TOO_LONG)
    identifiers: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        low = token.lower().rstrip(".")
        if low in _BODIES:
            # A body, any series letters, then EXACTLY ONE designator: a
            # second number after it is a value, never part of the name.
            parts = [token]
            j = i + 1
            while j < len(tokens) and len(parts) < 3 and tokens[j].lower() in _SERIES:
                parts.append(tokens[j])
                j += 1
            if j < len(tokens) and _DESIGNATOR.match(tokens[j]) and _HAS_DIGIT.search(tokens[j]):
                parts.append(tokens[j])
                j += 1
            else:
                return Check(None, BLOCKED_NO_IDENTIFIER)
            identifier = " ".join(parts)
            if not is_public_identifier(identifier):
                return Check(None, BLOCKED_DOCUMENT_NUMBER)
            identifiers.append(identifier)
            i = j
            continue
        if _YEAR.match(token):
            i += 1
            continue
        if low in ALLOWED_WORDS:
            i += 1
            continue
        if _DOCUMENT_NUMBER.match(token) or re.match(r"(?i)^(saes|samss|koc)\b", token):
            return Check(None, BLOCKED_DOCUMENT_NUMBER)
        if _HAS_DIGIT.search(token):
            return Check(None, BLOCKED_VALUE)
        if token[:1].isupper():
            return Check(None, BLOCKED_NAME)
        return Check(None, BLOCKED_WORD)
    if not identifiers:
        return Check(None, BLOCKED_NO_IDENTIFIER)
    return Check(" ".join(tokens), None, tuple(identifiers))


def available() -> bool:
    """The lane's own flag AND the market lane's two egress flags."""
    from . import market_providers
    return bool(settings.standard_lookup_enabled) and market_providers.live_enabled()


class LookupRefused(Exception):
    """Nothing was sent; `code` says why."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ensure_schema() -> None:
    from .db import connect
    with connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS standard_lookup_approvals (
            id          TEXT PRIMARY KEY,
            query       TEXT NOT NULL,
            approved_by TEXT,
            approved_at TEXT NOT NULL,
            used_at     TEXT
        )""")


def approve(query: str, *, approved_by: str | None) -> dict:
    """Record a person's approval of ONE filtered query. Refused queries are
    never stored."""
    result = check(query)
    if result.sendable is None:
        raise LookupRefused(result.blocked, f"query blocked: {result.blocked}")
    from .db import connect
    ensure_schema()
    approval_id = f"sla_{uuid.uuid4().hex[:16]}"
    with connect() as conn:
        conn.execute("INSERT INTO standard_lookup_approvals (id, query, approved_by, approved_at)"
                     " VALUES (?,?,?,?)", (approval_id, result.sendable, approved_by, _now()))
    return {"approval_id": approval_id, "query": result.sendable}


def search(approval_id: str, *, fetch=None) -> dict:
    """Send the approved query, once. `fetch` defaults to the market transport."""
    from . import market_providers, market_transport
    from .db import connect

    if not available():
        raise LookupRefused("off", "the standard lookup lane is off (STANDARD_LOOKUP_ENABLED and "
                                   "both market egress flags are required)")
    ensure_schema()
    conn = connect()
    row = conn.execute("SELECT query, used_at FROM standard_lookup_approvals WHERE id = ?",
                       (approval_id,)).fetchone()
    if row is None:
        raise LookupRefused("not_approved", "no such approval")
    result = check(row["query"])
    if result.sendable is None or result.sendable != row["query"]:
        raise LookupRefused(result.blocked or "changed", "the stored query no longer passes the filter")
    with conn:
        claimed = conn.execute("UPDATE standard_lookup_approvals SET used_at = ? WHERE id = ?"
                               " AND used_at IS NULL", (_now(), approval_id)).rowcount
    if claimed != 1:
        raise LookupRefused("already_used", "this approval was already used; approve the query again")
    out = market_providers.search_all(result.sendable, fetch=fetch or market_transport.transport())
    return {"query": result.sendable, "identifiers": list(result.identifiers),
            "rows": out.get("rows", []), "tiers_answered": out.get("tiers_answered", []),
            "failure": out.get("failure"), "audit": out.get("audit", [])}
