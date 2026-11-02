"""Owner decision, 1 Nov (part of #1478): ONLY the title block sets the equipment type; a section
or panel heading inside the page body never does. When the title block names no equipment type,
or names two different ones, the stored type is NULL, marked "engineer to confirm", and the CRS
review notes say so. Never a guess.

Found on a public pump datasheet: the panel label "MOTOR DATA" (page 1, line 11) was taken as the
sheet heading, so the Motor checklist ran instead of the Centrifugal Pump one.

Switch `settings.equipment_from_title_block_enabled` (OFF = every path unchanged). The title block
is `classification.title_block_lines` (page-1 edge lines and running lines, the document's own name).
Local only; no model, no network, no document text beyond the stored quote on the record.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .db import connect

NOTE = "Equipment type not read from the title block - engineer to confirm"
METHOD = "engineer_to_confirm"
TO_CONFIRM = "equipment type: engineer to confirm"
#: At most this many STANDARDS are kept when no type can choose. Not "all that match": the
#: match is any of the sheet's distinctive words, which most of a library meets. What the limit
#: leaves out is named on the run's notes.
KEEP_LIMIT = 5
KEPT = (
    f"{TO_CONFIRM}; kept for the review because the type could not be used to choose, "
    "not because its scope was checked"
)
LEFT_OUT = f"not checked: engineer to confirm (only the first {KEEP_LIMIT} standards by match are kept)"
#: Every match, however deep: the ranked standards are counted, never a page of chunks.
_ALL_MATCHES = 10_000_000
#: A line that calls itself a sheet or a labelled title: where a second type may be named.
_SHEET_WORDS = re.compile(
    r"data[\s\-]*sheet|specification|^\s*(?:document\s+)?title\s*:", re.I
)
#: A title line that starts with a reference word, or is a "specification:" label ("Ref.
#: specification: Electric Motors", "Applicable specification: ..."). It cites another
#: document, so it names that document's subject, never a second type of this sheet -
#: unless it names a data sheet (#1552): "APPLICABLE TO: COMPRESSOR DATA SHEET" and
#: "Ref. API 610 Motor data sheet" are a second type.
_REFERENCE = re.compile(
    r"^\s*(?:ref(?:erence)?s?\b|refer\b|see\b|(?:as\s+)?per\b|in\s+accordance\b"
    r"|according\s+to\b|applicable\b)|\bspecifications?\s*(?:no\.?|number)?\s*:",
    re.I,
)
_DATA_SHEET = re.compile(r"data[\s\-]*sheet", re.I)


def _citation(line: str) -> bool:
    """A reference line that names no data sheet. Only lines `_SHEET_WORDS` matched get
    here, so what is dropped is a reference line naming a specification."""
    return bool(_REFERENCE.search(line)) and not _DATA_SHEET.search(line)


def _sheet_line(line: str) -> bool:
    """A title line that may name a second type of THIS sheet."""
    return bool(_SHEET_WORDS.search(line)) and not _citation(line)


@dataclass
class TitleReading:
    """What the title block says: the evidence of the ONE type it names, or the
    reason it names none (`reason` = "none" | "ambiguous", with the types seen)."""

    evidence: object | None = None
    reason: str | None = None
    types: list[str] = field(default_factory=list)


def _same_family(a: str, b: str) -> bool:
    """One name is the other's words ("pump" in "centrifugal pump"): one type."""
    a, b = " ".join(a.lower().split()), " ".join(b.lower().split())
    if not a or not b:
        return False
    return bool(
        re.search(rf"\b{re.escape(a)}\b", b) or re.search(rf"\b{re.escape(b)}\b", a)
    )


def _other_types_in(lines, label: str) -> list[str]:
    """Equipment types of the vocabulary that a title line naming `label` ALSO names
    ("PUMP AND MOTOR DATA SHEET"), other than `label`'s own family."""
    from . import subject_scope

    vocab = subject_scope.vocabulary()
    found: list[str] = []
    for _page, line in lines:
        folded = subject_scope._fold(line)
        for phrase, types in vocab.phrases.items():
            if len(types) != 1 or not re.search(rf"\b{re.escape(phrase)}\b", folded):
                continue
            (name,) = types
            if vocab.kind.get(name) != subject_scope.EQUIPMENT or _same_family(
                name, label
            ):
                continue
            if name in vocab.phrases.get(subject_scope._fold(label), ()):
                continue  # the vocabulary itself spells `label` as this type
            if not any(_same_family(name, seen) for seen in found):
                found.append(name)
    return found


def _vocabulary_types(lines) -> list[str]:
    """Distinct types of the vocabulary that title lines name as their whole subject
    (`subject_scope.title_equipment` gives up on two; this says which two)."""
    from . import subject_scope

    vocab = subject_scope.vocabulary()
    out: list[str] = []
    for _page, line in lines:
        phrase = subject_scope._titled_phrase(line, vocab)
        for name in sorted(vocab.phrases.get(phrase, ())) if phrase else ():
            if vocab.kind.get(name) == subject_scope.EQUIPMENT and not any(
                _same_family(name, seen) for seen in out
            ):
                out.append(name)
    return out


def read_title_block(pages) -> TitleReading:
    """The one equipment type the title block names, or why it names none."""
    from . import classification

    lines = classification.title_block_lines(pages)
    evidence = classification.suggest_equipment_type_from_title(lines)
    if evidence is None:
        sheet = [(p, ln) for p, ln in lines if _sheet_line(ln)]
        named = _vocabulary_types(lines) or _other_types_in(sheet, "")
        if len(named) > 1:
            return TitleReading(None, "ambiguous", [n.title() for n in named])
        return TitleReading(None, "none", [])
    # a title line that names the type AND another one, or a second title line
    # naming another type, is ambiguous - never the first
    quote = " ".join(evidence.quote.lower().split())
    titled = [
        (p, ln)
        for p, ln in lines
        if quote in " ".join(ln.lower().split()) or _sheet_line(ln)
    ]
    others = _other_types_in(titled, evidence.equipment_type)
    if others:
        return TitleReading(
            None, "ambiguous", [evidence.equipment_type, *[o.title() for o in others]]
        )
    return TitleReading(evidence, None, [evidence.equipment_type])


def decide(conn, document_id: str, pages, kind_on: bool, role):
    """The evidence `classify_equipment_type_for_submittal` stores, or None (nothing stored).
    Switch on: ONLY the title block names the type; none or two types there store NULL, marked for
    the engineer (when the document may be a datasheet at all). Switch off: the title block, then
    the body fallback, as before."""
    from . import classification as c
    from .config import settings

    if settings.equipment_from_title_block_enabled:
        reading = read_title_block(pages)
        if reading.evidence is None and c._body_fallback_ok(
            kind_on, pages, document_id, role
        ):
            store_to_confirm(document_id, reading)
        return reading.evidence
    evidence = c.suggest_equipment_type_from_title(c.title_block_lines(pages))
    if evidence is None and not c._body_fallback_ok(kind_on, pages, document_id, role):
        # #1474: a body sentence naming equipment does not make a procedure,
        # a specification or a contract an equipment datasheet.
        return None
    return evidence or c._equipment_from_body(conn, document_id, kind_on)


def store_to_confirm(document_id: str, reading: TitleReading) -> None:
    """Equipment type NULL, marked for the engineer. The caller has already
    checked that the record is not confirmed."""
    from . import classification

    conn = connect()
    old = conn.execute(
        "SELECT equipment_type FROM document_classification WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    evidence = {
        "page": None,
        "quote": None,
        "method": METHOD,
        "reason": reading.reason,
        "types": reading.types,
        "confidence": None,
        "classifier_version": classification.EQUIPMENT_TYPE_CLASSIFIER_VERSION,
        "classified_at": classification._now(),
    }
    with conn:
        conn.execute(
            "UPDATE document_classification SET equipment_type = NULL,"
            " equipment_type_evidence = ? WHERE document_id = ?",
            (json.dumps(evidence), document_id),
        )
    if old is not None and old["equipment_type"] is not None:
        classification._audit_equipment_type_change(
            document_id,
            old_value=old["equipment_type"],
            evidence=classification.EquipmentTypeEvidence(
                equipment_type="engineer to confirm",
                page=None,
                quote="",
                method=METHOD,
                confidence=0.0,
                classifier_version=evidence["classifier_version"],
                classified_at=evidence["classified_at"],
            ),
            classified_by="equipment_type_classifier",
        )


def _marked(document_id: str) -> dict | None:
    """The stored "engineer to confirm" evidence: switch on, type NULL, nobody confirmed.
    None on a document whose CRS carries no equipment type at all (#1580, a procedure)."""
    from . import procedure_crs
    from .config import settings

    if not settings.equipment_from_title_block_enabled:
        return None
    if procedure_crs.no_equipment(document_id):
        return None
    row = (
        connect()
        .execute(
            "SELECT equipment_type, equipment_type_evidence, confirmed_by"
            " FROM document_classification WHERE document_id = ?",
            (document_id,),
        )
        .fetchone()
    )
    if row is None or row["equipment_type"] or row["confirmed_by"]:
        return None
    try:
        evidence = json.loads(row["equipment_type_evidence"] or "null")
    except ValueError:
        return None
    return (
        evidence
        if isinstance(evidence, dict) and evidence.get("method") == METHOD
        else None
    )


def keep_without_type(
    document_id: str,
    selected: dict,
    not_run: str | None,
    library: list,
    allowed: frozenset,
) -> str | None:
    """The standards step with no equipment term: the sentence for "why the scope clauses were
    not checked"; `not_run` unchanged when the type is not waiting for the engineer.

    The scope question compares a standard's scope with a type, so it has no subject here and
    no model is asked; no type is taken from the body, stored or proposed (owner, 1 Nov). What
    remains is what the sheet's own words match (`applicability._match_semantic`), ranked by
    standard. The first `KEEP_LIMIT` standards are kept and say why, so the rules are reviewed
    instead of a silent 0; the rest are recorded as left out, and `for_submittal` names them.
    A standard another route already found keeps that reason and takes no place."""
    if _marked(document_id) is None:
        return not_run
    from . import applicability

    matched = applicability._match_semantic(
        document_id, library, allowed, limit=_ALL_MATCHES
    )
    ranked = [
        sid
        for sid, row in matched.items()
        if selected.get(sid, row)["method"] == row["method"]
    ]
    for place, sid in enumerate(ranked):
        row = selected.setdefault(sid, dict(matched[sid]))
        row["satisfies_reference"] = False
        if place < KEEP_LIMIT:
            row["kept_without_type"] = True
        row["reason"] = f"{row['reason']}; {KEPT if place < KEEP_LIMIT else LEFT_OUT}"
    return f"scope clauses not checked: {TO_CONFIRM}"


def unknown_type_words(document_id: str) -> dict:
    """The review's words when no rule asked the sheet for a value and the type waits for
    the engineer (`comparison.plain_reason`, `_insufficient_reason`). Empty otherwise."""
    if _marked(document_id) is None:
        return {}
    why = (
        "equipment type is unknown (engineer to confirm), so which standards apply "
        "is not settled, and no rule checked asked this datasheet for a value"
    )
    return {"unknown_type_plain": f"The {why}.", "unknown_type_technical": f"the {why}"}


def equipment_sources(sources: tuple) -> tuple:
    """The sources of the equipment reading (`subject_scope.read_equipment`). Switch on: the
    stored type alone, which is the title block's answer. A stored title may be a section
    heading from an older ingest, and a body field ("Type: ... motor") may be about a part."""
    from .config import settings

    if not settings.equipment_from_title_block_enabled:
        return sources
    return tuple(s for s in sources if s[0] == "classification")


def _run_rows(review_run_id: str, allowed: frozenset) -> list:
    """This run's standards that the words matched, by name; only those the caller may read."""
    rows = (
        connect()
        .execute(
            "SELECT a.standard_document_id AS id, a.selection_reason AS reason, a.included,"
            " c.document_number, d.filename FROM review_applicable_standards a"
            " JOIN documents d ON d.id = a.standard_document_id"
            " LEFT JOIN document_classification c ON c.document_id = a.standard_document_id"
            " WHERE a.review_run_id = ? ORDER BY a.standard_document_id",
            (review_run_id,),
        )
        .fetchall()
    )
    return [r for r in rows if r["id"] in allowed]


def _limit_notes(review_run_id: str, allowed: frozenset) -> tuple[str, list[dict]]:
    """(the count sentence for the main note, the note naming what the limit left out)."""
    rows = _run_rows(review_run_id, allowed)
    kept = [r for r in rows if r["included"] and KEPT in r["reason"]]
    left = [r for r in rows if not r["included"] and LEFT_OUT in r["reason"]]
    total = len(kept) + len(left)
    where = "in the library this reviewer may read"
    if not total:
        return f" No standard {where} matched the sheet's own words.", []
    count = (
        f" Kept: {len(kept)} of the {total} standards that matched {where} "
        f"(limit {KEEP_LIMIT} standards)."
    )
    if not left:
        return count, []
    names = ", ".join(r["document_number"] or r["filename"] for r in left)
    return count, [
        {
            "note": f"{len(left)} more matched and were not checked: engineer to confirm",
            "standard": "",
            "count": len(left),
            "detail": f"Matched the sheet's own words {where}, over the limit of "
            f"{KEEP_LIMIT} standards: {names}.",
        }
    ]


def for_submittal(
    submittal_id: str,
    review_run_id: str | None = None,
    allowed: frozenset = frozenset(),
) -> list[dict]:
    """The Review notes when the submittal's equipment type waits for an engineer (NULL,
    marked): with a run, how many standards were kept and which the limit left out, for the
    standards in `allowed`. Nothing otherwise, and nothing with the switch off."""
    evidence = _marked(submittal_id)
    if evidence is None:
        return []
    seen = evidence.get("types") or []
    detail = (
        "The title block names two different equipment types (" + " / ".join(seen) + ")"
        if evidence.get("reason") == "ambiguous"
        else "The title block names no equipment type"
    )
    count, left_out = (
        _limit_notes(review_run_id, allowed) if review_run_id else ("", [])
    )
    return [
        {
            "note": NOTE,
            "standard": "",
            "count": None,
            "detail": (
                f"{detail}, so the equipment type is left empty and the equipment-type "
                "checklist was not chosen. A section heading inside the page never sets it. "
                "Any standard kept for this review was matched by the sheet's own words, not by a "
                f"scope check.{count} Confirm the equipment type on the classification."
            ),
        },
        *left_out,
    ]
