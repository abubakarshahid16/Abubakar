"""#805 plan change 6: what a tick signs beside a rule: its field role and typed check, from the compiled row it came from.

They are not in the checklist file's stamp, so the import records them on the approval and a read compares. Read only.
"""

from __future__ import annotations

import json
import sqlite3


def field_role_of(conn, version_id: str) -> dict:
    """The role the field-naming step gave the compiled row this version came from: its role, state and reason, all
    None when the step has not run or a copy has no such column. Never a reason to decide: `rule_field_naming`."""
    out = {}
    for names in (
        ("field_role", "field_role_state", "field_role_reason"),
        ("check_op", "check_values", "check_state", "check_reason"),
        ("sentence_strength",),
    ):
        try:
            row = conn.execute(
                f"SELECT {', '.join('c.' + n for n in names)} FROM rulebook_compiled_row l"
                " JOIN compiled_rules c ON c.id = l.compiled_row_id"
                " WHERE l.rule_version_id = ? ORDER BY l.rowid DESC LIMIT 1",
                (version_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
        out.update(zip(names, row or (None,) * len(names), strict=True))
    return out


def content_to_sign(conn, version_id: str) -> str:
    """The field role and typed check a tick signs with a rule. They are not in the file's stamp, so the tick records
    them and a read compares: a role or check added or changed after the tick is not what was signed."""
    now = field_role_of(conn, version_id)
    names = (
        "field_role",
        "field_role_state",
        "check_op",
        "check_values",
        "check_state",
        "sentence_strength",
    )
    return json.dumps({n: now[n] for n in names}, sort_keys=True)
