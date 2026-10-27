"""Order 261.2: a failed AI reading must never make a verdict more confident.

The datasheet reader asks the AI for each field of the equipment type's form and keeps only what
the code gates accept. When the AI's reading of a field did not come back (the model failed, was
cut off, timed out, answered malformed or unstable, left the field out of its answer, or was
stopped), the conflict the AI would have raised on that field never appears, and the rule
reader's value stands unchallenged (s2, 27 Oct: two 35B models on one Mac, AI facts 68 -> 39,
conflicts 16 -> 4, checklist meets 81 -> 88, the run summary saying nothing).

Two separate things, kept apart on purpose (planner, 22:22):
  * THE HARD RULE, per field, no threshold (`hold`): a checklist item becomes COMPLIANT only when
    the AI reading asked for on its field came back. The reader's own per-field reasons
    (`rejected_fields`, "role: reason") say which fields did not: an item whose field has an
    ERROR reason is held for the engineer, "AI reading missing". It never turns a failure into a
    pass and never lifts a hold.
  * THE BANNER (`assess` / `line`), never a verdict: the read "looked incomplete" when a page
    could not be read (unusable answer, timed out, stopped, unavailable) or, as an internal note
    only, when the agreed share of the AI's facts is low.

NOT a trigger: "more answers refused by the code gates than agreed". A CLEAN relief-valve datasheet read refuses 117
and agrees 58 (the AI always proposes more than it can prove). A refusal for a failed QUOTE is a
gate doing its job; only the reasons in `ERROR_REASONS` say the reading did not come back.
"""

from __future__ import annotations

from . import datasheets

NO_TEXT = "no text on this page"
#: The agreed share of the AI's facts under which the banner says so, as an internal note only
#: (planner first setting; a clean relief-valve sheet reads 0.85, the broken run 0.62, but a clean pump sheet reads
#: 0.53, so this alone never makes a sheet "incomplete").
AGREED_SHARE_FLOOR = 0.75
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
HELD = (
    "Engineer to check: the rule reader found this stated, but the AI reader's reading of "
    "'{role}' did not come back ({reason}), so the pass is not trusted. AI reading missing."
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
    """The banner record for a reader summary, or None when the AI reader was not asked or its
    read looks complete. Counts and reasons only; it never changes a verdict."""
    if not summary or summary.get("engine") in (None, "off"):
        return None
    agreed = int(summary.get("agreed") or 0)
    facts = int(summary.get("facts_written") or 0)
    timed_out = len(summary.get("timed_out") or [])
    # a page left to the code readers because the engine's answer was unusable, ran out of
    # time or was unavailable ("no text on this page" is a fact about the page, not a failure)
    failed = sum(
        1 for why in (summary.get("code_only") or {}).values() if why != NO_TEXT
    )
    why = []
    if failed:
        why.append("failed_pages")
    if timed_out:
        why.append("timed_out")
    if summary.get("stopped"):
        why.append("stopped")
    if summary.get("unavailable"):
        why.append("unavailable")
    if facts and agreed / facts < AGREED_SHARE_FLOOR:
        why.append("low_agreement")
    fields = missing_roles(summary)
    if fields:
        why.append("fields_missing")
    if not why:
        return None
    return {
        "agreed": agreed,
        "facts": facts,
        "timed_out_pages": timed_out,
        "failed_pages": failed,
        "fields_missing": len(fields),
        "why": why,
    }


def is_part(record: dict) -> bool:
    """True when a whole page could not be read (a "part that could not be trusted"); a low agreed
    share or missing fields alone are internal notes (the held passes already carry the reason)."""
    return any(
        w in ("failed_pages", "timed_out", "stopped", "unavailable")
        for w in record["why"]
    )


def _words(record: dict) -> str:
    said = {
        "failed_pages": f"{record['failed_pages']} page(s) had an unusable or missing AI answer",
        "timed_out": f"{record['timed_out_pages']} page(s) timed out",
        "stopped": "the reader was stopped before it finished",
        "unavailable": "the AI reader was unavailable",
        "fields_missing": f"the AI reading of {record['fields_missing']} field(s) did not come back",
        "low_agreement": f"the AI agreed with the rule reader on {record['agreed']} of "
        f"{record['facts']} facts it wrote",
    }
    return "; ".join(said[w] for w in record["why"])


def line(record: dict) -> str:
    """The sentence for the CRS banner and the review notes."""
    return (
        "The AI reading of this datasheet looked incomplete ("
        + _words(record)
        + "); a checklist pass on a field whose AI reading did not come back was held for the "
        "engineer."
    )


def with_reader(split: dict, document_id: str) -> dict:
    """The run's split with the reader summary and, when the read looked incomplete, its record."""
    reader = datasheets.latest_reader_summary(document_id)
    if reader:
        split = {**split, "reader": reader}
    record = assess(reader)
    return {**split, "degraded_read": record} if record else split


def hold(results: list[dict], document_id: str) -> list[dict]:
    """The checklist results with every pass whose field's AI reading did not come back held for
    the engineer. A failure, a missing value and every other status keep theirs."""
    missing = missing_roles(datasheets.latest_reader_summary(document_id))
    if not missing:
        return results
    held = []
    for r in results:
        if (
            r["status"] == "COMPLIANT"
            and r.get("checklist")
            and r.get("role") in missing
        ):
            reason = ", ".join(missing[r["role"]])
            r = {
                **r,
                "status": "NEEDS_ENGINEER_REVIEW",
                "detail": HELD.format(role=r["role"], reason=reason),
            }
        held.append(r)
    return held
