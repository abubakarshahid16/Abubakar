"""What a requirement is ABOUT, and whether it applies to this submittal (#453).

A standard holds clauses written for steam-turbine casings, for piping, for
relief valves. The review used to apply all of them to every submittal, so a
gas-service relief valve was checked against steam-turbine casing relief
(SAES-J-600 8.7, 8.8, 8.9.3) and a laboratory test clause on relieving
temperature. A requirement now becomes a check only when its SUBJECT fits the
submittal's equipment, or it has no specific subject.

GENERIC: nothing here names a standard, a clause or a material. The equipment
and component types, and the spellings that mean each, are ONE data file,
`reference/equipment_vocabulary.json`. Editing the file changes the result on
the next run, with no code change.

THE RULES
  * A requirement's subject is read from its OWN WORDING first: the equipment
    types named before its "shall" (its grammatical subject, not everything it
    mentions in passing). If that names none, from the nearest
    HEADING (its own section, then the sections of its parent clauses) that
    names one. If neither does, it is GENERAL and is always a check.
  * A COMPONENT (piping, flange, bolting) is not an equipment subject: every
    kind of equipment has them, so a clause about a flange never excludes.
  * A submittal's equipment is read from, in order, its classification's
    equipment type, its title, and its equipment-describing fields (the first
    that names an equipment type). If none does, the submittal's equipment is
    UNKNOWN and every requirement is kept: nothing is hidden when unsure.
  * A spelling listed under two types matches both ("valve"), so an unclear
    subject is kept.
  * A requirement about a different equipment type is NOT dropped silently:
    it is counted, grouped by subject, and shown on the run.

Pure functions over dicts, plus one function (`heading_sections`) that reads
the standards' section headings.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from . import numparse

VOCABULARY_PATH = Path(__file__).parent / "reference" / "equipment_vocabulary.json"

EQUIPMENT = "equipment"
COMPONENT = "component"


class Vocabulary:
    """Compiled from the JSON file: phrase -> the types it can mean."""

    def __init__(self, data: dict) -> None:
        self.kind: dict[str, str] = {}
        self.phrases: dict[str, set[str]] = {}
        for name, entry in (data.get("types") or {}).items():
            canonical = _fold(name)
            self.kind[canonical] = (entry or {}).get("kind", EQUIPMENT)
            for spelling in [name, *((entry or {}).get("synonyms") or ())]:
                folded = _fold(spelling)
                if folded:
                    self.phrases.setdefault(folded, set()).add(canonical)
                    # THE PLURAL RULE: "PZVs", "rupture disks" and "pumps"
                    # mean what the singular means, so the file lists a
                    # spelling once. A spelling already ending in s is left.
                    if not folded.endswith("s"):
                        self.phrases.setdefault(folded + "s", set()).add(canonical)
        ordered = sorted(self.phrases, key=len, reverse=True)
        self.pattern = (re.compile(r"(?<![a-z0-9])(?:" + "|".join(
            re.escape(p) for p in ordered) + r")(?![a-z0-9])") if ordered else None)
        self.field_labels = frozenset(
            _fold(label) for label in data.get("submittal_field_labels") or ())

    def types_in(self, text: object) -> set[str]:
        """Every type the text names (longest spelling wins at a position)."""
        if self.pattern is None:
            return set()
        found: set[str] = set()
        for match in self.pattern.finditer(_fold(text)):
            found |= self.phrases[match.group(0)]
        return found

    def equipment_in(self, text: object) -> set[str]:
        return {t for t in self.types_in(text) if self.kind.get(t) == EQUIPMENT}


def _fold(text: object) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", numparse.fold(text or "")).strip())


@lru_cache(maxsize=8)
def _load(path: str, mtime: float) -> Vocabulary:
    return Vocabulary(json.loads(Path(path).read_text(encoding="utf-8")))


def vocabulary(path: Path | str | None = None) -> Vocabulary:
    """The vocabulary, re-read when the file changes."""
    target = Path(path or VOCABULARY_PATH)
    return _load(str(target), target.stat().st_mtime)


# ---------------------------------------------------------------- the submittal

def submittal_equipment(classification: dict | None, facts: list[dict], vocab: Vocabulary
                        ) -> tuple[set[str], str | None]:
    """(equipment types, where they were read), or (empty, None) when unknown."""
    classification = classification or {}
    sources = (
        ("classification", classification.get("equipment_type")),
        ("title", classification.get("title")),
        ("fields", " ; ".join(
            str(f.get("field_value") or f.get("raw_value") or "")
            for f in facts
            if not f.get("is_blank")
            and _fold(f.get("field_label") or f.get("field_name")) in vocab.field_labels)),
    )
    for source, text in sources:
        found = vocab.equipment_in(text)
        if found:
            return found, source
    return set(), None


# ----------------------------------------------------------------- the clause

def heading_sections(standard_ids: list[str]) -> dict[str, dict[str, str]]:
    """{standard id: {clause number: section heading}} from the chunks."""
    from .db import connect
    from .standards import clause_number

    out: dict[str, dict[str, str]] = {sid: {} for sid in standard_ids}
    if not standard_ids:
        return out
    marks = ",".join("?" for _ in standard_ids)
    for row in connect().execute(
            f"SELECT DISTINCT document_id, section FROM chunks WHERE document_id IN ({marks})"
            " AND section IS NOT NULL", list(standard_ids)):
        number = clause_number(row["section"])
        if number:
            out[row["document_id"]].setdefault(number, row["section"])
    return out


_MODAL = re.compile(r"\b(?:shall|must|should|may|will|needs? to|is to|are to|is required|are required)\b",
                    re.IGNORECASE)


def _ancestors(clause: str | None) -> list[str]:
    parts = (clause or "").split(".")
    return [".".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)]


def requirement_subject(requirement: dict, headings: dict[str, str], vocab: Vocabulary
                        ) -> tuple[set[str], str]:
    """(equipment types it is about, where that was read: wording | heading |
    none). An empty set is GENERAL."""
    # THE GRAMMATICAL SUBJECT: what comes before the first "shall" / "must".
    # "Inlet piping shall be sloped back to the vessel" is about piping, not
    # about the vessel it mentions; "The steam turbine casing relief device
    # shall ..." is about a steam turbine. A sentence with no such verb (a
    # table line) is read whole.
    text = str(requirement.get("requirement_text") or "")
    verb = _MODAL.search(text)
    own = vocab.equipment_in(text[:verb.start()] if verb else text)
    if own:
        return own, "wording"
    chain = [requirement.get("chunk_section")]
    clause = requirement.get("clause")
    if clause:
        chain.append(headings.get(clause))
        chain.extend(headings.get(a) for a in _ancestors(clause))
    for section in chain:
        found = vocab.equipment_in(section)
        if found:
            return found, "heading"
    return set(), "none"


# ------------------------------------------------------------------ the gate

def gate(requirements: list[dict], *, classification: dict | None, facts: list[dict],
         headings_by_standard: dict[str, dict[str, str]] | None = None,
         standard_names: dict[str, str] | None = None,
         vocab: Vocabulary | None = None) -> dict:
    """Split `requirements` into what the review checks and what does not apply.

    Returns {"kept": [...], "not_applied": [one grouped line per subject],
    "summary": {...counts...}}. Order of `kept` is the order given.
    """
    vocab = vocab or vocabulary()
    equipment, source = submittal_equipment(classification, facts, vocab)
    headings_by_standard = headings_by_standard or {}
    kept: list[dict] = []
    summary = {"submittal_equipment": sorted(equipment), "equipment_source": source,
               "checked_general": 0, "checked_matching": 0,
               "kept_equipment_unknown": 0, "not_applied": 0}
    groups: dict[str, dict] = {}
    not_applied_items: list[dict] = []
    for requirement in requirements:
        subject, _where = requirement_subject(
            requirement, headings_by_standard.get(requirement.get("standard_document_id"), {}),
            vocab)
        if not subject:
            summary["checked_general"] += 1
            kept.append(requirement)
        elif not equipment:
            summary["kept_equipment_unknown"] += 1
            kept.append(requirement)
        elif subject & equipment:
            summary["checked_matching"] += 1
            kept.append(requirement)
        else:
            summary["not_applied"] += 1
            label = " / ".join(sorted(subject))
            not_applied_items.append({
                "requirement": requirement, "code": "other_equipment",
                "detail": f"about {label}, this submittal is {', '.join(sorted(equipment))}"})
            entry = groups.setdefault(label, {"subject": label, "count": 0, "standards": {}})
            entry["count"] += 1
            sid = requirement.get("standard_document_id") or ""
            standard = entry["standards"].setdefault(sid, {
                "standard_document_id": sid,
                "standard_name": (standard_names or {}).get(sid) or sid,
                "count": 0, "clauses": []})
            standard["count"] += 1
            clause = requirement.get("clause")
            if clause and clause not in standard["clauses"] and len(standard["clauses"]) < 8:
                standard["clauses"].append(clause)
    this_is = ", ".join(sorted(equipment))
    lines = []
    for entry in groups.values():
        standards = sorted(entry["standards"].values(), key=lambda s: -s["count"])
        lines.append({
            "subject": entry["subject"], "submittal_equipment": this_is,
            "count": entry["count"],
            "line": (f"{entry['count']} requirement{'s' if entry['count'] != 1 else ''} not applied: "
                     f"they are about {entry['subject']}, this submittal is {this_is}"),
            "standards": standards})
    lines.sort(key=lambda l: (-l["count"], l["subject"]))
    return {"kept": kept, "not_applied": lines, "summary": summary,
            # One item per requirement that does not apply, with its reason (#678).
            "not_applied_items": not_applied_items}


# ------------------------------------------------------- materials standards

def materials_gate(requirements: list[dict], *, facts: list[dict], standard_labels: dict[str, str],
                   is_materials_standard) -> dict:
    """#725 F5: a MATERIALS standard (NACE MR0175 / ISO 15156 ...) applies only
    to the datasheet's MATERIAL fields.

    Material fields are chosen by the one role test that already exists
    (`conditions._candidate_facts`, a stated material, never a measured
    quantity). A materials standard's requirement does not apply when the
    datasheet states no material at all, or when it is a table row whose row
    label (an alloy, a grade) is not a material any of those fields states.
    Its sentences stay checks while a material is stated. Every other
    standard passes untouched. Returns {"kept", "items"}; each item carries
    the reason code `not_material_field` and the detail."""
    from . import conditions

    materials = [f for f in conditions._candidate_facts(conditions.SHAPE_MATERIAL, facts)
                 if not conditions._is_empty(f.get("field_value"))]
    stated = " ; ".join(_fold(f.get("field_value")) for f in materials)
    kept: list[dict] = []
    items: list[dict] = []
    for requirement in requirements:
        label = standard_labels.get(requirement.get("standard_document_id") or "", "")
        if not label or not is_materials_standard(label):
            kept.append(requirement)
            continue
        row_label = _fold(requirement.get("condition"))
        if not materials:
            detail = "a materials standard, and this datasheet states no material"
        elif requirement.get("requirement_type") == "table_value" and not (
                row_label and re.search(r"(?<![a-z0-9])" + re.escape(row_label) + r"(?![a-z0-9])", stated)):
            detail = (f"a materials standard's table row {requirement.get('condition')!r}, "
                      "and no material field of this datasheet states it")
        else:
            kept.append(requirement)
            continue
        items.append({"requirement": requirement, "code": "not_material_field", "detail": detail})
    return {"kept": kept, "items": items}
