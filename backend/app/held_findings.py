"""A requirement the review held is an engineer-review row, not only a count (order 210, fix 3).

WHY. A requirement that APPLIES to a sheet but could not be checked - it names a
service the sheet does not state, its part's scope could not be confirmed - was
recorded in the scope ledger and the coverage counts and nowhere else. The
review's findings, the CRS and the engineer's queue showed nothing, so a sheet
that never answered "impact test results shall be stated" looked as if the
standard had no such clause (PF1: the vessel's impact test, the control valve's
fire-safe certificate). Now each such requirement also gets a finding of status
NEEDS_ENGINEER_REVIEW with the reason it was held, in the words the ledger
holds.

WHAT IT NEVER DOES. The row is never a pass: its status is the engineer's
question, its text says the requirement was NOT compared with the datasheet, and
the requirement keeps its place in the ledger (this adds a row; no count
moves). Not turned into rows: a garbled sentence (`text_quality`, not yet
confirmed as a requirement) and a list that states no requirement (flagged
`not_a_requirement`), neither of which is a clause an engineer can act on. A
requirement that already has a finding in the run gets no second one."""

from __future__ import annotations

NEEDS_ENGINEER_REVIEW = "NEEDS_ENGINEER_REVIEW"
NOT_ROWS = frozenset({"text_quality"})
HELD_REASON = "Held, not compared with the datasheet"


def eligible(item: dict) -> bool:
    return item.get("code") not in NOT_ROWS and not item.get("not_a_requirement")


def verdict(item: dict, ledger_reason: str) -> dict:
    """The finding's verdict: the engineer's question with the reason it was held."""
    reason = (item.get("detail") or "").strip() or ledger_reason
    return {
        "status": NEEDS_ENGINEER_REVIEW,
        "rationale": f"{HELD_REASON}: {reason}. An engineer decides whether it applies "
        "and, if it does, whether the datasheet meets it.",
        "limit": None,
        "observed": None,
        "exception_applied": None,
    }


def add(
    held: list[dict], pending: dict, rows: list, findings: list, run: tuple
) -> None:
    """Add a finding for each held requirement that has none yet to the run's
    `rows` (written once) and `findings` (returned), through the comparison's own
    row builder, so every gate it applies (citation resolution, duplicates)
    applies here too. `run` is (review run id, submittal id, whether the run's
    stored findings are being replaced)."""
    from .comparison import _prepare_finding as prepare_finding
    from .scope_ledger import REASONS

    run_id, submittal_id, replace = run
    for item in held:
        requirement = item["requirement"]
        if not eligible(item) or (requirement.get("id"), None) in pending:
            continue
        fallback = REASONS.get(item.get("code") or "", ("", "no reason recorded"))[1]
        row, unresolved = prepare_finding(
            review_run_id=run_id,
            submittal_document_id=submittal_id,
            requirement=requirement,
            fact=None,
            verdict=verdict(item, fallback),
            pending=pending,
            stored_replaced=replace,
        )
        pending[(row["requirement_id"], None)] = row["id"]
        rows.append(row)
        findings.append(
            {
                **row,
                "unresolved_evidence": unresolved,
                "citation_resolves": not unresolved,
            }
        )
