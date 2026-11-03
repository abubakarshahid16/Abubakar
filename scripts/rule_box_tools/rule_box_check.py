"""#805 rule boxes, STEPS 2 and 3: a typed, tested check for each box a or c rule, then a second opinion.

STEP 2 (reasoning model, ONE rule per prompt). Claude links the rule to a field of its equipment type's FIXED FIELD LIST
(`rule_field_naming.fixed_fields`: the checklist fields) and writes a typed check: an operator, a limit and a unit, or
an allowed / excluded list, with one passing and one failing test case. CODE VERIFIES AND CODE RUNS IT:

  * the field is on the list and its kind fits the limit and unit (`rule_field_naming.verify`);
  * the quote is inside the rule's own words; the limit, the unit and the comparator are in those words, bound as the
    compiler's own gate binds them (`compiled_rule_proof._limit_problem`); a condition is in the words too;
  * the limit and the unit agree with what the compiler stored, when it stored one;
  * both test cases run on the existing comparison (`comparison.compare` for a number, `rule_typed_check.decide` for a
    list; no new arithmetic): the passing case must come out COMPLIANT and the failing one NON_COMPLIANT.

Any failure is the status `failed check` with one fixed reason word, and the check is never used. A rule whose equipment
type has no fixed field list is `field list to confirm` (no call is made). A box b rule is stored by document kind
(`stored by kind`), for the AI to judge at review time. Boxes d and e are not touched here.

STEP 3 (a DIFFERENT model, fresh context, ONE rule per prompt, shown no earlier answer) is asked only: box, field,
limit, unit. It agrees only if all four match step 1's box and step 2's field, limit and unit after code
normalisation; only `agreed` rules advance (`advanced`).

STANDARDS TEXT ONLY. ON A COPY. Counts only in a report.
"""

from __future__ import annotations

import json
import re
import time

from app import claims, comparison, numparse, rule_field_naming, rule_typed_check
from app.ai.json_reply import unfenced
from app.compiled_rule_proof import _fold as _proof_fold
from app.compiled_rule_proof import _limit_problem, _main_clause
from app.config import settings
from rule_box_tools import rule_box_fields, rule_box_run
from rule_box_tools import rule_box_labels as rule_boxes

CHECK_VERSION = "box-check-v1"
SECOND_VERSION = "box-second-v1"
CHECKS, SECOND = "rule_box_checks", "rule_box_second"
CHECKED, FAILED, NO_CHECK = "checked", "failed check", "no typed check"
FIELD_TO_CONFIRM, BY_KIND = "field list to confirm", "stored by kind"
CHECK_BOXES, SENTENCE_BOX = ("a", "c"), "b"
NUMBER, LIST = "number", "list"
NUMBER_OPS = ("<=", ">=", "<", ">", "=")
LIST_OPS = rule_typed_check.OPERATIONS
NO_CHECK_REASONS = (
    "no_single_value",
    "not_on_the_sheet",
    "needs_another_document",
    "not_a_requirement",
)
CHECK_TOKENS, SECOND_TOKENS = 700, 400
QUOTE_CHARS = 1500
#: The model's own operator words, written back to the project's comparator.
_OP_ALIASES = {"==": "=", "≤": "<=", "≥": ">="}


def ensure_schema(conn) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {CHECKS} ("
        " rule_id TEXT PRIMARY KEY, status TEXT NOT NULL, reason TEXT, field_role TEXT, kind TEXT, op TEXT,"
        " limit_text TEXT, unit TEXT, values_json TEXT, condition_text TEXT, quote TEXT, pass_json TEXT, fail_json TEXT,"
        " document_kind TEXT, equipment_type TEXT, field_list_state TEXT, model TEXT, prompt_version TEXT, created_at TEXT NOT NULL)"
    )
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {SECOND} ("
        " rule_id TEXT PRIMARY KEY, box TEXT, field_role TEXT, limit_text TEXT, unit TEXT, agree INTEGER NOT NULL,"
        " differs TEXT, model TEXT NOT NULL, prompt_version TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    conn.commit()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _clean(text, limit: int = QUOTE_CHARS) -> str:
    words = " ".join(str(text or "").split())
    return words if len(words) <= limit else words[: limit - 1] + "…"


def fields_for(equipment_type: str | None, conn=None) -> dict[str, str] | None:
    """{role: kind} of the type's field list, or None: 'field list to confirm'. The approved checklist first; else, with
    a `conn`, the list built by `rule_box_fields` (state `FIELD_LIST_STATE`, to confirm). Never invented here."""
    name = rule_boxes.checklist_name(equipment_type)
    if name is None:
        return (
            rule_box_fields.stored(conn, equipment_type)
            if conn is not None and equipment_type
            else None
        )
    try:
        return rule_field_naming.fixed_fields(name)
    except rule_field_naming.NoFieldList:
        return None


def field_list_state(equipment_type: str | None) -> str:
    return (
        rule_box_fields.FIXED_STATE
        if rule_boxes.checklist_name(equipment_type)
        else rule_box_fields.FIELD_LIST_STATE
    )


def _fold(text) -> str:
    return " ".join(numparse.fold(str(text or "")).casefold().split())


def _unit_key(unit) -> str:
    return claims._fold_unit(str(unit or ""))


def _list_text(fields: dict[str, str]) -> str:
    return "\n".join(
        f"- {role}: {role.replace('_', ' ')} ({kind})" for role, kind in fields.items()
    )


# ----------------------------------------------------------------------------------------------- step 2


def check_prompt(row, label: str, equipment_type: str, fields: dict[str, str]) -> str:
    condition = _clean(row["condition_text"], 400)
    return (
        "You turn ONE requirement of an engineering standard into a typed check on ONE datasheet field, choosing the"
        " field only from the fixed list below. If a person could not check it by reading one field's value, say so.\n"
        f"THE EQUIPMENT: {equipment_type}\nTHE FIELD LIST:\n{_list_text(fields)}\n\n"
        f"THE STANDARD: {label}, clause {_clean(row['clause'], 30)}\n"
        + (f"ITS CONDITION: {condition}\n" if condition else "")
        + f"THE REQUIREMENT (its exact words): {_clean(row['quote'])}\n\n"
        "Answer ONLY one JSON object:\n"
        '{"field_role": <a name from the list, or null>, "kind": "number" | "list" | null,'
        ' "op": for a number one of "<=", ">=", "<", ">", "="; for a list one of "is_not", "is_one_of",'
        ' "at_least_class"; "limit": <for a number, the figure exactly as printed, else null>, "unit": <the unit exactly'
        ' as printed, else null>, "values": <for a list, the words of the allowed or excluded values copied exactly,'
        ' else []>, "condition": <the words of the requirement that say when it applies, copied exactly, else null>,'
        ' "quote": <the shortest exact words of the requirement that state the limit or the list>,'
        ' "pass_case": {"value": <a datasheet value that meets it>, "unit": <its unit or null>},'
        ' "fail_case": {"value": <a datasheet value that breaks it>, "unit": <its unit or null>},'
        f' "reason": <null when you write a check, else one of: {", ".join(NO_CHECK_REASONS)}>}}.\n'
        "Copy every figure and word exactly from the requirement. Never invent a limit."
    )


def _parse_object(text: str) -> dict | None:
    try:
        data = json.loads(unfenced(text))
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _case(case) -> tuple[str, str | None] | None:
    if not isinstance(case, dict) or not str(case.get("value") or "").strip():
        return None
    unit = case.get("unit")
    return str(case["value"]).strip(), (str(unit).strip() or None) if unit not in (
        None,
        "",
    ) else None


def _number_cases(
    op: str, limit: str, unit: str | None, passing, failing
) -> str | None:
    """Reason a test case fails, or None. The cases run on `comparison.compare`, the engine a review uses."""
    requirement = {
        "requirement_type": "numeric_limit",
        "operator": op,
        "raw_value": limit,
        "raw_unit": unit or "",
        "value": numparse.as_limit(limit),
    }
    want_dim = claims.unit_dimension(unit or "")
    for expected, case, reason in (
        (comparison.COMPLIANT, passing, "pass_case_fails"),
        (comparison.NON_COMPLIANT, failing, "fail_case_passes"),
    ):
        got = _case(case)
        if got is None:
            return "test_case_missing"
        value, case_unit = got
        if numparse.as_limit(value) is None:
            return "test_value_not_a_number"
        if (unit or case_unit) and claims.unit_dimension(case_unit or "") != want_dim:
            return "test_unit_not_the_quantity"
        fact = {
            "raw_value": value,
            "raw_unit": case_unit or "",
            "value": numparse.as_limit(value),
            "field_name": "test",
            "page": 1,
            "confirmed_by": "rule_box_check",
        }
        status = comparison.compare(requirement, fact).get("status")
        if status != expected:
            return reason
    return None


def _list_cases(op: str, values: list[str], role: str, passing, failing) -> str | None:
    free = rule_typed_check.is_free_text(role)
    synonyms = rule_typed_check.signed_synonyms(role)
    for expected, case, reason in (
        (rule_typed_check.COMPLIANT, passing, "pass_case_fails"),
        (rule_typed_check.NON_COMPLIANT, failing, "fail_case_passes"),
    ):
        got = _case(case)
        if got is None:
            return "test_case_missing"
        status, _words = rule_typed_check.decide(
            op, values, got[0], free_text=free, synonyms=synonyms
        )
        if status != expected:
            return reason
    return None


def verify_check(
    row, answer: dict | None, fields: dict[str, str]
) -> tuple[dict | None, str | None, str]:
    """(check, reason, status). `check` only when status is `checked`: everything verified and both cases passed."""
    if not isinstance(answer, dict):
        return None, "reply_unreadable", FAILED
    role, kind = answer.get("field_role"), answer.get("kind")
    if role is None or kind is None:
        said = answer.get("reason")
        return None, said if said in NO_CHECK_REASONS else "no_single_value", NO_CHECK
    quote = _fold(row["quote"])
    said_quote = _fold(answer.get("quote"))
    if len(said_quote) < 8 or said_quote not in quote:
        return None, "quote_not_in_rule", FAILED
    condition = " ".join(str(answer.get("condition") or "").split())
    if condition and _fold(condition) not in quote:
        return None, "condition_not_in_rule", FAILED
    op = _OP_ALIASES.get(str(answer.get("op") or ""), answer.get("op"))
    if kind == NUMBER:
        limit, unit = (
            str(answer.get("limit") or "").strip(),
            (str(answer.get("unit") or "").strip() or None),
        )
        as_row = {
            "limit_value": numparse.as_limit(limit),
            "comparator": op if op in NUMBER_OPS else None,
            "unit": unit,
        }
        if as_row["limit_value"] is None:
            return None, "limit_not_a_number", FAILED
        if op not in NUMBER_OPS:
            return None, "operator_not_allowed", FAILED
        role_ok, _state, why = rule_field_naming.verify(
            as_row, {"field_role": role}, fields
        )
        if role_ok is None:
            return None, why or "field_not_on_list", FAILED
        body = _main_clause(
            row["quote"], row["condition_text"] or "", row["exception_text"] or ""
        )
        problem = _limit_problem(
            limit, unit or "", op, body, _proof_fold(row["quote"]), row["field"] or ""
        )
        if problem:
            return None, problem, FAILED
        stored = row["limit_value"]
        if stored is not None and numparse.as_limit(limit) != float(stored):
            return None, "differs_from_compiled_limit", FAILED
        if row["unit"] and _unit_key(unit) != _unit_key(row["unit"]):
            return None, "differs_from_compiled_unit", FAILED
        why = _number_cases(
            op, limit, unit, answer.get("pass_case"), answer.get("fail_case")
        )
        if why:
            return None, why, FAILED
        check = {"kind": NUMBER, "op": op, "limit": limit, "unit": unit, "values": []}
    elif kind == LIST:
        if role not in fields:
            return None, "field_not_on_list", FAILED
        values = [str(v) for v in answer.get("values") or [] if str(v).strip()]
        as_row = {"quote": row["quote"], "field_role": role}
        good_op, good_values, state, why = rule_typed_check.verify(
            as_row, {"op": op, "values": values}, fields
        )
        if state != rule_typed_check.VERIFIED:
            return None, why or "list_not_verified", FAILED
        why = _list_cases(
            good_op, good_values, role, answer.get("pass_case"), answer.get("fail_case")
        )
        if why:
            return None, why, FAILED
        check = {
            "kind": LIST,
            "op": good_op,
            "limit": None,
            "unit": None,
            "values": good_values,
        }
    else:
        return None, "kind_not_allowed", FAILED
    check.update(
        field_role=role,
        quote=_clean(answer.get("quote")),
        condition=condition or None,
        pass_case=_case(answer.get("pass_case")),
        fail_case=_case(answer.get("fail_case")),
    )
    return check, None, CHECKED


def _record(conn, rule_id, status, reason, label, model, check=None) -> None:
    c = check or {}
    conn.execute(
        f"INSERT OR REPLACE INTO {CHECKS} (rule_id, status, reason, field_role, kind, op, limit_text, unit, values_json,"
        " condition_text, quote, pass_json, fail_json, document_kind, equipment_type, field_list_state, model, prompt_version, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            rule_id,
            status,
            reason,
            c.get("field_role"),
            c.get("kind"),
            c.get("op"),
            c.get("limit"),
            c.get("unit"),
            json.dumps(c.get("values") or []),
            c.get("condition"),
            c.get("quote"),
            json.dumps(c.get("pass_case")) if c else None,
            json.dumps(c.get("fail_case")) if c else None,
            label["document_kind"],
            label["equipment_type"],
            None
            if status in (FIELD_TO_CONFIRM, BY_KIND)
            else field_list_state(label["equipment_type"]),
            model,
            CHECK_VERSION,
            _now(),
        ),
    )


def settle_without_a_call(conn) -> dict:
    """Box b rules are stored by document kind; box a or c rules of a type with no field list are marked. No call."""
    ensure_schema(conn)
    rows = conn.execute(
        f"SELECT l.rule_id, l.box, l.document_kind, l.equipment_type FROM {rule_boxes.TABLE} l"
        f" WHERE l.box IN ('a','b','c') AND NOT EXISTS (SELECT 1 FROM {CHECKS} c WHERE c.rule_id = l.rule_id)"
    ).fetchall()
    counts = {BY_KIND: 0, FIELD_TO_CONFIRM: 0}
    for r in rows:
        if r["box"] == SENTENCE_BOX:
            _record(conn, r["rule_id"], BY_KIND, None, r, "")
            counts[BY_KIND] += 1
        elif fields_for(r["equipment_type"], conn) is None:
            _record(conn, r["rule_id"], FIELD_TO_CONFIRM, None, r, "")
            counts[FIELD_TO_CONFIRM] += 1
    conn.commit()
    return counts


def check_todo(conn) -> list:
    """Box a or c rules with a field list and no check stored yet, with their label."""
    rows = conn.execute(
        "SELECT r.id, r.standard_document_id, r.clause, r.field, r.comparator, r.limit_value, r.unit, r.condition_text,"
        " r.exception_text, r.quote, l.document_kind, l.equipment_type, l.box"
        f" FROM compiled_rules r JOIN {rule_boxes.TABLE} l ON l.rule_id = r.id"
        f" WHERE l.box IN ('a','c') AND NOT EXISTS (SELECT 1 FROM {CHECKS} c WHERE c.rule_id = r.id)"
        " ORDER BY r.standard_document_id, r.page, r.id"
    ).fetchall()
    return [r for r in rows if fields_for(r["equipment_type"], conn) is not None]


def check_jobs(conn, gate) -> tuple[list[rule_box_run.Job], dict, dict]:
    labels = rule_boxes.standard_labels(conn)
    refused: dict[str, str | None] = {}
    out, members, skipped = [], {}, 0
    for r in check_todo(conn):
        doc = r["standard_document_id"]
        if doc not in refused:
            refused[doc] = gate(doc, labels.get(doc, ""))
        if refused[doc] is not None:
            skipped += 1
            continue
        fields = fields_for(r["equipment_type"], conn)
        out.append(
            rule_box_run.Job(
                f"chk:{r['id']}",
                check_prompt(r, labels.get(doc, ""), r["equipment_type"], fields),
                frozenset({doc}),
                CHECK_TOKENS,
            )
        )
        members[f"chk:{r['id']}"] = (r, fields)
    return (
        out,
        members,
        {
            "rules_to_check": len(out),
            "rules_in_refused_standards": skipped,
            "prompts": len(out),
        },
    )


def check_storer(conn, members: dict, model: str):
    tally = {"checked": 0, "failed_check": 0, "no_typed_check": 0, "reasons": {}}

    def apply(job, text: str) -> bool:
        row, fields = members[job.key]
        check, reason, status = verify_check(row, _parse_object(text), fields)
        _record(conn, row["id"], status, reason, row, model, check)
        conn.commit()
        if status == CHECKED:
            tally["checked"] += 1
        elif status == NO_CHECK:
            tally["no_typed_check"] += 1
        else:
            tally["failed_check"] += 1
        if reason:
            tally["reasons"][reason] = tally["reasons"].get(reason, 0) + 1
        return True

    apply.tally = tally
    return apply


# ----------------------------------------------------------------------------------------------- step 3


def second_prompt(row, label: str, equipment_type: str, fields: dict[str, str]) -> str:
    """A fresh context: the requirement and the lists only; no earlier answer, box or check."""
    return (
        "You read ONE requirement of an engineering standard. Answer four things.\n"
        f"box: one letter.\n{rule_boxes.BOX_WORDS}.\n"
        f"field_role: the one datasheet field it limits, from this list only, or null:\n{_list_text(fields)}\n"
        "limit: for a number rule, the figure exactly as printed; for a list rule, the allowed or excluded words"
        " separated by |; else null.\nunit: the unit exactly as printed, else null.\n\n"
        f"THE EQUIPMENT: {equipment_type}\nTHE STANDARD: {label}, clause {_clean(row['clause'], 30)}\n"
        f"THE REQUIREMENT (its exact words): {_clean(row['quote'])}\n\n"
        'Answer ONLY one JSON object: {"box": "a", "field_role": null, "limit": null, "unit": null}.'
    )


def norm_limit(text) -> object:
    """A limit in comparable form: a number, a set of folded words, or None."""
    raw = str(text or "").strip()
    if not raw:
        return None
    number = numparse.as_limit(raw)
    if number is not None:
        return number
    parts = frozenset(_fold(p) for p in re.split(r"[|;]", raw) if _fold(p))
    return parts or None


def agree(
    first_box: str, check: dict, answer: dict | None
) -> tuple[bool, list[str], dict]:
    """(agreed, which of the four differ, the normalised second answer). All four must match."""
    if not isinstance(answer, dict):
        return False, ["reply_unreadable"], {}
    second = {
        "box": answer.get("box"),
        "field_role": answer.get("field_role"),
        "limit": norm_limit(answer.get("limit")),
        "unit": _unit_key(answer.get("unit")) or None,
    }
    mine_limit = (
        norm_limit(check.get("limit"))
        if check["kind"] == NUMBER
        else (frozenset(_fold(v) for v in check.get("values") or []) or None)
    )
    mine = {
        "box": first_box,
        "field_role": check["field_role"],
        "limit": mine_limit,
        "unit": _unit_key(check.get("unit")) or None,
    }
    differs = [
        k for k in ("box", "field_role", "limit", "unit") if second[k] != mine[k]
    ]
    return not differs, differs, second


def second_todo(conn) -> list:
    return conn.execute(
        "SELECT r.id, r.standard_document_id, r.clause, r.quote, l.box, l.equipment_type, c.field_role, c.kind, c.op,"
        f" c.limit_text, c.unit, c.values_json, c.model AS check_model FROM compiled_rules r"
        f" JOIN {CHECKS} c ON c.rule_id = r.id JOIN {rule_boxes.TABLE} l ON l.rule_id = r.id"
        f" WHERE c.status = '{CHECKED}' AND NOT EXISTS (SELECT 1 FROM {SECOND} s WHERE s.rule_id = r.id)"
        " ORDER BY r.standard_document_id, r.page, r.id"
    ).fetchall()


def second_jobs(conn, gate, model: str) -> tuple[list[rule_box_run.Job], dict, dict]:
    """Refuses the same model as step 2 used for a rule: a second check by the first model is no second check."""
    labels = rule_boxes.standard_labels(conn)
    refused: dict[str, str | None] = {}
    out, members, skipped, same_model = [], {}, 0, 0
    for r in second_todo(conn):
        if r["check_model"] == model:
            same_model += 1
            continue
        doc = r["standard_document_id"]
        if doc not in refused:
            refused[doc] = gate(doc, labels.get(doc, ""))
        if refused[doc] is not None:
            skipped += 1
            continue
        fields = fields_for(r["equipment_type"], conn)
        out.append(
            rule_box_run.Job(
                f"sec:{r['id']}",
                second_prompt(r, labels.get(doc, ""), r["equipment_type"], fields),
                frozenset({doc}),
                SECOND_TOKENS,
            )
        )
        members[f"sec:{r['id']}"] = r
    return (
        out,
        members,
        {
            "rules_to_second_check": len(out),
            "rules_in_refused_standards": skipped,
            "rules_whose_check_used_this_model": same_model,
            "prompts": len(out),
        },
    )


def second_storer(conn, members: dict, model: str):
    tally = {"agreed": 0, "differs": 0, "reasons": {}}

    def apply(job, text: str) -> bool:
        row = members[job.key]
        check = {
            "kind": row["kind"],
            "field_role": row["field_role"],
            "limit": row["limit_text"],
            "unit": row["unit"],
            "values": json.loads(row["values_json"] or "[]"),
        }
        ok, differs, second = agree(row["box"], check, _parse_object(text))
        conn.execute(
            f"INSERT OR REPLACE INTO {SECOND} (rule_id, box, field_role, limit_text, unit, agree, differs, model,"
            " prompt_version, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                row["id"],
                str(second.get("box") or "")[:1] or None,
                second.get("field_role"),
                json.dumps(sorted(second["limit"]))
                if isinstance(second.get("limit"), frozenset)
                else (None if second.get("limit") is None else str(second["limit"])),
                second.get("unit"),
                int(ok),
                ",".join(differs) or None,
                model,
                SECOND_VERSION,
                _now(),
            ),
        )
        conn.commit()
        tally["agreed" if ok else "differs"] += 1
        for d in differs:
            tally["reasons"][d] = tally["reasons"].get(d, 0) + 1
        return True

    apply.tally = tally
    return apply


def advanced(conn) -> int:
    """Rules that passed everything so far: checked in step 2, agreed in step 3."""
    return conn.execute(
        f"SELECT COUNT(*) FROM {CHECKS} c JOIN {SECOND} s ON s.rule_id = c.rule_id"
        f" WHERE c.status = '{CHECKED}' AND s.agree = 1"
    ).fetchone()[0]


def check_model() -> str:
    return settings.claude_reasoning_model


def second_model() -> str:
    """A model other than the reasoning one: the field-naming tier (`settings.rule_field_naming_model`), else the
    labelling model; the first that differs."""
    for name in (settings.rule_field_naming_model, settings.claude_labelling_model):
        if name and name != settings.claude_reasoning_model:
            return name
    raise ValueError("no configured model differs from the reasoning model")
