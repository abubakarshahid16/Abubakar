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


# ------------------------------------------------- #139: the cited clauses only
#
# A datasheet that cites a code for ONE ITEM ("<code>, AB-12 (for spot
# radiography)") applies that clause, not the whole code. Which standards are
# cited that way, and for which clauses, is `applicability.cited_clause_scope`;
# this gate finds those clauses in the standard's OWN text and keeps only the
# requirements inside them. It can only NARROW: a clause the standard's text
# does not show is never used to drop anything, and a requirement it cannot
# place with certainty stays a check.

#: The rest of a heading line after its id: nothing, a bracket ("(normative)"),
#: or a title whose first word is capitalised, after a space or a " - " / ":"
#: separator ("APPENDIX Q - ROUNDED INDICATIONS", "Annex A: Title"). A running
#: footer ("AB-11 - AB-12": the "title" is another id) and a sentence ("AB-12
#: shall apply") are not headings. Case-sensitive.
_TITLE_WORD = r"[A-Z][A-Za-z]{2,}(?![-\d])"
_TITLE_REST = (
    r"(?=\s*$|\s+\(|\s*[-\u2013\u2014:]\s*" + _TITLE_WORD + r"|\s+[A-Z][A-Za-z]+)"
)
#: A full stop after the id, only when a title follows ("ZT-32. Spot
#: examination"): "AB-12." ending a sentence on its own line, and "AB-12.
#: Spot radiographs ... shall" starting one, are no headings.
_ID_DOT = r"(?:\.(?=\s+[A-Z])(?!.*\b(?:shall|must|should)\b))?"
_HEADINGS = (
    (
        "appendix",
        re.compile(
            r"^(?i:(?:(?:non-?)?mandatory\s+|normative\s+|informative\s+)?"
            r"(?:appendix|annex))\s+(?P<id>[A-Z]{1,3}|\d{1,3})(?![A-Za-z0-9])"
            + _ID_DOT
            + _TITLE_REST
        ),
    ),
    (
        "article",
        re.compile(
            r"^(?i:article)\s+(?P<id>\d{1,3})(?!\d|\.\d)" + _ID_DOT + _TITLE_REST
        ),
    ),
    (
        "lettered",
        re.compile(
            r"^(?P<id>[A-Z]{1,4}-\d{1,4}[A-Z]?)(?![A-Za-z0-9-])" + _ID_DOT + _TITLE_REST
        ),
    ),
    # A numbered clause needs a title word of three letters or more: "6 in."
    # and "3 L" inside a sentence are not clause 6 and clause 3.
    (
        "number",
        re.compile(
            r"^(?P<id>\d{1,3}(?:\.\d{1,3}){0,5})\.?(?=\s+[A-Z][A-Za-z]{2,}|\s*[-\u2013\u2014:]\s*"
            + _TITLE_WORD
            + ")"
        ),
    ),
)
#: How much of a sentence's folded opening is looked for on its page, and the
#: least that is enough to place it.
_PLACE_CHARS = 48
_PLACE_MIN = 16


def _key(text: object) -> str:
    return re.sub(r"[^0-9a-z]", "", numparse.fold(text or ""))


#: A contents entry or a table row, never a heading: its title ends in a
#: number ("Spot Examination 146", "Carbon steel 19.6") or has dot leaders.
_NOT_A_TITLE = re.compile(r"\s[\d.,]+$|\.{4,}|(?:\.\s){3,}")
#: A numbered id alone on its line, its title on the next ("6.1" / "Casing").
_BARE_NUMBER = re.compile(r"^(?P<id>\d{1,3}(?:\.\d{1,3}){0,5})\.?$")
#: A page where at least this share of the heading-shaped lines - 5 or more
#: of them - are contents entries is a table of contents: none of its lines
#: is a heading (an entry printed without a page number included).
_CONTENTS_SHARE = 0.5
_CONTENTS_LEAST = 5


def _heading_shape(line: str) -> tuple[str, str, bool] | None:
    """(kind, id, is a contents entry or table row) for a heading-shaped line."""
    for kind, pattern in _HEADINGS:
        found = pattern.match(line)
        if found is not None:
            entry = bool(_NOT_A_TITLE.search(line[found.end("id") :]))
            return kind, found.group("id").upper(), entry
    return None


def _heading(line: str) -> tuple[str, str] | None:
    shape = _heading_shape(line)
    return shape[:2] if shape and not shape[2] else None


def _next_number(ident: str, last: str | None) -> bool:
    """Is numbered clause `ident` plausible after the last numbered heading
    `last` - its first child, its next sibling, or the next of a parent?"""
    if last is None:
        return True
    return ident.startswith(last + ".") or _follows(_numbers(ident), _numbers(last))


def _headings(pages: list[list[str]]) -> tuple[list[tuple[str, str] | None], set[int]]:
    """(the heading each line opens - None for a line that opens none - in
    reading order, the indexes of the BARE ones). Never a heading: a running
    header or footer, a contents entry or a table row (`_NOT_A_TITLE`), any
    line of a contents page. A numbered id alone on its line with a title on
    the next line is a BARE heading when it is a plausible next numbered
    clause (`_next_number`) and the next line is no running header: it may
    open a cited clause, never end one (a page number reads the same way)."""
    running = _running_lines(pages)
    out: list[tuple[str, str] | None] = []
    bare_at: set[int] = set()
    last: str | None = None
    for lines in pages:
        shapes = [s for s in map(_heading_shape, lines) if s]
        if len(shapes) >= _CONTENTS_LEAST and (
            sum(s[2] for s in shapes) >= _CONTENTS_SHARE * len(shapes)
        ):
            out.extend([None] * len(lines))  # a contents page
            continue
        heads: list[tuple[str, str] | None] = []
        page_last = last
        for i, line in enumerate(lines):
            head = None if re.sub(r"\d+", "#", line) in running else _heading(line)
            bare = _BARE_NUMBER.match(line)
            if (
                head is None
                and bare
                and i + 1 < len(lines)
                and re.match(_TITLE_WORD, lines[i + 1])
                and re.sub(r"\d+", "#", lines[i + 1]) not in running
                and _next_number(bare.group("id"), page_last)
            ):
                head = ("number", bare.group("id"))
                bare_at.add(len(out) + i)
            if head and head[0] == "number":
                page_last = head[1]
            heads.append(head)
        last = page_last
        out.extend(heads)
    return out, bare_at


def _numbers(ident: str) -> tuple[int, ...]:
    return tuple(int(p) for p in ident.split("."))


def _follows(head: tuple[int, ...], clause: tuple[int, ...]) -> bool:
    """Is numbered heading `head` a plausible NEXT clause after `clause` - its
    next sibling, or the next clause of one of its parents (4.1 -> 4.2, 5,
    5.1)? A page header "12 <title>" or a table row "150 Carbon steel" inside
    clause 4.1 is not, and does not end it."""
    return any(
        head[: k - 1] == clause[: k - 1]
        and len(head) >= k
        and head[k - 1] == clause[k - 1] + 1
        for k in range(1, len(clause) + 1)
    )


def _ends(clause: tuple[str, str], head: tuple[str, str]) -> bool:
    """Does heading `head` close the section of `clause`?"""
    kind, ident = clause
    if head == clause:
        return False
    if head[0] == "appendix":
        return True
    if kind in ("lettered", "article"):
        return head[0] == kind
    if kind == "number" and head[0] == "number":
        return _follows(_numbers(head[1]), _numbers(ident))
    return False


def _sequence(ident: str) -> tuple:
    """An id as (its family, its place in it): "AB-12" (AB, 12), "4.2"
    ((4,), 2), "7" ((), 7), "B" ((), 2)."""
    if "-" in ident:
        prefix, _, number = ident.partition("-")
        digits = re.match(r"\d+", number)
        return prefix, int(digits.group(0)) if digits else -1
    if ident.replace(".", "").isdigit():
        parts = _numbers(ident)
        return parts[:-1], parts[-1]
    return "letter", ord(ident[0]) if len(ident) == 1 else -1


def _ends_for_certain(clause: tuple[str, str], head: tuple[str, str]) -> bool:
    """Is `head` read FOR CERTAIN as the end of `clause`: another id of the
    same kind and family ("AB-12" -> "AB-13", "4.1" -> "4.2", Appendix 7 ->
    8; a lower one too, "AB-12" -> "AB-10": the "AB-12" opened was a
    contents line or a cross-reference)? Any other heading that closes it
    (another part, "5" after "4.1") may be a table row or a stray line: the
    end is not certain."""
    if head[0] != clause[0]:
        return False
    (fh, nh), (fc, nc) = _sequence(head[1]), _sequence(clause[1])
    return fh == fc and nh != nc and nh >= 0 and nc >= 0


#: A line repeated in the same place (the first or last lines of a page) on
#: at least this share of a standard's pages - and on 3 pages or more - is a
#: running header or footer, never a heading. Digits do not count, so "12
#: <title>" and "13 <title>" are one header.
_RUNNING_SHARE = 0.25
_RUNNING_EDGE = 3
_RUNNING_LETTERS = 6


def _running_lines(pages: list[list[str]]) -> set[str]:
    """The digit-free forms of the running headers and footers of `pages`."""
    seen: dict[str, set[int]] = {}
    for number, lines in enumerate(pages):
        for line in lines[:_RUNNING_EDGE] + lines[-_RUNNING_EDGE:]:
            # a bare clause id ("AB-12", "4.1") is never a running line: with
            # its digits gone, every heading of a part would look alike
            if len(re.findall(r"[A-Za-z]", line)) >= _RUNNING_LETTERS:
                seen.setdefault(re.sub(r"\d+", "#", line), set()).add(number)
    least = max(3, _RUNNING_SHARE * len(pages))
    return {form for form, where in seen.items() if len(where) >= least}


class StandardText:
    """A standard's page text, folded for placing sentences, with the
    position of every line. `pages`: [(page number, text)] in page order."""

    def __init__(self, pages: list[tuple[int, str]]) -> None:
        self.lines: list[str] = []
        self.offsets: list[int] = []
        self.page_bounds: dict[int, tuple[int, int]] = {}
        parts: list[str] = []
        at = 0
        split = [
            [" ".join(r.split()) for r in (t or "").splitlines() if r.strip()]
            for _, t in pages
        ]
        self.heads, self.bare = _headings(split)
        for (page, _text), lines in zip(pages, split, strict=True):
            start = at
            for line in lines:
                self.lines.append(line)
                self.offsets.append(at)
                folded = _key(line)
                parts.append(folded)
                at += len(folded)
            self.page_bounds[page] = (start, at)
        self.offsets.append(at)
        self.folded = "".join(parts)

    def spans(self, clause: tuple[str, str]) -> list[tuple[int, int, int]]:
        """Where `clause` runs: (start, soft end, end) from each heading of it.
        Only a heading read for certain (`_ends_for_certain`) ENDS it; one
        that only may be its end (`_ends`) marks the soft end, after which a
        requirement is the engineer's question, never "outside". A bare
        heading (`_headings`) ends nothing."""
        out: list[tuple[int, int, int]] = []
        opened: int | None = None
        soft: int | None = None
        for index, head in enumerate(self.heads):
            if head is None:
                continue
            if opened is not None and index not in self.bare and _ends(clause, head):
                if not _ends_for_certain(clause, head):
                    soft = self.offsets[index] if soft is None else soft
                    continue
                end = self.offsets[index]
                out.append((self.offsets[opened], end if soft is None else soft, end))
                opened = soft = None
            if opened is None and head == clause:
                opened = index
        if opened is not None:
            end = self.offsets[-1]
            out.append((self.offsets[opened], end if soft is None else soft, end))
        return out

    def place(self, requirement: dict) -> int | None:
        """Where the requirement's sentence starts, or None when it cannot be
        placed for certain (not found once, or too short to be sure)."""
        key = _key(
            requirement.get("source_text") or requirement.get("requirement_text")
        )[:_PLACE_CHARS]
        if len(key) < _PLACE_MIN:
            return None
        bounds = self.page_bounds.get(_page_of(requirement))
        if bounds is not None:
            # A sentence may run on to the next page.
            at = self.folded.find(key, bounds[0], bounds[1] + len(key))
            if at != -1:
                return at
        first = self.folded.find(key)
        if first != -1 and self.folded.find(key, first + 1) == -1:
            return first
        return None


def _page_of(requirement: dict) -> int | None:
    return requirement.get("page") or requirement.get("chunk_page")


def _stored_clause_in(clause_text: object, clause: tuple[str, str]) -> bool:
    """Is a requirement's stored clause number `clause` or one of its parts?"""
    stored = re.sub(r"\s+", "", str(clause_text or "")).upper()
    kind, ident = clause
    if not stored or kind == "article":
        return False
    if stored == ident:
        return True
    tails = {
        "lettered": "(.",
        "number": ".",
        "appendix": "-" if ident.isdigit() else ".-",
    }[kind]
    return stored.startswith(ident) and stored[len(ident) : len(ident) + 1] in tuple(
        tails
    )


def standard_pages(standard_id: str) -> list[tuple[int, str]]:
    """A standard's page text, in page order."""
    from .db import connect

    return [
        (r["page_no"], r["text"] or "")
        for r in connect().execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (standard_id,),
        )
    ]


#: Where a requirement lies against the cited clauses (`_where`).
INSIDE, UNSURE, OUTSIDE = "inside", "unsure", "outside"


def _where(requirement: dict, text: StandardText, spans: dict) -> str:
    """INSIDE, UNSURE or OUTSIDE the cited clauses (`spans`: the clauses the
    standard's text shows, each with where it runs). Its stored clause number
    first, then where its sentence sits: before a clause's soft end inside,
    between the soft end and the end UNSURE (the end was not read for
    certain). A sentence that cannot be placed is outside only when its whole
    page lies outside every clause; a page touching one keeps it a check. A
    clause found only by stored clause numbers has no place in the text, so
    a requirement with no stored number cannot be shown outside it."""
    if any(_stored_clause_in(requirement.get("clause"), c) for c in spans):
        return INSIDE
    if not requirement.get("clause") and any(not runs for runs in spans.values()):
        return INSIDE
    runs = [run for clause_runs in spans.values() for run in clause_runs]
    at = text.place(requirement)
    if at is not None:
        if any(lo <= at < soft for lo, soft, _hi in runs):
            return INSIDE
        return UNSURE if any(soft <= at < hi for _lo, soft, hi in runs) else OUTSIDE
    bounds = text.page_bounds.get(_page_of(requirement))
    touches = bounds is None or any(
        lo < bounds[1] and bounds[0] < hi for lo, _s, hi in runs
    )
    return INSIDE if touches else OUTSIDE


def _found_clauses(text: StandardText, rows: list[dict], clauses: list) -> dict:
    """{clause: where it runs} for the cited clauses FOUND: one of the
    standard's own requirements is placed inside it, or carries its number.
    A heading alone - a contents line, a heading printed in a form not read
    here - finds nothing, and an unfound clause narrows nothing."""
    placed = [at for at in (text.place(r) for r in rows) if at is not None]
    found = {}
    for c in clauses:
        runs = text.spans(c)
        if any(_stored_clause_in(r.get("clause"), c) for r in rows) or any(
            lo <= at < soft for at in placed for lo, soft, _hi in runs
        ):
            found[c] = runs
    return found


def _past_soft_end_item(name: str, cited_for: str) -> dict:
    return {
        "code": "applicability_unsure",
        "detail": f"the datasheet cites {name} for {cited_for}; this requirement "
        "follows a line that may or may not end the cited clause - the engineer "
        "decides whether it applies",
    }


def _outside_item(name: str, cited_for: str, sure: bool) -> dict:
    """The decision for a requirement outside the cited clauses. #143(2): on
    an UNSURE reading ("Section 3", "Annex E", "CL 150" can name a part of
    the code or a rating) it is never "does not apply": it stays in scope,
    not checked, for the engineer."""
    if sure:
        return {
            "code": "outside_cited_clauses",
            "detail": f"the datasheet cites {name} only for {cited_for}, "
            "and this requirement is outside them",
        }
    return {
        "code": "applicability_unsure",
        "detail": f"the datasheet cites {name} for {cited_for}, in words that "
        "may name a part of the code or a rating; this requirement is "
        "outside them - the engineer decides whether it applies",
    }


def citation_gate(
    requirements: list[dict],
    cited: dict[str, dict],
    standard_labels: dict[str, str],
    *,
    pages_of=standard_pages,
    label=None,
) -> dict:
    """#139: a standard the datasheet cites only for named clauses keeps only
    the requirements inside those clauses (and their sub-clauses).

    `cited`: {standard id: {"clauses": [(kind, id)], "pages": [...]}} from
    `applicability.cited_clause_scope`. A requirement is inside a clause when
    its stored clause number is that clause or a part of it, or its sentence
    lies between the clause's heading and the next heading in the standard's
    own text (`_inside`). The standard is narrowed only when EVERY printed
    clause is found (`_found_clauses`; one inside a printed range may be
    skipped by the numbering) - otherwise nothing of it is, and the summary
    says which clause. On a reading that is not sure (`CitedClause.sure`) the
    requirements outside go to "unsure" - in scope, not checked, the
    engineer decides - never to "does not apply". Every standard not in
    `cited` passes untouched. Returns {"kept", "items", "unsure", "summary"}."""
    from .standard_ids import clause_label

    label = label or clause_label
    out_ids: set[int] = set()
    items: list[dict] = []
    unsure: list[dict] = []
    summary: list[dict] = []
    for sid, scope in cited.items():
        rows = [r for r in requirements if r.get("standard_document_id") == sid]
        if not rows:
            continue
        text = StandardText(pages_of(sid))
        found = _found_clauses(text, rows, scope["clauses"])
        missing = [
            c
            for c in scope["clauses"]
            if c not in found and not getattr(c, "in_range", False)
        ]
        name = standard_labels.get(sid) or sid
        pages = ", ".join(str(p) for p in scope.get("pages") or [])
        cited_for = ", ".join(label(c) for c in found) + (
            f" (page {pages})" if pages else ""
        )
        sure = all(getattr(c, "sure", True) for c in scope["clauses"])
        item = _outside_item(name, cited_for, sure)
        where = {} if missing else {id(r): _where(r, text, found) for r in rows}
        out = [r for r in rows if where.get(id(r)) == OUTSIDE]
        soft = [r for r in rows if where.get(id(r)) == UNSURE]
        out_ids.update(id(r) for r in out + soft)
        (items if sure else unsure).extend({"requirement": r, **item} for r in out)
        unsure.extend(
            {"requirement": r, **_past_soft_end_item(name, cited_for)} for r in soft
        )
        summary.append(
            {
                "standard_document_id": sid,
                "standard": name,
                "clauses": [label(c) for c in scope["clauses"]],
                "clauses_not_found": [label(c) for c in missing],
                "narrowed": not missing,
                "sure": sure,
                "pages": list(scope.get("pages") or []),
                "kept": len(rows) - len(out) - len(soft),
                "outside": len(out),
                "unsure": len(soft),
            }
        )
    kept = [r for r in requirements if id(r) not in out_ids]
    return {"kept": kept, "items": items, "unsure": unsure, "summary": summary}


def citation_gate_for_run(
    requirements: list[dict],
    submittal_document_id: str,
    applicable: list[dict],
    standard_labels: dict[str, str],
    allowed_document_ids: frozenset[str],
) -> dict:
    """`citation_gate` for one review run, with the run's cited clauses
    (`applicability.cited_clause_scope`). A narrowing step must never take a
    review down: if reading the citations or a standard's text fails, NOTHING
    is narrowed (every requirement stays a check), the failure is logged by
    type (`errors.fell_back`) and the run's summary says the step did not run."""
    from . import applicability, errors

    try:
        cited = applicability.cited_clause_scope(
            submittal_document_id, applicable, allowed_document_ids=allowed_document_ids
        )
        return citation_gate(requirements, cited, standard_labels)
    except Exception as exc:  # noqa: BLE001 - logged; must never fail the review
        not_run = {
            "not_run": f"the cited-clause scope could not be read ({type(exc).__name__}); "
            "nothing was narrowed"
        }
        return errors.fell_back(
            "subject_scope: the cited-clause scope failed; nothing is narrowed",
            exc,
            {
                "kept": list(requirements),
                "items": [],
                "unsure": [],
                "summary": [not_run],
            },
        )
