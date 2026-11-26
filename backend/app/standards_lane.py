"""The standards converter lane at the Claude gate (CLAUDE.md rule 1; owner, 3 Nov 2026, #1584): rule-book text of a HELD
COMPANY STANDARD of the SAES, ISO, API, ASME or NACE family may go to Claude, under the caps, never a datasheet, procedure,
contract or CRS. A named lane, NOT the chat's per-request consent (a person picking documents for one request).

`open_for(conn, ids)` checks each document BEFORE anything is declared: classified a company standard (the converter's own
`standards_converter.require_role`), not held for an administrator's confirmation (`company_standard_confirm`, the same rule
reviews use), and of an allowed family by its OWN identifier (`family_of`: the recorded family or standard number, else the
family word the file name starts with). Any other document raises `NotStandardsLane` and nothing is carried. Inside,
the declared documents are exactly those ids; `claude_approved.refusal` lets them pass the owner's per-file list ONLY when every carried id was verified here. Blocks
(the register by name, the block file) are asked first and still win; the local-only bar, the egress flags, the key and the
claude_spend caps are untouched."""

from __future__ import annotations

import contextlib
import re
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


def family_of(conn, document_id: str, filename: str) -> str:
    """The family of the standard's OWN identifier: the family recorded for it (`standard_family`), else the one its recorded
    standard number names, else the family word the file name STARTS with. A family word later in a name is not the book's
    own id ("Notes on API pumps.pdf" names no family), so it never counts."""
    from .standards_inventory import FAMILY_OTHER, family_from_identifier

    try:
        row = conn.execute(
            "SELECT standard_family, document_number FROM document_classification WHERE document_id = ?", (document_id,)
        ).fetchone()
    except sqlite3.Error:  # an older table without these columns: the file name alone
        row = None
    if row is not None and row[0]:
        return str(row[0]).upper()
    if row is not None and row[1]:
        return family_from_identifier(str(row[1]))
    start = _START.match(filename or "")
    return family_from_identifier(start.group(1)) if start else FAMILY_OTHER


#: The family word a file name starts with (after any leading punctuation or spaces), ended by an underscore, a digit or any
#: other non-letter ("NACE_MR0175_..." is NACE); a letter of any alphabet after it, accented too, means a longer word: no family.
_START = re.compile(r"^[\W_]*([A-Za-z]+)(?![^\W\d_])")


def _held_for_confirmation(conn, document_id: str) -> bool:
    """A company standard a non-administrator uploaded that no administrator has confirmed (#620): reviews do not use it,
    and neither does this lane. Unreadable counts as held (the safe side)."""
    from .company_standard_confirm import held_clause

    clause, params = held_clause("d.id")
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'document_role_access'").fetchone():
            return False  # no upload grants recorded at all: nothing was uploaded by anyone, so nothing is held
        sql = f"SELECT 1 FROM documents d WHERE d.id = ? AND {clause}"
        return conn.execute(sql, [document_id, *params]).fetchone() is not None
    except sqlite3.Error:
        return True


def not_standards(conn, ids) -> list[str]:
    """The ids that may NOT go by this lane: not classified a company standard, held for an administrator's confirmation,
    not in the library, or whose own identifier is of another family."""
    from .standards_converter import NotStandardsText, require_role

    bad = []
    for d in sorted(ids):
        row = conn.execute("SELECT filename FROM documents WHERE id = ?", (d,)).fetchone()
        try:
            require_role(conn, d)
        except (NotStandardsText, sqlite3.Error):  # no classification held: never a standard
            bad.append(d)
            continue
        if row is None or _held_for_confirmation(conn, d) or family_of(conn, d, str(row[0] or "")) not in FAMILIES:
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


#: The lane's users, each named at its call site (owner, 3 Nov, 25 Nov and 26 Nov 2026, #1584): the standards converter (the rule
#: label job's two passes), the rule approval step with its blind sample judge, and the reading of a held book's FIGURE pages as
#: pictures (the tool `scripts/standards_figures.py`, #1584 7189065710). Nothing else opens the lane.
USERS = frozenset(
    {"standards converter", "rule approval", "rule approval judge", "figure reading"}
)


@contextlib.contextmanager
def open_for(conn, document_ids, checked: Checked | None = None, *, user: str):
    """Declare exactly these documents for the Claude calls inside, by the standards lane: each is checked here (`check`), or
    lies inside `checked`, a set `check` made earlier. Anything else is refused before anything is declared, and so is a
    caller not in USERS, a call inside a review run, or one inside another declaration (the lane never narrows a review's
    list or another caller's documents)."""
    from . import claude_approved

    if user not in USERS:
        raise NotStandardsLane(f"{user!r} is not a user of the standards lane; nothing is sent")
    if claude_approved.review_run() or claude_approved.carried() is not None:  # the gate's own question (spend ledger too)
        raise NotStandardsLane("the standards lane is never opened inside a review run or another declaration")
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
