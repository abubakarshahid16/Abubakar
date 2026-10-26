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


#: More held requirements than this of one standard and one kind of hold are ONE
#: row (a real sheet held 1,937; one row each would bury the 11 lines it has).
GROUP_ABOVE = 5
FIRST_CLAUSES = 6
KINDS = {
    "service": "the sentence names a service the datasheet does not state",
    "part_not_read": "the part of the standard it belongs to could not be read",
    "scope_unsure": "whether the part of the standard it belongs to applies could not be confirmed",
}


def kind_of(item: dict) -> str:
    if item.get("code") == "service_unknown":
        return "service"
    if str(item.get("decided_by") or "").startswith("code:scope-not-read"):
        return "part_not_read"
    return "scope_unsure"


def _group_row(prepare_finding, group: list[dict], kind: str, label: str, common: dict):
    """ONE finding for a group: the standard, the kind of hold, how many, the
    first clauses. The full list stays in the run's scope ledger."""
    first = group[0]["requirement"]
    clauses = [
        str(i["requirement"].get("clause"))
        for i in group
        if i["requirement"].get("clause")
    ]
    shown = ", ".join(clauses[:FIRST_CLAUSES]) + (
        " ..." if len(clauses) > FIRST_CLAUSES else ""
    )
    said = (
        f"{len(group)} requirements of {label} were held: {KINDS[kind]}"
        + (f" (clauses {shown})" if shown else "")
        + "; their exact reasons and the full list are in this run's scope ledger"
    )
    verdict_ = verdict({"detail": said}, said)
    row, unresolved = prepare_finding(
        requirement=first, fact=None, verdict=verdict_, **common
    )
    row["requirement"] = f"{len(group)} held requirements of {label}"
    return row, unresolved


def add(
    held: list[dict], pending: dict, rows: list, findings: list, run: tuple
) -> None:
    """Add findings for the held requirements that have none yet to the run's
    `rows` (written once) and `findings` (returned), through the comparison's own
    row builder, so every gate it applies (citation resolution, duplicates)
    applies here too. A standard with more than `GROUP_ABOVE` held requirements of
    one kind gets ONE row for them. `run` is (review run id, submittal id,
    whether the run's stored findings are being replaced, standard labels)."""
    from .comparison import _prepare_finding as prepare_finding
    from .scope_ledger import REASONS

    run_id, submittal_id, replace, labels = run
    common = {
        "review_run_id": run_id,
        "submittal_document_id": submittal_id,
        "pending": pending,
        "stored_replaced": replace,
    }
    groups: dict[tuple, list[dict]] = {}
    for item in held:
        requirement = item["requirement"]
        if eligible(item) and (requirement.get("id"), None) not in pending:
            key = (requirement.get("standard_document_id"), kind_of(item))
            groups.setdefault(key, []).append(item)
    for (sid, kind), group in groups.items():
        if len(group) > GROUP_ABOVE:
            made = [
                _group_row(
                    prepare_finding, group, kind, labels.get(sid) or str(sid), common
                )
            ]
        else:
            made = []
            for item in group:
                code = item.get("code") or ""
                fallback = REASONS.get(code, ("", "no reason recorded"))[1]
                made.append(
                    prepare_finding(
                        requirement=item["requirement"],
                        fact=None,
                        verdict=verdict(item, fallback),
                        **common,
                    )
                )
        for row, unresolved in made:
            pending[(row["requirement_id"], None)] = row["id"]
            rows.append(row)
            findings.append(
                {
                    **row,
                    "unresolved_evidence": unresolved,
                    "citation_resolves": not unresolved,
                }
            )
