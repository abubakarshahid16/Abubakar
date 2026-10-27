"""K1 (code audit 26 Oct): an issued number carries the engineer's confirmation only for the
words they confirmed.

A permanent number's key is the comment's SUBJECT (the field, the clause), not its words, so a
later run lands on the same number with a new value, reason or wording. Carrying the old
confirmation onto those words would issue a comment nobody read. The number stays; the tick does
not travel: the row is unconfirmed until the engineer confirms the new words (or edits them),
which also refreshes the words the number keeps (`main._mint_crs_numbers` refreshes the stored
words only from a row the engineer confirmed, never from one confirmed by its number alone).
"""

from __future__ import annotations

import re

from . import crs_mapping


def _fold(text) -> str:
    return " ".join(str(text or "").lower().split())


_EDITION_MARK = re.compile(r" \((?:19|20)\d\d\)")


def words_changed_since_issue(row: dict, snapshot: dict) -> bool:
    """True when the number kept words and this row's own words, folded for case and spacing,
    are not them. False for an AI/web draft (it prints the issued words,
    `crs_mapping.carry_issued_wording`) and when either side has no words (a number saved empty
    or as a waiting sentence by an older build: nothing to compare, the earlier behaviour stands)."""
    if str(row.get("ai_review_comment") or "").strip():
        return False
    # The stored words may end with the line `main._replaced_numbers` adds after this comparison
    # on a field row that replaces earlier numbers: not words of the comment.
    lines = str(snapshot.get("comment") or "").split("\n")
    while lines and _fold(lines[-1]).startswith(
        ("replaces earlier ", "earlier issued ")
    ):
        lines.pop()
    stored, now = _fold("\n".join(lines)), _fold(row.get("comment"))
    # Order 227: a row issued before references named their edition gains "(2023)" or
    # "(edition not recorded)" in its lead: that is not the words changing.
    now = now.replace(" (edition not recorded)", "")
    stored = stored.replace(" (edition not recorded)", "")
    if not _EDITION_MARK.search(stored):
        now = _EDITION_MARK.sub("", now)
    waiting = {_fold(w) for w in crs_mapping.WAITING_COMMENTS}
    return bool(
        stored
        and now
        and stored not in waiting
        and now not in waiting
        and stored != now
    )


def carry_confirmation(row: dict, record: dict) -> bool:
    """Carry an issued number's confirmation onto `row`. True when it was carried (the row is
    confirmed, `confirmed_by_number` says by the number alone when the row's own findings were
    not confirmed); False when the words changed (`changed_since_confirmed`, still unconfirmed)."""
    own = bool(row.get("engineer_confirmed"))
    if not own and words_changed_since_issue(row, record):
        row["changed_since_confirmed"] = True
        return False
    row["engineer_confirmed"] = True
    row["confirmed_by_number"] = not own
    return True
