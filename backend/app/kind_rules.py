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

import json
from contextlib import contextmanager
from contextvars import ContextVar

from .db import connect

DATASHEET = "datasheet"
_IGNORE: ContextVar[bool] = ContextVar("kind_rules_ignore", default=False)
_NO_TYPE: ContextVar[bool] = ContextVar("kind_rules_no_type", default=False)


@contextmanager
def reading_no_type(on: bool):
    """While `on`, `reading_for` reads no equipment: the CRS of a non-datasheet kind
    (`procedure_crs`), whatever `kind_chooses_rules_enabled` says. Selection is untouched."""
    token = _NO_TYPE.set(on)
    try:
        yield
    finally:
        _NO_TYPE.reset(token)


def _lookup(document_id: str | None) -> tuple[str | None, str | None, bool]:
    """`(kind, state, guess)` the router's table holds; `guess` is the
    classifier's own flag in the stored evidence."""
    if not document_id:
        return None, None, False
    row = (
        connect()
        .execute(
            "SELECT kind, state, evidence FROM document_kinds WHERE document_id = ?",
            (document_id,),
        )
        .fetchone()
    )
    if row is None:
        return None, None, False
    try:
        guess = bool(json.loads(row["evidence"] or "{}").get("guess"))
    except (TypeError, ValueError, AttributeError):
        guess = False
    return row["kind"], row["state"], guess


def enabled() -> bool:
    from .config import settings

    return bool(settings.kind_chooses_rules_enabled)


def _known(kind: str | None) -> bool:
    return bool(kind) and kind not in (DATASHEET, "unknown")


def not_a_datasheet(document_id: str | None) -> bool:
    """The document's kind is known and is not a datasheet (confirmed, or a
    suggestion that is not a guess), whatever `kind_chooses_rules_enabled` says."""
    kind, state, guess = _lookup(document_id)
    return _known(kind) and not (guess and state != "confirmed")


def blocked(document_id: str | None) -> dict | None:
    """`{"kind", "state", "reason"}` when the document's kind is known, is not a
    datasheet, and is either confirmed by an engineer or a suggestion the
    classifier did not mark as a guess. Else None (switch off, datasheet,
    unknown, needs an engineer, no kind stored, or a guessed kind)."""
    if not enabled() or _IGNORE.get():
        return None
    kind, state, guess = _lookup(document_id)
    if not _known(kind) or (guess and state != "confirmed"):
        return None
    return {"kind": kind, "state": state, "reason": f"the document is a {kind}"}


def unknown_mark(document_id: str | None) -> str | None:
    """A plain-words mark when the equipment rules still run because the kind is
    not decided or is only a guess; None when off, datasheet or decided."""
    if not enabled() or blocked(document_id) or _IGNORE.get():
        return None
    kind, state, guess = _lookup(document_id)
    if kind == DATASHEET:
        return None
    if _known(kind) and guess:
        return "document kind is a guess; datasheet rules kept"
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


def split_part(note: dict | None, checklist: dict | None = None) -> dict:
    """What the run stores of the note, in `requirement_split`."""
    return {
        **({"checklist": checklist} if checklist else {}),
        **({"kind_rules": note} if note else {}),
    }


def for_run(document_id: str, allowed, applied: list[str]) -> dict | None:
    """The note of one review run, in plain words: what the document's kind
    chose. `applied` = the standards the run applies. Blocked: what was not
    applied (checklist; the equipment-type standards the run did not use). The
    equipment type still gates requirement subjects: blanking it switched those
    gates off and sent 236 more requirements to "needs another document" on the
    saved HAZOP run (bench, 1 Nov). Unknown or guessed kind: marked, nothing
    changes. Off or datasheet: None."""
    b = blocked(document_id)
    if b is None:
        mark = unknown_mark(document_id)
        return {"blocked": False, "mark": mark} if mark else None
    unused = [
        row.get("identifier") or row["standard_document_id"]
        for row in profile(document_id, allowed)[1][0]
        if row["standard_document_id"] not in applied
    ]
    kind, state = b["kind"], b["state"] or "suggested"
    return {
        "blocked": True,
        "kind": kind,
        "checklist": (
            f"Datasheet checklist not applied: the document is a {kind} ({state})."
        ),
        "standards": (
            f"{len(unused)} standard(s) chosen for an equipment type were not "
            f"used: {', '.join(unused[:8])}, because the document is a {kind}."
            if unused
            else None
        ),
        "equipment_type": (
            "The equipment type still decides which requirements apply by "
            "subject; it was not used to choose the checklist or the standards."
        ),
    }


def lines(outcome: dict | None) -> list[dict]:
    """The note's plain lines for the run summary and the CRS review notes
    (`absence.unchecked_parts`, detail lines: not counted as unchecked parts)."""
    note = ((outcome or {}).get("requirement_split") or {}).get("kind_rules") or {}
    texts = (
        [note.get(k) for k in ("checklist", "standards", "equipment_type")]
        if note.get("blocked")
        else [note.get("mark")]
    )
    return [
        {"part": "document_kind", "line": t, "detail": True, "note": "Document kind"}
        for t in texts
        if t
    ]


def reading_for(document_id: str, equipment: set, source, doubt, facts) -> tuple:
    """`applicability._equipment_reading`'s answer; a non-datasheet kind reads
    no equipment (so no governing standard, no required-by-type, no by-type)."""
    if _NO_TYPE.get():
        return set(), None, None, facts
    if blocked(document_id):
        return set(), None, None, facts
    return equipment, source, doubt, facts


def unknown_type_words(document_id: str) -> dict:
    """`comparison`'s door to `equipment_title_block.unknown_type_words`."""
    from . import equipment_title_block

    return equipment_title_block.unknown_type_words(document_id)


def gate(note: dict | None, scope, *args) -> list:
    """The datasheet checks of a run: none for a non-datasheet kind."""
    return [] if note and note["blocked"] else scope.evaluate(*args)


def profile(document_id: str, allowed) -> tuple[dict, tuple]:
    """`(profile, part)` for `applicability.select`. A non-datasheet kind: the
    profile carries no equipment type, and `part` keeps the standards the type
    WOULD have chosen, each with the reason. Unknown kind: unchanged, marked."""
    from . import applicability as ap

    profile = ap._submittal_profile(document_id)
    reason = standards_exclusion(document_id)
    if reason is None:
        return profile, (None, unknown_mark(document_id))
    library = ap._library(allowed)
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
