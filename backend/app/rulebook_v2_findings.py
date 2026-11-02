"""#805 plan change 6: a review's version 2 rows as findings of the run, and what the run states about them."""

from __future__ import annotations

from . import rule_trust
from .rulebook_v2_review import (
    COMPLIANT,
    DECIDED,
    LABEL,
    ORIGIN,
    Review,
    Row,
    _texts,
    as_requirement,
)


def citation(rule: dict) -> str:
    edition = f" {rule['edition']}" if rule.get("edition") else ""
    return (
        f"{LABEL} rule {rule.get('rule_id')} version {rule.get('version')}: {rule.get('standard') or ''}{edition}"
        f" clause {rule.get('clause')} page {rule.get('page')}: {rule.get('quote') or ''}"
    )


def _tier_columns(row: Row) -> dict:
    """The safety tier and the open tick, as `rule_trust` gives them to every rule. A safety Pass waits for an engineer's
    tick, and `rule_trust.hold_open_ticks` holds the sheet's code for it."""
    if row.status not in DECIDED:
        return {"tier": None, "show_for_engineer_tick": None}
    rule = row.rule
    level, _why = rule_trust.tier(
        {
            **as_requirement(rule),
            "condition": (_texts(rule.get("conditions")) or [None])[0],
            "exceptions": _texts(rule.get("exceptions")),
        }
    )
    return {
        "tier": level,
        "show_for_engineer_tick": int(
            level == rule_trust.SAFETY and row.status == COMPLIANT
        ),
    }


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
                        **_tier_columns(row),
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
        "withheld": review.withheld,
        **(
            {"material_reference": review.reference_version}
            if review.reference_version
            else {}
        ),
    }
