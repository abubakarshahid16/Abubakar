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
#: A line that calls itself a sheet or a labelled title: where a second type may be named.
_SHEET_WORDS = re.compile(
    r"data[\s\-]*sheet|specification|^\s*(?:document\s+)?title\s*:", re.I
)
#: A line that CITES another document ("Ref. specification: Electric Motors", "Applicable
#: specification: ...", "Refer to SAES-A-004"): it names that document's subject, never a
#: second type of this sheet. A reference word alone is not enough (#1552): the line must
#: cite a document (a specification or standard, or a standard number), and a line that
#: names a data sheet ("APPLICABLE TO: COMPRESSOR DATA SHEET") is never a citation.
_REFERENCE = re.compile(
    r"^\s*(?:ref(?:erence)?s?\b|refer\b|see\b|(?:as\s+)?per\b|in\s+accordance\b"
    r"|according\s+to\b|applicable\b)|\bspecifications?\s*(?:no\.?|number)?\s*:",
    re.I,
)
_CITES_DOCUMENT = re.compile(
    r"(?i:\b(?:specifications?|standards?)\b)|\b[A-Z]{2,}(?:[\s\-]+[A-Z]{1,3})?[\s\-]+\d{2,}"
)
_DATA_SHEET = re.compile(r"data[\s\-]*sheet", re.I)


def _citation(line: str) -> bool:
    """A reference line that cites another document (and names no data sheet)."""
    return bool(
        _REFERENCE.search(line)
        and _CITES_DOCUMENT.search(line)
        and not _DATA_SHEET.search(line)
    )


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


def for_submittal(submittal_id: str) -> list[dict]:
    """The Review note when the submittal's equipment type waits for an engineer
    (NULL, marked). Nothing otherwise, and nothing with the switch off."""
    from .config import settings

    if not settings.equipment_from_title_block_enabled:
        return []
    row = (
        connect()
        .execute(
            "SELECT equipment_type, equipment_type_evidence, confirmed_by"
            " FROM document_classification WHERE document_id = ?",
            (submittal_id,),
        )
        .fetchone()
    )
    if row is None or row["equipment_type"] or row["confirmed_by"]:
        return []
    try:
        evidence = json.loads(row["equipment_type_evidence"] or "null")
    except ValueError:
        return []
    if not isinstance(evidence, dict) or evidence.get("method") != METHOD:
        return []
    seen = evidence.get("types") or []
    detail = (
        "The title block names two different equipment types (" + " / ".join(seen) + ")"
        if evidence.get("reason") == "ambiguous"
        else "The title block names no equipment type"
    )
    return [
        {
            "note": NOTE,
            "standard": "",
            "count": None,
            "detail": (
                f"{detail}, so the equipment type is left empty and the equipment-type "
                "checklist was not chosen. A section heading inside the page never sets it. "
                "Confirm the equipment type on the classification."
            ),
        }
    ]
