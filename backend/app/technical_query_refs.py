"""Another query a contractor's request NAMES (lead-4's blind score of the owner's approved answers, 27 Nov 2026: 4 of 7 approved replies
point to another clarification or technical query already answered, and the request itself sometimes names its number). Found by code,
never by the model: every TQ / CFC number in the query's question and in its email text, other than the query's own, is looked up among
the queries held here (a full number by its reference; a bare "CFC-5" by its type and running number). The page shows each, with the held
query's status, and the draft says "see it before replying". A held query the caller may not see is said to be held, never named or
linked (its id and status stay hidden). Read only; nothing leaves the machine.
"""

from __future__ import annotations

from typing import Any

from .technical_query_subject import _REF, parts_code

MAX_REFS = 12


def numbers_in(text: str) -> list[dict[str, Any]]:
    """Each TQ / CFC number written in `text`, once, in order: its reference as the subject parser forms it, type and running number."""
    out, seen = [], set()
    for m in _REF.finditer(text or ""):
        kind, number, prefix = (
            m.group("type").upper(),
            str(int(m.group("num"))),
            m.group("pre").upper(),
        )
        reference = f"{prefix}{kind}-{number}"
        if reference in seen:
            continue
        seen.add(reference)
        out.append(
            {
                "reference": reference,
                "type": kind,
                "number": number,
                "prefixed": bool(prefix),
                "contractor_code": parts_code(prefix),
            }
        )
    return out[:MAX_REFS]


def cross_refs(
    conn, item: dict[str, Any], visible_where: str, visible_args: list
) -> list[dict[str, Any]]:
    """The other queries this query's request names: `[{"reference", "held", "query_id", "status", "subject"}]`. `held` False = no such
    query is held here; a held one outside the caller's view keeps query_id, status and subject None."""
    own = (item.get("ref_key") or "").upper()
    texts = [
        item.get("confirmed_question") or "",
        item.get("edited_question") or "",
        item.get("proposed_question") or "",
    ]
    texts += [
        m.get("body_main") or m.get("body") or ""
        for m in item.get("messages") or []
        if m.get("is_inbound", 1)
    ]
    found = numbers_in("\n".join(texts))
    out = []
    for ref in found:
        if ref["reference"] == own or (
            not ref["prefixed"] and own.endswith(f"-{ref['type']}-{ref['number']}")
        ):
            continue  # the query's own number
        if ref["prefixed"]:
            rows = conn.execute(
                "SELECT id FROM technical_queries WHERE upper(ref_key)=? AND id<>?",
                (ref["reference"], item["id"]),
            ).fetchall()
        else:
            rows = conn.execute("SELECT id FROM technical_queries WHERE upper(ref_type)=? AND ref_number=? AND id<>?",
                                (ref["type"], ref["number"], item["id"])).fetchall()  # fmt: skip
        if not rows:
            out.append(
                {
                    "reference": ref["reference"],
                    "held": False,
                    "query_id": None,
                    "status": None,
                    "subject": None,
                }
            )
            continue
        ids = [r[0] for r in rows]
        where = (
            visible_where
            + (" AND " if visible_where else " WHERE ")
            + f"id IN ({','.join('?' * len(ids))})"
        )
        seen = conn.execute(
            "SELECT id, status, subject FROM technical_queries" + where,
            [*visible_args, *ids],
        ).fetchall()
        if not seen:
            out.append(
                {
                    "reference": ref["reference"],
                    "held": True,
                    "query_id": None,
                    "status": None,
                    "subject": None,
                }
            )
        for row in seen:
            out.append(
                {
                    "reference": ref["reference"],
                    "held": True,
                    "query_id": row[0],
                    "status": row[1],
                    "subject": row[2],
                }
            )
    return out


def mark(refs: list[dict[str, Any]]) -> str | None:
    """The draft's line: the held queries the request names, to read before replying (the engineer decides; nothing is copied)."""
    held = [r["reference"] for r in refs if r["held"]]
    if not held:
        return None
    unique = list(dict.fromkeys(held))
    return f"The request names {', '.join(unique)}, held in this system: see {'them' if len(unique) > 1 else 'it'} before replying."
