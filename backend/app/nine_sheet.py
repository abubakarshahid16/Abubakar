"""How the sheet and "How it was reviewed" READ the nine-role record (nine-role design, section B and A role 9).

Pure functions over a `nine_contract.ReviewRecord` (counts, ids and the codes' own reason words; never a document title or text):

  roles_line       the ONE line on the first sheet: "Roles run: 7 of 9: ...; not run: 2 Project context: <reason>". A run with no record
                   (every review before the record) says "Roles: not recorded (reviewed before the role record)": nothing is invented.
  how_rows         one row per role for the sheet "How it was reviewed": state, engine, models, calls, cost ("not known" when the record
                   has none, never 0), the reason when it did not run, and the counts it produced.
  not_checked_rows what a role did not read or did not send, with the reason, from the same record, for "What was not checked".
  apply_wordings   the writer (role 9): an AI wording of a comment is kept only when `crs_wording.lock` finds no number, unit, clause,
                   page, standard or status changed; else the code's own words stand and the drop is counted.
  load_record      the record of a run from its three tables, read only; None when the run has none.

The writer never builds a second sheet: the sheet is `crs_one`'s, the comments are `crs_comments`', the check is `crs_completeness`'.
No model, no network, no write.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter

from .nine_contract import (
    ROLE_NAMES,
    CallEntry,
    ReadEntry,
    ReviewRecord,
    RoleRecord,
)

NOT_RECORDED_LINE = "Roles: not recorded (reviewed before the role record)"
STATE_WORDS = {"ran": "ran", "ran_partly": "ran partly", "not_run": "not run"}
ENGINE_WORDS = {"claude": "Claude", "local": "Local", "code": "code only"}
UNKNOWN = "not known"
_NOT_READ_KEYS = ("not_read", "not_sent", "not_available", "left_out")


# ------------------------------------------------------------------------------------------------ the first sheet


def roles_line(record: ReviewRecord | None) -> str:
    """The first-sheet line. Words only from the record: a role that did not run is NAMED with its reason."""
    if record is None or not record.roles:
        return NOT_RECORDED_LINE
    if len(record.roles) != len(ROLE_NAMES):
        return f"Roles: the record holds {len(record.roles)} of {len(ROLE_NAMES)} roles (incomplete)"
    return record.roles_line()


# ------------------------------------------------------------------------------------------------ "How it was reviewed"


def _count_of(value) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{k} {_count_of(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return str(len(value))
    return str(value)


def _produced(role: RoleRecord) -> str:
    return "; ".join(
        f"{k.replace('_', ' ')}: {_count_of(v)}" for k, v in role.produced.items()
    )


def _reads(role: RoleRecord) -> str:
    if not role.reads:
        return ""
    kinds = Counter(r.document_kind.replace("_", " ") for r in role.reads)
    pictures = sum(r.pictures for r in role.reads)
    parts = ", ".join(f"{n} {k} block(s)" for k, n in sorted(kinds.items()))
    return parts + (f", {pictures} picture(s)" if pictures else "")


def how_rows(record: ReviewRecord | None) -> list[list]:
    """[label, detail] per role; [] when the run has no record (the sheet's first line already says "not recorded")."""
    if record is None:
        return []
    out: list[list] = []
    for r in record.roles:
        bits = [STATE_WORDS.get(r.state, r.state)]
        if r.engine:
            bits.append(ENGINE_WORDS.get(r.engine, r.engine))
        if r.models:
            bits.append(", ".join(r.models))
        bits.append(f"{r.calls} call(s)")
        if r.engine == "claude":
            bits.append("cost (USD) " + (UNKNOWN if r.usd is None else f"{r.usd:.2f}"))
        if r.why and r.state != "ran":
            bits.append("why: " + r.why)
        for extra in (_produced(r), _reads(r)):
            if extra:
                bits.append(extra)
        out.append([f"Role {r.role_no} {r.role}", "; ".join(bits)])
    return out


def not_checked_rows(record: ReviewRecord | None) -> list[list]:
    """[what, how many, why]: a role that did not run, and what a role did not read or send, from its own counts."""
    if record is None:
        return []
    rows: list[list] = []
    for r in record.roles:
        if r.state == "not_run":
            rows.append(
                [f"Role {r.role_no} {r.role} did not run", None, r.why or UNKNOWN]
            )
        elif r.state == "ran_partly":
            rows.append(
                [f"Role {r.role_no} {r.role} ran partly", None, r.why or UNKNOWN]
            )
        for key, value in r.produced.items():
            if not any(mark in key for mark in _NOT_READ_KEYS):
                continue
            if isinstance(value, dict):
                rows += [
                    [f"Role {r.role_no} {r.role}: {key.replace('_', ' ')}", n, str(why)]
                    for why, n in value.items()
                ]
            else:
                n = len(value) if isinstance(value, (list, tuple)) else value
                rows.append(
                    [
                        f"Role {r.role_no} {r.role}: {key.replace('_', ' ')}",
                        n,
                        "see the role's reason",
                    ]
                )
    return rows


# ------------------------------------------------------------------------------------------------ the writer (role 9)


def apply_wordings(
    rows: list[dict], wordings: dict[str, str]
) -> tuple[dict[str, str], dict[str, int]]:
    """(wordings kept by key, drops counted by reason). `rows` are the code-worded comments, each {key, comment, standard_reference,
    page_section, row_kind}; a wording is kept only when `crs_wording.lock` finds every fact of the code's words still there."""
    from . import crs_wording

    kept: dict[str, str] = {}
    dropped: Counter = Counter()
    by_key = {str(r["key"]): r for r in rows}
    for key, text in wordings.items():
        row = by_key.get(str(key))
        if row is None:
            dropped["no such comment"] += 1
            continue
        why = crs_wording.lock(text, row)
        if why is None:
            kept[str(key)] = text.strip()
        else:
            dropped[why] += 1
    return kept, dict(dropped)


# ------------------------------------------------------------------------------------------------ reading the stored record


def _has(conn, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def load_record(conn: sqlite3.Connection, run_id: str | None) -> ReviewRecord | None:
    """The run's record from `agent_review_role`, `agent_review_role_call` and `agent_review_role_read`; None when the run has no role
    rows (or the tables are not there: a review before the record). Reads only; it never makes a table."""
    if not run_id or not _has(conn, "agent_review_role"):
        return None
    rows = conn.execute(
        "SELECT * FROM agent_review_role WHERE run_id = ? ORDER BY role_no", (run_id,)
    ).fetchall()
    if not rows:
        return None
    reads: dict[int, list[ReadEntry]] = {}
    if _has(conn, "agent_review_role_read"):
        for r in conn.execute(
            "SELECT * FROM agent_review_role_read WHERE run_id = ? ORDER BY role_no, call_id, seq",
            (run_id,),
        ):
            reads.setdefault(r["role_no"], []).append(
                ReadEntry(
                    role_no=r["role_no"], call_id=r["call_id"], document_id=r["document_id"], document_kind=r["document_kind"],
                    pages=tuple(json.loads(r["pages_json"] or "[]")), chapter_id=r["chapter_id"], part_no=r["part_no"],
                    part_of=r["part_of"], chars=r["chars"] or 0, text_sha256=r["text_sha256"] or "", pictures=r["pictures"] or 0,
                )
            )  # fmt: skip
    calls: list[CallEntry] = []
    if _has(conn, "agent_review_role_call"):
        for c in conn.execute(
            "SELECT * FROM agent_review_role_call WHERE run_id = ? ORDER BY sent_at",
            (run_id,),
        ):
            calls.append(
                CallEntry(
                    role_no=c["role_no"], call_id=c["call_id"], step=c["step"], engine=c["engine"], model=c["model"] or "",
                    request_sha256=c["request_sha256"] or "", state=c["state"], error_code=c["error_code"], usd=c["usd"],
                    sent_at=c["sent_at"] or "",
                )
            )  # fmt: skip
    roles = tuple(
        RoleRecord(
            role_no=r["role_no"], role=r["role"], state=r["state"], why=r["why"], engine=r["engine"],
            models=tuple(json.loads(r["models_json"] or "[]")), calls=r["calls"] or 0, usd=r["usd"],
            produced=json.loads(r["produced_json"] or "{}"), reads=tuple(reads.get(r["role_no"], ())),
            started_at=r["started_at"], finished_at=r["finished_at"],
        )
        for r in rows
    )  # fmt: skip
    return ReviewRecord(
        run_id=run_id,
        paper_id="",
        engine_choice="automatic",
        roles=roles,
        calls=tuple(calls),
        shown_document_ids=None,
    )
