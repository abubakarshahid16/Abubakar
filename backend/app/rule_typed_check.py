"""#805 plan change 6, owner's first decided rule: a rule with a verified field role and no figure, checked by words.

AI PROPOSES, CODE VERIFIES, CODE DECIDES. A second call over stored rules, its own prompt version, on the naming step's
engine and model: one of `is_not`, `is_one_of`, `at_least_class`, with the values word for word from the quote. Code keeps
a proposal only when every value is in the quote, the field is a text field, the sentence's direction agrees (a "not" for
`is_not`, none for the other two), a list names at least two, and a class reads as a class. Else no check: a Query.

THE DECISION uses what the project already reads: `conditions` for a material, `field_links` for a class and for a named
value letter for letter. No spelling table, nothing per layout (rule 13). It says a verdict only when it can prove one. A
value that is merely different from a forbidden one is not proof it is not that one; another name for a listed one is not
a breach. Missing, unclear or multi-valued is decided before this, in `rulebook_v2_review`: a Query.

A person's tick signs the check with the rule; `plain_words` is what the checklist shows. On a COPY's `compiled_rules`.
"""

from __future__ import annotations

import hashlib
import json

from . import (
    claude_batch_run,
    condition_choice,
    conditions,
    field_links,
    rule_field_naming,
    standards_compiler,
    standards_converter,
)
from .ai.json_reply import unfenced
from .compile_budget import _room_gate
from .compiled_rule_report import compiled_rows, latest_compile
from .config import settings
from .db import add_column_if_missing
from .reasoning_provider import ClaudeProvider, Packet, schema_errors

PROMPT_VERSION = "field-check-v1"
IS_NOT, IS_ONE_OF, AT_LEAST_CLASS = "is_not", "is_one_of", "at_least_class"
OPERATIONS = (IS_NOT, IS_ONE_OF, AT_LEAST_CLASS)
VERIFIED, NO_CHECK, UNVERIFIED = "verified", "no_check", "unverified"
COMPLIANT, NON_COMPLIANT = "COMPLIANT", "NON_COMPLIANT"
# Why code did not keep a proposal.
VALUE_NOT_IN_QUOTE = "value_not_in_quote"
NOT_A_TEXT_FIELD = "not_a_text_field"
DIRECTION_DISAGREES = "direction_disagrees"
LIST_NOT_PLAIN = "list_not_plain"
NOT_A_CLASS = "not_a_class"
REPLY_UNREADABLE = "reply_unreadable"
MAX_OUTPUT_TOKENS = 150
_COLUMNS = (
    "check_op",
    "check_values",
    "check_state",
    "check_reason",
    "check_prompt",
    "check_model",
)
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "op": {"type": ["string", "null"]},
        "values": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["op", "values"],
    "additionalProperties": False,
}
SYSTEM = (
    "You read one requirement of an engineering standard about one datasheet field. Say whether a person could check it"
    " by reading that field alone. Answer JSON only:"
    ' {"op": "is_not" | "is_one_of" | "at_least_class" | null, "values": [...]}.'
    " is_not: the field must not be the named thing. is_one_of: the sentence plainly lists the allowed things."
    " at_least_class: the field must be at least the named pressure class. Copy each value word for word from the"
    " requirement. Answer null with no values for anything else, and whenever you are not sure."
)


def ensure_columns(conn) -> None:
    with conn:
        for column in _COLUMNS:
            add_column_if_missing(conn, "compiled_rules", column, "TEXT")


def _fold(text) -> str:
    return " ".join(str(text or "").casefold().split())


def verify(row, answer: dict | None, fields: dict[str, str]) -> tuple:
    """(op, values, state, reason). A proposal code cannot verify is no check at all."""
    if not isinstance(answer, dict):
        return None, [], UNVERIFIED, REPLY_UNREADABLE
    op, values = answer.get("op"), [v for v in answer.get("values") or [] if _fold(v)]
    if op is None:
        return None, [], NO_CHECK, None
    quote = _fold(row["quote"])
    refused = None
    if op not in OPERATIONS or not values:
        refused = REPLY_UNREADABLE
    elif not all(_fold(v) in quote for v in values):
        refused = VALUE_NOT_IN_QUOTE
    elif fields.get(row["field_role"]) != "text":
        refused = NOT_A_TEXT_FIELD
    elif bool(field_links._NEGATION.search(row["quote"] or "")) != (op == IS_NOT):
        refused = DIRECTION_DISAGREES
    elif op == IS_ONE_OF and len(values) < 2:
        refused = LIST_NOT_PLAIN
    elif op == AT_LEAST_CLASS and (len(values) != 1 or _class_of(values[0]) is None):
        refused = NOT_A_CLASS
    if refused:
        return None, [], UNVERIFIED, refused
    return op, values, VERIFIED, None


def _class_of(text: str):
    return field_links.read_categorical("flange_rating", text)


def _material(values: list[str], stated: str) -> bool | None:
    """Is the stated material among these? True, False proven by family, None when it cannot be told."""
    needs = [
        c
        for v in values
        for c in condition_choice.extract(_fold(v))
        if c.kind == "material"
    ]
    return (
        conditions._material_verdict(needs, {"field_value": stated}) if needs else None
    )


def decide(op: str, values: list[str], stated: str) -> tuple[str | None, str]:
    """(COMPLIANT or NON_COMPLIANT, words), or (None, words) when code cannot prove either."""
    named = field_links.is_named_value(stated, tuple(values))
    among = True if named else _material(values, stated)
    listed = "; ".join(values)
    if op == AT_LEAST_CLASS:
        got, need = _class_of(stated), _class_of(values[0])
        if got is None or need is None:
            return None, f"the value states no pressure class to set against {listed}"
        return (COMPLIANT if got >= need else NON_COMPLIANT), (
            f"the sheet states {stated}; the rule asks for at least {listed}"
        )
    if among is None:
        return None, f"the sheet states {stated}; code cannot tell it from {listed}"
    meets = among if op == IS_ONE_OF else not among
    words = "one of" if op == IS_ONE_OF else "not"
    return (COMPLIANT if meets else NON_COMPLIANT), (
        f"the sheet states {stated}; the rule asks for {words} {listed}"
    )


def plain_words(op: str | None, values: list[str]) -> str:
    """The check as the checklist shows it, for a person to sign."""
    listed = ", ".join(values)
    return {
        IS_NOT: f"The field must not be: {listed}",
        IS_ONE_OF: f"The field must be one of: {listed}",
        AT_LEAST_CLASS: f"The field must be at least: {listed}",
    }.get(op, "")


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
    return "chk-" + hashlib.sha256(str(row["id"]).encode("utf-8")).hexdigest()[:40]


def _todo(conn, document_id: str) -> tuple[dict | None, list]:
    """The rules this step asks about: a verified role and no figure, not asked yet."""
    run = latest_compile(conn, document_id)
    if run is None:
        return None, []
    rows = [dict(r) for r in compiled_rows(conn, run["id"])]
    return run, [
        r
        for r in rows
        if r.get("field_role_state") == rule_field_naming.VERIFIED
        and r.get("limit_value") is None
        and not r.get("check_prompt")
    ]


def _packets(rows, label: str) -> dict[str, Packet]:
    return {
        _custom_id(row): Packet(
            prompt=f"FIELD: {row['field_role'].replace('_', ' ')}\nREQUIREMENT: {row['quote']}",
            num_ctx=0,
            num_predict=MAX_OUTPUT_TOKENS,
            json_schema=ANSWER_SCHEMA,
            system=SYSTEM,
            step=standards_converter.step_for(label),
            prompt_version=PROMPT_VERSION,
        )
        for row in rows
    }


def _store(conn, rows, replies: dict, fields, model: str) -> dict:
    done: dict[str, int] = {}
    with conn:
        for row in rows:
            custom = _custom_id(row)
            if custom not in replies:
                continue
            op, values, state, reason = verify(row, replies[custom], fields)
            done[state] = done.get(state, 0) + 1
            if reason:
                done[f"reason:{reason}"] = done.get(f"reason:{reason}", 0) + 1
            conn.execute(
                "UPDATE compiled_rules SET check_op = ?, check_values = ?, check_state = ?, check_reason = ?,"
                " check_prompt = ?, check_model = ? WHERE id = ? AND check_prompt IS NULL",
                (
                    op,
                    json.dumps(values),
                    state,
                    reason,
                    PROMPT_VERSION,
                    model,
                    row["id"],
                ),
            )
    return dict(sorted(done.items()))


def name_checks(
    conn,
    documents: dict[str, str],
    equipment_type: str,
    *,
    estimate_only: bool = False,
    send=None,
    max_usd: float | None = None,
    **wait,
) -> list[dict]:
    """One report per standard: counts only. An estimate writes nothing and needs no key."""
    model = settings.rule_field_naming_model
    fields = rule_field_naming.fixed_fields(equipment_type)
    if not estimate_only:
        if settings.rule_field_naming_engine != rule_field_naming.ENGINE_CLAUDE:
            raise rule_field_naming.SwitchedOff(
                "RULE_FIELD_NAMING_ENGINE is off; nothing was sent"
            )
        for document_id, label in documents.items():
            standards_compiler.require_allowed(conn, document_id, label)
        ensure_columns(conn)
    reports, plans = {}, {}
    for document_id, label in sorted(documents.items(), key=lambda kv: kv[1]):
        run, rows = _todo(conn, document_id)
        base = {"standard": label, "prompt_version": PROMPT_VERSION, "rules": len(rows)}
        if run is None:
            reports[document_id] = {**base, "status": "not_compiled"}
        elif not rows:
            reports[document_id] = {**base, "status": "nothing_to_ask"}
        elif estimate_only:
            estimate = rule_field_naming._estimate(model, _packets(rows, label))
            reports[document_id] = {**base, "status": "estimate", "estimate": estimate}
        else:
            job = f"{document_id}:{PROMPT_VERSION}:{run['id']}"
            plans[document_id] = (job, rows, _packets(rows, label), base)
    if plans:
        limit = (
            settings.standards_compiler_max_usd_per_day if max_usd is None else max_usd
        )
        outcomes = claude_batch_run.run_many(
            conn,
            ClaudeProvider(model, transport=send),
            {job: packets for job, _rows, packets, _base in plans.values()},
            room=_room_gate(float(limit)),
            usable=lambda answer: _reply(answer) is not None,
            declared={plan[0]: {doc} for doc, plan in plans.items()},
            **wait,
        )
        for doc, (job, rows, _packets_sent, base) in plans.items():
            outcome = outcomes[job]
            replies = {c: _reply(a) for c, a in outcome.answers.items()}
            reports[doc] = {
                **base,
                **rule_field_naming.outcome_report(outcome, rows),
                "stored": _store(conn, rows, replies, fields, model),
            }
    return [reports[d] for d in sorted(reports, key=lambda d: documents[d])]
