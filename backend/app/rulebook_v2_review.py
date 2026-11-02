"""#805 plan change 6: a review reads approved version 2 rules beside version 1. RULEBOOK_V2_REVIEW_ENABLED, default off.

THE PATH. The document's equipment type (an unsure type gets no rules and says so), the rules a person approved for that
type, a snapshot of the book that the run records, then one row per rule. Code decides: the pairing goes through the
role table and the field names the project already has, the number through `comparison.compare`. No second parser and
no second comparator. Rule 13: nothing here knows a layout or a label's spelling.

WHEN UNSURE, A QUERY. Only a rule with one figure, its quote hash intact, owner approved, its conditions shown to hold
and its exceptions shown not to, on one trusted value, gets a verdict. Every other row is NEEDS_ENGINEER_REVIEW and
leads with one of `REASONS`. "Not mentioned" is never compliant. A version 1 row or checklist item on the same field
that says otherwise makes both rows a Query that says so.

APART. Rows carry `ORIGIN`, on neither lane of `coverage_pair`, which states them separately with their denominator.

`pair_rule_to_document` is the pairing alone, read only, for a checklist before any approval exists: no verdict.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field

from . import (
    checklist_scope,
    conditions,
    datasheet_checks,
    datasheet_roles,
    deferred_value,
    degraded_read,
    field_links,
    kind_rules,
    match_rules,
    material_reference,
    requirements_3b,
    rule_trust,
    rule_typed_check,
    rulebook_v2,
    subject_scope,
)
from .config import settings
from .rule_field_naming import VERIFIED as ROLE_VERIFIED
from .rulebook_v2_check import NO_UNIT

ORIGIN = "rulebook_v2"
LABEL = "Rulebook v2"
COMPLIANT, NON_COMPLIANT = "COMPLIANT", "NON_COMPLIANT"
QUERY = "NEEDS_ENGINEER_REVIEW"
DECIDED = (COMPLIANT, NON_COMPLIANT)

# Why a rule could not be paired with a value.
NO_SUCH_FIELD = (
    "no_such_field"  # the rule's field is no known role and no field read has that name
)
NOT_MENTIONED = "not_mentioned"  # a known field, and nothing read answers it
LEFT_BLANK = "left_blank"  # the field is there and states no value
ONLY_UNDER_QUALIFIER = (
    "only_under_a_qualifier"  # the field stated with a qualifier: code does not choose
)
SEVERAL_VALUES = "several_values"
PAIR_REFUSED = "pair_refused"  # `match_rules` refuses or doubts the pair
NOT_ON_DATASHEET = "not_on_datasheet"  # the field-naming step: no field of the type's list answers this rule
ROLE_NOT_VERIFIED = (
    "role_not_verified"  # the field-naming step proposed a role code could not verify
)
PAIR_REASONS = (
    NOT_ON_DATASHEET,
    ROLE_NOT_VERIFIED,
    NO_SUCH_FIELD,
    NOT_MENTIONED,
    LEFT_BLANK,
    ONLY_UNDER_QUALIFIER,
    SEVERAL_VALUES,
    PAIR_REFUSED,
)
# Why a rule does not decide.
QUOTE_HASH_MISMATCH = "quote_hash_mismatch"
NOT_IN_SNAPSHOT = "not_in_snapshot"
SNAPSHOT_NOT_RECORDED = "snapshot_not_recorded"
NO_FIGURE = "no_figure"
NOT_OWNER_APPROVED = "not_owner_approved"
SCOPE_OUTSIDE_SENTENCE = "scope_outside_sentence"
NOT_BINDING = "not_binding"
APPLIES_TO_NOT_VERIFIED = "applies_to_not_verified"
CONDITION_NOT_VERIFIED = "condition_not_verified"
EXCEPTION_NOT_RULED_OUT = "exception_not_ruled_out"
OTHER_DOCUMENT = "other_document"
VALUE_NOT_TRUSTED = "value_not_trusted"
VALUE_UNCLEAR = "value_unclear"
STATED_VALUE_NOT_A_LIMIT = "stated_value_not_a_limit"
READING_INCOMPLETE = "reading_incomplete"
V1_DISAGREES = "v1_disagrees"
REASONS = (
    *PAIR_REASONS,
    QUOTE_HASH_MISMATCH,
    NOT_IN_SNAPSHOT,
    SNAPSHOT_NOT_RECORDED,
    NO_FIGURE,
    NOT_OWNER_APPROVED,
    SCOPE_OUTSIDE_SENTENCE,
    NOT_BINDING,
    APPLIES_TO_NOT_VERIFIED,
    CONDITION_NOT_VERIFIED,
    EXCEPTION_NOT_RULED_OUT,
    OTHER_DOCUMENT,
    VALUE_NOT_TRUSTED,
    VALUE_UNCLEAR,
    STATED_VALUE_NOT_A_LIMIT,
    READING_INCOMPLETE,
    V1_DISAGREES,
)
# Why a run read no rule at all: stated on the run, no rows.
TYPE_UNSURE = "equipment_type_unsure"
NOT_A_DATASHEET = "not_a_datasheet"
BOOK_NOT_READY = "rulebook_not_ready"
USED = "used"
_LIMIT_OPERATORS = (">=", ">", "<=", "<", "=")
_BINDING = "shall"


@dataclass
class Pair:
    fact: dict | None
    reason: str | None
    role: str | None
    #: every fact read for this field: a version 1 row on any of them covers the same field
    fact_ids: set = field(default_factory=set)


def as_requirement(rule: dict) -> dict:
    """The one place a rule's contract names become the names the comparison and `rule_trust` read. `approval` rides
    along for `rule_trust`; `confirmed_by` is never set: that path means an engineer's own approval."""
    unit = rule.get("unit")
    if rule.get("value") is None and rule.get("limit_value") is not None:
        rule = {**rule, "value": rule["limit_value"]}
    has_figure = rule.get("value") is not None and rule.get("comparator") is not None
    quote = rule.get("quote") or ""
    return {
        "requirement_type": (
            conditions.GATED_TYPE if has_figure else requirements_3b.STATEMENT
        ),
        "field": rule.get("field"),
        "operator": rule.get("comparator"),
        "raw_value": _plain(rule["value"]) if has_figure else None,
        "raw_unit": "" if unit in (None, NO_UNIT) else unit,
        "requirement_text": quote,
        "source_text": quote,
        "quote": quote,
        "clause": rule.get("clause"),
        "page": rule.get("page"),
        "condition": None,
        "required_evidence_type": requirements_3b.required_evidence_type(quote),
        "approval": rule.get("approval"),
    }


def _plain(number) -> str:
    from .comparison import _plain as plain

    return plain(float(number))


# ------------------------------------------------------------------------------------------------- the pairing


def pair(rule: dict, facts: list[dict], equipment_type: str | None) -> Pair:
    """The one read value this rule's field names, or the named reason there is none. The only pairing code."""
    rules = datasheet_checks.load_rules()
    wanted = datasheet_roles.wanted_roles(equipment_type, rules)
    name = rule.get("field") or ""
    named = rule.get("field_role_state")
    if named == NOT_ON_DATASHEET:
        return Pair(None, NOT_ON_DATASHEET, None)
    if named and named != ROLE_VERIFIED:
        return Pair(None, ROLE_NOT_VERIFIED, None)
    role = rule.get("field_role") if named else None
    role = role or datasheet_checks.role_of(name, rules, wanted)

    def role_of_fact(fact: dict) -> str | None:
        return datasheet_checks.role_of(fact.get("field_name") or "", rules, wanted)

    if role is not None:
        found = [f for f in facts if role_of_fact(f) == role]
    else:
        found = [f for f in facts if rule_trust.same_field(f.get("field_name"), name)]
    if not found:
        if role is None:
            return Pair(None, NO_SUCH_FIELD, None)
        under = any(
            datasheet_checks.qualified_role_of(f.get("field_name") or "", rules) == role
            for f in facts
        )
        return Pair(None, ONLY_UNDER_QUALIFIER if under else NOT_MENTIONED, role)
    ids = {f.get("id") for f in found}
    filled = [f for f in found if not f.get("is_blank")]
    if not filled:
        return Pair(None, LEFT_BLANK, role, ids)
    fact, _why = datasheet_checks._one(filled)
    if fact is None:
        return Pair(None, SEVERAL_VALUES, role, ids)
    requirement = as_requirement(rule)
    sheet = match_rules.sheet_kind(facts, equipment_type)
    if match_rules.refusal(
        requirement, fact, sheet=sheet
    ) or match_rules.quantity_kind_doubt(requirement, fact):
        return Pair(None, PAIR_REFUSED, role, ids)
    return Pair(fact, None, role, ids)


def pairs(rule: dict, facts: list[dict], equipment_type: str | None) -> list[Pair]:
    """One `Pair` per equipment tag: a sheet of four valves states four set pressures, not one in doubt. An untagged
    value counts for every tag, and a tag's own value is never lent to another, as the checklist reads a sheet."""
    tags = sorted({f["equipment_tag"] for f in facts if f.get("equipment_tag")})
    if len(tags) < 2:
        return [pair(rule, facts, equipment_type)]
    found = [
        pair(
            rule,
            [f for f in facts if f.get("equipment_tag") in (tag, None)],
            equipment_type,
        )
        for tag in tags
    ]
    return found if any(f.fact is not None for f in found) else found[:1]


def _rows(conn: sqlite3.Connection, sql: str, params: tuple) -> list[dict]:
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    return [dict(r) for r in cursor.execute(sql, params)]


def pair_rule_to_document(
    conn: sqlite3.Connection, document_id: str, rule: dict
) -> dict:
    """Does this document state a value for this rule's field? The review's own pairing, on `conn`, read only, before
    any approval exists. No verdict, whatever the rule asks. The caller has already scoped `document_id`."""
    facts = _rows(
        conn,
        "SELECT * FROM submittal_facts WHERE submittal_document_id = ? AND superseded_at IS NULL"
        " ORDER BY page, field_name",
        (document_id,),
    )
    kinds = _rows(
        conn,
        "SELECT equipment_type FROM document_classification WHERE document_id = ?",
        (document_id,),
    )
    found = pairs(rule, facts, (kinds[0]["equipment_type"] or None) if kinds else None)
    read = [f.fact for f in found if f.fact is not None]
    said = sorted({_value_read(fact) for fact in read})
    stopped = next((f.reason for f in found if f.reason), None)
    return {
        "paired": bool(read),
        "reason": None if read else stopped,
        "value_read": said[0] if len(said) == 1 else None,
        "values_read": said,
        "tags_paired": len(read),
        "tags": len(found),
        "page": read[0].get("page") if read else None,
        "role": found[0].role,
        "not_on_datasheet_reason": rule.get("field_role_reason")
        if stopped == NOT_ON_DATASHEET
        else None,
        "check_in_plain_words": _check_words(rule),
    }


def _check_words(rule: dict) -> str:
    op, values = _check_of(rule)
    return rule_typed_check.plain_words(op, values) if op else ""


def _check_of(rule: dict) -> tuple[str | None, list[str]]:
    """The verified typed check on a rule: (op, values), or (None, []). The values are stored as JSON."""
    if rule.get("check_state") != rule_typed_check.VERIFIED:
        return None, []
    return rule.get("check_op"), json.loads(rule.get("check_values") or "[]")


def _value_read(fact: dict) -> str:
    said = f"{fact.get('raw_value') or ''} {fact.get('raw_unit') or ''}".strip()
    return said or str(fact.get("field_value") or "")


# ------------------------------------------------------------------------------------------- the equipment type


def equipment_type_of(
    document_id: str, record: dict, facts: list[dict]
) -> tuple[str | None, str | None]:
    """(type, None), or (None, why no rule is read). The review's one reader of what a submittal is; unsure is empty."""
    if kind_rules.blocked(document_id):
        return None, NOT_A_DATASHEET
    equipment, _source, doubt, *_rest = subject_scope.read_equipment(
        record, facts, subject_scope.vocabulary()
    )
    if doubt or len(equipment) != 1:
        return None, TYPE_UNSURE
    evidence = record.get("equipment_type_evidence") or {}
    if evidence.get("method") == "body_phrase_match" and not record.get("confirmed"):
        return None, TYPE_UNSURE
    return (checklist_scope.review_type(record) or next(iter(equipment))), None


# --------------------------------------------------------------------------------------------- the rule's scope


def _texts(values) -> list[str]:
    """A list of words or of rows with the words in them, as the rulebook's tables hold them."""
    listed = values if isinstance(values, list | tuple) else [values] if values else []
    said = [
        (v.get("condition_text") or v.get("value")) if isinstance(v, dict) else v
        for v in listed
    ]
    return [str(s) for s in said if str(s or "").strip()]


def _stems(text: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z0-9]+", text.lower())}


def _applies_to_this_type(rule: dict, equipment_type: str) -> bool:
    """Every word of who the rule is for is a word of the type, or of a class it belongs to. A narrower scope (a
    service, a size) is not shown by the type, so it is not shown at all."""
    from .comparison import subject_spellings

    named = rule.get("applies_to")
    rows = named if isinstance(named, list) else []
    if any(
        isinstance(v, dict)
        and v.get("key_type") not in (None, "subject", "equipment_type")
        for v in rows
    ):
        return False
    spellings = [_stems(s) for s in subject_spellings(equipment_type)]
    return all(
        any(_stems(text) <= spelled for spelled in spellings) for text in _texts(named)
    )


def _state_of(text: str, facts: list[dict], fact: dict) -> str | None:
    judged = conditions.evaluate(
        {"requirement_type": conditions.GATED_TYPE, "condition": text},
        facts,
        about=fact,
    )
    return None if judged is None else judged["state"]


def _context_dependent(rule: dict) -> bool:
    return bool(
        rule.get("context_flag")
        or rule.get("strength") == rulebook_v2.CONTEXT_DEPENDENT
    )


def _note_lifts_the_flag(rule: dict) -> bool:
    """The owner's written note, with the switch on, stands in for a scope outside the sentence. Only for that: a low
    reading confidence is not a matter of scope, and conditions are still verified after this."""
    note = str((rule.get("approval") or {}).get("note") or "").strip()
    return bool(
        settings.owner_note_lifts_context_flag_enabled
        and note
        and "low_ocr_confidence" not in str(rule.get("context_flag") or "")
    )


def _scope_reason(
    rule: dict, facts: list[dict], fact: dict, equipment_type: str
) -> str | None:
    flagged = _context_dependent(rule)
    if flagged and not _note_lifts_the_flag(rule):
        return SCOPE_OUTSIDE_SENTENCE
    strength = rule.get("sentence_strength") if flagged else rule.get("strength")
    if strength != _BINDING:
        return NOT_BINDING
    # who the rule is for is the context the note confirms; its conditions and exceptions are still verified below
    if not flagged and not _applies_to_this_type(rule, equipment_type):
        return APPLIES_TO_NOT_VERIFIED
    if any(
        _state_of(text, facts, fact) != conditions.SATISFIED
        for text in _texts(rule.get("conditions"))
    ):
        return CONDITION_NOT_VERIFIED
    # an exception lets a rule bind only by being shown NOT to hold: unknown is not "does not hold"
    if any(
        _state_of(text, facts, fact) != conditions.NOT_SATISFIED
        for text in _texts(rule.get("exceptions"))
    ):
        return EXCEPTION_NOT_RULED_OUT
    return None


def _owner_approved(requirement: dict) -> bool:
    return (
        rule_trust.tier_for_approved(requirement.get("approval"), requirement)
        == rule_trust.OWNER_APPROVED
    )


# ------------------------------------------------------------------------------------------------- the decision


@dataclass
class Row:
    rule: dict
    status: str
    reason: str | None
    words: str
    fact: dict | None = None
    role: str | None = None
    fact_ids: set = field(default_factory=set)
    rule_said: str | None = None
    trust_label: str = rule_trust.OWNER_APPROVED


def _query(rule: dict, reason: str, found: Pair | None = None, words: str = "") -> Row:
    if found is None:
        return Row(rule, QUERY, reason, words)
    return Row(rule, QUERY, reason, words, found.fact, found.role, found.fact_ids)


def _compared(rule: dict, requirement: dict, found: Pair, facts: list[dict]) -> Row:
    from . import comparison

    fact = found.fact
    verdict = comparison.compare(
        {**requirement, "condition": (_texts(rule.get("conditions")) or [None])[0]},
        fact,
        submittal_facts=facts,
    )
    status, words = verdict.get("status"), verdict.get("rationale") or ""
    if status in DECIDED:
        if requirement["operator"] == "=" and status == NON_COMPLIANT:
            return _query(rule, STATED_VALUE_NOT_A_LIMIT, found, words)
        return Row(rule, status, None, words, fact, found.role, found.fact_ids)
    judged = (verdict.get("condition") or {}).get("state")
    if judged is not None and judged != conditions.SATISFIED:
        reason = CONDITION_NOT_VERIFIED
    elif comparison.low_trust_reason(fact) or comparison._deferred_reason(fact):
        reason = VALUE_NOT_TRUSTED
    elif status == comparison.NOT_IN_DOCUMENT_SCOPE:
        reason = OTHER_DOCUMENT
    else:
        reason = VALUE_UNCLEAR
    return _query(rule, reason, found, words)


def _typed(rule: dict, found: Pair, op: str, values: list[str]) -> Row:
    """Code decides a rule checked by words, on the one trusted value of this tag."""
    from . import comparison

    fact = found.fact
    stated = " ".join(
        str(fact.get("field_value") or fact.get("raw_value") or "").split()
    )
    if not field_links.states_a_value(stated):
        return _query(rule, VALUE_UNCLEAR, found)
    status, words = rule_typed_check.decide(op, values, stated, rule.get("_reference"))
    if status is None:
        return _query(rule, VALUE_UNCLEAR, found, words)
    verdict = comparison._hold_low_trust_breach(
        {"status": status, "rationale": words}, fact
    )
    if verdict["status"] not in DECIDED:
        return _query(rule, VALUE_NOT_TRUSTED, found, verdict["rationale"])
    return Row(rule, status, None, words, fact, found.role, found.fact_ids)


def _judge(
    rule: dict, found: Pair, facts: list[dict], equipment_type: str, *, approved=None
) -> Row:
    """One rule on one tag's value, every step only able to hold it back. `approved` None: as if a person had."""
    requirement = as_requirement(rule)
    op, values = _check_of(rule)
    numeric = (
        requirement["raw_value"] is not None
        and requirement["operator"] in _LIMIT_OPERATORS
    )
    if not numeric and not (op and requirement["raw_value"] is None):
        return _query(rule, NO_FIGURE, found)
    if found.fact is None:
        return _query(rule, found.reason, found)
    if approved is not None and not approved(requirement, numeric):
        return _query(rule, NOT_OWNER_APPROVED, found)
    scope = _scope_reason(rule, facts, found.fact, equipment_type)
    if scope:
        return _query(rule, scope, found)
    row = (
        _compared(rule, requirement, found, facts)
        if numeric
        else _typed(rule, found, op, values)
    )
    # an owner-approved rule's verdict on a deferred value is a query, whatever D2's own switch says
    held = deferred_value.hold_owner_rule(
        {"status": row.status, "rationale": row.words}, found.fact
    )
    if held["status"] != row.status:
        return _query(rule, VALUE_NOT_TRUSTED, found, held["rationale"])
    if row.status in DECIDED and _context_dependent(rule):
        row.trust_label = rule_trust.OWNER_NOTE_CONTEXT
        note = rule["approval"]["note"]
        row.words = f"{row.words}. {rule_trust.OWNER_NOTE_CONTEXT_WORDS}: {note}"
    return row


def _approved(requirement: dict, numeric: bool) -> bool:
    if numeric:
        return _owner_approved(requirement)
    return rule_trust.owner_signed(requirement.get("approval"))


def decide_rule(
    rule: dict, facts: list[dict], equipment_type: str, in_force: frozenset
) -> list[Row]:
    """One approved rule against the sheet's values: a row per tag, or one row when no tag has a value."""
    quote = rule.get("quote") or ""
    if hashlib.sha256(quote.encode("utf-8")).hexdigest() != rule.get("quote_sha256"):
        return [_query(rule, QUOTE_HASH_MISMATCH)]
    if (rule.get("rule_id"), rule.get("version")) not in in_force:
        return [_query(rule, NOT_IN_SNAPSHOT)]
    return [
        _judge(rule, found, facts, equipment_type, approved=_approved)
        for found in pairs(rule, facts, equipment_type)
    ]


def _hold_on_incomplete_reading(rows: list[Row], document_id: str) -> None:
    """The same hold a checklist Pass gets when the AI reading did not all come back. A failure keeps its status."""
    for row in rows:
        if row.status != COMPLIANT:
            continue
        held = degraded_read.hold(
            [
                {
                    "status": COMPLIANT,
                    "checklist": True,
                    "role": row.role,
                    "rule_id": None,
                    "detail": "",
                }
            ],
            document_id,
        )
        if held[0]["status"] != COMPLIANT:
            row.rule_said, row.status = row.status, QUERY
            row.reason = READING_INCOMPLETE


@dataclass
class Review:
    review_run_id: str
    document_id: str
    state: str
    equipment_type: str | None = None
    snapshot_id: str | None = None
    rows: list[Row] = field(default_factory=list)
    rules: int = 0
    reference_version: str | None = None

    def settle_with_findings(self, prepared: list[dict], findings: list[dict]) -> None:
        settle_with_findings(self, prepared, findings)

    def settle_with_checks(self, results: list[dict]) -> list[dict]:
        return settle_with_checks(self, results)

    def store(self, conn) -> list[dict]:
        return store(conn, self)

    def summary(self) -> dict:
        return summary(self)


def begin(
    conn, review_run_id: str, document_id: str, record: dict, facts: list[dict]
) -> Review:
    """Decide every approved rule for this document and record the book the run used. No finding is written here, so a
    disagreement with version 1 can still change both sides."""
    if not settings.rulebook_v2_enabled or not rulebook_v2.has_schema(conn):
        return Review(review_run_id, document_id, BOOK_NOT_READY)
    equipment_type, unsure = equipment_type_of(document_id, record, facts)
    if unsure:
        rulebook_v2.record_run(conn, review_run_id)
        return Review(review_run_id, document_id, unsure)
    approved = getattr(rulebook_v2, "approved_rules", None)
    if approved is None:
        rulebook_v2.record_run(conn, review_run_id)
        return Review(review_run_id, document_id, BOOK_NOT_READY, equipment_type)
    rules = approved(conn, equipment_type)
    reference = (
        material_reference.signed(conn) if settings.material_reference_enabled else None
    )
    rules = [{**rule, "_reference": reference} for rule in rules]
    # An approval comes after the compile's snapshot, so the run freezes the book as it uses it; a re-run of this run
    # finds the same snapshot and reads the same rules.
    actor = f"review:{review_run_id}"
    with conn:
        snapshot_id = rulebook_v2.take_snapshot(
            conn, actor, "review_run", {"review_run": 1}, actor
        )
    recorded = rulebook_v2.record_run(conn, review_run_id, snapshot_id)
    held = frozenset(rulebook_v2.in_force_versions(conn, snapshot_id))
    if recorded is None or recorded["snapshot_id"] != snapshot_id:
        rows = [_query(rule, SNAPSHOT_NOT_RECORDED) for rule in rules]
    else:
        rows = [
            row
            for rule in rules
            for row in decide_rule(rule, facts, equipment_type, held)
        ]
    _hold_on_incomplete_reading(rows, document_id)
    return Review(
        review_run_id,
        document_id,
        USED,
        equipment_type,
        snapshot_id,
        rows,
        len(rules),
        reference.version if reference else None,
    )


# ------------------------------------------------------------------------------- version 1 beside version 2


def _said(row: Row) -> str | None:
    """What the rule itself said; only a row with a verdict, or one a disagreement already held, said anything."""
    if row.status in DECIDED:
        return row.status
    return row.rule_said if row.reason == V1_DISAGREES else None


def _disagree(row: Row, status: str) -> None:
    if row.status in DECIDED:
        row.rule_said, row.status, row.reason = row.status, QUERY, V1_DISAGREES
        row.words = (
            f"version 1 says {status} on this field and this rule said {row.rule_said}: "
            f"the two disagree, so neither is a verdict. {row.words}"
        )


def settle_with_findings(
    review: Review, prepared: list[dict], findings: list[dict]
) -> None:
    """A version 1 row and a version 2 rule on one field that disagree: both rows become a Query, before either is
    written. `prepared` and `findings` hold one row each, by id."""
    from . import comparison

    for row in review.rows:
        said = _said(row)
        for finding in prepared:
            status = finding.get("compliance_status")
            if (
                said is None
                or status not in DECIDED
                or status == said
                or finding.get("fact_id") not in row.fact_ids
            ):
                continue
            _disagree(row, status)
            held = {
                "compliance_status": QUERY,
                "severity": comparison._default_severity(QUERY),
                "required_action": comparison._required_action(QUERY),
                "ai_rationale": (
                    f"{V1_DISAGREES}: rule {row.rule.get('rule_id')} version {row.rule.get('version')} of the "
                    f"rulebook said {said} on this field: {finding.get('ai_rationale') or ''}"
                ),
                "rule_said": status,
            }
            finding.update(held)
            for shown in findings:
                if shown.get("id") == finding.get("id"):
                    shown.update(held)


def settle_with_checks(review: Review, results: list[dict]) -> list[dict]:
    """The same for a checklist item on the field. Any other check is the sheet against itself: not this question."""
    out = []
    for result in results:
        for row in review.rows:
            said, status = _said(row), result.get("status")
            if (
                said is not None
                and result.get("checklist")
                and status in DECIDED
                and status != said
                and result.get("fact_id") in row.fact_ids
            ):
                _disagree(row, status)
                result = {
                    **result,
                    "status": QUERY,
                    "rule_said": status,
                    "detail": f"{V1_DISAGREES}: the rulebook said {said} on this field. {result.get('detail') or ''}",
                }
        out.append(result)
    return out


# ------------------------------------------------------------------------------------------- the run's findings


def citation(rule: dict) -> str:
    edition = f" {rule['edition']}" if rule.get("edition") else ""
    return (
        f"{LABEL} rule {rule.get('rule_id')} version {rule.get('version')}: {rule.get('standard') or ''}{edition}"
        f" clause {rule.get('clause')} page {rule.get('page')}: {rule.get('quote') or ''}"
    )


def store(conn, review: Review) -> list[dict]:
    """The rows, as findings of the run, in one transaction, each citing its rule. A row an engineer rejected in this
    run is kept by the re-run's delete and not written again beside it."""
    if not review.rows:
        return []
    from . import comparison
    from . import review as review_mod

    rejected = {
        (f.get("requirement_source_text"), f.get("fact_id"))
        for f in review_mod.rejected_in_run(review.review_run_id, ORIGIN)
    }
    written = []
    with conn:
        for row in review.rows:
            rule, fact = row.rule, row.fact or {}
            cited = citation(rule)
            if (cited, fact.get("id")) in rejected:
                continue
            why = f"{row.reason}: " if row.reason else ""
            words = f"{why}{row.words}".strip().rstrip(":")
            written.append(
                review_mod.create(
                    {
                        "document_id": review.document_id,
                        "category": "requirement_deviation",
                        "severity": comparison._default_severity(row.status),
                        "requirement": (rule.get("quote") or "")[:4000],
                        "finding": f"{LABEL}: {words}"[:4000],
                        "required_action": comparison._required_action(row.status),
                        "status": "open",
                        "approval_status": "pending",
                        "review_run_id": review.review_run_id,
                        "origin": ORIGIN,
                        "compliance_status": row.status,
                        "contractor_page": fact.get("page"),
                        "contractor_section": rule.get("field"),
                        "contractor_evidence_text": fact.get("field_value")
                        or fact.get("raw_value"),
                        "requirement_source_text": cited,
                        "ai_rationale": f"{words} [{cited}]",
                        "fact_id": fact.get("id"),
                        "equipment_tag": fact.get("equipment_tag"),
                        "standard_clause": f"{rule.get('standard') or ''} {rule.get('clause') or ''}".strip(),
                        "rule_said": row.rule_said,
                        "trust_label": (
                            row.trust_label if row.status in DECIDED else None
                        ),
                    },
                    created_by=None,
                    conn=conn,
                )
            )
    return written


def summary(review: Review) -> dict:
    """Counts and fixed reason names: what the run stores and `coverage_pair` states. No document text."""
    reasons: dict[str, int] = {}
    for row in review.rows:
        if row.reason:
            reasons[row.reason] = reasons.get(row.reason, 0) + 1
    return {
        "state": review.state,
        "equipment_type": review.equipment_type,
        "snapshot_id": review.snapshot_id,
        "rules": review.rules,
        "reasons": dict(sorted(reasons.items())),
        **(
            {"material_reference": review.reference_version}
            if review.reference_version
            else {}
        ),
    }
