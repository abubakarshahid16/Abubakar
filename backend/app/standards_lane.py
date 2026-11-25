"""The standards converter lane at the Claude gate (CLAUDE.md rule 1; owner, 3 Nov 2026, #1584): rule-book text of a HELD
COMPANY STANDARD of the SAES, ISO, API, ASME or NACE family may go to Claude, under the caps, never a datasheet, procedure,
contract or CRS. A named lane, NOT the chat's per-request consent (a person picking documents for one request).

`open_for(conn, ids)` checks each document BEFORE anything is declared: classified a company standard (the converter's own
`standards_converter.require_role`) and named by an allowed family (`standards_inventory.family_from_identifier` on its file
name). Any other document raises `NotStandardsLane` and nothing is carried. Inside, the declared documents are exactly those
ids; `claude_approved.refusal` lets them pass the owner's per-file list ONLY when every carried id was verified here. Blocks
(the register by name, the block file) are asked first and still win; the local-only bar, the egress flags, the key and the
claude_spend caps are untouched."""

from __future__ import annotations

import contextlib
import sqlite3
from contextvars import ContextVar

#: The families the owner opened to the converter lane (#1584, 3 Nov 2026).
FAMILIES = frozenset({"SAES", "ISO", "API", "ASME", "NACE"})
#: The ids `open_for` verified for the calls inside it; empty outside the lane.
_VERIFIED: ContextVar[frozenset[str]] = ContextVar(
    "claude_standards_lane", default=frozenset()
)


class NotStandardsLane(RuntimeError):
    """A document that is not a held company standard of an allowed family was offered to the standards lane. Ids only."""


def not_standards(conn, ids) -> list[str]:
    """The ids that may NOT go by this lane: not classified a company standard, not in the library, or of another family."""
    from .standards_converter import NotStandardsText, require_role
    from .standards_inventory import family_from_identifier

    bad = []
    for d in sorted(ids):
        row = conn.execute(
            "SELECT filename FROM documents WHERE id = ?", (d,)
        ).fetchone()
        try:
            require_role(conn, d)
        except (
            NotStandardsText,
            sqlite3.Error,
        ):  # no classification held: never a standard
            bad.append(d)
            continue
        if row is None or family_from_identifier(str(row[0] or "")) not in FAMILIES:
            bad.append(d)
    return bad


class Checked(frozenset):
    """Document ids `check` verified (only this module makes one): lets a worker thread, which holds no database connection,
    open the lane for ids inside a set the main thread checked."""


def check(conn, document_ids) -> Checked:
    """The ids, verified as held company standards of an allowed family; `NotStandardsLane` for anything else (or no ids)."""
    ids = frozenset(str(d) for d in (document_ids or ()) if d)
    bad = not_standards(conn, ids) if conn is not None else sorted(ids)
    if bad or not ids:
        raise NotStandardsLane(f"not a held standard of an allowed family (ids: {', '.join(bad) or 'none'}); nothing is sent")
    return Checked(ids)


@contextlib.contextmanager
def open_for(conn, document_ids, checked: Checked | None = None):
    """Declare exactly these documents for the Claude calls inside, by the standards lane: each is checked here (`check`), or
    lies inside `checked`, a set `check` made earlier. Anything else is refused before anything is declared."""
    from . import claude_approved

    ids = frozenset(str(d) for d in (document_ids or ()) if d)
    if not (isinstance(checked, Checked) and ids and ids <= checked):
        check(conn, ids)
    carried, verified = claude_approved._CARRIED.set(ids), _VERIFIED.set(ids)
    try:
        yield
    finally:
        _VERIFIED.reset(verified)
        claude_approved._CARRIED.reset(carried)


def allows(ids) -> bool:
    """The gate's question (`claude_approved.refusal`): every carried id was verified by `open_for` in this context."""
    verified = _VERIFIED.get()
    return bool(ids) and bool(verified) and frozenset(ids) <= verified
