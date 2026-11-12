"""The paper's NAME in every review and CRS sentence, and the sentence that says what was NOT checked (K2, order 13).

ONE home. A sentence of a review or a CRS names the paper by its DECIDED kind ("this contract", "this procedure", "this
transmittal", "this datasheet"; "document" when the kind is unknown), never always "datasheet". The kind is the engineer's
confirmed kind when there is one, else the code's reading of the cover (`paper_kind.decide_paper_kind`, a pure reading); a
datasheet, and a paper whose kind cannot be read, keep the words they always had.

`not_checked_sentence` is the ONE plain sentence a review that checked nothing of a paper carries (no checklist held for its
kind, no requirement asked of it): it says what was not checked and why, and says that silence is not acceptance
(CLAUDE.md rule 4: "not mentioned" is never "compliant"). Words and a kind only: no document text, no file name.

Reads only; no model, no network.
"""

from __future__ import annotations

import re

from . import kind_review_table, paper_kind

DATASHEET = "datasheet"
UNKNOWN_NOUN = "document"
#: kind -> the noun a sentence uses. A kind outside the table is a "document".
NOUNS = {
    "datasheet": "datasheet",
    "procedure": "procedure",
    "contract": "contract",
    "transmittal": "transmittal",
    "calculation": "calculation",
    "specification": "specification",
    "drawing": "drawing",
    "test_record": "test record",
}


def noun_of_kind(kind: str | None) -> str:
    """The noun for a decided kind; "document" for an unknown or other kind."""
    return NOUNS.get(str(kind or "").strip().lower().replace(" ", "_"), UNKNOWN_NOUN)


def decided_kind(document_id: str) -> str | None:
    """The kind of a stored paper, or None when none can be read: an engineer's confirmed kind, else the cover's reading.
    A kind that is only a guess still names the paper (the sentence does not claim more than the noun)."""
    from . import doc_router, document_kind
    from .db import connect

    stored = document_kind.stored_kind(document_id)
    if stored is not None and stored[1] == doc_router.STATE_CONFIRMED and stored[0]:
        return paper_kind.to_paper_kind(stored[0])
    pages = [
        dict(r)
        for r in connect().execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (document_id,),
        )
    ]
    if not pages:
        return None
    got = paper_kind.decide_paper_kind(pages)
    return None if got.source_kind == "unknown" else got.paper_kind


def noun_of_document(document_id: str) -> str:
    """The noun for a stored paper (`decided_kind`)."""
    return noun_of_kind(decided_kind(document_id))


def is_datasheet_like(kind: str | None) -> bool:
    """A datasheet, or a paper whose kind is not known: the reviews and the CRS keep their older behaviour for them."""
    return not kind or str(kind).strip().lower() == DATASHEET


def not_checked_sentence(kind: str | None) -> str | None:
    """The one plain sentence for a review that asked NO requirement of a paper of this kind, or None for a datasheet or an
    unknown kind (their own sentences stay). Says what was not checked and why; silence is not acceptance."""
    if is_datasheet_like(kind):
        return None
    noun = noun_of_kind(kind)
    row = kind_review_table.row(kind)
    if row["review"] == "completeness":
        return (
            f"This {noun} is checked only against the library (documents listed against documents held); "
            "nothing else in it was checked."
        )
    if kind_review_table.checklist_ending(kind) is None:
        why = f"No {noun} checklist is held, so no point of this {noun} was checked"
    else:
        why = f"No requirement of an applicable standard asks this {noun} for a value, so nothing in it was compared"
    return f"{why}; that does not mean the {noun} is acceptable."


HELD = "NEEDS_ENGINEER_REVIEW"
NOTE_NOT_CHECKED = "Not checked"
NOTE_HELD = "Findings held for an engineer"


def held_sentence(held: int, rows: int) -> str:
    """The count of findings held for an engineer, with its boundary (whose findings it counts)."""
    return (
        f"{held} finding{'s' if held != 1 else ''} of this review run were held for an engineer (needs engineer review) "
        f"and are counted here, not listed as rows; this CRS has {rows} row{'s' if rows != 1 else ''}. "
        "Counted over this run's own findings only."
    )


def crs_meta(
    meta: dict,
    document_id: str,
    outcome: dict | None,
    findings: list[dict],
    rows: list[dict],
) -> dict:
    """The CRS meta of a run on a paper that is NOT a datasheet (a datasheet's CRS is unchanged: bench-proven): the quality export
    (one row per problem, a page or its reason, comments cut between words), a Review notes line that says what was NOT checked
    and why (never a silent empty CRS), and the count of findings held for an engineer with its boundary."""
    kind = decided_kind(document_id)
    if is_datasheet_like(kind):
        return meta
    comp = (outcome or {}).get("completeness") or {}
    sentence = comp.get("not_checked_plain") or (
        not_checked_sentence(kind) if comp.get("fields_required") == 0 else None
    )
    notes = list(meta.get("review_notes") or [])
    if sentence:
        notes.append(
            {
                "note": NOTE_NOT_CHECKED,
                "standard": "",
                "count": None,
                "detail": sentence,
            }
        )
    held = sum(1 for f in findings if f.get("compliance_status") == HELD)
    if held:
        notes.append(
            {
                "note": NOTE_HELD,
                "standard": "",
                "count": held,
                "detail": held_sentence(held, len(rows)),
            }
        )
    return {**meta, "review_notes": notes, "export_quality": True}


_WORD = re.compile(r"\bdatasheet\b", re.I)


def _swap(text: str, noun: str) -> str:
    return _WORD.sub(
        lambda m: noun.capitalize() if m.group(0)[0].isupper() else noun, text
    )


def in_noun(thing, completeness: dict | None):
    """The paper's noun in the review's sentences (K2): a run that recorded a decided kind other than a datasheet reads "contract",
    "procedure" ... where the sentences were written "datasheet", and a review that asked nothing of the paper says in one plain
    sentence what was not checked and why. Takes a reason string or a recommendation dict (its "reason" and "details"); a datasheet,
    an unknown kind and a run from before this change come back as they were."""
    noun = noun_in(completeness)
    if isinstance(thing, dict):
        return {
            **thing,
            **{
                k: in_noun(thing[k], completeness)
                for k in ("reason", "details")
                if isinstance(thing.get(k), str)
            },
        }
    if noun == DATASHEET or not isinstance(thing, str):
        return thing
    said = _swap(thing, noun)
    asked_nothing = (
        f"No applicable standard asks this {noun} for a value that was checked."
    )
    plain = (completeness or {}).get("not_checked_plain")
    return said.replace(asked_nothing, plain) if plain else said


def noun_in(completeness: dict | None) -> str:
    """The paper's noun in a sentence of the review: the run's recorded one, else "datasheet" (a run of a datasheet records none)."""
    return str((completeness or {}).get("paper_noun") or DATASHEET)


def run_words(document_id: str, required: int) -> dict:
    """What a run records about the paper's kind in its completeness: nothing for a datasheet or an unknown kind (its record stays
    as it was); else the noun, and, when no requirement was asked of it, the plain not-checked sentence."""
    kind = decided_kind(document_id)
    if is_datasheet_like(kind):
        return {}
    out = {"paper_noun": noun_of_kind(kind)}
    if not required:
        out["not_checked_plain"] = not_checked_sentence(kind)
    return out
