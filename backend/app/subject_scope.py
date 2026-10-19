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
  * THE DOCUMENT OUTRANKS THE GUESS (order 142): with no engineer
    confirmation, the reading is UNSURE, and treated as unknown, when a code
    the datasheet states as a field VALUE governs another equipment type and
    the sheet names no code of the type read, or when the title names another
    type than the classification. Which code governs what is data
    (`reference/governing_standards.json`); no field label or tag is read.
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

SOURCE_UNSURE = "unsure"


def submittal_equipment(
    classification: dict | None, facts: list[dict], vocab: Vocabulary
) -> tuple[set[str], str | None]:
    """(equipment types, where they were read), or (empty, None) when unknown.
    (empty, "unsure") when the reading is in doubt (`read_equipment`)."""
    equipment, source, _doubt = read_equipment(classification, facts, vocab)
    return equipment, source


def read_equipment(
    classification: dict | None, facts: list[dict], vocab: Vocabulary
) -> tuple[set[str], str | None, dict | None]:
    """(equipment types, where they were read, the doubt or None).

    The first of classification, title and equipment-describing fields that
    names an equipment type is the reading. When `equipment_doubt` finds the
    datasheet itself disagrees, the equipment is read as UNKNOWN (empty) with
    source "unsure", so nothing is ruled out by equipment type."""
    classification = classification or {}
    sources = (
        ("classification", classification.get("equipment_type")),
        ("title", classification.get("title")),
        (
            "fields",
            " ; ".join(
                str(f.get("field_value") or f.get("raw_value") or "")
                for f in facts
                if not f.get("is_blank")
                and _fold(f.get("field_label") or f.get("field_name"))
                in vocab.field_labels
            ),
        ),
    )
    for source, text in sources:
        found = vocab.equipment_in(text)
        if found:
            doubt = equipment_doubt(classification, facts, found, source, vocab)
            if doubt is not None:
                return set(), SOURCE_UNSURE, doubt
            return found, source, None
    return set(), None, None


def stated_codes(facts: list[dict]) -> list[dict]:
    """[{identifier, page, label}] for every standard a non-blank fact states
    as its VALUE. The label is only quoted back; a code inside a label with
    no value is not stated."""
    from . import standard_ids

    out: list[dict] = []
    for fact in facts:
        if fact.get("is_blank"):
            continue
        value = str(fact.get("field_value") or fact.get("raw_value") or "")
        for identifier in standard_ids.cited_standards(value):
            out.append(
                {
                    "identifier": identifier,
                    "page": fact.get("page"),
                    "label": str(
                        fact.get("field_label") or fact.get("field_name") or ""
                    ),
                }
            )
    return out


def _codes_of(types: set[str], table: dict) -> list[str]:
    """The codes the table says these types take, in whole or in part."""
    codes: list[str] = []
    for kind in sorted(types):
        codes.extend(table["equipment_types"].get(kind, []))
        codes.extend(e["standard"] for e in table["partial_standards"].get(kind, []))
    return codes


def _governed_types(identifier: str, table: dict, vocab: Vocabulary) -> list[str]:
    """The equipment types (not components) whose governing codes include it."""
    from . import standard_ids

    return sorted(
        kind
        for kind, codes in table["equipment_types"].items()
        if vocab.kind.get(kind) == EQUIPMENT
        and any(standard_ids.same_standard(identifier, c) for c in codes)
    )


def _sheet_text(classification: dict) -> str:
    """The submittal's own retrievable text, when the record names it."""
    document_id = classification.get("document_id")
    if not document_id:
        return ""
    from .db import connect

    rows = connect().execute(
        "SELECT text FROM chunks WHERE document_id=? AND retrievable=1", (document_id,)
    )
    return "\n".join(str(r["text"] or "") for r in rows)


def equipment_doubt(
    classification: dict | None,
    facts: list[dict],
    named: set[str],
    source: str | None,
    vocab: Vocabulary,
) -> dict | None:
    """Why the equipment reading `named` is in doubt, or None (order 142).

    In doubt, with no engineer confirmation, when (D) a code a fact states as
    its value governs another equipment type, is none of the named types'
    own or partial codes, and the sheet names no such code anywhere (fact
    values or its own text); or (T) the type came from the classification and
    the title names equipment types it shares none with. Returns
    {"named", "declared": [{identifier, governs, page, label}], "title",
    "reason"}."""
    classification = classification or {}
    if (
        not named
        or classification.get("confirmed_by")
        or classification.get("confirmed")
    ):
        return None
    from . import applicability, standard_ids

    table = applicability.governing_table()
    own = _codes_of(named, table)

    def is_own(identifier: str) -> bool:
        return any(standard_ids.same_standard(identifier, c) for c in own)

    stated = stated_codes(facts)
    declared = []
    for code in stated:
        governs = _governed_types(code["identifier"], table, vocab)
        if governs and not set(governs) & named and not is_own(code["identifier"]):
            declared.append({**code, "governs": governs})
    if declared and (
        any(is_own(c["identifier"]) for c in stated)
        or any(
            is_own(i) for i in standard_ids.cited_standards(_sheet_text(classification))
        )
    ):
        declared = []
    title = (
        sorted(vocab.equipment_in(classification.get("title")))
        if source == "classification"
        else []
    )
    if set(title) & named:
        title = []
    if not declared and not title:
        return None
    return {
        "named": sorted(named),
        "declared": declared,
        "title": title,
        "reason": _doubt_reason(sorted(named), source, declared, title),
    }


def _doubt_reason(
    named: list[str], source: str | None, declared: list[dict], title: list[str]
) -> str:
    """The plain sentence for the engineer. Built from data, no fixed names."""
    this = " / ".join(named)
    parts = []
    if declared:
        first = declared[0]
        where = (
            f"its {first['label']}"
            if first["label"]
            else "the value of one of its fields"
        )
        page = f" (page {first['page']})" if first.get("page") is not None else ""
        parts.append(
            f"the datasheet states {first['identifier']} as {where}{page}, a code for a "
            f"{' / '.join(first['governs'])}, and names no code for a {this}"
        )
    if title:
        parts.append(f"its title names a {' / '.join(title)}")
    return (
        f"equipment type unsure: read as {this} (from its {source or 'record'}), but "
        + "; and ".join(parts)
        + ". An engineer should confirm the equipment type; until then "
        "no standard or requirement is ruled out by equipment type."
    )


#: The words a datasheet uses to call itself a sheet ("CONTROL VALVE DATA
#: SHEET", "PUMP SPECIFICATION"), matched on `_fold`ed text.
_SHEET = r"(?:data ?sheets?|specifications?|spec sheets?)"
#: A line that IS a sheet title and nothing else: the equipment name, then the
#: sheet word ("CONTROL VALVE DATASHEET"), or the sheet word, "for"/"of", then
#: the name ("DATA SHEET FOR PRESSURE TRANSMITTERS"). Any other word on the
#: line (a sentence, a second type joined by "and") and it is not a title.
_SHEET_TITLE = re.compile(
    rf"^(?:{_SHEET} (?:for|of) (?P<after>.+)|(?P<before>.+?) {_SHEET})$")
#: A LABELLED title-block field ("Equipment: Control Valve", "Title: Pressure
#: Transmitter Data Sheet"): the label, a colon, the value. Read on the raw
#: line, because folding drops the colon that makes it a label.
_TITLE_FIELD = re.compile(
    r"^\s*(?:(?:document\s+)?title|equipment(?:\s+type)?)\s*:\s*(?P<value>\S.*)$",
    re.IGNORECASE)


def _titled_phrase(line: str, vocab: Vocabulary) -> str | None:
    """The vocabulary spelling a title line names AS ITS WHOLE SUBJECT, else None.

    Only two shapes count (rule 4: a word in free text is not a reading):
      * a labelled field, "Equipment:" or "Title:", whose value is the name,
        optionally with the sheet words around it;
      * an unlabelled line that is ONLY the name plus the sheet words.
    The name must be one whole spelling of the vocabulary that means exactly
    one equipment type. "This datasheet supports the ... transfer pumps", a
    bare "SOUR SERVICE DRUM" or "VALVE DATA SHEET" (three types) name none.
    """
    field = _TITLE_FIELD.match(line or "")
    text = _fold(field.group("value") if field else line)
    sheet = _SHEET_TITLE.match(text)
    if sheet is not None:
        text = sheet.group("after") or sheet.group("before")
    elif field is None:
        return None
    types = {t for t in vocab.phrases.get(text, ()) if vocab.kind.get(t) == EQUIPMENT}
    return text if len(types) == 1 else None


def title_equipment(lines: list[tuple[int, str]] | tuple, vocab: Vocabulary
                    ) -> tuple[str, int | None, str] | None:
    """(equipment type, page, the words that named it) when the title block
    names exactly ONE equipment type of the vocabulary, else None (#897).

    `lines` are `(page, line)` as `classification.title_block_lines` gives
    them. A line counts only when it is a genuine title (`_titled_phrase`):
    a labelled "Equipment:"/"Title:" field, or a line that is nothing but the
    name and the sheet words. Case and spacing do not matter; the whole name
    must be one spelling of the vocabulary ("pressure transmitter", never the
    "pressure" inside it), and a spelling that could mean several types
    counts for none. One type named: that is the reading. Two different
    types named: the title is ambiguous and the type stays UNKNOWN - never
    the first, never a guess. A word in a sentence, a note or a stray edge
    line is never read, so a cover that names no equipment stays unknown.
    """
    hits = [(page, line, phrase) for page, line in lines
            if (phrase := _titled_phrase(line, vocab))]
    found = {t for _p, _l, phrase in hits for t in vocab.phrases[phrase]
             if vocab.kind.get(t) == EQUIPMENT}
    if len(found) != 1:
        return None
    page, line, phrase = hits[0]
    return found.pop(), page, _quote(line, phrase)


def _quote(line: str, phrase: str) -> str:
    """The phrase as the line spells it (case and spacing kept), else the
    folded phrase."""
    match = re.search(r"\s+".join(re.escape(w) for w in phrase.split()), line, re.IGNORECASE)
    return match.group(0) if match else phrase


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
    equipment, source, doubt = read_equipment(classification, facts, vocab)
    headings_by_standard = headings_by_standard or {}
    kept: list[dict] = []
    summary = {"submittal_equipment": sorted(equipment), "equipment_source": source,
               "checked_general": 0, "checked_matching": 0,
               "kept_equipment_unknown": 0, "not_applied": 0}
    # Order 142: why the equipment was read as unsure, for the engineer.
    summary["equipment_unsure"] = doubt["reason"] if doubt else None
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

def partial_gate(requirements: list[dict], *, equipment: set[str], standard_labels: dict[str, str],
                 partial_standards: dict[str, list[dict]]) -> dict:
    """A standard an equipment type takes only IN PART (`partial_standards` in
    reference/governing_standards.json): ASME VIII Div 1 governs a relief valve
    only through its pressure relief device rules. On a review of that type,
    only that standard's requirements whose own words name one of the entry's
    `words` stay checks; the rest do not apply, with the reason. FOUND on the
    PSV review (2026-10-10): vessel-construction clauses (openings, castings)
    were checked against a relief valve's design pressure and read COMPLIANT.
    Every other standard, and every type with no entry, passes untouched.
    Returns {"kept", "items"}; items carry `outside_partial_scope`."""
    entries = [(kind, e) for kind in sorted(equipment) for e in partial_standards.get(kind, [])]
    if not entries:
        return {"kept": list(requirements), "items": []}
    from . import standard_ids

    kept: list[dict] = []
    items: list[dict] = []
    for requirement in requirements:
        label = standard_labels.get(requirement.get("standard_document_id") or "", "")
        entry = next(((kind, e) for kind, e in entries
                      if label and standard_ids.same_standard(label, e["standard"])), None)
        if entry is None:
            kept.append(requirement)
            continue
        kind, e = entry
        text = _fold(" ".join(str(requirement.get(k) or "")
                              for k in ("subject", "requirement_text", "source_text")))
        if any(re.search(r"(?<![a-z0-9])" + re.escape(_fold(w)) + r"(?![a-z0-9])", text) for w in e["words"]):
            kept.append(requirement)
            continue
        items.append({"requirement": requirement, "code": "outside_partial_scope",
                      "detail": (f"{e['standard']} applies to a {kind} only in its rules on "
                                 f"{e.get('applies_to') or 'one topic'}, and this requirement is not about that")})
    return {"kept": kept, "items": items}


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
