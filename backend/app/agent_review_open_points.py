"""How many lines of a run's AI review are still open: every line that is not a proven "Pass" and not class "Not applicable".

ONE home for the rule the sign route and the screen both use (the screen counts the same way in `plainWords.openPoints`). Read only. A run with no AI
review (no table, no run row) answers None, never 0: "no AI review" is not "nothing open".
"""

from __future__ import annotations

import sqlite3

from . import agent_review_schema


def open_points(conn: sqlite3.Connection, run_id: str) -> int | None:
    """The open lines of the run's AI review; None when the run has no AI review."""
    if not agent_review_schema.has_tables(conn):
        return None
    if (
        conn.execute(
            "SELECT 1 FROM agent_review_run WHERE run_id = ?", (run_id,)
        ).fetchone()
        is None
    ):
        return None
    row = conn.execute(
        "SELECT COUNT(*) FROM agent_review_line WHERE run_id = ? AND verdict_class != 'Not applicable' AND word != 'Pass'",
        (run_id,),
    ).fetchone()
    return int(row[0])


def refusal(open_count: int) -> str:
    """The plain reason a sign is refused while the AI review has open points and the engineer has not said they were read."""
    noun = "point" if open_count == 1 else "points"
    return (
        f"the AI review of this document has {open_count} open {noun} that "
        f"{'is' if open_count == 1 else 'are'} not on this sheet; read them and confirm that you have (ai_review_read) before signing"
    )
