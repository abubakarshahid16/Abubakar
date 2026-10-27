"""Order 261.2: a failed AI reading must never make a verdict more confident.

The datasheet reader asks the AI for each field of the equipment type's form and keeps only what
the code gates accept. When part of that reading did not come back, the conflict the AI would
have raised never appears and the rule reader's value stands unchallenged (s2, 27 Oct: two 35B
models on one Mac, the broken sheet read 5 of 5 pages "engine answer unusable", AI facts 68 ->
39, conflicts 16 -> 4, checklist meets 81 -> 88, the run summary saying nothing).

THE TRIGGER (planner 22:39, from s2's stored summaries): any page that was READ ONLY IN PART
(`partly_read`, "engine answer unusable") or CUT OFF, a page with an unusable answer or no AI
answer (`code_only`), a timed-out page, a stopped reader, or an unavailable reader. When it fires:
  * the sheet lists the part "the AI reading looked incomplete" (the CRS banner and the review
    notes), a banner that changes no verdict;
  * every checklist pass is held for the engineer, "AI reading missing": the summary says which
    PAGES failed, not which fields, so the safe unit is the whole checklist.
THE HARD RULE, per field, on top (`missing_roles`): a pass is held when the reader's own per-field
reasons (`rejected_fields`, "role: reason") name ANY role the item reads (its field, both sides
of a comparison, a condition role) with an ERROR reason (model failed, cut off, timed out,
malformed, unstable, field not answered, stopped).
It only ever turns COMPLIANT into NEEDS_ENGINEER_REVIEW; it never lifts a hold.

NOT triggers: "more answers refused by the code gates than agreed" (a CLEAN relief-valve read
refuses 117 and agrees 58) and a low agreed share (a clean pump sheet reads 0.53). Both are
recorded nowhere as a flag; a failed QUOTE or value check is a gate doing its job.
"""

from __future__ import annotations

from . import datasheets

NO_TEXT = "no text on this page"
#: The `form_reader.Reason` values that say the AI's reading of a field did NOT come back (the
#: engine failed, was cut off, timed out, answered malformed or unstable, left the field out, or
#: was stopped). A failed quote or value check is a gate doing its job and is NOT in this set.
ERROR_REASONS = frozenset(
    {
        "model_failed",
        "model_cut_off",
        "model_timed_out",
        "model_malformed",
        "model_stopped_by_a_limit",
        "model_unstable",
        "field_not_answered",
    }
)
#: The roles a calculation reads IN CODE (not named in the item's JSON): `datasheet_checks`
#: `api520_gas_area` / `api520_liquid_area` and the helpers they call. A test pins this table
#: against those functions' source, so a new input cannot be added without it.
FORMULA_INPUTS: dict[str, frozenset[str]] = {
    "api520_gas_area": frozenset(
        {
            "required_capacity",
            "set_pressure",
            "overpressure",
            "relieving_temperature",
            "molecular_weight",
            "compressibility",
            "specific_heat_ratio",
            "valve_type",
            "superimposed_back_pressure",
            "built_up_back_pressure",
        }
    ),
    "api520_liquid_area": frozenset(
        {
            "required_capacity",
            "density_relieving",
            "viscosity_relieving",
            "set_pressure",
            "overpressure",
            "valve_type",
            "superimposed_back_pressure",
            "built_up_back_pressure",
        }
    ),
}
HELD = (
    "Engineer to check: the AI reading this result depends on did not come back ({why}), "
    "so the pass is not trusted. AI reading missing."
)


def missing_roles(summary: dict | None) -> dict[str, list[str]]:
    """{role: [error reasons]} from the reader summary's per-field reasons ("role: reason")."""
    out: dict[str, list[str]] = {}
    for key in (summary or {}).get("rejected_fields") or {}:
        role, _sep, reason = str(key).partition(": ")
        if reason in ERROR_REASONS:
            out.setdefault(role, []).append(reason)
    return {role: sorted(set(reasons)) for role, reasons in out.items()}


def assess(summary: dict | None) -> dict | None:
    """The record for a reader summary whose AI reading did not fully come back, or None when
    the AI reader was not asked or its read is complete. Counts and reasons only; it changes no
    verdict (`hold` does, from the same summary)."""
    if not summary or summary.get("engine") == "off":
        return None
    partly = len(summary.get("partly_read") or {})
    cut_off = len(summary.get("cut_off") or [])
    timed_out = len(summary.get("timed_out") or [])
    # a page left to the code readers because the engine's answer was unusable, ran out of
    # time or was unavailable ("no text on this page" is a fact about the page, not a failure)
    failed = sum(
        1 for why in (summary.get("code_only") or {}).values() if why != NO_TEXT
    )
    counts = {
        "partly_read_pages": partly,
        "cut_off_pages": cut_off,
        "timed_out_pages": timed_out,
        "failed_pages": failed,
    }
    why = [name for name, n in counts.items() if n]
    if summary.get("stopped"):
        why.append("stopped")
    if summary.get("unavailable"):
        why.append("unavailable")
    fields = missing_roles(summary)
    if fields:
        why.append("fields_missing")
    if not why:
        return None
    return {**counts, "fields_missing": len(fields), "why": why}


def is_part(record: dict) -> bool:
    """True when a page of the sheet could not be fully read by the AI (a "part that could not be
    trusted" on the banner); per-field reasons alone are carried by the held passes."""
    return any(w != "fields_missing" for w in record["why"])


def _words(record: dict) -> str:
    said = {
        "partly_read_pages": f"{record['partly_read_pages']} page(s) were read only in part",
        "cut_off_pages": f"{record['cut_off_pages']} page(s) had the AI's answer cut off",
        "timed_out_pages": f"{record['timed_out_pages']} page(s) timed out",
        "failed_pages": f"{record['failed_pages']} page(s) had an unusable or missing AI answer",
        "stopped": "the reader was stopped before it finished",
        "unavailable": "the AI reader was unavailable",
        "fields_missing": f"the AI reading of {record['fields_missing']} field(s) did not come back",
    }
    return "; ".join(said[w] for w in record["why"])


def line(record: dict) -> str:
    """The sentence for the CRS banner and the review notes."""
    return (
        "The AI reading of this datasheet looked incomplete ("
        + _words(record)
        + "); checklist passes that depend on it were held for the engineer."
    )


def with_reader(split: dict, document_id: str) -> dict:
    """The run's split with the reader summary and, when the read looked incomplete, its record."""
    reader = datasheets.latest_reader_summary(document_id)
    if reader:
        split = {**split, "reader": reader}
    record = assess(reader)
    return {**split, "degraded_read": record} if record else split


def item_roles() -> dict[str, frozenset[str]]:
    """{checklist item id: every role the item reads} (its field, both sides of a comparison, the
    inputs of a calculation, a condition role), from the reference data and the local overlay."""
    from . import datasheet_checks as dc
    from .form_reader_fields import _roles_named_in

    rules = dc.load_rules()
    roles = rules["roles"]
    out: dict[str, frozenset[str]] = {}
    for key, entry in (rules.get("checklists") or {}).items():
        if not isinstance(entry, dict):  # the "_about" note
            continue
        for item in [*entry.get("items", []), *dc._local_items(key)]:
            body = {k: v for k, v in item.items() if k not in ("text", "source")}
            named = set(_roles_named_in(body, roles))
            named |= FORMULA_INPUTS.get(
                (item.get("rule") or {}).get("formula"), frozenset()
            )
            # a condition role whose phase is implied by another field reads that field too
            named |= {
                (roles[r].get("implied_by") or {}).get("role")
                for r in list(named)
                if (roles.get(r) or {}).get("implied_by")
            }
            out[item["id"]] = frozenset(named)
    return out


def hold(results: list[dict], document_id: str) -> list[dict]:
    """The checklist results with every pass whose AI reading did not come back held for the
    engineer. A failure, a missing value and every other status keep theirs."""
    summary = datasheets.latest_reader_summary(document_id)
    record = assess(summary)
    if not record:
        return results
    missing = missing_roles(summary)
    page_gap = is_part(record)
    roles_of = item_roles() if missing and not page_gap else {}
    held = []
    for r in results:
        if r["status"] == "COMPLIANT" and r.get("checklist"):
            why = _why_held(r, record, missing, roles_of, page_gap)
            if why:
                r = {
                    **r,
                    "status": "NEEDS_ENGINEER_REVIEW",
                    "detail": HELD.format(why=why),
                }
        held.append(r)
    return held


def _why_held(
    r: dict, record: dict, missing: dict, roles_of: dict, page_gap: bool
) -> str | None:
    if page_gap:
        return _words(
            {**record, "why": [w for w in record["why"] if w != "fields_missing"]}
        )
    needed = roles_of.get(r.get("rule_id")) or frozenset({r.get("role")})
    hit = sorted(needed & missing.keys())
    if not hit:
        return None
    return "; ".join(f"{role}: {', '.join(missing[role])}" for role in hit)
