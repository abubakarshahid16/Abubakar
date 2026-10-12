"""Every requirement in a review's scope ends in exactly ONE state, with a reason (#677).

A review starts from the standards in scope and their requirements. Before
#677 most of them left the run as a count in a grouped line ("6,350 table
values ... not compared"), with nothing recorded for the requirement itself
(#669). Now each one gets one decision, stored with the run:

  checked              compared with a value on the datasheet (a verdict);
  applies_not_checked  in scope, but not compared - and why (no matching
                       field, missing information, needs an engineer, needs
                       another document, unreadable text, applicability
                       unsure). An unsure case stays HERE, never dropped;
  does_not_apply       out of scope for this submittal - and why (another
                       kind of equipment, a service condition the submittal
                       says it does not have, a definition).

Each gate that decides something returns its per-requirement decisions
(`table_gate`, `subject_scope`, `service_scope`, the review itself); this
module only names the states and reasons and checks the whole set: exactly one
decision per requirement in scope, or the run fails loudly
(`check_complete`).

Generic: no reason names a standard, a clause or a datasheet.
"""
from __future__ import annotations

CHECKED = "checked"
APPLIES_NOT_CHECKED = "applies_not_checked"
DOES_NOT_APPLY = "does_not_apply"
#: #746: the equipment type's review checklist governs this standard; the
#: requirement stays quotable but is not checked one by one.
NOT_USED = "not_used"
STATES = (CHECKED, APPLIES_NOT_CHECKED, DOES_NOT_APPLY, NOT_USED)

#: reason code -> (state, plain words for an engineer). "checked" means what
#: #678's three-way split means by it: the requirement REACHED the comparison
#: (met / not met / needs engineer); the reason says how it ended there, so
#: "compared with a value" stays visible beside "needs an engineer".
REASONS: dict[str, tuple[str, str]] = {
    # checked: reached the comparison - how it ended
    "compared": (CHECKED, "compared with the datasheet value"),
    "missing_information": (CHECKED, "no value for it on this datasheet"),
    "needs_engineer": (CHECKED, "an engineer has to decide it"),
    "needs_other_document": (CHECKED, "it asks for evidence another document gives"),
    "not_applicable": (CHECKED, "the comparison found it does not apply here"),
    # applies, not checked
    "row_label_not_on_sheet": (APPLIES_NOT_CHECKED,
                               "table row: its row label is not on this datasheet"),
    "column_not_on_sheet": (APPLIES_NOT_CHECKED,
                            "table row: its column is not a field of this datasheet"),
    "other_row_matched": (APPLIES_NOT_CHECKED,
                          "table row: another row of the same table matched this datasheet"),
    "no_label": (APPLIES_NOT_CHECKED, "table row: it has no row label or column to match"),
    "unreadable_text": (APPLIES_NOT_CHECKED,
                        "its text failed the quality check and is not confirmed"),
    "service_unknown": (APPLIES_NOT_CHECKED,
                        "it applies only in a service the submittal does not state"),
    "applicability_unsure": (APPLIES_NOT_CHECKED,
                             "whether it applies could not be confirmed"),
    # does not apply
    "definition": (DOES_NOT_APPLY, "a definition, not a requirement"),
    # #746
    "covered_by_checklist": (NOT_USED, "the review checklist for this equipment type governs its standard"),
    "other_equipment": (DOES_NOT_APPLY, "it is about another kind of equipment"),
    "service_condition_not_met": (DOES_NOT_APPLY,
                                  "it applies only in a service this submittal says it is not in"),
    "informative_note": (DOES_NOT_APPLY, "an informative note, not a requirement"),
    "outside_partial_scope": (DOES_NOT_APPLY,
                              "the equipment type takes this standard only in part, and not this rule"),
    "not_material_field": (DOES_NOT_APPLY,
                           "a materials standard applies only to the material fields this datasheet states"),
}


#: A finding's status -> the reason code its requirement's decision carries.
STATUS_REASON = {
    "COMPLIANT": "compared", "NON_COMPLIANT": "compared", "CONDITIONAL": "compared",
    "MISSING_INFORMATION": "missing_information",
    "NEEDS_ENGINEER_REVIEW": "needs_engineer",
    "NOT_IN_DOCUMENT_SCOPE": "needs_other_document",
    "NOT_APPLICABLE": "not_applicable",
}


#: #678 item codes that differ from this module's reason codes.
_ITEM_CODE = {"text_quality": "unreadable_text"}


def build(*, checked: list[dict], status_of: dict, rejected: set,
          not_checked: list[dict], not_applied: list[dict], notes: dict | None = None,
          not_used: list[dict] | None = None) -> list[dict]:
    """The per-requirement decisions, from the SAME inputs #678's
    `requirement_split.build` counts: the requirements that reached the
    comparison (with their finding's status), and the not-checked / does-not-
    apply items (`{"requirement", "code", "detail"}`). One decision per stored
    row. `notes`: what an AI tier suggested and code did not confirm, kept on
    the decision of a requirement that was not compared with a value."""
    notes = notes or {}
    out: list[dict] = []
    for requirement in checked:
        rid = requirement.get("id")
        if rid in status_of:
            decided = from_finding(requirement, status_of[rid])
        else:
            decided = decision(requirement, "needs_engineer",
                               "an engineer rejected the pairing" if rid in rejected
                               else "no finding was written")
        if rid in notes and decided["reason_code"] != "compared":
            decided = {**decided, "reason": f"{decided['reason']}; {notes[rid]}"}
        out.append(decided)
    for item in not_checked:
        out.append(_from_item(item, APPLIES_NOT_CHECKED))
    for item in not_applied:
        out.append(_from_item(item, DOES_NOT_APPLY))
    for item in not_used or []:
        out.append(_from_item(item, NOT_USED))
    return out


def _from_item(item: dict, state: str) -> dict:
    code = _ITEM_CODE.get(item.get("code") or "", item.get("code") or "")
    words = (item.get("detail") or "").strip() or REASONS.get(code, (state, "no reason recorded"))[1]
    return {"requirement_id": item["requirement"].get("id"), "state": state,
            "reason_code": code or "no_reason_recorded", "reason": words,
            "decided_by": item.get("decided_by") or "code"}


def from_finding(requirement: dict, status: str | None) -> dict:
    """The decision for a requirement that reached the comparison. An unknown
    status is an engineer's question, never a silent state."""
    code = STATUS_REASON.get(status or "", "needs_engineer")
    detail = status.replace("_", " ").lower() if status and code == "compared" else None
    return decision(requirement, code, detail)


def ensure_schema() -> None:
    from .db import connect

    conn = connect()
    with conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS review_scope_decisions (
            review_run_id TEXT NOT NULL, requirement_id TEXT NOT NULL,
            state TEXT NOT NULL, reason_code TEXT NOT NULL, reason TEXT NOT NULL,
            decided_by TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY (review_run_id, requirement_id))""")


def store(review_run_id: str, decisions: list[dict]) -> None:
    """The run's ledger, replaced as a whole: a re-run decides its scope again.
    (Findings are not touched here; this is the run's own derived record.)"""
    from datetime import UTC, datetime

    from .db import connect

    ensure_schema()
    now = datetime.now(UTC).isoformat(timespec="seconds")
    conn = connect()
    with conn:
        conn.execute("DELETE FROM review_scope_decisions WHERE review_run_id = ?", (review_run_id,))
        conn.executemany(
            "INSERT INTO review_scope_decisions (review_run_id, requirement_id, state,"
            " reason_code, reason, decided_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(review_run_id, d["requirement_id"], d["state"], d["reason_code"], d["reason"],
              d["decided_by"], now) for d in decisions])


def decisions_for(review_run_id: str) -> list[dict]:
    from .db import connect

    ensure_schema()
    return [dict(r) for r in connect().execute(
        "SELECT * FROM review_scope_decisions WHERE review_run_id = ? ORDER BY requirement_id",
        (review_run_id,))]


def decision(requirement: dict, reason_code: str, detail: str | None = None,
             decided_by: str = "code") -> dict:
    """One requirement's decision. `detail` adds the specifics (the subject,
    the service stated) to the reason's plain words."""
    state, words = REASONS[reason_code]
    return {"requirement_id": requirement.get("id"), "state": state,
            "reason_code": reason_code,
            "reason": f"{words}: {detail}" if detail else words,
            "decided_by": decided_by}


class IncompleteScope(RuntimeError):
    """A requirement in scope has no decision, or more than one."""


def check_complete(in_scope: list[dict], decisions: list[dict]) -> dict:
    """Exactly one decision per requirement in scope, every state known.
    Returns the counts; raises `IncompleteScope` otherwise - a run must never
    report counts that do not add up to its scope."""
    from collections import Counter

    wanted = [r.get("id") for r in in_scope]
    got = [d["requirement_id"] for d in decisions]
    missing = set(wanted) - set(got)
    extra = set(got) - set(wanted)
    repeated = {i for i, n in Counter(got).items() if n > 1}
    if missing or extra or repeated or len(got) != len(wanted):
        raise IncompleteScope(
            f"scope ledger does not add up: {len(wanted)} in scope, {len(got)} decisions "
            f"({len(missing)} without a decision, {len(extra)} not in scope, "
            f"{len(repeated)} decided twice)")
    unknown = [d for d in decisions if d["state"] not in STATES]
    if unknown:
        raise IncompleteScope(f"{len(unknown)} decisions have an unknown state")
    counts = {s: 0 for s in STATES}
    by_reason: dict[str, int] = {}
    for d in decisions:
        counts[d["state"]] += 1
        by_reason[d["reason_code"]] = by_reason.get(d["reason_code"], 0) + 1
    return {"in_scope": len(wanted), **counts, "by_reason": by_reason}
