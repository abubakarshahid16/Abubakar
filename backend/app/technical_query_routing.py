"""Who sent a technical query and where it goes, read BY CODE from its document number (lead-4 and the planner, 26 Nov 2026: all 33 queries
of the first import showed "Unknown contractor").

Two admin-set maps, each set once: the contractor code inside the number ("<project>-<contractor>-<company>-<TYPE>-<n>") -> the
contractor, and the discipline code after the number (PRO, MET, ...) -> the department. They are tried first; the sender's address or
domain rule (`technical_queries._routed`) fills what is still blank. Only BLANK fields are ever filled (a value the message carried or an
engineer set is kept), and a saved rule fills the blanks of the queries already held. Never a guess from the mail's words.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

TABLE = "query_code_rules"
CONTRACTOR_CODE = "contractor_code"
DISCIPLINE = "discipline"
KINDS = (CONTRACTOR_CODE, DISCIPLINE)
_CODE = re.compile(r"^[A-Z0-9]{2,12}$")


def create_table(conn) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {TABLE} (id TEXT PRIMARY KEY, kind TEXT NOT NULL, code TEXT NOT NULL, contractor_name TEXT, "
        "department TEXT, created_by TEXT, created_at TEXT NOT NULL, UNIQUE(kind, code))"
    )


def rules(conn) -> list[dict[str, Any]]:
    """The code rules in the routing-rules shape (`match_type` is the kind, `match_value` the code)."""
    create_table(conn)
    return [
        {"id": r["id"], "match_type": r["kind"], "match_value": r["code"], "contractor_name": r["contractor_name"], "department": r["department"]}
        for r in conn.execute(f"SELECT * FROM {TABLE} ORDER BY kind, code")
    ]  # fmt: skip


def set_rule(
    conn,
    kind: str,
    code: str,
    contractor: str | None,
    department: str | None,
    actor_user_id: str | None,
) -> None:
    """Save one code rule (a contractor code sets the contractor; a discipline code sets the department), then fill the blanks it covers."""
    value = (code or "").strip().upper()
    if kind not in KINDS or not _CODE.match(value):
        raise ValueError(
            "a code rule names a contractor code or a discipline code of 2 to 12 letters or digits"
        )
    contractor = (
        ((contractor or "").strip() or None) if kind == CONTRACTOR_CODE else None
    )
    department = (department or "").strip() or None
    if not contractor and not department:
        raise ValueError(
            "a contractor code rule sets a contractor (and may set a department); a discipline rule sets a department"
        )
    from .technical_queries import now

    create_table(conn)
    conn.execute(
        f"INSERT INTO {TABLE}(id,kind,code,contractor_name,department,created_by,created_at) VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(kind, code) DO UPDATE SET contractor_name=excluded.contractor_name, department=excluded.department",
        (str(uuid.uuid4()), kind, value, contractor, department, actor_user_id, now()),
    )
    backfill(conn)


def delete_rule(conn, rule_id: str) -> None:
    create_table(conn)
    conn.execute(f"DELETE FROM {TABLE} WHERE id=?", (rule_id,))


def _rule(conn, kind: str, code: str | None):
    if not code:
        return None
    return conn.execute(
        f"SELECT * FROM {TABLE} WHERE kind=? AND code=?", (kind, code.upper())
    ).fetchone()


def by_code(
    conn,
    subject: str | None,
    discipline: str | None,
    contractor: str | None,
    department: str | None,
):
    """(contractor, department, source) filled from the code rules: only blank fields; `source` names the rule(s) used, or None."""
    from .technical_query_subject import parse

    create_table(conn)
    ref = parse(subject) or {}
    used = []
    if not contractor and (
        rule := _rule(conn, CONTRACTOR_CODE, ref.get("contractor_code"))
    ):
        contractor, used = rule["contractor_name"], [*used, rule["id"]]
        department = department or rule["department"]
    if not department and (
        rule := _rule(conn, DISCIPLINE, discipline or ref.get("discipline"))
    ):
        department, used = rule["department"], [*used, rule["id"]]
    return contractor, department, ("code:" + ",".join(used)) if used else None


def routed(
    conn,
    data: dict[str, Any],
    contractor: str | None,
    department: str | None,
    by_sender,
):
    """The code rules first, then `by_sender` (the address / domain rules) for what is still blank. (contractor, department, source)."""
    contractor, department, source = by_code(
        conn, data.get("subject"), None, contractor, department
    )
    if contractor and department:
        return contractor, department, source
    contractor, department, sender = by_sender(
        conn, data["from_address"], contractor, department
    )
    return contractor, department, source or sender


def backfill(conn) -> int:
    """Fill the blank contractor / department of the queries already held from the code rules; returns how many queries changed."""
    from .technical_queries import now

    changed = 0
    for q in conn.execute(
        "SELECT id, subject, discipline_code, contractor_name, department FROM technical_queries "
        "WHERE COALESCE(contractor_name,'')='' OR COALESCE(department,'')=''"
    ).fetchall():
        contractor, department, source = by_code(
            conn,
            q["subject"],
            q["discipline_code"],
            q["contractor_name"],
            q["department"],
        )
        if source and (contractor, department) != (
            q["contractor_name"],
            q["department"],
        ):
            conn.execute(
                "UPDATE technical_queries SET contractor_name=?, department=?, routing_source=?, updated_at=? WHERE id=?",
                (contractor, department, source, now(), q["id"]),
            )
            changed += 1
    return changed
