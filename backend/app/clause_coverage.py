"""PF4 (#884): clause coverage - every applicable rule accounted for.

Owner pass mark (PROOF FIRST, 13 Oct 2026): of the run's APPLICABLE
requirements (after the applicability gates, including those a checklist
covers), 100% sit in exactly one state:

  checked        reached the comparison and ended in it (met, not met,
                 conditional, the sheet states no value, or the comparison
                 found it does not apply) - shown with its finding;
  engineer       sent to the engineer, with the reason;
  not_checked    applies, but was not compared - with the reason.

A requirement a review CHECKLIST covers is counted in the denominator and
listed apart, in words that say it is not proof the whole standard was
checked. "Does not apply" is outside the denominator and listed apart too.

NOT A SECOND SOURCE OF TRUTH. This reads the run's own scope ledger (#677,
`scope_ledger`, one decision per requirement in scope, checked to add up when
the run was written) and regroups it. Read only: a run with no ledger says
so - never zero.

Ids, counts and reasons only; never clause text.
"""
from __future__ import annotations

from .db import connect
from . import scope_ledger

CHECKED, ENGINEER, NOT_CHECKED, CHECKLIST, DOES_NOT_APPLY = (
    "checked", "engineer", "not_checked", "covered_by_checklist", "does_not_apply")
STATES = (CHECKED, ENGINEER, NOT_CHECKED, CHECKLIST)

#: The ledger's reason code -> PF4's state. Every reason the ledger knows is
#: here (`test_every_ledger_reason_has_one_pf4_state`), so a new reason cannot
#: slip into no state.
STATE_OF = {
    "compared": CHECKED, "missing_information": CHECKED, "not_applicable": CHECKED,
    "needs_engineer": ENGINEER, "needs_other_document": ENGINEER,
    "covered_by_checklist": CHECKLIST,
}
_BY_LEDGER_STATE = {scope_ledger.APPLIES_NOT_CHECKED: NOT_CHECKED,
                    scope_ledger.DOES_NOT_APPLY: DOES_NOT_APPLY,
                    scope_ledger.NOT_USED: CHECKLIST}
for _code, (_state, _words) in scope_ledger.REASONS.items():
    if _code not in STATE_OF and _state in _BY_LEDGER_STATE:
        STATE_OF[_code] = _BY_LEDGER_STATE[_state]

CHECKLIST_NOTE = ("a review checklist covers this standard; this is not proof that every "
                  "clause of the standard was checked")
NO_LEDGER = "no coverage ledger is recorded for this run"


def _ledger(review_run_id: str) -> list[dict] | None:
    """READ ONLY: the run's stored decisions, or None when none are recorded."""
    conn = connect()
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table'"
                    " AND name = 'review_scope_decisions'").fetchone() is None:
        return None
    rows = [dict(r) for r in conn.execute(
        "SELECT requirement_id, state, reason_code, reason FROM review_scope_decisions"
        " WHERE review_run_id = ? ORDER BY requirement_id", (review_run_id,))]
    return rows or None


def _where(requirement_ids: list[str], allowed: frozenset[str]) -> dict:
    """Clause and standard of each requirement, only where the caller may
    read the standard (a filter only narrows)."""
    if not requirement_ids:
        return {}
    out: dict = {}
    ids = list(requirement_ids)
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        marks = ",".join("?" * len(part))
        for r in connect().execute(
                f"SELECT id, standard_document_id, clause FROM standard_requirements"
                f" WHERE id IN ({marks})", part):
            if r["standard_document_id"] in allowed:
                out[r["id"]] = {"standard_document_id": r["standard_document_id"],
                                "clause": r["clause"]}
    return out


def state_of(decision: dict) -> str:
    """PF4's state of one ledger decision. A reason this module does not
    know is NOT CHECKED, never silent."""
    return STATE_OF.get(decision["reason_code"]) or NOT_CHECKED


def summarise(decisions: list[dict]) -> dict:
    """The counts, the denominator and the one line, from a run's decisions -
    the SAME arithmetic for the route (`for_run`, from the stored ledger) and
    for the run record (`comparison` stores this at run end, PF4 step 1), so
    the two can never disagree (rule 8). Counts only; no clause text."""
    counts = {s: 0 for s in (*STATES, DOES_NOT_APPLY)}
    for d in decisions:
        counts[state_of(d)] += 1
    applicable = sum(counts[s] for s in STATES)
    adds_up = applicable + counts[DOES_NOT_APPLY] == len(decisions)
    share = round(100 * counts[CHECKED] / applicable, 1) if applicable else None
    return {"applicable": applicable, "counts": counts, "checked_share": share,
            "adds_up": adds_up, "line": line(counts, applicable, adds_up)}


def for_run(review_run_id: str, *, allowed_document_ids: frozenset[str]) -> dict:
    """The run's coverage ledger in PF4's states, with its denominator."""
    ledger = _ledger(review_run_id)
    if ledger is None:
        return {"review_run_id": review_run_id, "recorded": False, "note": NO_LEDGER,
                "applicable": None, "counts": None, "checked_share": None,
                "adds_up": None, "line": NO_LEDGER, "rows": []}
    where = _where([d["requirement_id"] for d in ledger], allowed_document_ids)
    rows = [{"requirement_id": d["requirement_id"], "state": state_of(d),
             "reason_code": d["reason_code"], "reason": d["reason"],
             "note": CHECKLIST_NOTE if state_of(d) == CHECKLIST else None,
             **where.get(d["requirement_id"], {"standard_document_id": None, "clause": None})}
            for d in ledger]
    return {"review_run_id": review_run_id, "recorded": True, "note": None,
            **summarise(ledger), "rows": rows}


def line(counts: dict, applicable: int, adds_up: bool) -> str:
    """The run report's one line - every count out of the applicable rules."""
    if not applicable:
        return (f"0 applicable requirements in this run "
                f"({counts[DOES_NOT_APPLY]} do not apply)")
    share = f"{100 * counts[CHECKED] / applicable:.1f}%"
    text = (f"{counts[CHECKED]} of {applicable} applicable requirement(s) checked ({share}), "
            f"{counts[ENGINEER]} sent to the engineer, {counts[NOT_CHECKED]} not checked")
    if counts[CHECKLIST]:
        text += f"; {counts[CHECKLIST]} covered by a checklist (not proof the whole standard was checked)"
    text += f"; {counts[DOES_NOT_APPLY]} do not apply"
    return text + ("" if adds_up else "; THE COUNTS DO NOT ADD UP - report this run")


NOTE = "Clause coverage"
NOT_RECORDED = ("Clause coverage is not recorded for this run (made before the coverage "
                "ledger); re-run the review to get it.")


def review_notes(outcome: dict | None) -> list[dict]:
    """PF4 step 2: the one CRS Review-notes row (internal copy) that states
    the run's clause coverage from the record the run stored at its end
    (`summarise`, PR #1013) - the same line, one home (CLAUDE.md rule 8).
    A run with no record says so; it is never 0."""
    cov = (outcome or {}).get("clause_coverage") or {}
    if not cov:
        return [{"note": NOTE, "standard": "", "count": None, "detail": NOT_RECORDED}]
    return [{"note": NOTE, "standard": "", "count": cov.get("applicable"),
             "detail": f"{cov.get('line')}. The share is out of this run's applicable "
                       "requirements; a checklist-covered requirement counts as covered "
                       "by its checklist, not as proof the whole standard was checked."}]
