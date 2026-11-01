"""#1474: the document KIND chooses the rule set.

A procedure, specification, contract, transmittal, drawing, FEED document or
standard never gets an equipment datasheet checklist or an equipment-type
"governing standard"; only a datasheet does. The kind is the router's
(`document_kinds`, confirmed or suggested). `unknown` and `needs_engineer` keep
today's behaviour and are marked. A kind only NARROWS what is applied (rule 5):
nothing here adds a standard or reads another document.

Behind `settings.kind_chooses_rules_enabled`, OFF by default: off, every
function here answers "not blocked" and the review is exactly as before.
"""

from __future__ import annotations

from contextvars import ContextVar

from .db import connect

DATASHEET = "datasheet"
_IGNORE: ContextVar[bool] = ContextVar("kind_rules_ignore", default=False)


def _lookup(document_id: str | None) -> tuple[str | None, str | None]:
    if not document_id:
        return None, None
    row = (
        connect()
        .execute(
            "SELECT kind, state FROM document_kinds WHERE document_id = ?",
            (document_id,),
        )
        .fetchone()
    )
    return (None, None) if row is None else (row["kind"], row["state"])


def enabled() -> bool:
    from .config import settings

    return bool(settings.kind_chooses_rules_enabled)


def blocked(document_id: str | None) -> dict | None:
    """`{"kind", "state", "reason"}` when the document's kind is known and is not
    a datasheet (equipment rules are not applied), else None (switch off,
    datasheet, unknown, needs an engineer, or no kind stored)."""
    if not enabled() or _IGNORE.get():
        return None
    kind, state = _lookup(document_id)
    if not kind or kind in (DATASHEET, "unknown"):
        return None
    return {"kind": kind, "state": state, "reason": f"the document is a {kind}"}


def unknown_mark(document_id: str | None) -> str | None:
    """A plain-words mark when the kind is unknown / not decided and the old
    equipment rules therefore still run; None when off, datasheet or known."""
    if not enabled():
        return None
    kind, state = _lookup(document_id)
    if kind == DATASHEET or (kind and kind != "unknown"):
        return None
    return (
        "document kind not decided ("
        + (state or "not routed")
        + "): the equipment rules still apply, as before"
    )


def checklist_not_applied(document_id: str | None) -> str | None:
    b = blocked(document_id)
    return None if b is None else f"datasheet checklist not applied: {b['reason']}"


def standards_exclusion(document_id: str | None) -> str | None:
    b = blocked(document_id)
    return None if b is None else f"chosen for an equipment type; {b['reason']}"


def checklist_note(note: dict | None) -> str | None:
    """The plain-words reason the checklist was not applied, from a run note."""
    return note["checklist"] if note and note["blocked"] else None


def split_part(note: dict | None) -> dict:
    """What the run stores of the note, in `requirement_split`."""
    return {"kind_rules": note} if note else {}


def for_run(document_id: str, classification: dict | None) -> tuple[dict, dict | None]:
    """`(classification, note)` for one review run. A non-datasheet kind: the note
    says, in plain words, what was not applied (checklist, equipment-type
    standards, the equipment type as a chooser). The classification itself is
    left whole: blanking it also switched off the requirement subject gates and
    sent 236 more requirements to "needs another document" on the saved HAZOP
    run (bench, 1 Nov), which widens the review. Unknown kind: unchanged, the
    note marks it. Off or datasheet: unchanged, no note."""
    classification = classification or {}
    b = blocked(document_id)
    if b is None:
        mark = unknown_mark(document_id)
        return classification, ({"blocked": False, "mark": mark} if mark else None)
    used = classification.get("equipment_type")
    return classification, {
        "blocked": True,
        "kind": b["kind"],
        "checklist": checklist_not_applied(document_id),
        "standards": standards_exclusion(document_id),
        "equipment_type": (
            f"equipment type '{used}' not used to choose the checklist or the "
            f"standards: {b['reason']}"
            if used
            else None
        ),
    }


def reading_for(document_id: str, reading: tuple) -> tuple:
    """`applicability._equipment_reading`'s answer; a non-datasheet kind reads
    no equipment (so no governing standard, no required-by-type, no by-type)."""
    return (set(), None, None, reading[3]) if blocked(document_id) else reading


def gate(note: dict | None, evaluate, *args) -> list:
    """The datasheet checks of a run: none for a non-datasheet kind."""
    return [] if note and note["blocked"] else evaluate(*args)


def profile_part(document_id: str, library: list[dict], allowed) -> tuple[dict, tuple]:
    """`(profile, part)` for `applicability.select`. A non-datasheet kind: the
    profile carries no equipment type, and `part` keeps the standards the type
    WOULD have chosen, each with the reason. Unknown kind: unchanged, marked."""
    from . import applicability as ap

    profile = ap._submittal_profile(document_id)
    reason = standards_exclusion(document_id)
    if reason is None:
        return profile, (None, unknown_mark(document_id))
    would = ap._match_attribute(library, profile, "equipment_type", ap.METHOD_EQUIPMENT)
    token = _IGNORE.set(True)
    try:
        would.update(ap.governing_standards(document_id, library, allowed)[0])
    finally:
        _IGNORE.reset(token)
    rows = [
        {
            "standard_document_id": sid,
            "identifier": row.get("identifier"),
            "reason": reason,
        }
        for sid, row in sorted(would.items())
    ]
    return {**profile, "equipment_type": None}, (rows, None)


def attach(check: dict, part: tuple, selected: dict) -> dict:
    """Add `kind_excluded` (what the type chose and nothing else did) or
    `kind_note` (kind undecided) to the standards check of a selection."""
    rows, mark = part
    if rows is not None:
        kept = [r for r in rows if r["standard_document_id"] not in selected]
        check = {**check, "kind_excluded": kept}
    return {**check, "kind_note": mark} if mark else check
