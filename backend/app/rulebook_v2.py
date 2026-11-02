"""#805 plan change 6, part A: the rulebook's version 2 tables. Behind RULEBOOK_V2_ENABLED, default off.

THE RECORD. `rulebook_rule` is one logical rule: its key outlives clause numbers, editions and readings.
`rulebook_version` is one reading of it, holding the requirement as field, comparator, value, unit; a rule with no
single figure holds none, and the table refuses one. Who it is for (`rulebook_applicability`) and when it does not
apply (`rulebook_exception`) are rows of their own, and `rulebook_provenance` is the page, verified quote hash, model
and prompt version behind it. `rulebook_approval` is a person's decision; `rulebook_event` is written by triggers.
`rulebook_snapshot` freezes the whole book once per compile, and `rulebook_run` says which snapshot a review run used.

NOTHING IS EVER REWRITTEN. Triggers refuse UPDATE and DELETE on all of it, and INSERT OR REPLACE, which would slip past
a delete trigger. A version's rows are sealed by the counts it was written with. A change appends a version, and an
approval belongs to one version: the next one is not in force until a person decides on it.

ONLY A PERSON APPROVES. One script calls `record_decision`, `scripts/import_rule_approvals.py`, for a tick a named signer
made in a returned checklist. No route or job does. The database refuses an approval whose approver is not an active
row of `users`, or that names no tier (owner or engineer) or no equipment type. No rule is in force without one.
`approved_rules` is the only way out of the book for a review, and holds only what such an approval covers.

NOTHING READS THIS FOR A VERDICT unless RULEBOOK_V2_REVIEW_ENABLED is on (`rulebook_v2_review`). `rulebook_run` says
which: version 1 and no snapshot, or version 2 and the snapshot the run froze.

A COPY ONLY. Only `ensure_schema` creates the tables; nothing at startup calls it, and it refuses a live-shaped file.
The tables grant nothing: read access stays with the grant tables (CLAUDE.md rule 5). `standard_requirements` is not
written here.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from . import live_guard
from .config import settings
from .rulebook_v2_check import CANNOT_TELL, Outcome, check_requirement
from .rulebook_v2_schema import (
    APPROVE,
    CONTEXT_DEPENDENT,  # noqa: F401 - the word callers read here
    ENGINEER,  # noqa: F401
    OWNER,  # noqa: F401
    REJECT,  # noqa: F401
    RETIRE,  # noqa: F401
    SCHEMA,
    TABLES,  # noqa: F401
    TIERS,  # noqa: F401
    V1,
    V2,
    trigger_sql,
)

logger = logging.getLogger(__name__)


class SwitchedOff(RuntimeError):
    """RULEBOOK_V2_ENABLED is off, so nothing was read or written."""


class RefusedLive(RuntimeError):
    """This file is shaped like a live database; version 2 tables go on a copy."""


class RuleRefused(ValueError):
    """A decision this module will not record. Says why, never in document words."""


def require_on() -> None:
    if not settings.rulebook_v2_enabled:
        raise SwitchedOff("RULEBOOK_V2_ENABLED is off; nothing was read or written")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def has_schema(conn) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'rulebook_event'"
    ).fetchone()
    return row[0] == 1


def _is_missing(conn, statement: str, held: set[str]) -> bool:
    words = statement.split()
    if words[0] != "ALTER":
        return words[2] not in held
    # Empty before the table exists, and then the ALTER runs after its CREATE.
    return words[5] not in {
        r[1] for r in conn.execute(f"PRAGMA table_info({words[2]})")
    }


def ensure_schema(conn) -> None:
    """Create what is missing, all or none, on a copy. Run twice it does nothing; no other table is touched."""
    require_on()
    path = next(
        (r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), ""
    )
    if path and live_guard.is_live_shaped(path):
        raise RefusedLive("this is a live-shaped database; run on a copy")
    held = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    missing = [s for s in SCHEMA if _is_missing(conn, s, held)]
    if not missing:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        for statement in missing:
            conn.execute(statement)
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


# ------------------------------------------------------------------------------------------------ appending


@dataclass(frozen=True)
class Reading:
    """One reading of one rule, ready to append."""

    rule_key: str
    standard: str
    requirement: Mapping
    strength: str | None
    sentence_strength: str | None
    context_flag: str | None
    applicability: tuple[tuple[str, str, int | None], ...]
    exceptions: tuple[str, ...]
    provenance: Mapping


_REQUIREMENT_FIELDS = (
    "kind",
    "field",
    "comparator",
    "value",
    "value_low",
    "value_high",
    "value_text",
    "unit",
    "unit_dimension",
)


def content_hash_of(
    requirement: Mapping,
    strength,
    sentence_strength,
    context_flag,
    applicability,
    exceptions,
    quote_sha256: str,
) -> str:
    """The same reading hashes the same: re-running on unchanged text makes no new version."""
    body = {
        "requirement": {k: requirement.get(k) for k in _REQUIREMENT_FIELDS},
        "strength": [strength, sentence_strength, context_flag],
        "applicability": sorted([kind, value] for kind, value, *_ in applicability),
        "exceptions": sorted(exceptions),
        "quote": quote_sha256,
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()


def _content_hash(reading: Reading) -> str:
    return content_hash_of(
        reading.requirement,
        reading.strength,
        reading.sentence_strength,
        reading.context_flag,
        reading.applicability,
        reading.exceptions,
        reading.provenance["quote_sha256"],
    )


def _insert_provenance(conn, version_id: str, source: Mapping) -> str:
    provenance_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO rulebook_provenance (id, rule_version_id, standard_document_id, edition, clause, page, quote,"
        " quote_sha256, quote_start, quote_end, page_source, page_min_conf, text_sha256, model, prompt_version,"
        " batch_id, compile_run_id, verified_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            provenance_id,
            version_id,
            source["standard_document_id"],
            source["edition"],
            source["clause"],
            source["page"],
            source["quote"],
            source["quote_sha256"],
            source["quote_start"],
            source["quote_end"],
            source["page_source"],
            source["page_min_conf"],
            source["text_sha256"],
            source["model"],
            source["prompt_version"],
            source["batch_id"],
            source["compile_run_id"],
            _now(),
        ),
    )
    return provenance_id


def _insert_version(conn, reading: Reading, rule_id, number, previous, actor) -> str:
    version_id, need = uuid.uuid4().hex, reading.requirement
    conn.execute(
        "INSERT INTO rulebook_version (id, rule_id, version_no, supersedes_id, content_hash, quote_sha256, kind, field,"
        " comparator, value, value_low, value_high, value_text, unit, unit_dimension, strength, sentence_strength,"
        " context_flag, applicability_count, exception_count, recorded_by, recorded_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            version_id,
            rule_id,
            number,
            previous,
            _content_hash(reading),
            reading.provenance["quote_sha256"],
            need["kind"],
            need["field"],
            need.get("comparator"),
            need.get("value"),
            need.get("value_low"),
            need.get("value_high"),
            need.get("value_text"),
            need.get("unit"),
            need.get("unit_dimension"),
            reading.strength,
            reading.sentence_strength,
            reading.context_flag,
            len(reading.applicability),
            len(reading.exceptions),
            actor,
            _now(),
        ),
    )
    provenance_id = _insert_provenance(conn, version_id, reading.provenance)
    for key_type, value, on_page in reading.applicability:
        conn.execute(
            "INSERT INTO rulebook_applicability (id, rule_version_id, key_type, value, on_page, provenance_id)"
            " VALUES (?,?,?,?,?,?)",
            (uuid.uuid4().hex, version_id, key_type, value, on_page, provenance_id),
        )
    for words in reading.exceptions:
        conn.execute(
            "INSERT INTO rulebook_exception (id, rule_version_id, condition_text, provenance_id) VALUES (?,?,?,?)",
            (uuid.uuid4().hex, version_id, words, provenance_id),
        )
    return version_id


def append_reading(conn, reading: Reading, actor: str) -> tuple[str, str]:
    """Write one reading inside the caller's transaction. Returns what happened, new_rule, new_version (the change
    waits for a person), new_source (the same reading on another text or edition) or unchanged, and the version."""
    rule = conn.execute(
        "SELECT id FROM rulebook_rule WHERE rule_key = ?", (reading.rule_key,)
    ).fetchone()
    if rule is None:
        rule_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO rulebook_rule (id, rule_key, standard, created_by, created_at) VALUES (?,?,?,?,?)",
            (rule_id, reading.rule_key, reading.standard, actor, _now()),
        )
        return "new_rule", _insert_version(conn, reading, rule_id, 1, None, actor)
    latest = conn.execute(
        "SELECT id, version_no, content_hash FROM rulebook_version WHERE rule_id = ?"
        " ORDER BY version_no DESC LIMIT 1",
        (rule[0],),
    ).fetchone()
    if latest[2] != _content_hash(reading):
        return "new_version", _insert_version(
            conn, reading, rule[0], latest[1] + 1, latest[0], actor
        )
    source = reading.provenance
    known = conn.execute(
        "SELECT 1 FROM rulebook_provenance WHERE rule_version_id = ? AND standard_document_id = ? AND page = ?"
        " AND text_sha256 = ? AND prompt_version = ?",
        (
            latest[0],
            source["standard_document_id"],
            source["page"],
            source["text_sha256"],
            source["prompt_version"],
        ),
    ).fetchone()
    if known:
        return "unchanged", latest[0]
    _insert_provenance(conn, latest[0], source)
    return "new_source", latest[0]


def link_compiled_row(conn, compile_run_id: str, row_id: str, version_id: str) -> None:
    """Which version this compile's row became, once, inside the caller's transaction."""
    known = conn.execute(
        "SELECT 1 FROM rulebook_compiled_row WHERE compile_run_id = ? AND compiled_row_id = ?",
        (compile_run_id, row_id),
    ).fetchone()
    if not known:
        conn.execute(
            "INSERT INTO rulebook_compiled_row (compile_run_id, compiled_row_id, rule_version_id) VALUES (?,?,?)",
            (compile_run_id, row_id, version_id),
        )


# --------------------------------------------------------------------------------------- a person's decision


def _standing(conn, version_id: str) -> dict[str, dict]:
    """{equipment type: the approval that stands for it}. For each type the LAST decision counts, and it must be an
    approval. A decision that names no type (a retirement) ends every approval before it."""
    standing: dict[str, dict] = {}
    columns = {r[1] for r in conn.execute("PRAGMA table_info(rulebook_approval)")}
    signed = "signed_content" if "signed_content" in columns else "NULL"
    for row in conn.execute(
        "SELECT id, decision, equipment_type, approver_id, approver_name, decided_at, tier, note,"
        f" {signed} FROM rulebook_approval WHERE rule_version_id = ? ORDER BY rowid",
        (version_id,),
    ):
        names = (
            "id",
            "decision",
            "type",
            "by_id",
            "by",
            "at",
            "tier",
            "note",
            "signed",
        )
        one = dict(zip(names, row, strict=True))
        kind = _fold_type(one["type"])
        if not kind:
            standing.clear()
        elif one["decision"] == APPROVE:
            standing[kind] = one
        else:
            standing.pop(kind, None)
    return standing


DOCUMENT_GONE = "document_deleted"
DROPPED_BY_LATER_COMPILE = "not_in_the_newest_compile"


def _fold_type(equipment_type: str | None) -> str:
    return " ".join((equipment_type or "").casefold().split())


def approval_in_force(conn, version_id: str) -> str | None:
    """The newest approval this version stands on for any equipment type, or None."""
    standing = _standing(conn, version_id)
    return max(standing.values(), key=lambda a: a["at"])["id"] if standing else None


def _insert_decision(
    conn,
    version_id: str,
    *,
    decision: str,
    engineer_id: str,
    tier: str,
    equipment_type: str | None = None,
    provenance_viewed: tuple[str, ...] = (),
    note: str | None = None,
    source_sha256: str | None = None,
    signed_content: str | None = None,
) -> str:
    if decision == APPROVE:
        held = {
            r[0]
            for r in conn.execute(
                "SELECT id FROM rulebook_provenance WHERE rule_version_id = ?",
                (version_id,),
            )
        }
        if not provenance_viewed or not set(provenance_viewed) <= held:
            raise RuleRefused(
                "an approval names the quotes of this version that were read"
            )
    person = conn.execute(
        "SELECT display_name FROM users WHERE id = ?", (engineer_id,)
    ).fetchone()
    approval_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO rulebook_approval (id, rule_version_id, decision, approver_id, decided_at, note,"
        " provenance_viewed, tier, equipment_type, approver_name, source_sha256, signed_content)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            approval_id,
            version_id,
            decision,
            engineer_id,
            _now(),
            note,
            json.dumps(sorted(provenance_viewed)),
            tier,
            equipment_type,
            person[0] if person else None,
            source_sha256,
            signed_content,
        ),
    )
    return approval_id


def record_decision(conn, version_id: str, **decision) -> str:
    """One person's decision on one version."""
    return record_decisions(conn, [{"version_id": version_id, **decision}])[0]


def record_decisions(conn, decisions: list[dict]) -> list[str]:
    """A person's decisions, all or none. Its only caller is the import of a signer's ticks."""
    require_on()
    with conn:
        return [_insert_decision(conn, **one) for one in decisions]


def last_decision(conn, version_id: str, equipment_type: str) -> tuple | None:
    """(decision, approver id) of the last decision on this version for this type, or None."""
    wanted = _fold_type(equipment_type)
    last = None
    for row in conn.execute(
        "SELECT decision, approver_id, equipment_type FROM rulebook_approval"
        " WHERE rule_version_id = ? ORDER BY rowid",
        (version_id,),
    ):
        if _fold_type(row[2]) in ("", wanted):
            last = (row[0], row[1])
    return last


def checklist_stamp(equipment_type: str, rows) -> str:
    """The stamp of a checklist file: its equipment type and each row's (rule id, version, snapshot). The generator
    writes the same hash (`checklib.rulebook_stamp`), and a returned file whose stamp differs is refused."""
    body = [
        _fold_type(equipment_type),
        sorted([str(a), int(b), str(c)] for a, b, c in rows),
    ]
    blob = json.dumps(body, separators=(",", ":")).encode("utf-8")
    return "rb2-" + hashlib.sha256(blob).hexdigest()[:24]


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
    )
    return json.dumps({n: now[n] for n in names}, sort_keys=True)


def signed_content_of(conn, version_id: str, equipment_type: str) -> str | None:
    """What the approval standing for this type recorded, or None."""
    return (_standing(conn, version_id).get(_fold_type(equipment_type)) or {}).get(
        "signed"
    )


def approved_rules(conn, equipment_type: str) -> list[dict]:
    """The rules a review of this equipment type may use: the current version of a rule, when the last decision on it
    for this type is a person's approval. An unapproved or superseded rule never appears: a rule whose newest reading
    waits for a decision is absent, not served from its older reading. Off, or no tables: nothing.

    Nor does an approved rule whose document is gone, or that the newest compile of its standard no longer holds: those
    are in `withheld_rules`, with why, and logged here (ids and reasons only). Read-only, on any connection.

    `document_id` is the source the quote comes from: a caller keeps a rule only if the reader may read that document
    (rule 5). `unit` is as stored, `rulebook_v2_check.NO_UNIT` for a sentence that prints none; `value` is None for a
    rule with no single figure, so a caller that compares has nothing to compare and says "cannot tell"."""
    rules, withheld = _read_book(conn, equipment_type)
    for one in withheld:
        logger.warning(
            "rulebook: approved rule %s withheld: %s", one["rule_id"], one["reason"]
        )
    return rules


def withheld_rules(conn, equipment_type: str) -> list[dict]:
    """Rules approved for this type that `approved_rules` will not give, each with its rule id, version and reason."""
    return _read_book(conn, equipment_type)[1]


def _dropped_by_a_later_compile(conn, rule_id: str, standard: str) -> bool:
    """The newest compile of this rule's standard holds no row of this rule. Partial or whole: the rule is not served
    on a reading the newest compile did not repeat. It is not retired: a person may still decide, and a later compile
    that finds it again serves it again."""
    newest = conn.execute(
        "SELECT compile_run_id FROM rulebook_snapshot WHERE standard = ? OR standard_document_id IN"
        " (SELECT p.standard_document_id FROM rulebook_provenance p JOIN rulebook_version v"
        " ON v.id = p.rule_version_id WHERE v.rule_id = ?) ORDER BY rowid DESC LIMIT 1",
        (standard, rule_id),
    ).fetchone()
    if newest is None:
        return False
    return (
        conn.execute(
            "SELECT 1 FROM rulebook_compiled_row c JOIN rulebook_version v ON v.id = c.rule_version_id"
            " WHERE c.compile_run_id = ? AND v.rule_id = ? LIMIT 1",
            (newest[0], rule_id),
        ).fetchone()
        is None
    )


def _read_book(conn, equipment_type: str) -> tuple[list[dict], list[dict]]:
    wanted = _fold_type(equipment_type)
    if not settings.rulebook_v2_enabled or not wanted or not has_schema(conn):
        return [], []
    out, withheld = [], []
    for row in conn.execute(
        "SELECT v.id, v.rule_id, v.version_no, v.field, v.comparator, v.value, v.unit, v.context_flag, v.strength,"
        " r.standard FROM rulebook_version v JOIN rulebook_rule r ON r.id = v.rule_id"
        " WHERE v.version_no = (SELECT MAX(version_no) FROM rulebook_version WHERE rule_id = v.rule_id)"
        " ORDER BY r.standard, v.rule_id"
    ).fetchall():
        approval = _standing(conn, row[0]).get(wanted)
        if approval is None:
            continue
        source = conn.execute(
            "SELECT p.clause, p.page, p.quote, p.quote_sha256, p.edition, p.standard_document_id"
            " FROM rulebook_provenance p JOIN documents d ON d.id = p.standard_document_id"
            " WHERE p.rule_version_id = ? ORDER BY p.rowid DESC LIMIT 1",
            (row[0],),
        ).fetchone()
        reason = None
        if source is None:
            reason = DOCUMENT_GONE
        elif _dropped_by_a_later_compile(conn, row[1], row[9]):
            reason = DROPPED_BY_LATER_COMPILE
        if reason:
            withheld.append({"rule_id": row[1], "version": row[2], "reason": reason})
            continue
        keys = conn.execute(
            "SELECT key_type, value FROM rulebook_applicability WHERE rule_version_id = ? ORDER BY rowid",
            (row[0],),
        ).fetchall()
        exceptions = conn.execute(
            "SELECT condition_text FROM rulebook_exception WHERE rule_version_id = ? ORDER BY rowid",
            (row[0],),
        ).fetchall()
        out.append(
            {
                "rule_id": row[1],
                "version": row[2],
                "field": row[3],
                "comparator": row[4],
                "value": row[5],
                "unit": row[6],
                "applies_to": next((k[1] for k in keys if k[0] == "subject"), None),
                "conditions": [k[1] for k in keys if k[0] != "subject"],
                "exceptions": [e[0] for e in exceptions],
                **field_role_of(conn, row[0]),
                "signed_matches": approval["signed"] == content_to_sign(conn, row[0]),
                "clause": source[0],
                "page": source[1],
                "quote": source[2],
                "quote_sha256": source[3],
                "standard": row[9],
                "edition": source[4],
                "document_id": source[5],
                "context_flag": row[7],
                "strength": row[8],
                "approval": {
                    "by": approval["by"] or approval["by_id"],
                    "at": approval["at"],
                    "tier": approval["tier"],
                    "note": approval["note"],
                },
            }
        )
    return out, withheld


# ------------------------------------------------------------------------------------------------ snapshots


def _current_versions(conn) -> list:
    return conn.execute(
        "SELECT v.id, v.version_no, v.content_hash, r.rule_key FROM rulebook_version v"
        " JOIN rulebook_rule r ON r.id = v.rule_id"
        " WHERE v.version_no = (SELECT MAX(version_no) FROM rulebook_version WHERE rule_id = v.rule_id)"
        " ORDER BY r.rule_key"
    ).fetchall()


def take_snapshot(
    conn,
    compile_run_id: str,
    document_id: str,
    counts: Mapping,
    actor: str,
    standard: str | None = None,
) -> str:
    """The whole book as it stands, once per compile, inside the caller's transaction. Each member names the approval
    it stood on then, or none: a member with none is held, not in force, whatever is decided later."""
    found = conn.execute(
        "SELECT id FROM rulebook_snapshot WHERE compile_run_id = ?", (compile_run_id,)
    ).fetchone()
    if found:
        return found[0]
    members = [
        (row, approval_in_force(conn, row[0])) for row in _current_versions(conn)
    ]
    digest = hashlib.sha256(
        json.dumps([[r[3], r[1], r[2], a or ""] for r, a in members]).encode("utf-8")
    ).hexdigest()
    snapshot_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO rulebook_snapshot (id, compile_run_id, standard_document_id, snapshot_hash, rules_total,"
        " rules_in_force, counts_json, created_by, created_at, standard) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            snapshot_id,
            compile_run_id,
            document_id,
            digest,
            len(members),
            sum(1 for _r, a in members if a),
            json.dumps(counts, sort_keys=True),
            actor,
            _now(),
            standard,
        ),
    )
    conn.executemany(
        "INSERT INTO rulebook_snapshot_rule (snapshot_id, rule_version_id, approval_id) VALUES (?,?,?)",
        [(snapshot_id, r[0], a) for r, a in members],
    )
    return snapshot_id


def in_force(conn, snapshot_id: str) -> list[str]:
    """The versions a run on this snapshot may use: approved when it was taken. Nothing else, ever."""
    return [
        r[0]
        for r in conn.execute(
            "SELECT rule_version_id FROM rulebook_snapshot_rule WHERE snapshot_id = ? AND approval_id IS NOT NULL"
            " ORDER BY rule_version_id",
            (snapshot_id,),
        )
    ]


def in_force_versions(conn, snapshot_id: str) -> list[tuple[str, int]]:
    """`in_force`, as the (rule id, version number) pairs a rule is known by."""
    return [
        (r[0], r[1])
        for r in conn.execute(
            "SELECT v.rule_id, v.version_no FROM rulebook_snapshot_rule s"
            " JOIN rulebook_version v ON v.id = s.rule_version_id"
            " WHERE s.snapshot_id = ? AND s.approval_id IS NOT NULL",
            (snapshot_id,),
        )
    ]


def record_run(
    conn, review_run_id: str, used_snapshot_id: str | None = None
) -> dict | None:
    """The run says which rulebook it used: version 1 and no snapshot, with the newest snapshot named apart as not
    used, or version 2 and its snapshot. Off, or tables not created (a live database): nothing, and nothing is created.
    A run's record is written once."""
    if not settings.rulebook_v2_enabled or not has_schema(conn):
        return None
    done = conn.execute(
        "SELECT used_version, snapshot_id, latest_snapshot_id FROM rulebook_run WHERE review_run_id = ?",
        (review_run_id,),
    ).fetchone()
    if done is None:
        newest = conn.execute(
            "SELECT id FROM rulebook_snapshot ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        done = (
            V2 if used_snapshot_id else V1,
            used_snapshot_id,
            newest[0] if newest else None,
        )
        with conn:
            conn.execute(
                "INSERT INTO rulebook_run (review_run_id, used_version, snapshot_id, latest_snapshot_id, recorded_at)"
                " VALUES (?,?,?,?,?)",
                (review_run_id, *done, _now()),
            )
    return {
        "used_version": done[0],
        "snapshot_id": done[1],
        "latest_snapshot_id": done[2],
    }


# ------------------------------------------------------------------------------------------------ one check


def check_version(
    conn,
    version_id: str,
    value: object,
    unit: str | None = None,
    *,
    applies: Mapping[str, bool] | None = None,
    excepted: Mapping[str, bool] | None = None,
) -> Outcome:
    """One rule's outcome, in the order a rule is read: approved, who it is for, unless, what it demands. `applies`
    and `excepted` answer by row id; a row with no answer is unknown, so "cannot tell". A rule found not to bind has no
    outcome (`outcome` None) and says why. No verdict code calls this; a test holds that."""
    require_on()
    if approval_in_force(conn, version_id) is None:
        return Outcome(CANNOT_TELL, "not_approved")
    rows = conn.execute(
        "SELECT id FROM rulebook_applicability WHERE rule_version_id = ?", (version_id,)
    ).fetchall()
    answers = [(applies or {}).get(r[0]) for r in rows]
    if False in answers:
        return Outcome(None, "does_not_apply")
    if None in answers:
        return Outcome(CANNOT_TELL, "applicability_unknown")
    rows = conn.execute(
        "SELECT id FROM rulebook_exception WHERE rule_version_id = ?", (version_id,)
    ).fetchall()
    answers = [(excepted or {}).get(r[0]) for r in rows]
    if True in answers:
        return Outcome(None, "excepted")
    if None in answers:
        return Outcome(CANNOT_TELL, "exception_unknown")
    names = ("kind", "comparator", "value", "value_low", "value_high", "unit")
    row = conn.execute(
        f"SELECT {', '.join(names)} FROM rulebook_version WHERE id = ?", (version_id,)
    ).fetchone()
    return check_requirement(dict(zip(names, row, strict=True)), value, unit)


# ------------------------------------------------------------------------------------------------- the checks


#: SQL that must return zero: what the tables' own constraints cannot hold.
_ZERO_ROWS = {
    "version_without_provenance": "SELECT v.id FROM rulebook_version v WHERE NOT EXISTS"
    " (SELECT 1 FROM rulebook_provenance p WHERE p.rule_version_id = v.id)",
    "version_short_of_applicability": "SELECT v.id FROM rulebook_version v WHERE v.applicability_count <>"
    " (SELECT COUNT(*) FROM rulebook_applicability a WHERE a.rule_version_id = v.id)",
    "version_short_of_exceptions": "SELECT v.id FROM rulebook_version v WHERE v.exception_count <>"
    " (SELECT COUNT(*) FROM rulebook_exception e WHERE e.rule_version_id = v.id)",
    "approval_unsigned": f"SELECT id FROM rulebook_approval WHERE tier IS NULL"
    f" OR (decision = '{APPROVE}' AND equipment_type IS NULL)",
    "snapshot_member_unapproved": "SELECT s.rule_version_id FROM rulebook_snapshot_rule s JOIN rulebook_approval a"
    f" ON a.id = s.approval_id WHERE a.decision <> '{APPROVE}' OR a.rule_version_id <> s.rule_version_id",
    "version_without_event": "SELECT v.id FROM rulebook_version v WHERE NOT EXISTS (SELECT 1 FROM rulebook_event e"
    " WHERE e.entity = 'rulebook_version' AND e.entity_id = v.id)",
}


def integrity_problems(conn) -> dict[str, int]:
    """{check: rows that break it}; empty when the book holds. Counts only. A dropped trigger is one of them."""
    out = {
        name: count
        for name, sql in _ZERO_ROWS.items()
        if (count := len(conn.execute(sql).fetchall()))
    }
    held = {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")
    }
    wanted = {statement.split()[2] for statement in trigger_sql()}
    if wanted - held:
        out["trigger_missing"] = len(wanted - held)
    return out
