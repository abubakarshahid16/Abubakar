"""#805 FIELD-FIRST linking: for each field of an equipment type's form, find the rules that name that field's quantity.

The rule-first pipeline asked "which field does this rule limit?" and most rules limit nothing a datasheet states. This asks
the other way round, one field per prompt, starting from the approved #746 checklist field list
(`rule_field_naming.fixed_fields`, `reference/datasheet_checks.json`):

  * CANDIDATES by CODE (keyword, no model): rules of ANY document kind (a datasheet is checked against specification and
    standard rules too), labelled box a or c, of the type or `general`, whose own words contain ALL the words of the
    field's label (`subject_pairing.quantity_words`, the pairing rule used for submittals). At most `CANDIDATES` per field,
    datasheet / any kinds first, then rules that carry a figure.
  * CLAUDE picks the governing ones (at most `MAX_PICKS`) and writes the typed check for each, with its scope words.
  * CODE VERIFIES exactly as the rule-first path does (`rule_box_check.verify_check`: quote, limit, unit, comparator,
    subject against the field label, scope words in the rule, both test cases run). A pick that fails is `failed check`.

ON A COPY. Standards text only. Counts only in a report. Off unless run as `rule_boxes.py fieldfirst`.
"""

from __future__ import annotations

from app import subject_pairing
from rule_box_tools import rule_box_check, rule_box_labels, rule_box_run, rule_box_scope

CANDIDATES = 10
MAX_PICKS = 3
FIELD_TOKENS = 1800
KIND_ORDER = {"datasheet": 0, "any": 1, "standard": 2, "specification": 3}


def candidates(conn, equipment_type: str, role: str) -> list:
    """The rules, of any kind, that name this field's quantity, best first. Code only."""
    want = subject_pairing.quantity_words(rule_box_scope.label_of(role), equipment_type)
    if not want:
        return []
    types = {equipment_type, rule_box_labels.GENERAL}
    marks = ",".join("?" for _ in types)
    rows = conn.execute(
        "SELECT r.id, r.standard_document_id, r.clause, r.field, r.comparator, r.limit_value, r.unit, r.condition_text,"
        " r.exception_text, r.applies_to, r.quote, l.document_kind, l.equipment_type, l.box"
        f" FROM compiled_rules r JOIN {rule_box_labels.TABLE} l ON l.rule_id = r.id"
        f" WHERE l.box IN ('a','c') AND l.equipment_type IN ({marks}) ORDER BY r.id",
        tuple(sorted(types)),
    ).fetchall()
    hits = [
        r
        for r in rows
        if want <= subject_pairing.quantity_words(r["quote"], equipment_type)
    ]
    hits.sort(
        key=lambda r: (
            KIND_ORDER.get(r["document_kind"], 9),
            0
            if rule_box_check.has_figure(r) or rule_box_check.is_list_rule(r["quote"])
            else 1,
            len(r["quote"]),
            r["id"],
        )
    )
    return hits[:CANDIDATES]


def prompt_for(
    equipment_type: str, role: str, kind: str, rows: list, labels: dict[str, str]
) -> str:
    lines = []
    for n, r in enumerate(rows, 1):
        scope = "".join(
            f"\n   {name}: {rule_box_check._clean(r[col], 300)}"
            for name, col in (
                ("APPLIES TO", "applies_to"),
                ("CONDITION", "condition_text"),
                ("EXCEPTION", "exception_text"),
            )
            if rule_box_check._has(r, col)
        )
        figures = "; ".join(f"{v} {u}" for v, u in rule_box_check.figures_of(r)[:6])
        lines.append(
            f"{n}. [{labels.get(r['standard_document_id'], '')}, clause {r['clause']}, a {r['document_kind']} rule]"
            f" {rule_box_check._clean(r['quote'], 700)}{scope}"
            + (f"\n   FIGURES CODE FOUND: {figures}" if figures else "")
        )
    return (
        f"You build the check for ONE datasheet field of a {equipment_type}: {role.replace('_', ' ')} (kind {kind}).\n"
        "Below are requirements of engineering standards that name this quantity. Pick at most "
        f"{MAX_PICKS} that GOVERN this field, meaning the requirement limits exactly this quantity of this equipment (not a"
        " different quantity, not a sub-part, not a procedure). For each pick write a typed check. Pick none if none governs"
        " it. Copy every figure and word exactly from the requirement; carry its scope words.\n\n"
        "CANDIDATES:\n" + ("\n".join(lines) or "(none)") + "\n\n"
        'Answer ONLY one JSON object: {"picks": [{"candidate": <number>, "kind": "number" | "list", "op": for a number one'
        ' of "<=", ">=", "<", ">", "="; for a list one of "is_not", "is_one_of", "at_least_class", "limit": <figure as'
        ' printed or null>, "unit": <unit as printed or null>, "values": [<list words copied exactly>], "condition":'
        ' <words saying when it applies or null>, "scope": <words of APPLIES TO / CONDITION / EXCEPTION that narrow it or'
        ' null>, "subject": <words naming the quantity, copied exactly>, "quote": <shortest exact words stating the limit>,'
        ' "pass_case": {"value": ..., "unit": ...}, "fail_case": {"value": ..., "unit": ...}}]}.'
    )


def dry_plan(conn, types: list[str]) -> list[dict]:
    plan = []
    for t in types:
        fields = rule_box_check.fields_for(t, conn) or {}
        for role, kind in fields.items():
            rows = candidates(conn, t, role)
            plan.append({"type": t, "role": role, "kind": kind, "rows": rows})
    return plan


def jobs(conn, plan: list[dict], gate) -> tuple[list[rule_box_run.Job], dict]:
    labels = rule_box_labels.standard_labels(conn)
    out, members = [], {}
    for item in plan:
        rows = [
            r
            for r in item["rows"]
            if gate(
                r["standard_document_id"], labels.get(r["standard_document_id"], "")
            )
            is None
        ]
        if not rows:
            continue
        key = f"ff:{item['type']}:{item['role']}"
        out.append(
            rule_box_run.Job(
                key,
                prompt_for(item["type"], item["role"], item["kind"], rows, labels),
                frozenset(r["standard_document_id"] for r in rows),
                FIELD_TOKENS,
            )
        )
        members[key] = (
            item["type"],
            item["role"],
            rows,
            rule_box_check.fields_for(item["type"], conn),
        )
    return out, members


def storer(conn, members: dict, model: str):
    tally = {
        "fields_asked": 0,
        "picks": 0,
        "checked": 0,
        "failed_check": 0,
        "reasons": {},
    }

    def apply(job, text: str) -> bool:
        _type, role, rows, fields = members[job.key]
        data = rule_box_check._parse_object(text) or {}
        tally["fields_asked"] += 1
        for pick in (data.get("picks") or [])[:MAX_PICKS]:
            n = pick.get("candidate") if isinstance(pick, dict) else None
            if not isinstance(n, int) or not 1 <= n <= len(rows):
                continue
            row = rows[n - 1]
            answer = {**pick, "field_role": role, "reason": None}
            check, reason, status = rule_box_check.verify_check(row, answer, fields)
            tally["picks"] += 1
            rule_box_check._record(conn, row["id"], status, reason, row, model, check)
            if check:
                conn.execute(
                    f"UPDATE {rule_box_check.CHECKS} SET subject = ?, scope_text = ?, scope_required = ?, scope_question = ?"
                    " WHERE rule_id = ?",
                    (
                        check["subject"],
                        check["scope"],
                        int(bool(check["scope"])),
                        f"Does this scope apply to this equipment: {check['scope']}?"
                        if check["scope"]
                        else None,
                        row["id"],
                    ),
                )
            tally[
                "checked" if status == rule_box_check.CHECKED else "failed_check"
            ] += 1
            if reason:
                tally["reasons"][reason] = tally["reasons"].get(reason, 0) + 1
        conn.commit()
        return True

    apply.tally = tally
    return apply
