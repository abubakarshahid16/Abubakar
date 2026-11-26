"""Who is this query? Read from the SUBJECT of its email by code (owner, 26 Nov 2026, 02:40).

A query email's subject carries a document number with a type code: `<project>-<contractor>-<company>-<TYPE>-<running number> - <DISCIPLINE>_..._<title>`
(TYPE is TQ = technical query, or CFC = conflict finding clarification). The reference is the query's identity: a forward or a reply with the same
reference joins the SAME query. A subject with no reference is not dropped: it is flagged "needs a person". Shapes only here; no real number is in
this file or in its tests (invented ones).
"""

from __future__ import annotations

import re

TYPES = ("TQ", "CFC")
TYPE_WORDS = {"TQ": "Technical query", "CFC": "Conflict finding clarification"}
_REPLY = re.compile(r"^\s*(?:(?:re|fw|fwd|aw|wg)\s*:\s*)+", re.IGNORECASE)
_REF = re.compile(
    r"(?<![A-Za-z0-9])(?P<pre>(?:[A-Za-z0-9._]+-){0,5})(?P<type>TQ|CFC)-(?P<num>\d{1,9})(?!\d)",
    re.IGNORECASE,
)
_DISCIPLINE = re.compile(r"^\s*[-–—]?\s*(?P<disc>[A-Za-z]{2,8})(?=[_\s]|$)")


def parts_code(prefix: str) -> str | None:
    """The contractor's code in a number's prefix "<project>-<contractor>-<company>-": the part before the company's, or None."""
    parts = prefix.strip("-").split("-")
    return parts[-2] if len(parts) >= 3 else None


def parse(subject: str | None) -> dict | None:
    """`{"reference", "type", "number", "discipline", "contractor_code", "title"}` from a subject, or None when it carries no TQ/CFC reference.

    `prefixed` is False for a bare number ("TQ-12"): two senders or projects can send the same bare number, so it never joins a query.
    `reference` is the identity: the part before the type (project, contractor, company), the type and the running number, upper case, with the
    number's leading zeros removed so "TQ-007" and "TQ-7" are one. Re:/Fwd: prefixes are ignored. `discipline` is the code after the number (None
    when there is none); `title` is the last part after the underscores (or the rest of the subject), at most 200 characters."""
    text = _REPLY.sub("", str(subject or "")).strip()
    found = _REF.search(text)
    if not found:
        return None
    kind = found.group("type").upper()
    number = str(int(found.group("num")))
    prefix = found.group("pre").upper()
    rest = text[found.end() :]
    disc = _DISCIPLINE.match(rest)
    parts = [p.strip() for p in rest.split("_") if p.strip()]
    title = (
        parts[-1] if len(parts) > 1 else (rest[disc.end() :] if disc else rest)
    ).strip(" -–—_:")[:200]
    return {
        "reference": f"{prefix}{kind}-{number}",
        "prefixed": bool(prefix),  # only a number with its project-contractor-company prefix is a query's identity; a bare "TQ-12" is not
        "type": kind,
        "number": number,
        "discipline": disc.group("disc").upper() if disc else None,
        # the contractor's code: the part just before the company's in "<project>-<contractor>-<company>-<TYPE>-<n>" (None when the
        # number does not carry all three)
        "contractor_code": parts_code(prefix),
        "title": title or None,
    }
