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

from . import scope_ledger, standard_ids

VOCABULARY_PATH = Path(__file__).parent / "reference" / "service_conditions.json"


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for c in data.get("conditions") or []:
        out.append({
            "name": c["name"],
            "standards": tuple(c.get("standards") or ()),
            "markers": tuple(m.casefold() for m in c.get("requirement_markers") or ()),
            "labels": tuple(m.casefold() for m in c.get("field_labels") or ()),
            "present": frozenset(m.casefold() for m in c.get("declared_present") or ()),
            "absent": frozenset(m.casefold() for m in c.get("declared_absent") or ()),
            # #725 F6: "value" conditions (turbine exhaust, pump discharge,
            # thermal relief) are declared by WHAT the application fields say,
            # not by a yes/no field.
            "mode": c.get("mode") or "declared",
            "satisfied_by": tuple(m.casefold() for m in c.get("satisfied_by") or ()),
        })
    return out


def conditions(path: Path | str | None = None) -> list[dict]:
    p = Path(path or VOCABULARY_PATH)
    return _load(str(p), p.stat().st_mtime)


def _words(text: object) -> str:
    return " " + re.sub(r"[^a-z0-9/]+", " ", str(text or "").casefold()).strip() + " "


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
        stated.append((fact, raw))
    if not stated:
        return None
    for fact, raw in stated:
        if any(f" {m} " in _words(raw) for m in condition["satisfied_by"]):
            return {"present": True, "label": fact.get("field_label") or fact.get("field_name"),
                    "value": raw, "page": fact.get("page"), "fact_id": fact.get("id")}
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


def gate(requirements: list[dict], *, facts: list[dict],
         standard_labels: dict[str, str] | None = None,
         path: Path | str | None = None,
         headings_by_standard: dict[str, dict[str, str]] | None = None) -> dict:
    """{"kept": [...], "items": [{"requirement", "code", "detail"} - one per
    requirement that does not apply, the shape #678's counts take],
    "declarations": {condition: what the sheet says, or None}}. Order kept."""
    labels = standard_labels or {}
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
    for requirement in requirements:
        label = labels.get(requirement.get("standard_document_id") or "", "")
        out = None
        for c in conds:
            d = declared[c["name"]]
            if d is not None and d["present"] is False and specific_to(
                    c, requirement, label, _heading_of(requirement, headings_by_standard)):
                page = f", page {d['page']}" if d.get("page") is not None else ""
                out = {"requirement": requirement, "code": "service_condition_not_met",
                       "detail": (f"{scope_ledger.REASONS['service_condition_not_met'][1]}: "
                                  f"{c['name']}; the datasheet says {d['label']}: {d['value']}{page}")}
                break
        if out is None:
            kept.append(requirement)
        else:
            items.append(out)
    return {"kept": kept, "items": items, "declarations": declared}
