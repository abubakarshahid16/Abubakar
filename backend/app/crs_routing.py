"""CRS ROUTING BY HOLD REASON (Part of #805, Cycle 2; owner order 10 Nov 2026, step 4),
behind CRS_ROUTING_BY_HOLD_REASON_ENABLED (off).

WHICH SHEET SHOWS A ROW, NEVER A VERDICT. No finding's status, rule result or decided count
changes here and nothing is deleted: a row either stays on the CRS or is shown, with its
reason, on a sheet the engineer reads (the internal "Compliance list", or the Review notes
where a standard not held is named). Four general rules, each read from stored fields and
the standards check, never from a comment's words, a layout or a standard's name (rule 13):

R1  A "did not reference standard X" row (`applicability.standards_check`'s
    `required_not_cited`) stays a CRS row only when the project specification held for the
    review (`project_specification.used`) has a requirement naming X whose quote is
    verified on its own stored passage (`compiled_rule_proof.quote_verified`). Otherwise it
    is a Review note with that reason. A clarification row ("confirm whether X applies",
    the equipment type unsure) is not a generic "did not reference" row; it stays.
R2  A held datasheet check whose stored hold reason (`hold_reason`) is
    `applicability_not_stated` or `applicability_not_stated_absent` goes to the internal
    list with its reason (owner, 10 Nov: YES). `applicability_several_values` stays.
R3  A held datasheet check whose hold reason is `field_several_values`, checked only by a
    draft rule, goes to the internal list with its reason only when EVERY value the sheet
    states for that field (`_field_values`: every fact of the sheet that may be the field,
    not only the one the finding stores) is present and unmarked: no placeholder
    (`blank_markers.fact_is_placeholder`) and no deferral phrase ("By Contractor", "TBA";
    `blank_markers.names_a_marker`). One marked, blank or dash value keeps the row. A row
    held because the field it is checked AGAINST has two values (its own field states one)
    stays.
R4  A cited standard the scope check says does not appear to apply (`cited_not_applicable`)
    is not a CRS comment: it is a Review note naming the standard and the check's reason.

ALWAYS KEPT: a finding an engineer decided (confirmed or accepted, `crs_decider.decider`), a row with an issued number, a
finding with no hold code, and `deferred_marker` (a figure followed by "By Contractor" is not
a confirmed value; owner, 10 Nov: those rows stay on the CRS).
"""

from __future__ import annotations

from . import crs_decider, hold_reason
from .config import settings

R2, R3 = "R2", "R3"
R2_CODES = frozenset(
    {hold_reason.APPLICABILITY_NOT_STATED, hold_reason.APPLICABILITY_NOT_STATED_ABSENT}
)
#: The reason each moved finding shows on the internal list, by its stored code.
REASON_WORDS = {
    hold_reason.APPLICABILITY_NOT_STATED: (
        "whether it applies depends on a condition the sheet does not state"
    ),
    hold_reason.APPLICABILITY_NOT_STATED_ABSENT: (
        "the field is not given, and whether it is needed depends on a condition"
        " the sheet does not state"
    ),
    hold_reason.FIELD_SEVERAL_VALUES: (
        "the field has more than one value on the sheet, only a draft rule checks it,"
        " and every value it states is given with no placeholder or deferral mark"
    ),
}
LISTED_PREFIX = "Engineer to check here, not a CRS comment: "
NOTE_NOT_REQUIRED = (
    "Did not reference - not a CRS comment, no held project specification requires it"
)
NOTE_NOT_APPLICABLE = "Checks not done - cited standard does not appear to apply"
#: `crs_mapping.ROW_KIND_STANDARD_NOT_CITED` / `ROW_KIND_STANDARD_NOT_APPLICABLE`, as literals so this module
#: never imports the CRS mapping; a test holds them equal.
NOT_CITED, NOT_APPLICABLE = "standard_not_cited", "standard_not_applicable"
_HELD, _DATASHEET = "NEEDS_ENGINEER_REVIEW", "datasheet_check"


def enabled() -> bool:
    return bool(settings.crs_routing_by_hold_reason_enabled)


# ------------------------------------------------------------ R2 / R3: one finding


def rule(finding: dict) -> str | None:
    """The rule ("R2" or "R3") that moves this finding to the internal list, else None. Switch off: None."""
    if not enabled() or finding.get("origin") != _DATASHEET:
        return None
    if finding.get("compliance_status") != _HELD or crs_decider.decider(finding):
        return None
    if finding.get("approval_status") == "rejected":
        return None
    code = hold_reason.of(finding)
    if code in R2_CODES:
        return R2
    if (
        code == hold_reason.FIELD_SEVERAL_VALUES
        and _draft_only(finding)
        and _every_value_unmarked(finding)
    ):
        return R3
    return None


def _draft_only(finding: dict) -> bool:
    """Checked only by a draft rule: no person's label, not a safety field, and the rule is
    unproven or its checklist is a draft."""
    from .compliance_list import PERSON_LABELS, UNPROVEN
    from .datasheet_checks import is_draft_checklist

    if finding.get("trust_label") in PERSON_LABELS or finding.get("tier") == "SAFETY":
        return False
    if finding.get("show_for_engineer_tick"):
        return False
    return finding.get("trust_label") == UNPROVEN or is_draft_checklist(
        finding.get("requirement")
    )


def _every_value_unmarked(finding: dict) -> bool:
    """A value was read, the field itself states two or more different values for the finding's
    tag (`same_value.key`, as the check compares them), and every value is present and unmarked."""
    from .same_value import key

    if not str(finding.get("contractor_evidence_text") or "").strip():
        return False
    values = _field_values(finding.get("fact_id"))
    tag = values[0].get("equipment_tag") if values else None
    differ = {key(f) for f in values if f.get("equipment_tag") == tag}
    return len(differ) >= 2 and all(_unmarked(f) for f in values)


def _unmarked(fact: dict) -> bool:
    """Present, and no placeholder, blank mark or deferral phrase anywhere in it."""
    from .blank_markers import fact_is_placeholder, names_a_marker

    printed = [fact.get(k) for k in ("field_value", "raw_value", "value_note")]
    if fact.get("is_blank") or fact.get("blank_marker") or not any(printed[:2]):
        return False
    if fact_is_placeholder(fact):
        return False
    return not any(names_a_marker(str(v)) for v in printed if v)


def _field_values(fact_id: str | None) -> list[dict]:
    """Every value the sheet states for the field of this fact: the current facts of the same
    submittal that may be that field (a role their names share with it, or the same label),
    the fact itself first. Wider than the check's own reading, never narrower: one more value
    can only keep a row on the CRS. No fact on record: []."""
    facts = _sheet_facts(fact_id) if fact_id else []
    own = next((f for f in facts if f.get("id") == fact_id), None)
    if own is None:
        return []
    from .datasheet_checks import load_rules

    rules = load_rules()
    roles, label = _roles(own, rules), _label(own)
    same = [
        f
        for f in facts
        if f is not own and (roles & _roles(f, rules) or (label and _label(f) == label))
    ]
    return [own, *same]


def _roles(fact: dict, rules: dict) -> set[str]:
    from .datasheet_roles import roles_of

    names = {fact.get("field_name"), fact.get("field_label")}
    return {r for n in names if n for r in roles_of(str(n), rules)}


def _label(fact: dict) -> str:
    return " ".join(
        str(fact.get("field_label") or fact.get("field_name") or "").lower().split()
    )


def _sheet_facts(fact_id: str) -> list[dict]:
    """The current facts of the submittal this fact belongs to (the fact itself always)."""
    from .db import connect

    rows = (
        connect()
        .execute(
            "SELECT * FROM submittal_facts WHERE submittal_document_id ="
            " (SELECT submittal_document_id FROM submittal_facts WHERE id = ?)"
            " AND (superseded_at IS NULL OR id = ?)",
            (fact_id, fact_id),
        )
        .fetchall()
    )
    return [dict(r) for r in rows]


def status_words(finding: dict) -> str:
    """The internal list's Status cell for a moved finding: the reason, in words."""
    return LISTED_PREFIX + REASON_WORDS.get(
        hold_reason.of(finding) or "", "held for the engineer"
    )


# ------------------------------------------------------------ R1 / R4: the standards rows


def standards(
    rows: list[dict],
    notes: list[dict],
    check: dict | None,
    run_id: str,
    crs_scope: str,
    allowed: frozenset[str],
) -> tuple[list[dict], list[dict]]:
    """`main._crs_content`'s rows after composing (via `export_status.one_row`): (rows kept,
    notes + one Review note per row moved). Switch off, or no standards row: as they came."""
    if not enabled() or not any(
        r.get("row_kind") in (NOT_CITED, NOT_APPLICABLE) for r in rows
    ):
        return rows, notes
    keep = _kept_keys(rows, run_id, crs_scope)
    required = _spec_requires(run_id, allowed)
    kept, moved = [], []
    for row in rows:
        note = (
            None
            if row.get("comment_key") in keep
            else moved_note(row, check or {}, required)
        )
        if note is None:
            kept.append(row)
        else:
            moved.append(note)
    return kept, [*notes, *moved]


def _entry(entries, identifier: str) -> dict | None:
    return next((e for e in entries or [] if e.get("identifier") == identifier), None)


def moved_note(row: dict, check: dict, required) -> dict | None:
    """The Review note a standards row becomes (R1, R4), or None when it stays a CRS row.
    `required(identifier)`: the held project specification requires it with a verified quote."""
    if row.get("engineer_confirmed"):
        return None
    ident = str(row.get("standard_reference") or "")
    if row.get("row_kind") == NOT_CITED:
        entry = _entry(check.get("required_not_cited"), ident)
        if entry is None or entry.get("unsure") or required(ident):
            return None
        detail = (
            f"{ident} is listed for this submittal ({entry.get('reason') or 'no reason recorded'}) and the "
            f"contractor did not cite it. No project specification held for this review requires {ident} "
            "with a quote verified on its page, so it is not a comment to the contractor. This does not say "
            f"the document complies with {ident}."
        )
        return {
            "note": NOTE_NOT_REQUIRED,
            "standard": ident,
            "count": None,
            "detail": detail,
        }
    if row.get("row_kind") == NOT_APPLICABLE:
        entry = _entry(check.get("cited_not_applicable"), ident)
        if entry is None:
            return None
        detail = (
            f"{ident} is cited by this submittal; the scope check says it does not appear to apply "
            f"({entry.get('reason') or 'no reason recorded'}). Listed here, not as a CRS comment; "
            "engineer to confirm."
        )
        return {
            "note": NOTE_NOT_APPLICABLE,
            "standard": ident,
            "count": None,
            "detail": detail,
        }
    return None


def _kept_keys(rows: list[dict], run_id: str, crs_scope: str) -> set[str]:
    """Standards rows that stay whatever R1 / R4 say: an engineer decided them on this run,
    or their number was issued (a machine draft's number is not issued)."""
    from . import crs_issue, crs_numbers

    keys = [
        r["comment_key"]
        for r in rows
        if r.get("row_kind") in (NOT_CITED, NOT_APPLICABLE) and r.get("comment_key")
    ]
    records = crs_numbers.lookup(crs_scope, keys)
    issued = {k for k, record in records.items() if record.get("issued", 1)}
    decided = {d.get("subject") for d in crs_issue.decisions(run_id)}
    return issued | (decided & set(keys))


def requires(identifier: str, verified_quotes: list[str]) -> bool:
    """Does a verified quote of the project specification name this standard?"""
    from .standard_ids import names_standard

    return any(names_standard(q, identifier) for q in verified_quotes)


def spec_quotes(submittal_id: str | None, allowed: frozenset[str]) -> list[str]:
    """The quotes of the project specification held for this submittal (marked by a person,
    readable by the caller) that are verified on their own stored passage. None held: []."""
    from . import project_specification
    from .compiled_rule_proof import quote_verified
    from .db import connect

    spec = project_specification.used(submittal_id, allowed) if submittal_id else None
    if spec is None:
        return []
    pairs = (
        connect()
        .execute(
            "SELECT r.source_text, c.text FROM standard_requirements r JOIN chunks c ON c.id = r.chunk_id"
            " WHERE r.standard_document_id = ? AND r.superseded_at IS NULL",
            (spec["id"],),
        )
        .fetchall()
    )
    return [quote for quote, passage in pairs if quote_verified(quote, passage)]


def _spec_requires(run_id: str, allowed: frozenset[str]):
    from .db import connect

    run = (
        connect()
        .execute(
            "SELECT submittal_document_id FROM review_runs WHERE id = ?", (run_id,)
        )
        .fetchone()
    )
    quotes = spec_quotes(run["submittal_document_id"] if run else None, allowed)
    return lambda identifier: requires(identifier, quotes)
