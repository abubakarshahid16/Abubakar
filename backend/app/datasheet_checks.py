"""Datasheet self-checks (kind B): what a datasheet says against ITSELF.

Owner order 2026-09-26, item 2c. A review with no standard held said nothing
at all - yet a reviewer reading any vessel sheet checks that the design
pressure is at least the operating pressure, that the test pressure is above
the design pressure, that the mandatory fields are filled and carry units.
None of that needs a standard. It needs arithmetic on the sheet's own values.

PURE ARITHMETIC, RULES AS DATA. `evaluate` takes the datasheet's facts and
returns results; it opens no database, calls no model, reads no network. The
rules are `reference/datasheet_checks.json` - roles (which field names mean
"design pressure"), unit families, placeholder words, consistency pairs and
mandatory fields per equipment type (the placeholder words are
`blank_markers`, shared with the datasheet reader) - each with an id and plain-English text.

WHAT IT NEVER DOES:
  * compare two values it cannot put on one scale (different units that do
    not normalise to one, gauge against absolute) - that pair is skipped, not
    guessed;
  * choose between two different values under one field name - ambiguous is
    skipped too;
  * call a field "not stated" because it was not FOUND: an absent mandatory
    field goes through `comparison.qualify_by_pages` like every absence, so a
    page nobody read makes it an engineer's question, not the contractor's.

`store` writes the results as findings with `origin = 'datasheet_check'`,
cited to the datasheet page and field, in the run - where
`comparison.recommend_code` counts them like any finding (kind B decides by
code; never by a model).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import blank_markers

RULES_PATH = Path(__file__).parent / "reference" / "datasheet_checks.json"
ORIGIN = "datasheet_check"
LABEL = "Datasheet check"

COMPLIANT = "COMPLIANT"
NON_COMPLIANT = "NON_COMPLIANT"
MISSING_INFORMATION = "MISSING_INFORMATION"

_OPS = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b,
        "<=": lambda a, b: a <= b, "<": lambda a, b: a < b}
_OP_WORDS = {">=": "at least", ">": "above", "<=": "at most", "<": "below"}
_GAUGE = re.compile(r"(g|\(g\)|gauge)$")
_ABSOLUTE = re.compile(r"(a|\(a\)|abs)$")


def load_rules(path: Path = RULES_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fold(text) -> str:
    return " ".join(str(text or "").lower().replace(":", " ").split())


def role_of(field_name: str, rules: dict) -> str | None:
    name = _fold(field_name)
    for role, spec in rules["roles"].items():
        if any(re.search(p, name) for p in spec["names"]):
            return role
    return None


def _pretty(role: str) -> str:
    return role.replace("_", " ").capitalize()


def _unit_kind(unit: str | None, rules: dict) -> str | None:
    folded = _fold(unit)
    for kind, units in rules["units"].items():
        if folded in units:
            return kind
    return None


def _pressure_basis(unit: str | None) -> str:
    folded = _fold(unit).replace(" ", "")
    if _GAUGE.search(folded):
        return "gauge"
    if _ABSOLUTE.search(folded):
        return "absolute"
    return ""


def _number(fact: dict) -> tuple[float, str, str] | None:
    """(value, scale, basis) on one comparable scale, or None."""
    basis = _pressure_basis(fact.get("raw_unit"))
    if fact.get("normalized_value") is not None and fact.get("normalized_unit"):
        return float(fact["normalized_value"]), str(fact["normalized_unit"]), basis
    try:
        return float(str(fact.get("raw_value"))), _fold(fact.get("raw_unit")), basis
    except (TypeError, ValueError):
        return None


def _label(fact: dict, role: str) -> str:
    """The field as the DATASHEET names it ("Hydrotest pressure"), not the
    rule's role name ("test pressure")."""
    name = str(fact.get("field_label") or fact.get("field_name") or "").strip()
    return name[:1].upper() + name[1:] if name else _pretty(role)


def _shown(fact: dict) -> str:
    return str(fact.get("field_value") or fact.get("raw_value") or "").strip()


def _result(rule_id: str, status: str, text: str, detail: str, fact: dict | None,
            role: str, tag: str | None) -> dict:
    return {"rule_id": rule_id, "status": status, "text": text, "detail": detail,
            "field": (fact or {}).get("field_label") or (fact or {}).get("field_name") or _pretty(role),
            "value": _shown(fact) if fact else None, "page": (fact or {}).get("page"),
            "equipment_tag": tag, "fact_id": (fact or {}).get("id"), "role": role}


GENERIC = "_generic"


def mandatory_list_key(equipment_type: str | None, rules: dict) -> str:
    """Which entry of the `mandatory` table an `equipment_type` is checked
    against. Never None: `GENERIC` when nothing more specific applies.

    1. The table's own key, compared case- and space-insensitively (an
       engineer confirming "pressure vessel" means "Pressure Vessel").
    2. Otherwise the EQUIPMENT FAMILY, through the one canonical label ->
       family mapping the project already has
       (`match_rules.sheet_kind_from_equipment_type`, which the review's
       rule 2 uses for the same labels): "Centrifugal Compressor" and
       "Reciprocating Compressor" are the family "compressor", checked
       against the table entry of that same family. When several entries
       share the family, the one named by the bare family word wins
       ("Pump" over "Centrifugal Pump"); with no bare entry the family must
       name exactly one entry, or it decides nothing.
    3. Otherwise `GENERIC` - an unknown or unanticipated type still gets the
       generic minimum (see GENERIC_FALLBACK in `evaluate`), never nothing.

    Before this, the lookup was verbatim: two labels the classifier emits
    ("Centrifugal Compressor", "Reciprocating Compressor") missed the
    "Compressor" key and silently fell to the 2-field generic list.
    """
    from .match_rules import sheet_kind_from_equipment_type
    if not equipment_type:
        return GENERIC
    table = [key for key in rules["mandatory"] if key != GENERIC]
    folded = _fold(equipment_type)
    exact = next((key for key in table if _fold(key) == folded), None)
    if exact is not None:
        return exact
    family = sheet_kind_from_equipment_type(equipment_type)
    if family is None:
        return GENERIC
    same = [key for key in table if sheet_kind_from_equipment_type(key) == family]
    bare = [key for key in same if _fold(key) == family]
    if bare:
        return bare[0]
    return same[0] if len(same) == 1 else GENERIC


def evaluate(facts: list[dict], *, equipment_type: str | None, page_texts: dict[int, str],
             rules: dict | None = None) -> list[dict]:
    """Every check's result for one datasheet. Pure."""
    rules = rules or load_rules()
    by_tag: dict[str | None, dict[str, list[dict]]] = {}
    for fact in facts:
        role = role_of(fact.get("field_name") or "", rules)
        if role:
            by_tag.setdefault(fact.get("equipment_tag"), {}).setdefault(role, []).append(fact)
    if not by_tag:
        by_tag[None] = {}
    out: list[dict] = []
    # GENERIC_FALLBACK (2026-09-27): `equipment_type` is unknown/unconfirmed
    # on almost every submittal today (nothing wrote it before B9, and B9's
    # classifier itself only matches a document whose own text names its
    # equipment - many still will not). Before this fallback that meant
    # `mandatory` was silently `[]`: every one of these checks ran and found
    # nothing to say, on every such document, forever. A generic minimum
    # (design and test conditions any datasheet states) now runs instead -
    # never zero checks for the mere fact that the type is not yet known.
    # An equipment_type the mandatory table has no entry for, directly or
    # through its equipment family (a value this file's author never
    # anticipated - see `mandatory_list_key`), gets the same generic list,
    # for the same reason: a name that fails to look up is not evidence the
    # sheet needs no checking. A label the CLASSIFIER emits must never land
    # here - tests/test_datasheet_checks.py enumerates them all.
    mandatory = rules["mandatory"].get(mandatory_list_key(equipment_type, rules), [])
    equipment_phrase = f"a {equipment_type}" if equipment_type else "any datasheet"
    # UNTAGGED FIELDS ARE THE SHEET'S COMMON SECTION (audit 2026-09-30). A
    # two-pump sheet states design pressure once, for both pumps, and rated
    # flow per pump. Grouping strictly by tag reported design pressure missing
    # for P-101A AND P-101B and rated flow missing for "no tag". Now an
    # untagged value counts for every tag on the sheet; a tag's OWN value is
    # never lent to another tag or to the common section.
    common = by_tag.get(None, {})
    tagged = any(tag is not None for tag in by_tag)
    for tag, roles in by_tag.items():
        # The common section of a sheet that has tags: absences are judged per
        # tag (below), not here; its own placeholders and units still are.
        shared_section = tag is None and tagged
        # ---- mandatory fields: present, and not a placeholder
        for role in mandatory:
            found = roles.get(role, [])
            if not found and (shared_section or (tag is not None and common.get(role))):
                # Stated once in the common section - its placeholder, if any,
                # is reported there, once, not repeated per tag.
                continue
            if not found:
                out.append(_result("DS-M1", MISSING_INFORMATION,
                                   f"{_pretty(role)} is a mandatory field for {equipment_phrase}.",
                                   f"{_pretty(role)} was not found in the fields read from the datasheet.",
                                   None, role, tag))
                continue
            for fact in found:
                # ONE LIST (rule 8): `blank_markers`, the list the datasheet
                # reader itself used to mark the fact blank - a lone "*" or
                # "VENDOR TO ADVISE" is a placeholder here exactly as there.
                printed = fact.get("field_value") or fact.get("blank_marker") or ""
                if fact.get("is_blank") or (printed.strip()
                                            and blank_markers.classify(printed)[0]):
                    out.append(_result("DS-M2", MISSING_INFORMATION,
                                       f"{_pretty(role)} is a mandatory field for {equipment_phrase}.",
                                       f"{_label(fact, role)} is marked '{_shown(fact) or fact.get('blank_marker')}' "
                                       f"on page {fact.get('page')}; the contractor is to provide the value.",
                                       fact, role, tag))
        # ---- units: present, and of the field's kind
        for role in rules["needs_unit"]:
            for fact in roles.get(role, []):
                if fact.get("is_blank") or fact.get("raw_value") in (None, ""):
                    continue
                kind = rules["roles"][role]["kind"]
                unit = fact.get("raw_unit")
                if not unit:
                    out.append(_result("DS-U1", MISSING_INFORMATION,
                                       f"{_pretty(role)} needs a unit.",
                                       f"{_label(fact, role)} is stated as '{_shown(fact)}' on page "
                                       f"{fact.get('page')} without a unit.", fact, role, tag))
                elif (found := _unit_kind(unit, rules)) and found != kind:
                    out.append(_result("DS-U2", NON_COMPLIANT,
                                       f"{_pretty(role)} must be stated in a {kind} unit.",
                                       f"{_label(fact, role)} is stated in '{unit}' on page {fact.get('page')}, "
                                       f"which is a {found} unit, not a {kind} unit.", fact, role, tag))
        # ---- consistency: pure arithmetic, same scale only
        for rule in rules["consistency"]:
            left, right = roles.get(rule["left"], []), roles.get(rule["right"], [])
            if tag is not None:
                if not left and not right:
                    continue    # both sides common: judged once, in the common section
                # A side this tag does not state is the common section's.
                left = left or common.get(rule["left"], [])
                right = right or common.get(rule["right"], [])
            if len({_shown(f) for f in left}) != 1 or len({_shown(f) for f in right}) != 1:
                continue    # absent, or two different values under one name: not chosen
            a, b = _number(left[0]), _number(right[0])
            if a is None or b is None or a[1] != b[1] or a[2] != b[2]:
                continue    # not on one scale: skipped, never guessed
            ok = _OPS[rule["op"]](a[0], b[0])
            calc = (f"{_label(left[0], rule['left'])} {_shown(left[0])} (page {left[0].get('page')}) is "
                    f"{'' if ok else 'not '}{_OP_WORDS[rule['op']]} {_label(right[0], rule['right']).lower()} "
                    f"{_shown(right[0])} (page {right[0].get('page')}).")
            out.append(_result(rule["id"], COMPLIANT if ok else NON_COMPLIANT, rule["text"],
                               calc, left[0], rule["left"], tag))
    # ---- revision block: two or more of the revision table's own headings
    # Two DISTINCT revision-table headings on one page (row_noise's markers,
    # read line by line): the rule row_noise uses to recognise the block.
    from .row_noise import _REVISION_TABLE_MARKERS
    def _block(text: str) -> bool:
        lines = (text or "").splitlines()
        return sum(1 for m in _REVISION_TABLE_MARKERS if any(m.search(ln) for ln in lines)) >= 2
    has_block = any(_block(text) for text in page_texts.values())
    if page_texts and equipment_type:
        out.append(_result("DS-R1", COMPLIANT if has_block else MISSING_INFORMATION,
                           "A datasheet carries a revision block.",
                           ("A revision block was found." if has_block else
                            "No revision block was found on the datasheet pages read."),
                           None, "revision_block", None))
    return out


# ---------------------------------------------------------------- store

def store(review_run_id: str, submittal_id: str, results: list[dict], *,
          pages_read: dict) -> list[dict]:
    """Write each result as a finding of the run (origin 'datasheet_check')."""
    from . import comparison
    from . import review as review_mod
    from .db import connect
    written = []
    # A CHECK AN ENGINEER REJECTED in this run is kept by the re-run's delete
    # (`review.UNDECIDED_SQL`) and not written again beside it (audit
    # 2026-09-30): same rule, same field, same tag, same value.
    fold = lambda v: " ".join(str(v or "").lower().split())  # noqa: E731
    rejected = {(fold(f.get("requirement_source_text")), f.get("fact_id"),
                 fold(f.get("equipment_tag")), fold(f.get("contractor_section")))
                for f in review_mod.rejected_in_run(review_run_id, ORIGIN)}
    # A PASS IS NOT A COMMENT. Only what the engineer must act on is written;
    # a check that held adds no row (it would only pad every count).
    for r in (x for x in results if x["status"] != COMPLIANT):
        status, detail = r["status"], r["detail"]
        if r["rule_id"] == "DS-M1":
            # AN ABSENCE IS QUALIFIED LIKE EVERY ABSENCE: not found is not "not
            # stated" while a page is unread or read only by the page reader.
            verdict = comparison.qualify_by_pages(
                {"status": status, "rationale": detail}, pages_read)
            status, detail = verdict["status"], verdict["rationale"]
        if (fold(f"{LABEL} {r['rule_id']}: {r['text']}"), r["fact_id"],
                fold(r["equipment_tag"]), fold(r["field"])) in rejected:
            continue
        finding = review_mod.create({
            "document_id": submittal_id, "category": "technical_query",
            "severity": "major" if status == NON_COMPLIANT else "minor",
            "requirement": r["text"][:4000], "finding": f"{LABEL}: {detail}"[:4000],
            "required_action": ("Contractor to correct the datasheet." if status == NON_COMPLIANT
                                else "Contractor to provide the value." if status == MISSING_INFORMATION
                                else "None."),
            "status": "open", "approval_status": "pending",
        }, created_by=None)
        conn = connect()
        with conn:
            conn.execute(
                """UPDATE review_findings SET review_run_id = ?, origin = ?, compliance_status = ?,
                       contractor_page = ?, contractor_section = ?, contractor_evidence_text = ?,
                       requirement_source_text = ?, ai_rationale = ?, fact_id = ?, equipment_tag = ?
                   WHERE id = ?""",
                (review_run_id, ORIGIN, status, r["page"], r["field"], r["value"],
                 f"{LABEL} {r['rule_id']}: {r['text']}",
                 detail if detail.startswith(("UNREAD_PAGES", "PAGE_READER_ONLY"))
                 else f"{LABEL} {r['rule_id']}: {detail}",
                 r["fact_id"], r["equipment_tag"], finding["id"]))
        written.append({**finding, "compliance_status": status, "origin": ORIGIN,
                        "contractor_page": r["page"], "ai_rationale": detail})
    return written
