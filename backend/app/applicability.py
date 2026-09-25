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
identifiers a sheet cites. `keyword.search` is FTS5 for exact standard numbers
and `search.search` is the hybrid path; both take `allowed_document_ids`
keyword-only, so access filters before ranking rather than after.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import datasheets, keyword, standards, submittal_review
from .db import connect

#: The selection rules, in the priority master plan section 11 gives them.
#:
#: The METHOD IS RECORDED PER ROW, because "it was retrieved" is not a reason an
#: engineer can act on and "the datasheet names it in note 8" is. A row without
#: a method is refused by `record_selection`.
METHOD_REFERENCED = "referenced"          # 1. named in the datasheet
METHOD_EQUIPMENT = "equipment_type"       # 2. mapped to the equipment
METHOD_DISCIPLINE = "discipline"          # 3. discipline match
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
    "manual", "referenced", "equipment_type", "scope", "service", "project"})
CANDIDATE_ONLY_REASON = {
    "discipline": ("a shared discipline alone is not evidence that this standard "
                   "governs this equipment; considered, not included - an engineer "
                   "may add it"),
    "semantic": ("similar wording alone is not evidence of applicability; "
                 "considered, not included - an engineer may add it"),
}

#: Priority order, lowest number wins when two rules pick the same standard.
#: A standard both cited and semantically similar is recorded as CITED: the
#: stronger reason is the true one and the weaker one adds nothing.
_PRIORITY = {
    METHOD_MANUAL: 0,
    METHOD_REFERENCED: 1,
    METHOD_EQUIPMENT: 2,
    METHOD_SCOPE: 2,
    METHOD_DISCIPLINE: 3,
    METHOD_SERVICE: 4,
    METHOD_SEMANTIC: 5,
    METHOD_PROJECT: 6,
}

#: CONFIDENCE IS NEVER "high" (CLAUDE.md rule 4). These are the ceiling for
#: each method, and even an explicit citation stops at 0.9: the sheet naming a
#: standard is strong evidence that it governs, not proof that this revision of
#: it is the right one.
_CONFIDENCE = {
    METHOD_MANUAL: 0.9,
    METHOD_REFERENCED: 0.9,
    METHOD_EQUIPMENT: 0.7,
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


#: A Saudi Aramco standard number inside a LIBRARY FILENAME. Filenames are not
#: citations - they carry revision notes, dates and draft markers - so this is
#: anchored at the start and reads only the number.
_FILENAME_NUMBER = re.compile(r"^\s*(SAES)[-\s]*([A-Z])[-\s]*(\d{1,4})", re.IGNORECASE)


def library_identifier(filename: str) -> str | None:
    """The standard number a library filename carries, zero-padded. Or None.

    `SAES-B-14 -Final Draft 01-29-23.pdf` is SAES-B-014. The series number is
    written three digits wide everywhere Saudi Aramco prints it, and one file
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


def _referenced_in_submittal(document_id: str,
                             allowed_document_ids: frozenset[str]) -> list[str]:
    """The standard identifiers this submittal's own text cites.

    Read from the chunks under the caller's grants, using phase 4's detector -
    so a datasheet's citations and a chat answer's citations come from the same
    text.
    """
    where, args = _scope_clause(allowed_document_ids, "document_id")
    rows = connect().execute(
        "SELECT text FROM chunks" + where + " AND document_id = ?",
        [*args, document_id]).fetchall()
    return datasheets.referenced_standards(" ".join(r["text"] or "" for r in rows))


def citation_evidence(document_id: str, identifier: str,
                      allowed_document_ids: frozenset[str]) -> tuple[int | None, str | None]:
    """WHERE the submittal cites `identifier`: (page, the line it is on).

    B5: "named in the submittal" is a reason; the page and the printed line
    are the EVIDENCE an engineer checks it against. Read from the submittal's
    own chunks under the caller's grants, with the same detector selection
    uses, so the evidence is the citation that was matched. (None, None) when
    no single chunk carries it - never a guessed page.
    """
    key = normalise_identifier(identifier)
    where, args = _scope_clause(allowed_document_ids, "document_id")
    rows = connect().execute(
        "SELECT page_start, text FROM chunks" + where + " AND document_id = ?"
        " ORDER BY page_start, ordinal", [*args, document_id]).fetchall()
    for row in rows:
        text = row["text"] or ""
        if not any(normalise_identifier(n) == key
                   for n in datasheets.referenced_standards(text)):
            continue
        for line in text.splitlines():
            if any(normalise_identifier(n) == key
                   for n in datasheets.referenced_standards(line)):
                return row["page_start"], " ".join(line.split())[:200]
        return row["page_start"], None
    return None, None


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


# --------------------------------------------------------------- selection

def _match_referenced(library: list[dict], referenced: list[str]) -> dict[str, dict]:
    """Rule 1: standards the datasheet NAMES that are in the library."""
    by_key: dict[str, dict] = {}
    for entry in library:
        for candidate in (entry.get("document_number"),
                          # The PARSED number before the raw filename: the raw
                          # form carries revision text, so its key is
                          # "SAESB14FINALDRAFT..." and matches no citation.
                          library_identifier(entry.get("filename") or ""),
                          entry.get("filename")):
            key = normalise_identifier(candidate or "")
            if key:
                by_key.setdefault(key, entry)
    out: dict[str, dict] = {}
    for identifier in referenced:
        key = normalise_identifier(identifier)
        entry = by_key.get(key)
        if entry is None:
            # A prefix match catches "API RP 520 Pt-1" against a library entry
            # numbered "API RP 520". A citation naming a PART of a standard is
            # a citation of that standard.
            entry = next((v for k, v in by_key.items()
                          if key.startswith(k) or k.startswith(key)), None)
        if entry is not None:
            out[entry["id"]] = {
                "method": METHOD_REFERENCED,
                "reason": f"named in the submittal as {identifier}",
                "identifier": identifier,
            }
    return out


def missing_references(library: list[dict], referenced: list[str]) -> list[str]:
    """The standards a submittal CITES that the library does not hold.

    ONE HOME FOR THIS RULE, because two copies of it were both wrong. The
    dashboard (phase 6) and the CRS export (phase 7) each did:

        matched = _match_referenced(library, names)
        missing = [n for n in names if normalise_identifier(n) not in matched]

    - and `_match_referenced` is keyed by DOCUMENT ID ("doc_a3df..."), not by
    identifier ("SAESL132"). An identifier never equals a document id, so
    EVERY cited standard was reported missing, always. On the drum sheet that
    was 15 of 15, when six - SAES-A-133, SAES-A-206, SAES-L-109, SAES-L-132,
    SAES-W-010, SAES-W-016 - are in the library. The dashboard printed "21 of
    21 cited standards are not in the library", and the CRS told a contractor
    six standards were unavailable that were sitting in the library.

    Asked PER NAME, of `_match_referenced` itself, rather than by reading the
    identifiers back out of one combined result: that result is keyed by
    document, so when two citations reach the SAME standard under DIFFERENT
    keys - the prefix rule makes "API RP 520 Pt-1" and "API RP 520" both the
    standard numbered API RP 520 - only the last one's identifier survives,
    and the other would be reported missing. The same defect, one level down.
    (Two spellings that normalise to the same key cannot collide this way;
    the survivor still matches both.) Per name reuses the exact matching rule
    (exact key, then prefix) and cannot drift from what selection considers a
    match.

    Returns the cited names in the submittal's own spelling, one per standard,
    in citation order.
    """
    missing: list[str] = []
    seen: set[str] = set()
    for name in referenced:
        key = normalise_identifier(name)
        if not key or key in seen:
            continue
        seen.add(key)
        if not _match_referenced(library, [name]):
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
    what `keyword.search`'s keyword-only parameter enforces.

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
        hits = keyword.search(" OR ".join(terms), limit=limit,
                              allowed_document_ids=searchable)
    except Exception:  # noqa: BLE001 - a retrieval failure is not a selection
        return {}
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


def select(
    submittal_document_id: str, *, allowed_document_ids: frozenset[str],
    review_run_id: str | None = None, persist: bool = True,
    actor: dict | None = None,
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
    referenced = _referenced_in_submittal(submittal_document_id, allowed_document_ids)

    selected: dict[str, dict] = {}
    for candidates in (
        _match_referenced(library, referenced),
        _match_attribute(library, profile, "equipment_type", METHOD_EQUIPMENT),
        _match_attribute(library, profile, "discipline", METHOD_DISCIPLINE),
        _match_attribute(library, profile, "service", METHOD_SERVICE),
        _match_attribute(library, profile, "project", METHOD_PROJECT),
        _match_semantic(submittal_document_id, library, allowed_document_ids),
    ):
        for standard_id, row in candidates.items():
            existing = selected.get(standard_id)
            if existing is None or _PRIORITY[row["method"]] < _PRIORITY[existing["method"]]:
                selected[standard_id] = dict(row)

    matched_keys = {
        normalise_identifier(row.get("identifier") or "")
        for row in selected.values() if row["method"] == METHOD_REFERENCED
    }
    missing = [
        # Listed by THE IDENTIFIER THE DATASHEET USED, not by a canonical form
        # this system prefers. An engineer goes looking for the string their
        # document wrote.
        {"identifier": identifier,
         "reason": "cited by the submittal and not present in the library"}
        for identifier in referenced
        if normalise_identifier(identifier) not in matched_keys
    ]
    selected, missing = _semantic_cannot_cover_a_missing_reference(selected, missing)

    # B5: THE EVIDENCE for every citation - the page and the line it is on.
    for standard_id, row in selected.items():
        if row["method"] == METHOD_REFERENCED and row.get("identifier"):
            page, quote = citation_evidence(
                submittal_document_id, row["identifier"], allowed_document_ids)
            row["evidence_page"], row["evidence_quote"] = page, quote
            if page is not None:
                row["reason"] = f"{row['reason']} (page {page})"

    # B5: THE SCOPE DECISION (applicability_v2) on every standard that has a
    # stored, verified scope record - only with an approved taxonomy.
    decisions, scope_not_run = scope_decisions(library, profile)
    from . import applicability_v2 as v2
    for standard_id, decision in decisions.items():
        verdict = decision.get("decision")
        evidence = {"evidence_page": decision.get("page"),
                    "evidence_quote": decision.get("quote"),
                    "scope_decision": verdict}
        row = selected.get(standard_id)
        if verdict == v2.APPLICABLE and (row is None or row["method"] not in INCLUDING_METHODS):
            selected[standard_id] = {
                "method": METHOD_SCOPE, "identifier": None, **evidence,
                "reason": f"its scope clause covers this equipment: "
                          f"\"{decision.get('quote') or ''}\" (page {decision.get('page')})"}
        elif verdict == v2.NOT_APPLICABLE and row is not None:
            if row["method"] == METHOD_REFERENCED:
                # CITED STANDARDS ARE NEVER EXCLUDED BY A SCOPE READING: the
                # datasheet says it governs. The disagreement is shown.
                row["scope_decision"] = verdict
                row["reason"] = (f"{row['reason']}; its scope clause reads as not "
                                 f"covering this equipment (\"{decision.get('quote') or ''}\", "
                                 f"page {decision.get('page')}) - engineer to confirm")
            else:
                row.update(evidence)
                row["excluded_by_scope"] = (
                    f"its scope clause excludes this equipment: "
                    f"\"{decision.get('quote') or ''}\" (page {decision.get('page')})")
        elif row is not None:
            row["scope_decision"] = verdict

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
        "referenced_total": len(referenced),
        "library_size": len(library),
        **completeness(selected, missing, submittal_document_id,
                       allowed_document_ids=allowed_document_ids),
    }


def completeness(selected: dict, missing: list, submittal_document_id: str, *,
                 allowed_document_ids: frozenset[str]) -> dict:
    """How much of this review could actually be performed.

    TWO THINGS REDUCE IT AND THEY ARE REPORTED SEPARATELY BEFORE BEING
    COMBINED, because they have different remedies:

      * a missing referenced standard - somebody must load the standard;
      * the submittal's own extraction recall from phase 4 - the datasheet was
        only partly readable, and on the real pump sheet that was 0.43.

    Multiplied rather than averaged: a review with every standard present but
    half the datasheet unread is half a review, and so is the reverse. An
    average would let one good number hide the other.

    None when there is nothing to judge - never 0, which would read as total
    failure rather than "no basis to compute this". And None, too, when the
    extraction half was never measured, rather than a score built from the
    other half alone (B18) - except where that other half is already 0.
    """
    referenced_total = len(missing) + sum(
        1 for row in selected.values() if row["method"] == METHOD_REFERENCED)
    reference_coverage = (
        (referenced_total - len(missing)) / referenced_total
        if referenced_total else None)

    facts = datasheets.list_facts(
        submittal_document_id, allowed_document_ids=allowed_document_ids)
    pages = {f["page"] for f in facts if f["page"] is not None}
    extraction = round(len(pages) / max(len(pages), 1), 3) if facts else None
    row = connect().execute(
        "SELECT page_count FROM documents WHERE id = ?",
        (submittal_document_id,)).fetchone()
    if row and row["page_count"] and facts:
        extraction = round(len(pages) / row["page_count"], 3)

    # B18: AN UNMEASURED FACTOR IS NOT A FACTOR OF ONE. The two Nones mean
    # different things. `reference_coverage` is None when the submittal cites
    # no standard: there is nothing to cover, and leaving it out is right.
    # `extraction` is None when no fact was ever extracted: the other half of
    # the review was never MEASURED. Dropping it made "every cited standard
    # held, datasheet unread" report completeness 1.0. Now that is None -
    # unless a measured factor is already 0, which no unknown can raise (M-03:
    # 0 of 15 cited standards held, so 0.0 is determinate and stays).
    if extraction is None:
        overall = 0.0 if reference_coverage == 0 else None
    else:
        parts = [p for p in (reference_coverage, extraction) if p is not None]
        overall = round(__import__("math").prod(parts), 3)
    return {
        "reference_coverage": (round(reference_coverage, 3)
                               if reference_coverage is not None else None),
        "extraction_coverage": extraction,
        "completeness": overall,
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
#: `discipline` IS DELIBERATELY EXCLUDED, found and fixed 2026-09-25 by the
#: owner's own spot-check of "not applicable" verdicts: `document_classification
#: .discipline` for a COMPANY_STANDARD is the committee that owns it - "Piping
#: Standards Committee", "Loss Prevention Standards Committee" - read verbatim
#: off the cover page's "Document Responsibility" line (178 of 179 standards
#: that have a discipline recorded are committee-shaped, measured on the live
#: corpus). For a CONTRACTOR_SUBMITTAL, `discipline` is a broad category -
#: "Mechanical" - read off the submittal's own title block
#: (`classify_metadata_for_submittal`). These are two DIFFERENT VOCABULARIES,
#: not two spellings of the same fact, and comparing them for equality can
#: never produce a true confirmation - only a false "does not match". 9 of 10
#: sampled `not_applicable` verdicts on the first regression submittal were
#: exactly this: "discipline 'Piping Standards Committee' does not match the
#: submittal's 'Mechanical'" - a standard whose governing committee is Piping
#: reported as not applicable to a Mechanical submittal, which is backwards.
#: No committee-to-category mapping exists in this codebase (`disciplines.py`'s
#: `canonical()` only collapses SPELLING variants of the SAME committee name,
#: it does not translate "Piping Standards Committee" to "Mechanical") - until
#: one does, `discipline` is evidence to SHOW, never a fact to COMPARE here.
_COMPARABLE_FIELDS = ("equipment_type", "service", "project")


def applicability_with_reasons(submittal_document_id: str, *,
                               allowed_document_ids: frozenset[str]) -> list[dict]:
    """Every standard in the caller's library, classified for THIS submittal
    into exactly one of four buckets - applicable and assessable, applicable
    but needs another document, not applicable (with the reason), or
    unknown - per the master order.

    BUILT ENTIRELY FROM WHAT `select()` AND `standards.list_standards`
    ALREADY COMPUTE. No new inference, no new confidence score, no claim
    this system could not already support before this function existed -
    it only RECLASSIFIES `select()`'s own output into the four buckets the
    order asks for, and states a reason using the same attribute
    comparisons `_match_attribute` already makes (never a semantic
    judgement this system cannot back with a field-for-field comparison).

    "NOT APPLICABLE" IS NEVER GUESSED FROM SILENCE. A standard with no
    recorded equipment_type/service/project of its own, or a submittal with
    none of its own, cannot be compared on those axes at all - that is
    `STATUS_UNKNOWN`, not a "not applicable" this system has no basis to
    assert. `discipline` is deliberately not one of the comparable axes -
    see `_COMPARABLE_FIELDS`.
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
                "reason": scoped_out or (
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
        reason = ("; ".join(mismatches) if mismatches else
                 "not cited by the submittal, and no shared equipment type, "
                 "service or project recorded")
        out.append({"standard_document_id": std_id,
                   "document_number": entry.get("document_number"),
                   "filename": entry.get("filename"),
                   "status": STATUS_NOT_APPLICABLE, "reason": reason})

    order = {STATUS_APPLICABLE_ASSESSABLE: 0,
            STATUS_APPLICABLE_NEEDS_ANOTHER_DOCUMENT: 1,
            STATUS_UNKNOWN: 2, STATUS_NOT_APPLICABLE: 3}
    return sorted(out, key=lambda r: (
        order[r["status"]], r["document_number"] or r["filename"] or ""))


# ----------------------------------------------------------- persistence


def _audit(action: str, actor: dict | None, resource_id: str | None,
           detail: str | None = None) -> None:
    """Durable record of a selection decision. Ids and counts only."""
    conn = connect()
    try:
        with conn:
            conn.execute(
                """INSERT INTO audit_events
                       (at, actor_user_id, actor_username, action,
                        resource_type, resource_id, outcome, detail)
                   VALUES (?, ?, ?, ?, 'review', ?, 'ok', ?)""",
                (_now(), (actor or {}).get("id"),
                 ((actor or {}).get("email") or "unauthenticated")[:200],
                 action, resource_id, detail))
    except Exception:  # noqa: BLE001 - an unwritable audit must not block it
        pass


def record_selection(
    *, review_run_id: str, standard_document_id: str, method: str,
    reason: str, confidence: float | None = None, included: bool = True,
    exclusion_reason: str | None = None, evidence_page: int | None = None,
    evidence_quote: str | None = None, scope_decision: str | None = None,
) -> dict:
    """Write one row of `review_applicable_standards`.

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
    return row


def is_included(row: dict) -> bool:
    """B5: applied to the review only on EVIDENCE - a citation, an equipment,
    service or project classification, a scope clause, or an engineer - and
    never when a confirmed scope reading excludes it."""
    return row["method"] in INCLUDING_METHODS and not row.get("excluded_by_scope")


def _persist(submittal_document_id: str, review_run_id: str | None,
             selected: dict[str, dict],
             allowed_document_ids: frozenset[str], *,
             scope_not_run: str | None = None) -> None:
    """Write the selection, and the standards considered and RULED OUT.

    Every selectable standard the caller may read is accounted for: the ones
    chosen with their reason, and the ones passed over with theirs. A library
    entry that simply did not match any rule is an EXCLUDED row, not an
    absence, because "we looked at this and it did not apply" is the answer an
    engineer is actually asking for.
    """
    if not review_run_id:
        return
    for standard_id, row in selected.items():
        included = is_included(row)
        exclusion = None
        if not included:
            exclusion = row.get("excluded_by_scope") or CANDIDATE_ONLY_REASON.get(
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
        exclusion_reason=None if include else reason.strip())
    _audit("review.applicability_override", actor, review_run_id,
           detail=f"standard={standard_document_id} included={include}")
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
