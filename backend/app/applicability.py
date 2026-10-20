"""Phase 5A: which standards apply to a submittal, why, and what is missing.

THIS MODULE ANSWERS ONE QUESTION AND REFUSES THE NEXT ONE. It says which
standards govern a submittal and on what grounds. It says nothing about whether
the submittal complies - that is 5B, and keeping the two apart is what stops a
selection heuristic turning into a compliance verdict.

THE FAILURE MODE THIS IS BUILT AGAINST

Master plan section 23: "vector similarity finds candidates and must never be
the sole basis for declaring compliance or non-compliance." Section 11 puts
explicit references first in the priority order and semantic retrieval fifth.
Put those together and there is one specific way this goes wrong:

    A datasheet cites API 610. API 610 is not in the library. Dense retrieval
    finds some vaguely related pump document. It lands on the list as
    "applicable". The missing standard disappears, and a review that could not
    possibly have been done looks complete.

So the rule here is stronger than "prefer references":

    A SEMANTICALLY RETRIEVED STANDARD MAY NEVER SUBSTITUTE FOR AN EXPLICITLY
    REFERENCED ONE THAT IS ABSENT.

A missing reference stays on the missing list no matter what else was found,
and it lowers completeness. `_semantic_cannot_cover_a_missing_reference` is
where that is enforced and it is the single most important function in the
file.

WHAT IS REUSED, NOT REBUILT

`review_applicable_standards` is the phase 1 relation, filled at last - not a
second table and not collapsed to JSON, because it needs joins, permission
filtering and audit. `standards.selectable_standard_ids` already excludes
superseded revisions. `datasheets.referenced_standards` already reads the
identifiers a sheet cites. `fts_index.search` is FTS5 for exact standard numbers
and `search.search` is the hybrid path; both take `allowed_document_ids`
keyword-only, so access filters before ranking rather than after.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import datasheets, errors, fts_index, standard_ids, standards, submittal_review
from .db import connect
from .held_standards import mark_rows

#: The selection rules, in the priority master plan section 11 gives them.
#:
#: The METHOD IS RECORDED PER ROW, because "it was retrieved" is not a reason an
#: engineer can act on and "the datasheet names it in note 8" is. A row without
#: a method is refused by `record_selection`.
METHOD_REFERENCED = "referenced"          # 1. named in the datasheet
METHOD_POSSIBLE = "possible_citation"     # 1.5 looks like a library number, unconfirmed (#702)
METHOD_EQUIPMENT = "equipment_type"       # 2. mapped to the equipment
METHOD_GOVERNING = "governing_standard"   # 2. governs this equipment type (#725 F5)
#: RETIRED as a selection rule (#212): kept so stored rows that carry it stay
#: readable. A standard's `discipline` is the committee that owns it ("Piping
#: Standards Committee") and a submittal's is a broad category ("Mechanical"),
#: so the two do not match - measured on a copy of the current library
#: 2026-10-09: 178 of 179 standards with a discipline are committee-shaped, no
#: submittal's equals any standard's, and 0 of 11,786 stored selection rows in
#: 43 runs carry this method (the progress log records one earlier run where
#: it did select). A mapping between the two would be a manual
#: taxonomy (owner decision 2026-09-28: none), and since B5 a discipline match
#: could not include a standard anyway.
METHOD_DISCIPLINE = "discipline"          # 3. discipline match (retired, #212)
METHOD_SERVICE = "service"                # 4. service / operating conditions
METHOD_SEMANTIC = "semantic"              # 5. dense retrieval
METHOD_PROJECT = "project"                # 6. contract / project requirement
METHOD_MANUAL = "manual"                  # an engineer's own decision
#: B5: the standard's own SCOPE CLAUSE names the submittal's equipment
#: (applicability_v2.decide on a stored, verified scope record).
METHOD_SCOPE = "scope"

#: B5 (live wiring, 2026-09-25): methods that are EVIDENCE a standard governs
#: this submittal - it is cited, or it is classified for this equipment,
#: service or project, or its scope clause names it. A discipline match alone
#: ("mechanical" and "mechanical") and textual similarity are only reasons to
#: LOOK: before this, both were included, so every mechanical standard in the
#: library was compared against every mechanical datasheet. They are recorded
#: as considered and not included, with the reason, and an engineer may add
#: any of them (`override`).
INCLUDING_METHODS = frozenset({
    "governing_standard",  # #725 F5: reference/governing_standards.json
    "manual", "referenced", "equipment_type", "scope", "service", "project"})
CANDIDATE_ONLY_REASON = {
    "possible_citation": ("possible match, engineer to confirm: the submittal names something "
                          "that looks like this standard's number or title but is not its "
                          "recorded document number; considered, not included - an engineer "
                          "may add it"),
    "discipline": ("a shared discipline alone is not evidence that this standard "
                   "governs this equipment; considered, not included - an engineer "
                   "may add it"),
    "semantic": ("similar wording alone is not evidence of applicability; "
                 "considered, not included - an engineer may add it"),
}

#: Priority order, lowest number wins when two rules pick the same standard.
#: A standard both cited and semantically similar is recorded as CITED: the
#: stronger reason is the true one and the weaker one adds nothing.
#:
#: #725 F5: EVERY INCLUDING REASON OUTRANKS EVERY CANDIDATE-ONLY ONE. The old
#: order put discipline (3) above service (4), semantic (5) above project (6)
#: and a possible citation (1.5) above an equipment match (2), so a standard
#: matched both ways was recorded by its weaker, candidate-only reason - and
#: left out of the review although an including rule had picked it.
_PRIORITY = {
    METHOD_MANUAL: 0,
    METHOD_REFERENCED: 1,
    METHOD_EQUIPMENT: 2,
    METHOD_GOVERNING: 2,
    METHOD_SCOPE: 2,
    METHOD_SERVICE: 3,
    METHOD_PROJECT: 3,
    METHOD_POSSIBLE: 4,
    METHOD_DISCIPLINE: 5,
    METHOD_SEMANTIC: 6,
}

#: CONFIDENCE IS NEVER "high" (CLAUDE.md rule 4). These are the ceiling for
#: each method, and even an explicit citation stops at 0.9: the sheet naming a
#: standard is strong evidence that it governs, not proof that this revision of
#: it is the right one.
_CONFIDENCE = {
    METHOD_MANUAL: 0.9,
    METHOD_REFERENCED: 0.9,
    METHOD_POSSIBLE: 0.5,
    METHOD_EQUIPMENT: 0.7,
    METHOD_GOVERNING: 0.7,
    METHOD_SCOPE: 0.7,
    METHOD_DISCIPLINE: 0.5,
    METHOD_SERVICE: 0.5,
    METHOD_SEMANTIC: 0.4,
    METHOD_PROJECT: 0.4,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _scope_clause(allowed_document_ids: frozenset[str], column: str) -> tuple[str, list[str]]:
    if not allowed_document_ids:
        return " WHERE 1 = 0", []
    marks = ",".join("?" for _ in allowed_document_ids)
    return f" WHERE {column} IN ({marks})", sorted(allowed_document_ids)


def normalise_identifier(identifier: str) -> str:
    """A standard identifier reduced to a comparison key.

    `API RP 520 Pt-1`, `API-RP-520 PT1` and `apirp520pt1` are the same
    standard written three ways. Punctuation and spacing are dropped and the
    rest upper-cased; nothing else, because the digits are the identity.
    """
    return re.sub(r"[^A-Z0-9]", "", (identifier or "").upper())


#: A client standard number inside a LIBRARY FILENAME. Filenames are not
#: citations - they carry revision notes, dates and draft markers - so this is
#: anchored at the start and reads only the number.
_FILENAME_NUMBER = re.compile(r"^\s*(SAES)[-\s]*([A-Z])[-\s]*(\d{1,4})", re.IGNORECASE)


def library_identifier(filename: str) -> str | None:
    """The standard number a library filename carries, zero-padded. Or None.

    `SAES-B-14 -Final Draft 01-29-23.pdf` is SAES-B-014. The series number is
    written three digits wide everywhere the client prints it, and one file
    in this corpus was saved with the leading zero dropped - so the document
    was in the library, was cited as SAES-B-014, and could not be matched to
    itself.

    THE PADDING IS DONE HERE AND NOT IN THE CITATION PATTERN, deliberately. A
    two-digit alternative in `_REFERENCED_STANDARD` would make every "SAES-A-4"
    in running prose a citation, and far worse, it would match the first two
    digits of a three-digit number and silently cite the wrong standard. A
    filename is a name somebody typed once; a citation is a claim about which
    document governs. Only the first is forgiving.
    """
    match = _FILENAME_NUMBER.match(filename or "")
    if match is None:
        return None
    return f"{match.group(1).upper()}-{match.group(2).upper()}-{int(match.group(3)):03d}"


class ApplicabilityError(ValueError):
    """A selection could not be recorded. Carries a reason, never a row."""


# ------------------------------------------------------------- the library

def _library(allowed_document_ids: frozenset[str]) -> list[dict]:
    """Every SELECTABLE standard the caller may read.

    `standards.selectable_standard_ids` already excludes superseded revisions,
    so a superseded standard cannot be selected here and stays readable
    everywhere else - the 3A rule, reused rather than restated.
    """
    ids = standards.selectable_standard_ids(allowed_document_ids=allowed_document_ids)
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    rows = connect().execute(
        f"""SELECT d.id, d.filename, c.document_number, c.title, c.discipline,
                   c.equipment_type, c.service, c.project
            FROM documents d JOIN document_classification c ON c.document_id = d.id
            WHERE d.id IN ({marks})""", sorted(ids)).fetchall()
    return [dict(r) for r in rows]


def _submittal_profile(document_id: str) -> dict:
    """What the submittal is, from its classification. Nothing is guessed."""
    row = connect().execute(
        "SELECT discipline, equipment_type, service, project"
        " FROM document_classification WHERE document_id = ?",
        (document_id,)).fetchone()
    return dict(row) if row else {
        "discipline": None, "equipment_type": None, "service": None, "project": None}


GOVERNING_PATH = Path(__file__).resolve().parent / "reference" / "governing_standards.json"


def governing_table(path: Path | None = None) -> dict:
    """reference/governing_standards.json: {"equipment_types": {type: [ids]},
    "materials_standards": [ids]}. A missing or malformed file RAISES - a
    review never runs with the table silently empty."""
    data = json.loads((path or GOVERNING_PATH).read_text(encoding="utf-8"))
    types = data.get("equipment_types")
    materials = data.get("materials_standards")
    if (data.get("format") != "governing-standards/1" or not isinstance(types, dict)
            or not all(isinstance(v, list) and all(isinstance(i, str) for i in v) for v in types.values())
            or not isinstance(materials, list)):
        raise ValueError(f"{(path or GOVERNING_PATH).name}: not a governing-standards/1 table")
    partial = data.get("partial_standards") or {}
    if not isinstance(partial, dict) or not all(
            isinstance(v, list) and all(isinstance(e, dict) and e.get("standard") and e.get("words")
                                        for e in v) for v in partial.values()):
        raise ValueError(f"{(path or GOVERNING_PATH).name}: partial_standards is malformed")
    return {"equipment_types": {k.strip().lower(): v for k, v in types.items()},
            "materials_standards": list(materials),
            "equipment_subtypes": data.get("equipment_subtypes") or {},
            "partial_standards": {k.strip().lower(): v for k, v in partial.items()}}


def is_materials_standard(entry_or_label: dict | str, table: dict | None = None) -> bool:
    """Is this library entry (or label) one of the materials standards?"""
    table = table or governing_table()
    if isinstance(entry_or_label, dict):
        return any(find_standard([entry_or_label], m) is not None for m in table["materials_standards"])
    return any(standard_ids.same_standard(entry_or_label, m) for m in table["materials_standards"])


def _equipment_reading(document_id: str, allowed: frozenset[str]) -> tuple:
    """(equipment, source, doubt, facts): `subject_scope.read_equipment` on the
    submittal's own record and facts. Unsure (order 142): empty equipment."""
    from . import classification, subject_scope

    facts = datasheets.list_facts(document_id, allowed_document_ids=allowed)
    record = classification.of_document(document_id) or {}
    reading = subject_scope.read_equipment(record, facts, subject_scope.vocabulary())
    return set(reading[0]), reading[1], reading[2], facts


def governing_standards(submittal_document_id: str, library: list[dict],
                        allowed_document_ids: frozenset[str]) -> tuple[dict[str, dict], list[dict]]:
    """#725 F5: the standards that GOVERN this submittal's equipment type.

    The type is read by `subject_scope` - THE one reader of what a submittal
    is (classification, then title, then its own type fields) - and the reason
    says where it was read. Each governing identifier the library holds is
    selected (`governing_standard`, included); one it does not hold is
    returned as not held, never as met. Unknown or unsure type: nothing.
    Returns (candidates by standard id, not-held rows)."""
    reading = _equipment_reading(submittal_document_id, allowed_document_ids)
    equipment, source = reading[0], reading[1]
    if not equipment:
        return {}, []
    from . import equipment_subtype as subtype

    table = governing_table()
    text = _submittal_text(submittal_document_id, allowed_document_ids)
    selected: dict[str, dict] = {}
    not_held: list[dict] = []
    seen: set[str] = set()
    for kind in sorted(equipment):
        for identifier, verdict in subtype.identifiers(kind, text, table):
            key = standard_ids.key(identifier)
            if key in seen:
                continue
            seen.add(key)
            entry = find_standard(library, identifier)
            where = f"{kind} (read from the submittal's {source})"
            if entry is None:
                not_held.append({"identifier": identifier,
                                 "reason": f"governs a {where} and is not present in the library"})
            elif entry["id"] not in selected:
                selected[entry["id"]] = subtype.row(identifier, verdict, where)
    return selected, not_held


#: #754 F5b: why a standard is in a submittal's REQUIRED set.
REQUIRED_BY_TYPE = "equipment type"
REQUIRED_BY_SERVICE = "service"


def _cited_by(cited: list[str], identifier: str) -> bool:
    return any(standard_ids.same_standard(c, identifier) for c in cited)


def _cited_other_type(
    cited: list[str], reading: tuple, own: list[str], stated: list[dict]
) -> tuple[list[dict], list[dict]]:
    """#754 / order 142: the cited codes that govern only OTHER equipment
    types, as (not applicable, declared check). A code the datasheet states
    as a field VALUE, or one this type takes in part (`partial_standards`), is
    never called not applicable: the engineer checks it. `reading`: (equipment,
    source); `own`: required codes; no `stated` when the type is unknown."""
    (equipment, source), gov = reading, governing_table()
    this, same = ", ".join(sorted(equipment)), standard_ids.same_standard
    partial = [e for k in sorted(equipment) for e in gov["partial_standards"].get(k, [])]
    not_applicable: list[dict] = []
    declared: list[dict] = []
    for c in dict.fromkeys([*cited, *(s["identifier"] for s in stated)]):
        others = [k for k, ids in gov["equipment_types"].items() if _cited_by(ids, c)]
        others = ", ".join(sorted(k for k in others if k not in equipment))
        if not others or _cited_by(own, c) or (c not in cited and _cited_by(cited, c)):
            continue
        said = next((s for s in stated if same(c, s["identifier"])), None)
        part = next((e for e in partial if same(c, e["standard"])), None)
        if said is not None:
            page = f" (page {said['page']})" if said.get("page") is not None else ""
            why = f"the datasheet states {c} as its {said['label'] or 'own field value'}"
            why = f"{why}{page}; it is a code for a {others}"
            declared.append({"identifier": c, "reason": f"{why} - {_WHICH_TYPE}"})
        elif part is not None:
            why = f"a {this} takes {c} in part ({part.get('applies_to') or 'some clauses'})"
            why = f"{why}; it is also a code for a {others}"
            declared.append({"identifier": c, "reason": f"{why} - {_WHICH_CLAUSES}"})
        elif equipment:
            why = f"it governs {others}, and this submittal is a {this}"
            not_applicable.append({"identifier": c, "reason": f"{why} (read from its {source})"})
    return not_applicable, declared


_WHICH_TYPE = "engineer to check which equipment this is"
_WHICH_CLAUSES = "engineer to check which clauses apply"


def standards_check(submittal_document_id: str, *, allowed_document_ids: frozenset[str],
                    library: list[dict] | None = None) -> dict:
    """#754 F5b: the standards that APPLY to this submittal, against the ones
    it CITES. A senior engineer reviews a datasheet against the standards that
    apply to it, and says so when the contractor did not reference one.

    REQUIRED = the governing standards for the submittal's equipment type
    (`governing_standards.json`, the type read by `subject_scope`) + the
    standards of every service condition the datasheet DECLARES present
    (`service_conditions.json`, `required_standards`). The contractor's own
    citations are reviewed too; they are not "required" by this rule.

    Outcomes, every one a result (data files only, no per-document rule):
      * required and cited: nothing to say;
      * `required_not_cited`: reviewed anyway (held or not), and ONE CRS
        comment per standard - never one per requirement;
      * `cited_not_held`: the existing "missing standards" list, never met;
      * `cited_not_applicable`: a cited standard that governs only OTHER
        equipment types, or belongs to a service condition the datasheet
        declares absent - a note asking to confirm, never a verdict;
      * `declared_check`: a code the datasheet states as a field value, or
        one its type takes in part, that governs another type - engineer to check;
      * `equipment_unsure`: why the type is unsure (order 142), else None;
      * `not_used`: every other library standard, counted, not listed.
    Unknown type, no declared condition: the review behaves as before.
    """
    from . import equipment_subtype, service_scope, subject_scope

    library = _library(allowed_document_ids) if library is None else library
    text = _submittal_text(submittal_document_id, allowed_document_ids)
    referenced = datasheets.referenced_standards(text)
    cited = list(dict.fromkeys([*referenced, *(
        r["identifier"] for r in library_citations(library, text).values()
        if r["method"] == METHOD_REFERENCED)]))
    reading = _equipment_reading(submittal_document_id, allowed_document_ids)
    equipment, source, doubt, facts = reading
    gov = governing_table()
    required = equipment_subtype.required(equipment, source, text, gov, REQUIRED_BY_TYPE)
    declared_absent: list[tuple[dict, str]] = []
    for condition in service_scope.conditions():
        if condition["mode"] == "value" or not (condition["required"] or condition["standards"]):
            continue
        stated = service_scope.declaration(condition, facts)
        if stated is None:
            continue
        where = f"{stated['label']}: {stated['value']}" + (
            f", page {stated['page']}" if stated.get("page") else "")
        if stated["present"]:
            for identifier in condition["required"]:
                required.append({"identifier": identifier, "by": REQUIRED_BY_SERVICE,
                                 "reason": f"the datasheet states {condition['name']} ({where})"})
        else:
            declared_absent.append((condition, where))

    seen: set[str] = set()
    unique: list[dict] = []
    required_not_cited: list[dict] = []
    for r in required:
        k = standard_ids.key(r["identifier"])
        if k in seen:
            continue
        seen.add(k)
        unique.append(r)
        if _cited_by(cited, r["identifier"]):
            continue
        entry = find_standard(library, r["identifier"])
        required_not_cited.append({**r, "held": entry is not None,
                                   "standard_document_id": entry["id"] if entry else None})

    stated = subject_scope.stated_codes(facts) if equipment or doubt else []
    own = [r["identifier"] for r in required]
    cited_not_applicable, declared_check = _cited_other_type(
        cited, (equipment, source), own, stated
    )
    for condition, where in declared_absent:
        for c in cited:
            if any(standard_ids.same_standard(c, s) for s in condition["standards"]) \
                    and not any(x["identifier"] == c for x in cited_not_applicable):
                cited_not_applicable.append({
                    "identifier": c,
                    "reason": f"the datasheet states no {condition['name']} ({where})"})

    used = {e["id"] for e in (find_standard(library, c) for c in cited) if e}
    used |= {r["standard_document_id"] for r in required_not_cited if r["standard_document_id"]}
    used |= {e["id"] for e in (find_standard(library, r["identifier"]) for r in required) if e}
    return {
        "equipment_types": sorted(equipment),
        "cited": cited,
        "required": [{"identifier": r["identifier"], "by": r["by"], "reason": r["reason"]}
                     for r in unique],
        "required_not_cited": required_not_cited,
        "cited_not_held": missing_references(library, referenced),
        "cited_not_applicable": cited_not_applicable,
        "declared_check": declared_check,
        "equipment_unsure": doubt["reason"] if doubt else None,
        "not_used": max(0, len(library) - len(used)),
    }


def _submittal_text(document_id: str, allowed_document_ids: frozenset[str]) -> str:
    """The submittal's own chunk text, read under the caller's grants."""
    where, args = _scope_clause(allowed_document_ids, "document_id")
    rows = connect().execute(
        "SELECT text FROM chunks" + where + " AND document_id = ?",
        [*args, document_id]).fetchall()
    return " ".join(r["text"] or "" for r in rows)


def citation_evidence(document_id: str, identifier: str,
                      allowed_document_ids: frozenset[str]) -> tuple[int | None, str | None]:
    """WHERE the submittal cites `identifier`: (page, the printed line).

    B5: "named in the submittal" is a reason; the page and the printed line
    are the EVIDENCE an engineer checks it against. The chunks decide WHETHER
    the caller may see a citation - read under the caller's grants, with the
    same detector selection uses - and the PAGE's own text decides where it is.

    THE DEFECT THIS REPLACED: the chunk's `page_start` and first "line" (a
    whole prose chunk) were published - a quote of the page header, without
    the standard, on the wrong page. Now the page is the one whose text holds
    the citation, and the quote its printed line (with the line above when
    the line is only a label's value).

    (None, None) when no chunk carries it. When the page text is unavailable
    the chunk's own line is quoted, with its page only if the chunk lies on ONE
    page - a chunk spanning pages gives (None, quote), never a guessed page.
    """
    key = normalise_identifier(identifier)
    where, args = _scope_clause(allowed_document_ids, "document_id")
    rows = connect().execute(
        "SELECT page_start, page_end, text FROM chunks" + where + " AND document_id = ?"
        " ORDER BY page_start, ordinal", [*args, document_id]).fetchall()
    for row in rows:
        quote = _printed_line(row["text"] or "", key, identifier)
        if quote is None:
            continue
        first, last = row["page_start"], row["page_end"] or row["page_start"]
        for page in range(first, last + 1):
            on_page = _printed_line(_page_text(document_id, page), key, identifier)
            if on_page is not None:
                return page, on_page
        return (first if first == last else None), quote
    return None, None


def _page_text(document_id: str, page: int) -> str:
    found = connect().execute(
        "SELECT text FROM pages WHERE document_id = ? AND page_no = ?",
        (document_id, page)).fetchone()
    return (found["text"] if found else "") or ""


#: A printed line shorter than this many words is a value, not a statement -
#: "API 610" alone in a datasheet cell - so its label on the line above is
#: quoted with it.
_SHORT_LINE_WORDS = 6


#: The longest quote published as evidence.
_QUOTE_CHARS = 200


def _printed_line(text: str, key: str, identifier: str | None = None) -> str | None:
    """The line of `text` citing the standard whose key is `key`, or None.

    `identifier` (#702) is the library's own number for a standard the
    built-in detector cannot read ("XYZ-PR-0042"): when no built-in citation
    on a line has `key`, the lines are searched for that number itself, whole
    numbers only, with any dash or space between its parts.

    A line longer than a quote is cut to the words AROUND the citation, never
    to its first characters - a quote that does not contain what it is
    evidence of is not evidence.
    """
    lines = [" ".join(line.split()) for line in text.splitlines()]
    lines = [line for line in lines if line]
    for index, line in enumerate(lines):
        for raw, start, stop in datasheets.referenced_standard_spans(line):
            if normalise_identifier(raw) != key:
                continue
            return _quoted(lines, index, line, start, stop)
    pattern = standard_ids._token_pattern(identifier) if identifier else None
    if pattern is not None:
        for index, line in enumerate(lines):
            found = pattern.search(line.replace("_", " ").upper())
            if found is None:
                continue
            return _quoted(lines, index, line, found.start(), found.end())
    return None


def _quoted(lines: list[str], index: int, line: str, start: int, stop: int) -> str:
    """`line` as evidence: a bare cell value is quoted with its label above."""
    if len(line.split()) < _SHORT_LINE_WORDS and index > 0:
        shift = len(lines[index - 1]) + 1
        line, start, stop = f"{lines[index - 1]} {line}", start + shift, stop + shift
    return _around(line, start, stop)


def _around(line: str, start: int, stop: int) -> str:
    """At most `_QUOTE_CHARS` of `line`, centred on `line[start:stop]`, on word edges."""
    if len(line) <= _QUOTE_CHARS:
        return line
    lo = max(0, min(start - (_QUOTE_CHARS - (stop - start)) // 2, len(line) - _QUOTE_CHARS))
    hi = lo + _QUOTE_CHARS
    if lo > 0:
        lo = line.find(" ", lo, start) + 1 or lo
    if hi < len(line):
        cut = line.rfind(" ", stop, hi)
        hi = cut if cut != -1 else hi
    return line[lo:hi].strip()


# ------------------------------------- #139: the clauses a citation names


def _applies_whole(
    submittal_document_id: str,
    library: list[dict],
    referenced: dict[str, dict],
    allowed_document_ids: frozenset[str],
) -> set[str]:
    """The cited standards that apply WHOLE for another reason as well: the
    equipment type or a declared service requires it, it is classified for
    this equipment, service or project, or its own scope clause covers it."""
    whole = {
        sid for sid, a in referenced.items() if a.get("scope_decision") == "APPLICABLE"
    }
    check = standards_check(
        submittal_document_id, allowed_document_ids=allowed_document_ids
    )
    for r in check["required"]:
        entry = find_standard(library, r["identifier"])
        if entry is not None:
            whole.add(entry["id"])
    profile = _submittal_profile(submittal_document_id)
    for field, method in (
        ("equipment_type", METHOD_EQUIPMENT),
        ("service", METHOD_SERVICE),
        ("project", METHOD_PROJECT),
    ):
        whole |= set(_match_attribute(library, profile, field, method))
    return whole


def _citations_in(flat: str, candidates: list[dict]) -> list[tuple[dict, int, int]]:
    """Every citation of a candidate in `flat`: (entry, start, end). The
    built-in citation reader first, then each candidate's own recorded number
    (#702's company standards) on a same-length upper copy, so the positions
    are the text's; a second reading of the same citation is not counted."""
    spans = [
        (raw, s, e, None) for raw, s, e in datasheets.referenced_standard_spans(flat)
    ]
    upper = standard_ids._DASHES.sub("-", flat.replace("_", " ")).upper()
    for entry in candidates:
        names = (
            entry.get("document_number"),
            library_identifier(entry.get("filename") or ""),
        )
        for pattern in filter(
            None, (standard_ids._token_pattern(n) for n in names if n)
        ):
            spans.extend(
                (m.group(0), m.start(), m.end(), entry) for m in pattern.finditer(upper)
            )
    out: list[tuple[dict, int, int]] = []
    for raw, s, e, named in spans:
        entry = named or find_standard(candidates, raw)
        if entry is not None and not any(
            o["id"] == entry["id"] and s < oe and os_ < e for o, os_, oe in out
        ):
            out.append((entry, s, e))
    return out


def cited_clause_scope(
    submittal_document_id: str,
    applicable: list[dict],
    *,
    allowed_document_ids: frozenset[str],
) -> dict[str, dict]:
    """#139: {standard id: {"clauses", "pages"}} for every applied standard
    the datasheet names ONLY for named clauses.

    A standard is narrowed only when ALL of these hold, so this can only ever
    NARROW a review, never widen it (rule 5's direction):
      * it is applied BECAUSE the datasheet names it (`referenced`) - not by
        an engineer, and not for any other reason as well (`_applies_whole`);
      * EVERY place the datasheet names it names clauses too - one bare
        citation anywhere means the whole standard is cited. Read in the
        submittal's page text, every page in order and joined, so a citation
        or its clauses split over a page break is read whole. Not the chunk
        text: a table chunk lists its cells out of printed order, so a clause
        printed next to a citation is not next to it there.
    Whether the clauses exist in the standard is checked against the
    standard's own text by `subject_scope.citation_gate`, which narrows."""
    referenced = {
        a["standard_document_id"]: a
        for a in applicable
        if a.get("selection_method") == METHOD_REFERENCED
    }
    library = [e for e in _library(allowed_document_ids) if e["id"] in referenced]
    if not library:
        return {}
    whole = _applies_whole(
        submittal_document_id, library, referenced, allowed_document_ids
    )
    candidates = [e for e in library if e["id"] not in whole]
    if not candidates:
        return {}
    starts: list[tuple[int, int]] = []  # (offset, page number)
    flat = ""
    for row in connect().execute(
        "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
        (submittal_document_id,),
    ):
        starts.append((len(flat), row["page_no"]))
        flat += " ".join((row["text"] or "").split()) + " "
    found: dict[str, dict] = {}
    bare: set[str] = set()
    for entry, s, e in _citations_in(flat, candidates):
        clauses = standard_ids.clause_qualifiers(flat, s, e)
        if not clauses:
            bare.add(entry["id"])
            continue
        into = found.setdefault(entry["id"], {"clauses": [], "pages": []})
        for c in clauses:
            # one entry per clause: printed outright if printed anywhere, and
            # unsure if read unsure anywhere
            old = next((k for k in into["clauses"] if k == c), None)
            if old is not None:
                c = standard_ids.CitedClause(
                    *c, in_range=old.in_range and c.in_range, sure=old.sure and c.sure
                )
            into["clauses"] = [k for k in into["clauses"] if k != c] + [c]
        page = max(p for at, p in starts if at <= s)
        if page not in into["pages"]:
            into["pages"].append(page)
    return {sid: v for sid, v in found.items() if sid not in bare}


# ------------------------------------------------ B5: the scope decision

def load_taxonomy() -> dict | None:
    """The owner-approved taxonomy (`settings.applicability_taxonomy_path`),
    or None when none is approved or it cannot be read. Never a built-in
    default: the taxonomy is a proposal until the owner approves one."""
    from .config import settings
    path = settings.applicability_taxonomy_path
    # An empty APPLICABILITY_TAXONOMY_PATH= parses as Path("."), a directory:
    # anything that is not a readable file is "no taxonomy approved".
    if not path or not Path(path).is_file():
        return None
    try:
        data = json.loads(open(path, encoding="utf-8").read())
    except (OSError, ValueError):
        return None
    lexicon = {str(k).lower(): tuple(v) for k, v in (data.get("lexicon") or {}).items()
               if isinstance(v, (list, tuple)) and len(v) == 2}
    if not lexicon:
        return None
    return {"lexicon": lexicon, "types": dict(data.get("types") or {})}


def store_scope_record(standard_document_id: str, record: dict, *,
                       prompt_version: str | None = None,
                       not_applicable_confirmed: bool = False) -> None:
    """Keep a standard's VERIFIED scope record for the live review to read.

    The caller has already dropped every item whose quote did not verify
    (scope_records.verify). `not_applicable_confirmed` is True only when the
    reader's three re-reads agreed on NOT_APPLICABLE."""
    submittal_review.ensure_schema()
    conn = connect()
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO standard_scope_records"
            " (standard_document_id, record_json, prompt_version,"
            "  not_applicable_confirmed, created_at) VALUES (?,?,?,?,?)",
            (standard_document_id, json.dumps(record), prompt_version,
             1 if not_applicable_confirmed else 0, _now()))


def scope_record(standard_document_id: str) -> tuple[dict, bool] | None:
    """(record, not_applicable_confirmed), or None when never read."""
    row = connect().execute(
        "SELECT record_json, not_applicable_confirmed FROM standard_scope_records"
        " WHERE standard_document_id = ?", (standard_document_id,)).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["record_json"]), bool(row["not_applicable_confirmed"])
    except ValueError:
        return None


def scope_profile(profile: dict, taxonomy: dict):
    """The submittal as `applicability_v2.Profile`, from its classification's
    equipment type named through the approved lexicon. Unknown stays None -
    a profile with no type decides nothing but UNKNOWN."""
    from . import applicability_v2
    nodes = applicability_v2.nodes_for(profile.get("equipment_type"), taxonomy["lexicon"])
    type_name = next((name for level, name in sorted(nodes) if level == applicability_v2.TYPE), None)
    family = cls = None
    if type_name is not None:
        parents = taxonomy["types"].get(type_name) or {}
        family, cls = parents.get("family"), parents.get("class")
    return applicability_v2.Profile(type=type_name, family=family, cls=cls)


def scope_decisions(library: list[dict], profile: dict) -> tuple[dict[str, dict], str | None]:
    """{standard id: decision} for every library standard with a stored scope
    record, and why the step did not run (None when it ran).

    A NOT_APPLICABLE the reader did not confirm three times is reported as
    UNKNOWN: the asymmetric rule of applicability_v2 - a wrong exclusion
    hides a standard from the engineer, the worst error."""
    from . import applicability_v2
    taxonomy = load_taxonomy()
    if taxonomy is None:
        return {}, "scope clauses not checked: no equipment taxonomy is approved"
    p = scope_profile(profile, taxonomy)
    if p.type is None:
        return {}, "scope clauses not checked: the submittal's equipment type is unknown"
    out: dict[str, dict] = {}
    for entry in library:
        stored = scope_record(entry["id"])
        if stored is None:
            continue
        record, confirmed = stored
        decision = applicability_v2.decide(record, p, taxonomy["lexicon"])
        if decision.get("decision") == applicability_v2.NOT_APPLICABLE and not confirmed:
            decision = {**decision, "decision": applicability_v2.UNKNOWN,
                        "basis": "NOT_APPLICABLE not confirmed by three re-reads; "
                                 + str(decision.get("basis") or "")}
        out[entry["id"]] = decision
    return out, None


#: Step name for the reasoning-based scope decision (owner request
#: 2026-09-28), so its Claude-lane spend, if any, is attributed separately
#: from every other step.
SCOPE_REASONING_STEP = "scope-reasoning-decide"


def _scope_decision_record_hash(record: dict) -> str:
    """A content fingerprint of a scope record, for the cache below.

    Not the record's `created_at` or any row id - the CONTENT. Two rows
    written at different times with identical verified items must hash the
    same, so a harmless re-run of `generate_scope_records.py` that produces
    an unchanged record does not invalidate a cache that is still correct.
    """
    blob = json.dumps(record, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _cached_scope_decision(standard_document_id: str, equipment_type: str,
                           record: dict, provider, step: str) -> dict:
    """`applicability_reasoning.decide_with_confirmation_by_reasoning`,
    memoised per (standard, equipment type, exact scope-record content,
    prompt version) - B5 cost fix, owner request 2026-09-28.

    WHY: the model was asked afresh on EVERY review for every standard with
    a scope record - hundreds of calls, mostly repeats, so cost scaled with
    the library and blocked other background work (`docs/code-review/`,
    2026-09-28). A cache, not a shortcut: the full call (with its 3x
    NOT_APPLICABLE confirmation) runs once per (standard, equipment type,
    scope-record content, prompt version). A row is never served stale:
    `record_hash` changes with the scope record and `prompt_version` with
    `applicability_reasoning.PROMPT_VERSION`; a miss recomputes and overwrites.

    THE EVIDENCE BACKFILL (`with_covered_evidence`) RUNS ON EVERY RETURN, hit
    or miss, never in what is STORED (bug fix 2026-09-28): stored, it would
    freeze into old rows, which would come back without a quote forever.
    """
    from . import applicability_reasoning
    record_hash = _scope_decision_record_hash(record)
    prompt_version = applicability_reasoning.PROMPT_VERSION
    submittal_review.ensure_schema()
    conn = connect()
    row = conn.execute(
        "SELECT decision_json FROM applicability_scope_decision_cache"
        " WHERE standard_document_id = ? AND equipment_type = ?"
        " AND record_hash = ? AND prompt_version = ?",
        (standard_document_id, equipment_type, record_hash, prompt_version)).fetchone()
    if row is not None:
        try:
            cached = json.loads(row["decision_json"])
        except ValueError:
            cached = None  # corrupt row - fall through and recompute rather than crash
        if cached is not None:
            return applicability_reasoning.with_covered_evidence(cached, record)
    decision = applicability_reasoning.decide_with_confirmation_by_reasoning(
        record, equipment_type, provider, step=step)
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO applicability_scope_decision_cache"
            " (standard_document_id, equipment_type, record_hash, prompt_version,"
            "  decision_json, created_at) VALUES (?,?,?,?,?,?)",
            (standard_document_id, equipment_type, record_hash, prompt_version,
             json.dumps(decision), _now()))
    return applicability_reasoning.with_covered_evidence(decision, record)


def _scope_reasoning_candidates(
    library: list[dict], selected: dict[str, dict], submittal_document_id: str,
    allowed_document_ids: frozenset[str], *, cap: int,
) -> list[dict]:
    """#946: the pool the AI scope-reasoning step is allowed to ask about -
    every standard a CHEAPER route already surfaced, plus up to `cap` more
    ranked by the submittal's own distinctive words. `cap <= 0` or a library
    no bigger than it: the whole library, unchanged (today's behaviour).

    Never drops a standard any other route already found - only stops
    ASKING THE MODEL about standards nothing else suggests either, the same
    bounded risk `_match_semantic` already accepts for suggesting a standard
    to an engineer, applied here to spending a model call checking one.
    """
    if cap <= 0 or len(library) <= cap:
        return library
    wanted = {entry["id"] for entry in library if entry["id"] in selected}
    remaining = cap - len(wanted)
    if remaining > 0:
        ranked = _match_semantic(submittal_document_id, library, allowed_document_ids,
                                 limit=remaining + len(wanted))
        for standard_id in ranked:
            if len(wanted) >= cap:
                break
            wanted.add(standard_id)
    return [entry for entry in library if entry["id"] in wanted]


def scope_decisions_by_reasoning(library: list[dict], profile: dict,
                                 provider=None, heartbeat=None) -> tuple[dict[str, dict], str | None]:
    """`scope_decisions`, without a taxonomy: the AI reads a standard's
    already-verified scope record directly against the submittal's own
    classified equipment type (`applicability_reasoning.py`, owner request
    2026-09-28 - no manual equipment lexicon).

    Same shape and same safety rule as `scope_decisions`: {standard id:
    decision}, and why the step did not run (None when it ran). A
    NOT_APPLICABLE the reader did not confirm three times is reported as
    UNKNOWN - a wrong exclusion hides a standard from the engineer, the
    worst error.

    A standard with no stored scope record is skipped exactly like the
    taxonomy path skips one - `scripts/generate_scope_records.py` is the
    explicit step that creates them; this function only reads.

    `heartbeat`, optional (`ingest.IngestionWorker` passes its `_beat`):
    called after every standard WITH a stored scope record, hit or miss. One
    uncached call can run 15-20+ minutes, and the worker's own heartbeat
    only ticks between jobs, so without it the worker read as "not moving".
    """
    equipment_type = profile.get("equipment_type")
    if not equipment_type:
        return {}, "scope clauses not checked: the submittal's equipment type is unknown"
    out: dict[str, dict] = {}
    ran_any = False
    for entry in library:
        stored = scope_record(entry["id"])
        if stored is None:
            continue
        record, _confirmed = stored
        ran_any = True
        try:
            from . import reasoning_provider as rp
            engine = provider or rp.get_provider("reasoning", step=SCOPE_REASONING_STEP)
            # #806 S3: the prompt carries this standard's scope quotes (and
            # the submittal's equipment TYPE, a classification label only).
            from . import claude_approved
            with claude_approved.carrying([entry["id"]]):
                decision = _cached_scope_decision(
                    entry["id"], equipment_type, record, engine, SCOPE_REASONING_STEP)
        except Exception as exc:  # noqa: BLE001 - budget cap, refusal or a down model:
            # stays with an engineer as "not decided", never crashes the review. #450: AND SAYS SO.
            # It used to be skipped with no record, so a model that was down for every standard read
            # as "scope checked, nothing excluded". The standard is UNKNOWN, with the reason.
            errors.fell_back("applicability: scope check failed", exc, None)
            from . import applicability_v2
            out[entry["id"]] = {
                "decision": applicability_v2.UNKNOWN, "quote": None, "page": None,
                "basis": ("could not be checked: the scope reasoning did not "
                          f"complete ({type(exc).__name__})")}
            continue
        finally:
            if heartbeat is not None:
                heartbeat()
        out[entry["id"]] = decision
    if not ran_any:
        return {}, "scope clauses not checked: no standard in the library has a verified scope record yet"
    return out, None

# --------------------------------------------------------------- selection

def _library_names(entry: dict) -> list[str]:
    """The names a library entry is known by, most reliable first."""
    return [name for name in (
        entry.get("document_number"),
        # The PARSED number before the raw filename: the raw form carries
        # revision text ("SAES-B-14 -Final Draft 01-29-23"), and an exact
        # key of it matches no citation.
        library_identifier(entry.get("filename") or ""),
        entry.get("filename")) if name]


def find_standard(library: list[dict], identifier: str) -> dict | None:
    """The library entry `identifier` names, or None. THE lookup (#452).

    An exact key first, so a citation written the way the library writes it
    always finds that entry. Then `standard_ids.same_standard`, which reads
    family, number and part: "API RP 520 Pt-1" finds the API 520 Part I
    document, and "API 65" never finds API 650. There is no prefix rule any
    more - it was the A02/A03 defect ("API650".startswith("API65")).
    """
    key = normalise_identifier(identifier)
    if not key:
        return None
    for entry in library:
        if any(normalise_identifier(name) == key for name in _library_names(entry)):
            return entry
    for entry in library:
        if any(standard_ids.same_standard(identifier, name) for name in _library_names(entry)):
            return entry
    return None


def _match_referenced(library: list[dict], referenced: list[str]) -> dict[str, dict]:
    """Rule 1: standards the datasheet NAMES that are in the library."""
    out: dict[str, dict] = {}
    for identifier in referenced:
        entry = find_standard(library, identifier)
        if entry is not None:
            out[entry["id"]] = {
                "method": METHOD_REFERENCED,
                "reason": f"named in the submittal as {identifier}",
                "identifier": identifier,
            }
    return out


#: A file name's leading identifier: letters and digits joined by - or _
#: ("STD-Q-210" in "STD-Q-210_Ed2024.pdf"). Trailing edition/revision groups
#: are not part of the number.
_FILE_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+){1,6}")
_EDITION_GROUP = re.compile(r"^(?:ed|edn|rev|r|v|issue|iss)\d*$|^(?:19|20)\d\d$|^\d{1,2}$",
                            re.IGNORECASE)


def _identifier_like(text: str) -> bool:
    """Enough to identify one standard: a digit, a letter, five characters."""
    alnum = re.sub(r"[^A-Za-z0-9]", "", text or "")
    return (len(alnum) >= 5 and any(c.isdigit() for c in alnum)
            and any(c.isalpha() for c in alnum))


def _file_identifier(filename: str) -> str | None:
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", filename or "").strip()
    match = _FILE_IDENTIFIER.match(stem)
    if match is None:
        return None
    groups = re.split(r"[-_]", match.group(0))
    while len(groups) > 2 and _EDITION_GROUP.match(groups[-1]):
        groups.pop()
    ident = "-".join(groups)
    return ident if _identifier_like(ident) and len(groups) >= 2 else None


def _fold_words(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))


def library_citations(library: list[dict], text: str) -> dict[str, dict]:
    """Library standards the submittal names by THE LIBRARY'S OWN identifiers (#702).

    `datasheets.referenced_standards` only reads the built-in families, so a
    company or project standard numbered any other way ("STD-Q-210",
    "ABC-ENG-PRC-0042 Rev 3") was never "cited", and a review selected none of
    the standards its datasheets named (0 of 3 on every hidden-exam datasheet).
    This starts from the other end: for each library standard, is its OWN
    identifier in the text? Matching is `standard_ids.names_standard`'s: whole
    numbers, any dash or space between the parts, never a substring.

    Three sources, strongest first:
      * the recorded `document_number`: REFERENCED, included - the number on the
        standard's own cover and the number in the submittal agree;
      * the identifier at the start of the FILE NAME, and the TITLE (three or
        more words): `possible_citation`, shown as "possible match, engineer to
        confirm", never silently dropped and never silently included.
    One row per library standard, the strongest source.
    """
    folded_text = " " + _fold_words(text) + " "
    out: dict[str, dict] = {}
    for entry in library:
        number = (entry.get("document_number") or "").strip()
        if _identifier_like(number) and standard_ids.names_standard(text, number):
            out[entry["id"]] = {
                "method": METHOD_REFERENCED, "identifier": number,
                "reason": f"named in the submittal as {number} (this standard's document number)"}
            continue
        from_file = _file_identifier(entry.get("filename") or "")
        if from_file and standard_ids.names_standard(text, from_file):
            out[entry["id"]] = {
                "method": METHOD_POSSIBLE, "identifier": from_file,
                "reason": (f"possible match, engineer to confirm: the submittal names {from_file}, "
                           "which is the number at the start of this file's name")}
            continue
        title = _fold_words(entry.get("title") or "")
        if len(title.split()) >= 3 and f" {title} " in folded_text:
            out[entry["id"]] = {
                "method": METHOD_POSSIBLE, "identifier": None,
                "reason": ("possible match, engineer to confirm: the submittal names this "
                           f"standard's title ({entry.get('title')})")}
    return out


def missing_references(library: list[dict], referenced: list[str]) -> list[str]:
    """The standards a submittal CITES that the library does not hold.

    ONE HOME FOR THIS RULE, because two copies were both wrong: the dashboard
    and the CRS export checked identifiers against `_match_referenced`, which
    is keyed by DOCUMENT ID, so EVERY cited standard was reported missing
    (15 of 15 on one sheet, six of them in the library).

    Asked PER NAME, of `find_standard` itself (#452): a result keyed by
    document keeps one identifier when two spellings reach the same standard
    ("API RP 520 Pt-1" and "API RP 520"), and the other would read missing.
    `select` used to keep such a second copy; it now asks here.

    Returns the cited names in the submittal's own spelling, one per standard
    (two spellings of one missing standard are listed once), in citation order.
    """
    missing: list[str] = []
    seen: set[str] = set()
    for name in referenced:
        key = standard_ids.key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        if find_standard(library, name) is None:
            missing.append(name.strip())
    return missing


def _match_attribute(library: list[dict], profile: dict, field: str,
                     method: str) -> dict[str, dict]:
    """Rules 2, 3, 4 and 6: a shared classification attribute.

    Compared case-insensitively and only when BOTH sides have a value. A null
    on either side is not a match - "this standard has no discipline recorded"
    and "this submittal has no discipline recorded" are not evidence that they
    belong together.
    """
    wanted = (profile.get(field) or "").strip().lower()
    if not wanted:
        return {}
    out: dict[str, dict] = {}
    for entry in library:
        value = (entry.get(field) or "").strip().lower()
        if value and value == wanted:
            out[entry["id"]] = {
                "method": method,
                "reason": f"{field.replace('_', ' ')} matches the submittal: {wanted}",
                "identifier": entry.get("document_number"),
            }
    return out


def _match_semantic(document_id: str, library: list[dict],
                    allowed_document_ids: frozenset[str],
                    limit: int = 5) -> dict[str, dict]:
    """Rule 5: standards whose text resembles the submittal's.

    FTS5 over the submittal's own words, restricted to the library ids and to
    the caller's grants - ACCESS FILTERS BEFORE RANKING, never after, which is
    what `fts_index.search`'s keyword-only parameter enforces.

    THE WEAKEST RULE, AND IT IS TREATED AS ONE. It carries the lowest
    confidence, it is overridden by every other method, and it can never cover
    for a missing explicit reference.
    """
    library_ids = frozenset(e["id"] for e in library)
    searchable = library_ids & allowed_document_ids
    if not searchable:
        return {}
    where, args = _scope_clause(allowed_document_ids, "document_id")
    rows = connect().execute(
        "SELECT text FROM chunks" + where + " AND document_id = ? LIMIT 20",
        [*args, document_id]).fetchall()
    terms = _distinctive_terms(" ".join(r["text"] or "" for r in rows))
    if not terms:
        return {}
    try:
        hits = fts_index.search(" OR ".join(terms), limit=limit,
                              allowed_document_ids=searchable)
    except Exception as exc:  # noqa: BLE001 - a retrieval failure is not a selection
        return errors.fell_back("applicability: keyword search failed", exc, {})
    out: dict[str, dict] = {}
    for hit in hits:
        standard_id = hit.get("document_id")
        if standard_id in library_ids:
            out[standard_id] = {
                "method": METHOD_SEMANTIC,
                "reason": "retrieved as textually similar to the submittal; "
                          "NOT a citation and not evidence of applicability "
                          "on its own",
                "identifier": None,
            }
    return out


_STOPWORDS = frozenset({
    "the", "and", "for", "with", "shall", "this", "that", "from", "are", "was",
    "data", "sheet", "page", "note", "rev", "no", "of", "to", "in", "at", "by",
})


def _distinctive_terms(text: str, limit: int = 12) -> list[str]:
    """The submittal's own distinctive words, for the semantic probe."""
    counts: dict[str, int] = {}
    for word in re.findall(r"[A-Za-z]{4,}", text or ""):
        lower = word.lower()
        if lower in _STOPWORDS:
            continue
        counts[lower] = counts.get(lower, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [word for word, _count in ranked[:limit]]


def _semantic_cannot_cover_a_missing_reference(
    selected: dict[str, dict], missing: list[dict],
) -> tuple[dict[str, dict], list[dict]]:
    """THE GUARD THIS PHASE EXISTS FOR.

    A standard the submittal CITES and the library does not hold stays on the
    missing list, whatever else retrieval turned up. Nothing is removed from
    the selection - a semantically similar standard may well be worth reading -
    but it is never allowed to mark a citation satisfied.

    Concretely: a client pump datasheet cites API 610. API 610 is not in the
    library. Dense retrieval finds a NORSOK coating standard. Without this, the
    coating standard appears as "applicable", the API 610 line disappears, and
    a review that could not have been performed reads as complete.

    So the function returns the missing list UNCHANGED, and marks every
    semantic row with the fact that it satisfies nothing. That is the whole
    job: it is written as its own function, with its own name, so that deleting
    it is a visible act rather than an edited condition.
    """
    for row in selected.values():
        if row["method"] == METHOD_SEMANTIC:
            row["satisfies_reference"] = False
    return selected, missing


def _hold_on_unsure_type(selected: dict, check: dict, library: list, profile: dict):
    """Order 142: an unsure equipment type rules nothing in or out. AI-first:
    the scope reasoning ran, but no row is excluded by it ("engineer to
    check"). A row from the type alone is held for the engineer, or falls
    back to its service or project match; a declared code says so."""
    unsure = check.get("equipment_unsure")
    declared = check.get("declared_check") or []
    other: dict = {}
    if unsure:
        other = _match_attribute(library, profile, "project", METHOD_PROJECT)
        other |= _match_attribute(library, profile, "service", METHOD_SERVICE)
    for sid, row in list(selected.items()) if unsure else ():
        if row["method"] in (METHOD_EQUIPMENT, METHOD_SCOPE) and sid in other:
            note = row.get("excluded_by_scope")
            row = selected[sid] = {**other[sid], "excluded_by_scope": note}
        scoped_out = row.pop("excluded_by_scope", None)
        if scoped_out:
            tail = "the equipment type is unsure, engineer to check"
            row["reason"] = f"{row['reason']}; {scoped_out} - {tail}"
        if row["method"] in (METHOD_EQUIPMENT, METHOD_SCOPE):
            why = f"it came only from the equipment type ({unsure})"
            row["held_for_engineer"] = f"held for the engineer to check: {why}"
            continue
        ident = row.get("identifier") if row["method"] == METHOD_REFERENCED else None
        said = [d for d in declared if ident and _cited_by([d["identifier"]], ident)]
        if said:
            tail = "the equipment type is unsure - engineer to confirm"
            row["reason"] = f"{row['reason']}; {said[0]['reason']}; {tail}"


def select(
    submittal_document_id: str, *, allowed_document_ids: frozenset[str],
    review_run_id: str | None = None, persist: bool = True,
    actor: dict | None = None, heartbeat=None,
) -> dict:
    """Which standards apply to this submittal, why, and what is missing.

    Runs every rule, keeps the STRONGEST reason per standard, and reports what
    the submittal cites that the library does not hold.

    ZERO APPLICABLE STANDARDS IS A VALID ANSWER, not an error. On this
    repository's corpus it is the CORRECT answer for a client datasheet: every
    standard those sheets cite is absent, and a system that found some anyway
    would be lying.
    """
    submittal_review.ensure_schema()
    library = _library(allowed_document_ids)
    profile = _submittal_profile(submittal_document_id)
    submittal_text = _submittal_text(submittal_document_id, allowed_document_ids)
    referenced = datasheets.referenced_standards(submittal_text)

    governing, governing_missing = governing_standards(
        submittal_document_id, library, allowed_document_ids)
    # #754 F5b: required vs cited FIRST. A standard a declared service
    # condition requires, held but not cited, is reviewed anyway.
    check = standards_check(submittal_document_id, allowed_document_ids=allowed_document_ids,
                            library=library)
    for r in check["required_not_cited"]:
        if r["by"] == REQUIRED_BY_SERVICE and r["standard_document_id"] \
                and r["standard_document_id"] not in governing:
            governing[r["standard_document_id"]] = {
                "method": METHOD_GOVERNING, "identifier": r["identifier"],
                "reason": f"{r['identifier']} is required because {r['reason']}"}

    selected: dict[str, dict] = {}
    for candidates in (
        _match_referenced(library, referenced),
        library_citations(library, submittal_text),
        _match_attribute(library, profile, "equipment_type", METHOD_EQUIPMENT),
        # After the classification match: a tie keeps the standard's own
        # equipment classification as the reason (both are included).
        governing,
        _match_attribute(library, profile, "service", METHOD_SERVICE),
        _match_attribute(library, profile, "project", METHOD_PROJECT),
        _match_semantic(submittal_document_id, library, allowed_document_ids),
    ):
        for standard_id, row in candidates.items():
            existing = selected.get(standard_id)
            if existing is None or _PRIORITY[row["method"]] < _PRIORITY[existing["method"]]:
                selected[standard_id] = dict(row)

    missing = [
        # By THE IDENTIFIER THE DATASHEET USED; ONE helper (#452: a rebuilt list lost a spelling).
        {"identifier": identifier,
         "reason": "cited by the submittal and not present in the library"}
        for identifier in missing_references(library, referenced)
    ]
    selected, missing = _semantic_cannot_cover_a_missing_reference(selected, missing)

    # B5: THE EVIDENCE for every citation - the page and the line it is on.
    for standard_id, row in selected.items():
        if row["method"] in (METHOD_REFERENCED, METHOD_POSSIBLE) and row.get("identifier"):
            page, quote = citation_evidence(
                submittal_document_id, row["identifier"], allowed_document_ids)
            row["evidence_page"], row["evidence_quote"] = page, quote
            if page is not None:
                row["reason"] = f"{row['reason']} (page {page})"

    # B5: THE SCOPE DECISION on every standard with a verified scope record: by AI reasoning
    # (owner 2026-09-28, on since #736), or when off the taxonomy path (`applicability_v2`).
    from . import standard_judgment
    from .config import settings as _settings
    if _settings.applicability_reasoning_enabled:
        # #946: cap the pool asked about (`_scope_reasoning_candidates`); the
        # cheap non-AI taxonomy path below still scans the whole library.
        scope_candidates = _scope_reasoning_candidates(
            library, selected, submittal_document_id, allowed_document_ids,
            cap=_settings.applicability_scope_reasoning_candidate_cap)
        decisions, scope_not_run = scope_decisions_by_reasoning(
            scope_candidates, profile, heartbeat=heartbeat)
    else:
        scope_candidates = library
        decisions, scope_not_run = scope_decisions(library, profile)
    from . import applicability_v2 as v2
    for standard_id, decision in decisions.items():
        verdict = decision.get("decision")
        evidence = {"evidence_page": decision.get("page"),
                    "evidence_quote": decision.get("quote"),
                    "scope_decision": verdict}
        # HONEST RENDERING (2026-09-28): an empty quote once printed `""` as a
        # citation. `decide_by_reasoning` backs every APPLICABLE(_CANDIDATE)
        # with the record's verified quote; a NULL that survives (a generic
        # scope naming no item) says so in plain words.
        cited = (f"\"{decision.get('quote')}\" (page {decision.get('page')})"
                 if decision.get("quote") else "no specific quoted clause")
        row = selected.get(standard_id)
        if verdict == v2.APPLICABLE and (row is None or row["method"] not in INCLUDING_METHODS):
            selected[standard_id] = {
                "method": METHOD_SCOPE, "identifier": None, **evidence,
                "reason": f"its scope clause covers this equipment: {cited}"}
        elif verdict == v2.NOT_APPLICABLE and row is not None:
            if row["method"] == METHOD_REFERENCED:
                # CITED STANDARDS ARE NEVER EXCLUDED BY A SCOPE READING: the
                # datasheet says it governs. The disagreement is shown.
                row["scope_decision"] = verdict
                row["reason"] = (f"{row['reason']}; its scope clause reads as not "
                                 f"covering this equipment ({cited}) - engineer to confirm")
            else:
                row.update(evidence)
                row["excluded_by_scope"] = (
                    f"its scope clause excludes this equipment: {cited}")
        elif row is not None:
            row["scope_decision"] = verdict
    _hold_on_unsure_type(selected, check, library, profile)  # order 142
    standard_judgment.hold(selected, check, library, find_standard)

    if persist:
        _persist(submittal_document_id, review_run_id, selected, allowed_document_ids,
                 scope_not_run=scope_not_run)
        _audit("review.applicability_selected", actor, submittal_document_id,
               detail=f"selected={len(selected)} missing={len(missing)} "
                      f"library={len(library)}")

    return {
        "submittal_document_id": submittal_document_id,
        "review_run_id": review_run_id,
        # Every candidate with its method and reason; `included` says which
        # ones the review applies (B5: evidence methods only).
        "selected": [
            {"standard_document_id": sid, **row, "included": is_included(row)}
            for sid, row in sorted(
                selected.items(), key=lambda kv: _PRIORITY[kv[1]["method"]])
        ],
        "scope_decision_not_run": scope_not_run,
        "missing_references": missing,
        # #725 F5: governing standards for the equipment type that the library
        # does not hold. Apart from `missing_references` (which the CRS words
        # as "this submittal cites"): the submittal did not cite these.
        "governing_not_held": [
            g for g in governing_missing
            if standard_ids.key(g["identifier"]) not in {standard_ids.key(m["identifier"]) for m in missing}],
        "referenced_total": len(referenced),
        "library_size": len(library),
        # #946: how many of the library's standards the AI scope-reasoning
        # step actually asked about, out of how many it could have (every
        # count states its boundary - CLAUDE.md rule 4). Equal to
        # `library_size` when the candidate cap did not bind (or is off, or
        # the non-AI taxonomy path ran instead - that path still scans the
        # whole library, unchanged).
        "scope_candidates_asked": len(scope_candidates),
        # #754 F5b: required vs cited, computed from the same library.
        "standards_check": check,
        **completeness(selected, missing, submittal_document_id,
                       allowed_document_ids=allowed_document_ids),
    }


def route_counts(submittal_document_id: str, *, allowed_document_ids: frozenset[str]) -> dict:
    """#946: how many standards each selection route touched, for ONE
    submittal - counts only, never a document, a clause or a quote (CLAUDE.md
    rule 1). One number per method `select()` can record (the STRONGEST route
    per standard, same merge `select()` itself does), plus how many of the
    library's standards no route touched at all, and how many ended up
    `included`.

    READ-ONLY (`persist=False`, nothing written). Run this before and after a
    change to a selection route to see its actual effect on one real
    submittal, without creating a review run - this is the tool #946's
    measurement step uses, and the one to re-run on a real submittal to
    cross-check an invented-fixture measurement.
    """
    result = select(submittal_document_id, allowed_document_ids=allowed_document_ids,
                    persist=False)
    by_method = dict.fromkeys(_PRIORITY, 0)
    included = 0
    for row in result["selected"]:
        by_method[row["method"]] += 1
        if row["included"]:
            included += 1
    return {
        "submittal_document_id": submittal_document_id,
        "library_size": result["library_size"],
        "by_method": by_method,
        "included": included,
        "considered_not_included": len(result["selected"]) - included,
        "no_route_matched": result["library_size"] - len(result["selected"]),
        # #946: how many standards actually got an AI scope-reasoning model
        # call this run - the speed measurement, out of `library_size`.
        "scope_candidates_asked": result["scope_candidates_asked"],
    }


def completeness(selected: dict, missing: list, submittal_document_id: str, *,
                 allowed_document_ids: frozenset[str]) -> dict:
    """How much of this review could actually be performed.

    ONE FORMULA (B10). This module computes only what it alone knows - the
    share of cited standards held locally - and delegates the extraction half
    and the combination to `comparison.completeness_for_run`, the formula that
    decides the review code. It used to carry a second formula (pages with a
    fact / page count, multiplied), which disagreed with the gate's and, with
    the page count unknown, reported extraction 1.0 for any sheet with facts.

    None when there is nothing to judge - never 0 - and None when the
    extraction half was never measured (B18), except where the reference half
    is already 0; both rules now live in that one function.
    """
    from . import comparison  # local: comparison does not import this module

    referenced_total = len(missing) + sum(
        1 for row in selected.values() if row["method"] == METHOD_REFERENCED)
    reference_coverage = (
        round((referenced_total - len(missing)) / referenced_total, 3)
        if referenced_total else None)
    run = comparison.completeness_for_run(
        submittal_document_id, allowed_document_ids=allowed_document_ids,
        reference_coverage=reference_coverage)
    return {
        "reference_coverage": reference_coverage,
        "extraction_coverage": run["extraction_coverage"],
        "completeness": run["completeness"],
    }


# --------------------------------------------- applicability with reasons

#: Held, matched to this submittal, and has at least one extracted
#: requirement to compare a submitted value against.
STATUS_APPLICABLE_ASSESSABLE = "applicable_assessable"
#: Held and matched, but nothing has been extracted from it yet - the
#: standard applies, but this review cannot assess against it until that
#: extraction (a document-side action, not a submittal defect) happens.
STATUS_APPLICABLE_NEEDS_ANOTHER_DOCUMENT = "applicable_needs_another_document"
#: Held, not matched by any rule, and the submittal and this standard have
#: enough recorded attributes to say so with a stated reason.
STATUS_NOT_APPLICABLE = "not_applicable"
#: Held, not matched, but neither the submittal nor the standard records
#: enough (equipment type, service, project) to judge either way - a real
#: "don't know", not a disguised "not applicable".
STATUS_UNKNOWN = "unknown"

#: THE FIELDS THIS FUNCTION MAY COMPARE FOR A "DOES NOT MATCH" CLAIM.
#: `discipline` IS DELIBERATELY EXCLUDED (owner spot-check, 2026-09-25): for a
#: COMPANY_STANDARD it is the owning committee ("Piping Standards Committee",
#: read off the cover page; 178 of 179 on the live corpus), for a
#: CONTRACTOR_SUBMITTAL a broad category ("Mechanical", from its title block).
#: Two DIFFERENT VOCABULARIES: equality can only give a false "does not match"
#: (9 of 10 sampled `not_applicable` verdicts were exactly this). No
#: committee-to-category mapping exists (`disciplines.canonical` only folds
#: spellings), so `discipline` is evidence to SHOW, never to COMPARE here.
_COMPARABLE_FIELDS = ("equipment_type", "service", "project")


def applicability_with_reasons(submittal_document_id: str, *,
                               allowed_document_ids: frozenset[str]) -> list[dict]:
    """Every standard in the caller's library, classified for THIS submittal
    into exactly one of four buckets - applicable and assessable, applicable
    but needs another document, not applicable (with the reason), or
    unknown - per the master order.

    BUILT ENTIRELY FROM WHAT `select()` AND `standards.list_standards`
    ALREADY COMPUTE. No new inference or confidence score: it only
    RECLASSIFIES `select()`'s output into the four buckets, with a reason from
    the attribute comparisons `_match_attribute` already makes (never a
    semantic judgement no field-for-field comparison backs). An unsure
    equipment type (order 142) is not compared.

    "NOT APPLICABLE" IS NEVER GUESSED FROM SILENCE. A standard, or a
    submittal, with no recorded equipment_type/service/project cannot be
    compared on those axes - that is `STATUS_UNKNOWN`, never "not
    applicable". `discipline` is not a comparable axis (`_COMPARABLE_FIELDS`).
    """
    result = select(submittal_document_id,
                    allowed_document_ids=allowed_document_ids, persist=False)
    # B5: only rows the review APPLIES are "selected"; a candidate the policy
    # did not include (a discipline match alone, similar wording, a confirmed
    # scope exclusion) is reported with that reason, never as applicable.
    selected_by_id = {row["standard_document_id"]: row
                      for row in result["selected"] if row["included"]}
    considered_by_id = {row["standard_document_id"]: row
                        for row in result["selected"] if not row["included"]}
    profile = _submittal_profile(submittal_document_id)
    if result["standards_check"]["equipment_unsure"]:  # order 142: not an axis
        profile = {**profile, "equipment_type": None}
    library = _library(allowed_document_ids)
    requirement_counts = {
        row["id"]: row["requirement_count"]
        for row in standards.list_standards(
            allowed_document_ids=allowed_document_ids, include_superseded=True)}

    submittal_has_profile = any(
        (profile.get(f) or "").strip() for f in _COMPARABLE_FIELDS)

    out: list[dict] = []
    for entry in library:
        std_id = entry["id"]
        selection = selected_by_id.get(std_id)
        if selection is not None:
            if requirement_counts.get(std_id):
                status = STATUS_APPLICABLE_ASSESSABLE
                reason = f"selected ({selection['method']}): {selection['reason']}"
            else:
                status = STATUS_APPLICABLE_NEEDS_ANOTHER_DOCUMENT
                reason = (f"selected ({selection['method']}): "
                          f"{selection['reason']}, but no requirements have "
                          "been extracted from this standard yet - nothing "
                          "here has been compared against the submittal")
            out.append({"standard_document_id": std_id,
                       "document_number": entry.get("document_number"),
                       "filename": entry.get("filename"),
                       "status": status, "reason": reason})
            continue

        considered = considered_by_id.get(std_id)
        if considered is not None:
            scoped_out = considered.get("excluded_by_scope")
            out.append({
                "standard_document_id": std_id,
                "document_number": entry.get("document_number"),
                "filename": entry.get("filename"),
                "status": STATUS_NOT_APPLICABLE if scoped_out else STATUS_UNKNOWN,
                "reason": scoped_out or considered.get("held_for_engineer") or (
                    f"considered ({considered['method']}): {considered['reason']} - "
                    + CANDIDATE_ONLY_REASON.get(considered["method"], "not included")),
            })
            continue

        standard_has_profile = any(
            (entry.get(f) or "").strip() for f in _COMPARABLE_FIELDS)
        if not submittal_has_profile or not standard_has_profile:
            out.append({
                "standard_document_id": std_id,
                "document_number": entry.get("document_number"),
                "filename": entry.get("filename"),
                "status": STATUS_UNKNOWN,
                "reason": ("not cited by the submittal, and " + (
                    "the submittal" if not submittal_has_profile
                    else "this standard") +
                    " has no recorded equipment type, service or project "
                    "to compare - applicability cannot be determined"),
            })
            continue

        mismatches = [
            f"{field.replace('_', ' ')} '{entry.get(field)}' does not match "
            f"the submittal's '{profile.get(field)}'"
            for field in _COMPARABLE_FIELDS
            if (entry.get(field) or "").strip()
            and (profile.get(field) or "").strip()
            and entry[field].strip().lower() != profile[field].strip().lower()
        ]
        if not mismatches:
            # #450: NOTHING TO COMPARE IS NOT "NOT APPLICABLE". Both sides have
            # a profile, but they share no filled axis, so nothing was shown to
            # differ. Absence of a shared field is UNKNOWN, never an exclusion.
            out.append({"standard_document_id": std_id,
                       "document_number": entry.get("document_number"),
                       "filename": entry.get("filename"),
                       "status": STATUS_UNKNOWN,
                       "reason": ("not cited by the submittal, and no shared equipment "
                                  "type, service or project is recorded on both sides - "
                                  "applicability cannot be determined")})
            continue
        out.append({"standard_document_id": std_id,
                   "document_number": entry.get("document_number"),
                   "filename": entry.get("filename"),
                   "status": STATUS_NOT_APPLICABLE, "reason": "; ".join(mismatches)})

    order = {STATUS_APPLICABLE_ASSESSABLE: 0,
            STATUS_APPLICABLE_NEEDS_ANOTHER_DOCUMENT: 1,
            STATUS_UNKNOWN: 2, STATUS_NOT_APPLICABLE: 3}
    return sorted(out, key=lambda r: (
        order[r["status"]], r["document_number"] or r["filename"] or ""))


# ----------------------------------------------------------- persistence


def _audit(action: str, actor: dict | None, resource_id: str | None,
           detail: str | None = None, *, conn=None) -> None:
    """Durable record of a selection decision. Ids and counts only.

    Never swallowed (B10): it used to catch every error, so a decision could
    stand with no audit row. Given `conn`, it is written inside the caller's
    transaction and rolls back with it."""
    if conn is not None:
        conn.execute(_AUDIT_SQL, _audit_args(action, actor, resource_id, detail))
        return
    own = connect()
    with own:
        own.execute(_AUDIT_SQL, _audit_args(action, actor, resource_id, detail))


_AUDIT_SQL = """INSERT INTO audit_events
       (at, actor_user_id, actor_username, action,
        resource_type, resource_id, outcome, detail)
   VALUES (?, ?, ?, ?, 'review', ?, 'ok', ?)"""


def _audit_args(action, actor, resource_id, detail) -> tuple:
    return (_now(), (actor or {}).get("id"),
            ((actor or {}).get("email") or "unauthenticated")[:200],
            action, resource_id, detail)


def record_selection(
    *, review_run_id: str, standard_document_id: str, method: str,
    reason: str, confidence: float | None = None, included: bool = True,
    exclusion_reason: str | None = None, evidence_page: int | None = None,
    evidence_quote: str | None = None, scope_decision: str | None = None,
    audit: tuple | None = None,
) -> dict:
    """Write one row of `review_applicable_standards`.

    `audit` - (action, actor, resource_id, detail) - is written in the SAME
    transaction as the row, so an engineer's override is never stored
    unaudited (B10).

    NO STANDARD ON THE LIST WITHOUT A REASON AND A METHOD. Both are refused
    when empty rather than defaulted, because "it was retrieved" is not a
    reason an engineer can act on and a row without one is a recommendation
    nobody can audit.

    An EXCLUDED row needs its own reason. "We looked at this and it did not
    apply" is an answer an engineer asks for, and it is the reason the row is
    kept rather than deleted.
    """
    submittal_review.ensure_schema()
    if method not in _PRIORITY:
        raise ApplicabilityError(f"unknown selection method {method!r}")
    if not (reason or "").strip():
        raise ApplicabilityError("a selection without a reason is not auditable")
    if not included and not (exclusion_reason or "").strip():
        raise ApplicabilityError("an excluded standard must say why")
    ceiling = _CONFIDENCE[method]
    if confidence is None:
        confidence = ceiling
    # CONFIDENCE IS NEVER "high" (CLAUDE.md rule 4). The per-method ceiling is
    # the cap, so no caller can talk a selection up past what its evidence is.
    confidence = min(float(confidence), ceiling)

    row = {
        "id": str(uuid.uuid4()),
        "review_run_id": review_run_id,
        "standard_document_id": standard_document_id,
        "selection_reason": reason.strip(),
        "selection_method": method,
        "confidence": confidence,
        "included": 1 if included else 0,
        "exclusion_reason": exclusion_reason,
        "created_at": _now(),
        "evidence_page": evidence_page,
        "evidence_quote": evidence_quote,
        "scope_decision": scope_decision,
    }
    conn = connect()
    with conn:
        # P2: AN ENGINEER'S OVERRIDE IS NEVER REPLACED BY THE MACHINE. A later
        # automatic selection on the same run keeps the manual row as it is.
        existing = conn.execute(
            "SELECT selection_method FROM review_applicable_standards"
            " WHERE review_run_id = ? AND standard_document_id = ?",
            (review_run_id, standard_document_id)).fetchone()
        if (existing is not None and existing["selection_method"] == METHOD_MANUAL
                and method != METHOD_MANUAL):
            return {**row, "kept_engineer_override": True}
        # The phase 1 relation carries UNIQUE(review_run_id,
        # standard_document_id), so a re-run replaces rather than duplicates.
        conn.execute(
            "DELETE FROM review_applicable_standards"
            " WHERE review_run_id = ? AND standard_document_id = ?",
            (review_run_id, standard_document_id))
        conn.execute(
            """INSERT INTO review_applicable_standards
               (id, review_run_id, standard_document_id, selection_reason,
                selection_method, confidence, included, exclusion_reason,
                created_at, evidence_page, evidence_quote, scope_decision)
               VALUES (:id, :review_run_id, :standard_document_id,
                       :selection_reason, :selection_method, :confidence,
                       :included, :exclusion_reason, :created_at,
                       :evidence_page, :evidence_quote, :scope_decision)""", row)
        if audit is not None:
            _audit(*audit, conn=conn)
    return row


def is_included(row: dict) -> bool:
    """B5: applied to the review only on EVIDENCE - a citation, an equipment,
    service or project classification, a scope clause, or an engineer - and
    never when a confirmed scope reading excludes it, nor while it is held
    for the engineer (order 142)."""
    if row.get("held_for_engineer"):
        return False
    return row["method"] in INCLUDING_METHODS and not row.get("excluded_by_scope")


def _persist(submittal_document_id: str, review_run_id: str | None,
             selected: dict[str, dict],
             allowed_document_ids: frozenset[str], *,
             scope_not_run: str | None = None) -> None:
    """Write the selection, and the standards considered and RULED OUT.

    Every selectable standard the caller may read is accounted for: the ones
    chosen with their reason, and the ones passed over with theirs. A library
    entry that matched no rule is an EXCLUDED row, not an absence.
    """
    if not review_run_id:
        return
    for standard_id, row in selected.items():
        included = is_included(row)
        exclusion = None
        if not included:
            held = row.get("excluded_by_scope") or row.get("held_for_engineer")
            exclusion = held or CANDIDATE_ONLY_REASON.get(
                row["method"], "not evidence that this standard governs the submittal")
            if scope_not_run and not row.get("excluded_by_scope"):
                exclusion = f"{exclusion}; {scope_not_run}"
        record_selection(
            review_run_id=review_run_id, standard_document_id=standard_id,
            method=row["method"], reason=row["reason"], included=included,
            exclusion_reason=exclusion,
            evidence_page=row.get("evidence_page"),
            evidence_quote=row.get("evidence_quote"),
            scope_decision=row.get("scope_decision"))
    mark_rows(review_run_id, selected)
    for entry in _library(allowed_document_ids):
        if entry["id"] in selected:
            continue
        record_selection(
            review_run_id=review_run_id, standard_document_id=entry["id"],
            method=METHOD_SEMANTIC,
            reason="considered from the library and not selected",
            included=False,
            exclusion_reason="no citation, equipment, discipline, service or "
                             "project match with this submittal"
                             + (f"; {scope_not_run}" if scope_not_run else ""),
        )


def override(
    review_run_id: str, standard_document_id: str, *, include: bool,
    reason: str, allowed_document_ids: frozenset[str],
    actor: dict | None = None,
) -> dict:
    """An engineer adds or removes a standard. AUDITED, and a reason is required.

    Master plan section 11: "Selection is automatic. Engineers may add or
    remove a standard afterward with an audit reason." The reason is not
    optional here - an override with no reason is indistinguishable from a
    mistake six months later.

    BOTH DOCUMENTS MUST BE READABLE. A caller who can read a submittal does not
    thereby gain the right to attach any standard in the database to it.
    """
    submittal_review.ensure_schema()
    if not (reason or "").strip():
        raise ApplicabilityError("an override without a reason is not auditable")
    if standard_document_id not in allowed_document_ids:
        raise ApplicabilityError("no document with that id")
    run = submittal_review.get_review_run(
        review_run_id, allowed_document_ids=allowed_document_ids)
    if run is None:
        raise ApplicabilityError("no review run with that id")

    row = record_selection(
        review_run_id=review_run_id, standard_document_id=standard_document_id,
        method=METHOD_MANUAL, reason=reason.strip(), included=include,
        exclusion_reason=None if include else reason.strip(),
        audit=("review.applicability_override", actor, review_run_id,
               f"standard={standard_document_id} included={include}"))
    return row


def applicable_standards(review_run_id: str, *,
                         allowed_document_ids: frozenset[str],
                         include_excluded: bool = True) -> list[dict]:
    """The recorded selection for one run, under the caller's grants.

    Delegates to `submittal_review.list_applicable_standards`, which already
    filters TWICE - the run's submittal must be readable AND each standard row
    is restricted to standards the caller may read. Reading a submittal does
    not grant every standard it cites.
    """
    return submittal_review.list_applicable_standards(
        review_run_id, allowed_document_ids=allowed_document_ids,
        include_excluded=include_excluded)
