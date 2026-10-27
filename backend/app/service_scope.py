"""Service-condition scope (#638, #677): a requirement that applies only in a
service the submittal says it is NOT in does not apply.

Sour-service requirements (NACE MR0175 / ISO 15156 and the like) were checked
against every submittal. Subject scope (#453) decides by equipment kind; this
decides by the SERVICE the datasheet states. Data, not code: the conditions,
their standards, the wording that marks a requirement, and the datasheet
labels and values that declare a condition are in
`reference/service_conditions.json`.

THE RULE, and its one-sidedness on purpose:
  * declared ABSENT on the datasheet (a cited field: label, value, page)
    -> "does not apply: service condition not met", with that citation;
  * declared PRESENT -> a check, as before;
  * NOT DECLARED -> a check, as before. Unknown is never "does not apply":
    dropping a sour-service rule because the sheet is silent is the failure
    this exists to prevent.

Pure functions over dicts; the vocabulary file is read once.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from . import clause_support, scope_ledger, standard_ids

VOCABULARY_PATH = Path(__file__).parent / "reference" / "service_conditions.json"


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for c in data.get("conditions") or []:
        out.append(
            {
                "name": c["name"],
                "standards": tuple(c.get("standards") or ()),
                "markers": tuple(
                    m.casefold() for m in c.get("requirement_markers") or ()
                ),
                "labels": tuple(m.casefold() for m in c.get("field_labels") or ()),
                "present": frozenset(
                    m.casefold() for m in c.get("declared_present") or ()
                ),
                "absent": frozenset(
                    m.casefold() for m in c.get("declared_absent") or ()
                ),
                # #725 F6: "value" conditions (turbine exhaust, pump discharge,
                # thermal relief) are declared by WHAT the application fields say,
                # not by a yes/no field.
                "mode": c.get("mode") or "declared",
                "satisfied_by": tuple(
                    m.casefold() for m in c.get("satisfied_by") or ()
                ),
                # A "value" condition with `contradicted_by` is absent only when a stated field
                # names one of THESE (another construction); a stated field naming neither is
                # unknown, never "does not apply".
                "contradicted_by": tuple(
                    m.casefold() for m in c.get("contradicted_by") or ()
                ),
                # #754 F5b: standards a datasheet DECLARING the condition present
                # is reviewed against (applicability.standards_check).
                "required": tuple(c.get("required_standards") or ()),
            }
        )
    return out


def conditions(path: Path | str | None = None) -> list[dict]:
    p = Path(path or VOCABULARY_PATH)
    return _load(str(p), p.stat().st_mtime)


def _words(text: object) -> str:
    return " " + re.sub(r"[^a-z0-9/]+", " ", str(text or "").casefold()).strip() + " "


def _negated(raw: object) -> bool:
    """Does a stated value carry a negation ("Not overhung", "non-overhung", "not OH2")?"""
    return any(w in _NEGATIONS for w in _words(raw).split())


def _value_declaration(condition: dict, facts: list[dict]) -> dict | None:
    """#725 F6, a "value" condition: present when ANY stated application field
    (label in `field_labels`, value not blank or a placeholder) names one of
    `satisfied_by`; absent only when such fields are stated and NONE does -
    the stated value is the citation. No such field stated: None (unknown,
    the requirement stays a check)."""
    from . import conditions as conditions_mod

    stated = []
    for fact in facts:
        if fact.get("is_blank"):
            continue
        label = _words(fact.get("field_label") or fact.get("field_name"))
        if not any(f" {m} " in label for m in condition["labels"]):
            continue
        raw = fact.get("field_value") if fact.get("field_value") not in (None, "") else fact.get("raw_value")
        if conditions_mod._is_empty(raw) or not str(raw or "").strip():
            continue
        if condition.get("contradicted_by") and _negated(raw):
            continue  # "Not overhung" states no construction: unknown, never a construction
        stated.append((fact, raw))
    if not stated:
        return None
    for fact, raw in stated:
        if any(f" {m} " in _words(raw) for m in condition["satisfied_by"]):
            return {"present": True, "label": fact.get("field_label") or fact.get("field_name"),
                    "value": raw, "page": fact.get("page"), "fact_id": fact.get("id")}
    if condition.get("contradicted_by"):
        for fact, raw in stated:
            if any(f" {m} " in _words(raw) for m in condition["contradicted_by"]):
                return {
                    "present": False,
                    "label": fact.get("field_label") or fact.get("field_name"),
                    "value": raw,
                    "page": fact.get("page"),
                    "fact_id": fact.get("id"),
                }
        return None
    fact, raw = stated[0]
    return {"present": False, "label": fact.get("field_label") or fact.get("field_name"),
            "value": raw, "page": fact.get("page"), "fact_id": fact.get("id")}


def declaration(condition: dict, facts: list[dict]) -> dict | None:
    """What the datasheet itself says about `condition`: {"present": bool,
    "label", "value", "page", "fact_id"} from the first field that names it
    with a value that reads as present or absent; None when no field does."""
    if condition.get("mode") == "value":
        return _value_declaration(condition, facts)
    for fact in facts:
        if fact.get("is_blank"):
            continue
        label = _words(fact.get("field_label") or fact.get("field_name"))
        if not any(f" {m} " in label or m in label for m in condition["labels"]):
            continue
        raw = fact.get("field_value") if fact.get("field_value") not in (None, "") \
            else fact.get("raw_value")
        value = " ".join(_words(raw).split())
        if not value:
            continue
        if value in condition["absent"]:
            present = False
        elif value in condition["present"] or any(
                f" {m} " in _words(raw) for m in condition["present"] if len(m) > 2):
            present = True
        else:
            continue
        return {"present": present, "label": fact.get("field_label") or fact.get("field_name"),
                "value": raw, "page": fact.get("page"), "fact_id": fact.get("id")}
    return None


def specific_to(condition: dict, requirement: dict, standard_label: str, heading: str = "") -> bool:
    """Is `requirement` one that applies only in `condition`'s service? Its
    standard, its own wording, or (#725 F6) the heading of its clause or of a
    parent clause ("8.7 Turbine exhaust") carries the condition."""
    if any(standard_ids.same_standard(standard_label, s) or any(
            standard_ids.same_standard(cited, s) for cited in standard_ids.cited_standards(standard_label))
           for s in condition["standards"]):
        return True
    text = _words(" ".join(str(requirement.get(k) or "") for k in (
        "requirement_text", "source_text", "condition")) + " " + (heading or ""))
    return any(f" {m} " in text for m in condition["markers"])


def _heading_of(requirement: dict, headings_by_standard: dict[str, dict[str, str]]) -> str:
    """The headings of a requirement's clause and of its parent clauses."""
    from .subject_scope import _ancestors

    headings = headings_by_standard.get(requirement.get("standard_document_id") or "", {})
    clause = requirement.get("clause")
    return " ".join(h for h in (headings.get(c) for c in [clause, *_ancestors(clause)] if c) if h)


#: Words that make a sentence about a construction unsafe to drop: it is a list, a negation or an
#: exception, so it may apply to the construction the sheet HAS.
_CUE_WORDS = frozenset(
    {
        "not",
        "non",
        "no",
        "except",
        "excepting",
        "excluding",
        "unless",
        "nor",
        "neither",
        "but",
        "and",
        "or",
        "besides",
        "other",
        "apart",
    }
)
_NEGATIONS = frozenset(
    {
        "not",
        "non",
        "no",
        "without",
        "neither",
        "nor",
        "other",
        "excluding",
        "except",
        "unless",
        "excepting",
        "apart",
        "besides",
    }
)
_UNSURE_CONSTRUCTION = (
    "the sentence names a pump construction in a list, a negation or an exception, or next to "
    "another construction; an engineer decides whether it applies to this pump"
)


def _names_the_sheets_own(
    conds: list[dict], declared: dict, requirement: dict, label: str, heading: str
) -> bool:
    """Does the sentence also name a condition the sheet DECLARES present? Then it applies. A
    construction is named by its marker phrase or by one of its own words or codes, whichever
    side of an "and" it stands."""
    text = " ".join(
        str(requirement.get(k) or "")
        for k in ("requirement_text", "source_text", "condition")
    )
    words = _words(text)
    return any(
        declared[o["name"]] is not None
        and declared[o["name"]]["present"]
        and (
            specific_to(o, requirement, label, heading)
            or (
                o["contradicted_by"]
                and any(f" {m} " in words for m in o["satisfied_by"])
            )
        )
        for o in conds
    )


def _plainly_about(c: dict, conds: list[dict], requirement: dict) -> bool:
    """May a sentence be dropped for the construction condition `c`? Only when it names that ONE
    construction, no other, no "vertical" (an unclassified construction word), and no negation,
    exception or list word within a few words of the marker. Anything else stays held."""
    text = " ".join(
        str(requirement.get(k) or "")
        for k in ("requirement_text", "source_text", "condition")
    )
    words = " " + re.sub(r"[^a-z0-9/]+", " ", text.casefold()).strip() + " "
    if " vertical " in words or " vertically " in words:
        return False
    if not any(f" {m} " in words for m in c["markers"]):
        return False  # only the sentence's OWN words may drop it, never a heading
    for o in conds:
        if (
            o is not c
            and o["contradicted_by"]
            and any(f" {m} " in words for m in (*o["markers"], *o["satisfied_by"]))
        ):
            return False
    tokens = words.split()
    for marker in c["markers"]:
        pieces = marker.split()
        for i in range(len(tokens) - len(pieces) + 1):
            if tokens[i : i + len(pieces)] == pieces:
                near = (
                    tokens[max(0, i - 4) : i]
                    + tokens[i + len(pieces) : i + len(pieces) + 3]
                )
                if any(t in _CUE_WORDS for t in near):
                    return False
    return True


def gate(requirements: list[dict], *, facts: list[dict],
         standard_labels: dict[str, str] | None = None,
         path: Path | str | None = None,
         headings_by_standard: dict[str, dict[str, str]] | None = None) -> dict:
    """{"kept": [...], "items": [{"requirement", "code", "detail"} - one per
    requirement that does not apply, the shape #678's counts take],
    "declarations": {condition: what the sheet says, or None}, "held": [...]
    (applies, not checked: the sentence names a service the sheet does not
    state, or that states no requirement, `clause_support`)}. Order kept."""
    labels = standard_labels or {}
    support = clause_support.hold_non_requirements(requirements)
    requirements = support["kept"]
    conds = conditions(path)
    declared = {c["name"]: declaration(c, facts) for c in conds}
    if headings_by_standard is None and any(d is not None and d["present"] is False
                                            for d in declared.values()):
        from .subject_scope import heading_sections
        headings_by_standard = heading_sections(sorted({
            r.get("standard_document_id") for r in requirements if r.get("standard_document_id")}))
    headings_by_standard = headings_by_standard or {}
    kept: list[dict] = []
    items: list[dict] = []
    unsure: list[dict] = []
    for requirement in requirements:
        label = labels.get(requirement.get("standard_document_id") or "", "")
        out = None
        for c in conds:
            d = declared[c["name"]]
            heading = _heading_of(requirement, headings_by_standard)
            if d is not None and d["present"] is False and specific_to(
                    c, requirement, label, heading):
                if _names_the_sheets_own(conds, declared, requirement, label, heading):
                    continue
                if c["contradicted_by"] and not _plainly_about(c, conds, requirement):
                    out = False
                    break
                page = f", page {d['page']}" if d.get("page") is not None else ""
                out = {"requirement": requirement, "code": "service_condition_not_met",
                       "detail": (f"{scope_ledger.REASONS['service_condition_not_met'][1]}: "
                                  f"{c['name']}; the datasheet says {d['label']}: {d['value']}{page}")}
                break
        if out is None:
            kept.append(requirement)
        elif out is False:
            unsure.append(
                {
                    "requirement": requirement,
                    "code": "service_unknown",
                    "detail": _UNSURE_CONSTRUCTION,
                }
            )
        else:
            items.append(out)
    # A construction condition the sheet does not decide stays HELD (unknown), so only the
    # conditions it did decide, and the plain ones, are left to this gate by name.
    decided = [
        c for c in conds if not (c["contradicted_by"] and declared[c["name"]] is None)
    ]
    known = clause_support.known_words(
        [c["name"] for c in decided] + [m for c in decided for m in c["markers"]]
    )
    unstated = clause_support.hold_unstated_services(kept, facts=facts, known=known)
    return {
        "kept": unstated["kept"],
        "items": items,
        "declarations": declared,
        "held": support["held"] + unstated["held"] + unsure,
    }
