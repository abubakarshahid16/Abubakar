"""#805 plan change 6, owner's order: name each compiled rule's field from the equipment type's fixed field list.

A SECOND STEP OVER STORED RULES. `compile-v2` stays frozen and is not paid for again: one call per rule, its own prompt
version, Batch, the answer cache, `RULE_FIELD_NAMING_MODEL`. Engine `RULE_FIELD_NAMING_ENGINE`, default off. An estimate
sends nothing and needs no key.

AI PROPOSES, CODE VERIFIES. The list is `datasheet_roles.wanted_roles`, the roles the type's own mandatory list and
checklist use, read as data; a type with no list is refused. Code checks the role is on that list, the rule's unit fits
the role's kind, and a figure's comparator can apply to it. What fails stays `unverified`, and never pairs. A rule the
reply says no field answers is kept as `not_on_datasheet`, with one of a few reasons. Nothing is dropped. A person's tick
on the checklist signs the rule and its role; nothing here approves anything.

ONCE PER RULE. A stored result is never overwritten, so what a person read is what stands. On a COPY's `compiled_rules`.
Standards text goes out only through `claude_batch_run` and `reader_transport`. Counts only in any report.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from . import (
    claims,
    claude_batch_run,
    datasheet_checks,
    datasheet_roles,
    standards_compiler,
    standards_converter,
)
from .ai.json_reply import unfenced
from .compile_budget import _room_gate
from .compiled_rule_report import compiled_rows, latest_compile
from .config import settings
from .db import add_column_if_missing
from .reasoning_provider import ClaudeProvider, Packet, schema_errors

PROMPT_VERSION = "field-role-v1"
ENGINE_CLAUDE = "claude"
VERIFIED, NOT_ON_DATASHEET, UNVERIFIED = "verified", "not_on_datasheet", "unverified"
#: Why no datasheet field answers a rule: the reply's choice, fixed words, no document text.
NOT_ON_SHEET_REASONS = (
    "installation_or_piping",
    "test_or_inspection",
    "document_or_record",
    "design_method",
    "another_property_not_listed",
)
# Why code did not accept a proposed field.
ROLE_NOT_ON_TYPE = "role_not_on_type"
UNIT_DOES_NOT_FIT = "unit_does_not_fit"
COMPARATOR_DOES_NOT_FIT = "comparator_does_not_fit"
REPLY_UNREADABLE = "reply_unreadable"
MAX_OUTPUT_TOKENS = 120
#: The role kinds and the `claims` dimensions that are the same quantity. `number` is whatever is not one of these.
_DIMENSIONS = {
    "pressure": {"pressure"},
    "temperature": {"temperature"},
    "length": {"length"},
    "flow": {"mass_flow", "volumetric_flow"},
    "area": {"area"},
    "density": {"density"},
    "viscosity": {"viscosity"},
    "percent": {"percent"},
}
_MEASURED = frozenset().union(*_DIMENSIONS.values())
_COLUMNS = (
    "field_role",
    "field_role_state",
    "field_role_reason",
    "field_role_prompt",
    "field_role_model",
)
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "field_role": {"type": ["string", "null"]},
        "reason": {"type": ["string", "null"]},
    },
    "required": ["field_role", "reason"],
    "additionalProperties": False,
}


class SwitchedOff(RuntimeError):
    """RULE_FIELD_NAMING_ENGINE is off, so nothing was sent."""


class NoFieldList(ValueError):
    """This equipment type has no fixed field list to choose from."""


def ensure_columns(conn) -> None:
    with conn:
        for column in _COLUMNS:
            add_column_if_missing(conn, "compiled_rules", column, "TEXT")


def fixed_fields(equipment_type: str) -> dict[str, str]:
    """{role: its kind}: the one list the checklist uses for this type."""
    rules = datasheet_checks.load_rules()
    table = rules.get("checklists") or {}
    if datasheet_checks.table_key(equipment_type, table) not in table:
        raise NoFieldList(f"{equipment_type!r} has no checklist field list")
    wanted = datasheet_roles.wanted_roles(equipment_type, rules)
    return {role: rules["roles"][role]["kind"] for role in sorted(wanted)}


def system_text(fields: dict[str, str]) -> str:
    listed = "\n".join(
        f"- {role}: {role.replace('_', ' ')} ({kind})" for role, kind in fields.items()
    )
    return (
        "You read one requirement of an engineering standard and name the one datasheet field it limits, choosing only"
        " from this fixed list. Pick a field only when the requirement is about the value that field states. Answer"
        ' JSON only: {"field_role": <a name from the list, or null>, "reason": <null when you name a field, else one'
        f" of: {', '.join(NOT_ON_SHEET_REASONS)}>}}.\n\nTHE LIST:\n{listed}"
    )


def _prompt(row) -> str:
    return (
        f"FIELD AS READ: {row['field']}\nCOMPARATOR: {row['comparator']}\nUNIT: {row['unit']}\n"
        f"REQUIREMENT: {row['quote']}"
    )


def _unit_fits(unit: str | None, kind: str) -> bool:
    dimension = claims.unit_dimension(unit or "")
    if kind == "number":
        return dimension not in _MEASURED
    return dimension in _DIMENSIONS.get(kind, ())


def verify(row, answer: dict | None, fields: dict[str, str]) -> tuple:
    """(role, state, reason). Code's word on the reply: a role it cannot verify is not a role."""
    if not isinstance(answer, dict):
        return None, UNVERIFIED, REPLY_UNREADABLE
    role = answer.get("field_role")
    if role is None:
        said = answer.get("reason")
        return (
            None,
            NOT_ON_DATASHEET,
            said if said in NOT_ON_SHEET_REASONS else "another_property_not_listed",
        )
    if role not in fields:
        return None, UNVERIFIED, ROLE_NOT_ON_TYPE
    if row["limit_value"] is not None:
        if fields[role] == "text" or not row["comparator"]:
            return None, UNVERIFIED, COMPARATOR_DOES_NOT_FIT
        if not _unit_fits(row["unit"], fields[role]):
            return None, UNVERIFIED, UNIT_DOES_NOT_FIT
    return role, VERIFIED, None


def _reply(answer: dict | None) -> dict | None:
    text = (answer or {}).get("text") or ""
    if (answer or {}).get("finish_reason") == "length" or schema_errors(
        text, ANSWER_SCHEMA
    ):
        return None
    try:
        return json.loads(unfenced(text))
    except (ValueError, TypeError):
        return None


def _custom_id(row) -> str:
    return "role-" + hashlib.sha256(str(row["id"]).encode("utf-8")).hexdigest()[:40]


def _packets(rows, label: str, system: str) -> dict[str, Packet]:
    return {
        _custom_id(row): Packet(
            prompt=_prompt(row),
            num_ctx=0,
            num_predict=MAX_OUTPUT_TOKENS,
            json_schema=ANSWER_SCHEMA,
            system=system,
            step=standards_converter.step_for(label),
            prompt_version=PROMPT_VERSION,
        )
        for row in rows
    }


def _store(conn, rows, replies: dict[str, dict | None], fields, model: str) -> Counter:
    done: Counter = Counter()
    with conn:
        for row in rows:
            custom = _custom_id(row)
            if custom not in replies:
                continue
            role, state, reason = verify(row, replies[custom], fields)
            done[state] += 1
            if reason:
                done[f"reason:{reason}"] += 1
            conn.execute(
                "UPDATE compiled_rules SET field_role = ?, field_role_state = ?, field_role_reason = ?,"
                " field_role_prompt = ?, field_role_model = ? WHERE id = ? AND field_role_prompt IS NULL",
                (role, state, reason, PROMPT_VERSION, model, row["id"]),
            )
    return done


def _job(document_id: str, run_id: str) -> str:
    return f"{document_id}:{PROMPT_VERSION}:{run_id}"


def _todo(conn, document_id: str) -> tuple[dict | None, list]:
    run = latest_compile(conn, document_id)
    if run is None:
        return None, []
    rows = compiled_rows(conn, run["id"])
    if rows and "field_role_prompt" not in dict(
        rows[0]
    ):  # the step has not run on this copy
        return run, rows
    return run, [r for r in rows if not r["field_role_prompt"]]


def _estimate(model: str, packets: dict[str, Packet]) -> dict:
    worst = standards_compiler.estimate(model, packets)
    rules = len(packets)
    return {
        **worst,
        "worst_usd_per_100_rules": round(worst["worst_usd"] * 100 / rules, 4)
        if rules
        else None,
    }


def _sent(conn, plans: dict, fields, model: str, send, max_usd, **wait) -> dict:
    """Ask, in one batch as the API allows, and store what came back. `wait`: the Batch run's own options."""
    provider = ClaudeProvider(model, transport=send)
    limit = settings.standards_compiler_max_usd_per_day if max_usd is None else max_usd
    outcomes = claude_batch_run.run_many(
        conn,
        provider,
        {_job(doc, plan[4]): plan[2] for doc, plan in plans.items()},
        room=_room_gate(float(limit)),
        usable=lambda answer: _reply(answer) is not None,
        declared={_job(doc, plan[4]): {doc} for doc, plan in plans.items()},
        **wait,
    )
    reports = {}
    for doc, (_label, rows, _packets_sent, base, run_id) in plans.items():
        outcome = outcomes[_job(doc, run_id)]
        replies = {c: _reply(a) for c, a in outcome.answers.items()}
        stored = _store(conn, rows, replies, fields, model)
        reports[doc] = {
            **base,
            "status": "waiting" if outcome.waiting else "done",
            "rules": len(rows),
            "answered": len(outcome.answers),
            "not_answered": len(rows) - len(outcome.answers),
            "stored": dict(sorted(stored.items())),
        }
    return reports


def name_fields(
    conn,
    documents: dict[str, str],
    equipment_type: str,
    *,
    estimate_only: bool = False,
    client=None,
    send=None,
    max_usd: float | None = None,
    **wait,
) -> list[dict]:
    """One report per standard: counts only. An estimate writes nothing."""
    model = settings.rule_field_naming_model
    fields = fixed_fields(equipment_type)
    wait["client"] = client
    if not estimate_only:
        if settings.rule_field_naming_engine != ENGINE_CLAUDE:
            raise SwitchedOff("RULE_FIELD_NAMING_ENGINE is off; nothing was sent")
        for document_id, label in documents.items():
            standards_compiler.require_allowed(conn, document_id, label)
    if not estimate_only:
        ensure_columns(conn)
    system, reports, plans = system_text(fields), {}, {}
    for document_id, label in sorted(documents.items(), key=lambda kv: kv[1]):
        run, rows = _todo(conn, document_id)
        base = {
            "standard": label,
            "equipment_type": equipment_type,
            "fields_on_list": len(fields),
            "prompt_version": PROMPT_VERSION,
        }
        if run is None:
            reports[document_id] = {**base, "status": "not_compiled"}
            continue
        packets = _packets(rows, label, system)
        if estimate_only:
            reports[document_id] = {
                **base,
                "status": "estimate",
                "rules": len(rows),
                "estimate": _estimate(model, packets),
            }
            continue
        plans[document_id] = (label, rows, packets, base, run["id"])
    if plans:
        reports |= _sent(conn, plans, fields, model, send, max_usd, **wait)
    return [reports[d] for d in sorted(reports, key=lambda d: documents[d])]
