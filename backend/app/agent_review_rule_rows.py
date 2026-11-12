"""The stored rule rows of an AI review run: which rules were asked or left out, with their words (moved unchanged from agent_review_jobs)."""

from __future__ import annotations

from . import agent_review_rules as rules
from . import rule_labels
from .db import connect

#: Words of the contract (`api/agent_review_schemas.py`).
#: The label table's tier words -> the contract's. A tier we cannot name is never shown as approved.
TIER_WORDS = {
    "owner": "Owner",
    "engineer": "Engineer",
    "AI approved": "AI approved",
    "not AI approved": "Not AI approved",
}
#: The core's reason -> the contract's left-out word (`rules.REASON_WORDS`); "paper kind unknown" is said once on the run.
LEFT_OUT_WORDS = {
    k: v for k, v in rules.REASON_WORDS.items() if k != rules.KIND_UNKNOWN
}


def _tier_word(item: dict) -> str | None:
    """The tier of a rule ITEM as asked (a checklist item has none: None)."""
    if item.get("source") != "rule":
        return None
    if item.get("rule_tier") == rules.RULE_NOT_APPROVED:
        return "Not AI approved"
    return (
        TIER_WORDS.get((item.get("rule_label") or {}).get("tier")) or "Not AI approved"
    )


def _line_tier(line: dict) -> str | None:
    """The tier of a stored LINE: the one the exit wrote (`tier`, from the CURRENT label table); a checklist line has none."""
    if line.get("checklist") is True and line.get("tier") is None:
        return None
    return TIER_WORDS.get(line.get("tier")) or "Not AI approved"


def _equipment_of(label: dict | None) -> str | None:
    """The equipment (type, else family) a rule's label AGREES on; None when the label has none or it is not agreed."""
    label = label or {}
    if str(label.get("equip_state") or "") != "agreed":
        return None
    return label.get("equip_type") or label.get("equip_family") or None


def _asked_row(run_id: str, it: dict, cache: dict, kind: str) -> tuple:
    lab = it.get("rule_label") or {}
    ref = it.get("rule_quote_ref") or it.get("clause_quote_ref")
    entry = cache.get(ref) if isinstance(ref, str) else None
    quote = (
        entry.get("text")
        if isinstance(entry, dict)
        else (entry if isinstance(entry, str) else None)
    )
    full = (
        rule_labels.label_for(connect(), requirement_id=str(it.get("rule_version_id")))
        or {}
    )
    read_from = "scan" if str(full.get("read_from") or "") == "scan" else "text"
    return (run_id, str(it.get("item_id")), 1, None, str(it.get("standard") or ""), str(it.get("clause") or ""), quote,
            it.get("clause_page"), it.get("standard_document_id"), read_from, lab.get("paper_kind") or kind,
            lab.get("field"), _equipment_of(lab.get("equipment")), _tier_word(it))  # fmt: skip


def _write_rules(run_id: str, doc: dict, cache: dict, kind: str) -> None:
    """Every rule of the run: asked, or left out with its one reason. Idempotent (a resumed run writes the same rows)."""
    block = doc.get("rule_labels") or {}
    rows = [
        _asked_row(run_id, it, cache, kind)
        for it in doc.get("items") or []
        if it.get("source") == "rule"
    ]
    for rec in block.get("left_out") or []:
        reason = LEFT_OUT_WORDS.get(rec.get("reason"))
        if reason is None:
            continue  # "paper kind unknown": said once on the run, not once per rule
        rows.append((run_id, str(rec.get("rule_version_id") or rec.get("item_id")), 0, reason,
                     str(rec.get("rule_book") or ""), str(rec.get("clause") or ""), None, rec.get("page"),
                     rec.get("standard_document_id"), "text", rec.get("needs_paper_kind"), None, None, None))  # fmt: skip
    with connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO agent_review_rule (run_id, rule_key, asked, left_out_reason, rule_book, clause, quote,"
            " quote_page, standard_document_id, read_from, paper_kind, field, equipment, tier)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )


def _write_missing(run_id: str, missing: list[dict]) -> None:
    with connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO agent_review_missing_book (run_id, name, why) VALUES (?,?,?)",
            [
                (run_id, str(m.get("rule_book")), str(m.get("why") or ""))
                for m in missing
                if m.get("rule_book")
            ],
        )
