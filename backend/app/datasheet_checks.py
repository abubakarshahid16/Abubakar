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

from . import absence, blank_markers

RULES_PATH = Path(__file__).parent / "reference" / "datasheet_checks.json"
ORIGIN = "datasheet_check"
LABEL = "Datasheet check"

COMPLIANT = "COMPLIANT"
NON_COMPLIANT = "NON_COMPLIANT"
MISSING_INFORMATION = "MISSING_INFORMATION"
NEEDS_ENGINEER_REVIEW = "NEEDS_ENGINEER_REVIEW"

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


def _sentence(reason: str) -> str:
    """"Could not be checked: <reason>." as a sentence that starts a finding."""
    text = absence.could_not_be_checked_sentence(reason)
    return text[:1].upper() + text[1:]


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
    return table_key(equipment_type, rules["mandatory"])


def table_key(equipment_type: str | None, table: dict) -> str:
    """`mandatory_list_key`'s lookup for any table keyed by equipment type
    (the mandatory lists, the review checklists): the table's own key, else
    the equipment family's, else `GENERIC`."""
    from .match_rules import sheet_kind_from_equipment_type
    if not equipment_type:
        return GENERIC
    table = [key for key in table if key != GENERIC]
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


def revision_check_not_run(equipment_type: str | None, page_texts: dict) -> str | None:
    """Why the revision-block check (DS-R1) did not run, or None when it did.

    #633: it used to be dropped silently, so a sheet with no page text, or no
    known equipment type, read as having passed a check nobody made. This is
    not a finding (a review of a sheet with no equipment type would then always
    carry one more engineer question); the run records it and every export
    lists it among the parts that could not be checked.
    """
    if not page_texts:
        return "no page text was read for this datasheet"
    if not equipment_type:
        return "the equipment type is unknown"
    return None


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
            if not left or not right:
                continue    # absent: the mandatory-field checks say so
            # #633: A PAIR THAT CANNOT BE COMPARED IS SAID, NOT SKIPPED. Both
            # fields are on the sheet; if they cannot be checked against each
            # other (a name with two different values, a value that is not a
            # number, two different scales or pressure bases) a design pressure
            # below the operating pressure would be invisible. It is an
            # engineer's question, with the reason; never a guess either way.
            if len({_shown(f) for f in left}) != 1 or len({_shown(f) for f in right}) != 1:
                out.append(_result(rule["id"], NEEDS_ENGINEER_REVIEW, rule["text"],
                                   _sentence(
                                       "a field in this pair has two different values on the "
                                       "sheet, so none was chosen"),
                                   left[0], rule["left"], tag))
                continue
            a, b = _number(left[0]), _number(right[0])
            if a is None or b is None or a[1] != b[1] or a[2] != b[2]:
                out.append(_result(rule["id"], NEEDS_ENGINEER_REVIEW, rule["text"],
                                   _sentence(
                                       "the two values are not numbers on one scale and "
                                       "pressure basis"),
                                   left[0], rule["left"], tag))
                continue
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
    # ---- #746 THE REVIEW CHECKLIST for this equipment type (DRAFT until a
    # client discipline engineer signs it off): each item carries its clause.
    checklist = checklist_for(equipment_type, rules)
    if checklist:
        for tag, roles in by_tag.items():
            if tag is None and tagged:
                continue    # the common section counts for every tag (above)
            for item in checklist["items"]:
                out.append(evaluate_item(item, roles, common if tag is not None else {},
                                         tag, rules, draft=checklist["draft"], page_texts=page_texts))
    if page_texts and equipment_type:
        out.append(_result("DS-R1", COMPLIANT if has_block else MISSING_INFORMATION,
                           "A datasheet carries a revision block.",
                           ("A revision block was found." if has_block else
                            "No revision block was found on the datasheet pages read."),
                           None, "revision_block", None))
    return out


# ---------------------------------------------------------------- #746 checklist

NOT_APPLICABLE = "NOT_APPLICABLE"
#: The local, git-ignored overlay (`<data_dir>/checklists/<type>.json`): items
#: not (yet) approved for the repo stay on the machine. Client standard items
#: approved by the owner (2026-10-10) are in the committed JSON, in our own words.
LOCAL_DIR_NAME = "checklists"
_RULE_KINDS = ("required", "compare", "constant", "percent_of", "allowed", "above_by")


def _local_items(key: str) -> list[dict]:
    from .config import settings
    slug = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    path = Path(settings.data_dir) / LOCAL_DIR_NAME / f"{slug}.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [{**item, "local": True} for item in data.get("items", [])]


def checklist_for(equipment_type: str | None, rules: dict) -> dict | None:
    """The equipment type's review checklist: the committed items plus the
    local overlay's, each validated (an item without a source clause or with
    an unknown rule kind is refused loudly, never run). None when the type
    has none."""
    table = rules.get("checklists") or {}
    if not table:
        return None
    key = table_key(equipment_type, table)
    if key not in table:
        return None
    entry = table[key]
    items = list(entry.get("items", [])) + _local_items(key)
    for item in items:
        source = item.get("source") or {}
        if not (item.get("id") and item.get("text") and source.get("standard") and source.get("clause")):
            raise ValueError(f"checklist item {item.get('id')!r} needs an id, text and a source clause")
        if (item.get("rule") or {}).get("kind") not in _RULE_KINDS:
            raise ValueError(f"checklist item {item['id']!r}: unknown rule kind")
    draft = (entry.get("sign_off") or {}).get("status") != "signed"
    return {"key": key, "items": items, "draft": draft}


def checklist_sources(equipment_type: str | None, rules: dict | None = None) -> dict | None:
    """#746: `{"key", "items", "standards"}` - the type's checklist, how many
    items it has, and the standards its items cite (from `source.standard`,
    never a list written in code). None when the type has no checklist."""
    checklist = checklist_for(equipment_type, rules or load_rules())
    if not checklist:
        return None
    return {"key": checklist["key"], "items": len(checklist["items"]),
            "standards": sorted({i["source"]["standard"] for i in checklist["items"]})}


def _measure(fact: dict):
    """The fact's value as a `claims.Measurement`: read from the printed number
    and unit, or the stored normalised value when the printed unit cannot be
    read."""
    import dataclasses

    from . import claims
    raw = fact.get("raw_value")
    if raw in (None, ""):
        return None
    m = claims.normalise(str(raw), fact.get("raw_unit") or "")
    if m.normalized_value is None and fact.get("normalized_value") is not None and fact.get("normalized_unit"):
        m = dataclasses.replace(m, normalized_value=float(fact["normalized_value"]),
                                normalized_unit=fact["normalized_unit"])
    return m


def _scale(m) -> tuple[float, str, str | None] | None:
    """(number, scale, gauge/absolute) - normalised when possible, else the
    printed number on its own spelling."""
    from . import claims
    if m is None:
        return None
    base, reference = claims.split_reference(m.raw_unit)
    if m.normalized_value is not None and m.normalized_unit:
        return m.normalized_value, m.normalized_unit, reference
    number = claims.parse_value(str(m.raw_value))
    if number is None:
        return None
    return number, _fold(base), reference


def _one(found: list[dict]) -> tuple[dict | None, str | None]:
    """The one value a field states, or why there is not one."""
    if not found:
        return None, "absent"
    if len({_shown(f) for f in found}) != 1:
        return None, "two different values"
    return found[0], None



def coverage(results: list[dict]) -> dict | None:
    """The reader-coverage line of a review (planner 2026-10-10, roadmap R11):
    of the checklist's fields (each field once, across tags), how many were
    READ as a fact, and how many are on the sheet but were NOT read (a reader
    gap, with the pages): the to-do list for the datasheet reader. None when
    the review ran no checklist."""
    items = [r for r in results if r.get("checklist")]
    if not items:
        return None
    fields: dict[str, str] = {}
    gap_pages: dict[str, set] = {}
    for r in items:
        role = r.get("role") or ""
        state = "read" if r.get("fact_id") else ("gap" if r.get("reader_gap") else "absent")
        # a field read for one tag counts as read; a gap only if never read
        if fields.get(role) != "read":
            fields[role] = "read" if state == "read" else (fields.get(role) if fields.get(role) == "gap" else state)
        if r.get("reader_gap"):
            gap_pages.setdefault(role, set()).update(r.get("pages") or [])
    gaps = sorted(f for f, st in fields.items() if st == "gap")
    return {"fields": len(fields), "read": sum(1 for st in fields.values() if st == "read"),
            "on_sheet_not_read": len(gaps),
            "gap_pages": sorted({p for f in gaps for p in gap_pages.get(f, ())})}


def _page_span(page_texts: dict[int, str] | None) -> str:
    pages = sorted(page_texts or {})
    if not pages:
        return "none"
    return f"{pages[0]}-{pages[-1]}" if len(pages) > 1 else str(pages[0])


def _synonyms() -> dict[str, list[str]]:
    data = json.loads((RULES_PATH.parent / "field_synonyms.json").read_text(encoding="utf-8"))
    return data.get("groups") or {}


def label_patterns(role: str, rules: dict) -> list[re.Pattern]:
    """The ways a sheet prints this role's label: the role's own name patterns
    (written for whole folded labels, used here without their anchors) and,
    when the role is a group of `field_synonyms.json`, every spelling of it."""
    out = []
    for pattern in rules["roles"].get(role, {}).get("names", []):
        body = pattern[1:] if pattern.startswith("^") else pattern
        body = body[:-1] if body.endswith("$") else body
        body = body.replace("( .*)?", "")
        out.append(re.compile(r"(?<![a-z0-9])(?:" + body + r")(?![a-z0-9])"))
    # Other wordings a sheet uses for this field (`printed_as`, data): "Effective
    # area" for the orifice area, "blocked discharge" for the relief case.
    group = (_synonyms().get(role.replace("_", " ")) or []) + list(
        rules["roles"].get(role, {}).get("printed_as", []))
    for spelling in group:
        out.append(re.compile(r"(?<![a-z0-9])" + re.escape(spelling.lower()) + r"(?![a-z0-9])"))
    return out


def label_search(role: str, rules: dict, page_texts: dict[int, str]) -> list[int] | None:
    """The pages whose own text prints the role's label, or None when the
    search cannot decide anything: no page text at all, or a page with no text
    (a scan the text layer does not cover), where the label could be."""
    from .datasheets import normalise_field_name
    if not page_texts or any(not (t or "").strip() for t in page_texts.values()):
        return None
    patterns = label_patterns(role, rules)
    words = [w for w in role.split("_") if w]
    if not patterns and not words:
        return None
    found = []
    for page, text in sorted(page_texts.items()):
        # Lines JOINED: a label wraps ("Orifice" / "area") or is combined
        # ("Inlet / Outlet size"). The search errs towards FINDING the label:
        # a false "on the sheet, engineer check" costs a look; a false
        # "missing" blames the contractor for a value the sheet prints.
        folded = " ".join(normalise_field_name(line) for line in (text or "").splitlines())
        if any(p.search(folded) for p in patterns) or _words_near(words, folded.split()):
            found.append(page)
    return found


#: How many words apart a label's own words may stand and still be the label.
LABEL_WINDOW = 6


def _words_near(words: list[str], tokens: list[str]) -> bool:
    """Every word of the role's name ("orifice", "area") within LABEL_WINDOW
    tokens of the first, each matched by its first five letters ("relie"
    finds relief and relieving, "press" finds press. and pressure)."""
    stems = [w[:5] for w in words]
    for i, tok in enumerate(tokens):
        if not tok.startswith(stems[0]):
            continue
        window = tokens[max(0, i - LABEL_WINDOW):i + LABEL_WINDOW + 1]
        if all(any(t.startswith(stem) for t in window) for stem in stems[1:]):
            return True
    return False


def evaluate_item(item: dict, roles: dict, common: dict, tag: str | None, rules: dict,
                  *, draft: bool, page_texts: dict[int, str] | None = None) -> dict:
    """One checklist item's result: COMPLIANT, NON_COMPLIANT, MISSING_INFORMATION
    (the field is not given; qualified by the pages read when stored),
    NEEDS_ENGINEER_REVIEW (with the reason) or NOT_APPLICABLE (its condition
    does not hold, with the reason). Pure: code decides, no model."""
    from . import claims

    rule = item["rule"]
    source = item["source"]
    cite = f"{source['standard']} {source['clause']}"
    text = f"{item['text']} ({cite}{'; DRAFT checklist, not signed off' if draft else ''})"
    field = rule.get("field") or rule.get("left")

    def get(role):
        return roles.get(role) or common.get(role) or []

    def res(status, detail, fact=None, role=None):
        r = _result(item["id"], status, text, detail, fact, role or field, tag)
        return {**r, "source": cite, "severity": item.get("severity", "minor"),
                "checklist": True, "local": bool(item.get("local"))}

    raw_conditions = item.get("condition")
    # One condition, or a list that must ALL hold (a bellows valve AND sour service).
    conditions = (raw_conditions if isinstance(raw_conditions, list)
                  else [raw_conditions] if raw_conditions else [])
    unknown = None    # the first condition the sheet does not state, if any
    for condition in conditions:
        cond_fact, why = _one(get(condition["role"]))
        # `when_unknown: "evaluate"` - set ONLY on items whose answer cannot
        # be wrong whatever the condition ("the molecular weight is stated",
        # "k is above 1"): an unknown condition does not stop them. Any other
        # item with an unknown condition is an engineer's question.
        if cond_fact is None:
            if item.get("when_unknown") != "evaluate":
                state = ("the sheet does not state it" if why == "absent"
                         else "it has two different values on the sheet")
                return res(NEEDS_ENGINEER_REVIEW, _sentence(
                    f"whether it applies depends on the {_pretty(condition['role']).lower()}, and {state}"))
            unknown = unknown or condition
            continue
        stated = _fold(_shown(cond_fact))
        if not any(_fold(word) in stated for word in condition["any"]):
            return res(NOT_APPLICABLE,
                       f"Does not apply: {_label(cond_fact, condition['role'])} is "
                       f"'{_shown(cond_fact)}' (page {cond_fact.get('page')}).",
                       cond_fact, condition["role"])
    kind = rule["kind"]
    fact, why = _one(get(field))
    if fact is None and unknown is not None:
        # The condition is unknown and the field is absent: whether the
        # contractor owes this value is not known, so it is not a missing value.
        return res(NEEDS_ENGINEER_REVIEW, _sentence(
            f"the {_pretty(field).lower()} is not given, and whether it is needed depends on the "
            f"{_pretty(unknown['role']).lower()}, which the sheet does not state"))
    if fact is None:
        if why == "absent":
            # PLANNER 2026-10-10 (F-a): a field not read as a fact is searched
            # for in the text of every page. On the sheet but not read is a
            # READER GAP, never the contractor's omission; not in any page's
            # text, with every page's text there, is missing (the contractor's).
            searched = label_search(field, rules, page_texts or {})
            if searched is None:
                return res(MISSING_INFORMATION,
                           f"{_pretty(field)} was not found in the fields read from the datasheet.")
            if searched:
                pages = ", ".join(str(n) for n in searched)
                r = res(NEEDS_ENGINEER_REVIEW,
                        f"{_pretty(field)} is on the sheet but was not read: engineer to check "
                        f"page{'s' if len(searched) > 1 else ''} {pages}.")
                return {**r, "reader_gap": True, "pages": searched}
            r = res(MISSING_INFORMATION,
                    f"{_pretty(field)} was not found in the fields read or in the text of "
                    f"pages {_page_span(page_texts)}; the contractor is to provide it.")
            return {**r, "text_searched": True}
        return res(NEEDS_ENGINEER_REVIEW,
                   _sentence(f"the {_pretty(field).lower()} has two different values on the sheet"),
                   get(field)[0])
    if fact.get("is_blank"):
        return res(MISSING_INFORMATION,
                   f"{_label(fact, field)} is marked '{_shown(fact) or fact.get('blank_marker')}' "
                   f"on page {fact.get('page')}; the contractor is to provide the value.", fact)
    noted = f" The sheet marks this value '{fact['value_note']}'." if fact.get("value_note") else ""
    where = f"{_label(fact, field)} {_shown(fact)} (page {fact.get('page')})"
    if kind == "required":
        return res(COMPLIANT, f"{where} is stated.{noted}", fact)
    if kind == "allowed":
        stated = _fold(_shown(fact))
        ok = any(_fold(v) in stated for v in rule["values"])
        return res(COMPLIANT if ok else NON_COMPLIANT,
                   f"{where} is {'one of' if ok else 'not one of'}: {', '.join(rule['values'])}.{noted}",
                   fact)
    measured = _measure(fact)
    unit = (rule.get("unit") or "").strip()
    if (kind == "constant" and unit and measured is not None and not (fact.get("raw_unit") or "").strip()
            and unit.lower() in _fold(fact.get("field_label") or fact.get("field_name"))):
        # A value printed with no unit under a label that names it ("Over
        # pressure %": 21) is in that unit; any other unit-less value is not
        # guessed.
        measured = claims.normalise(str(fact.get("raw_value")), unit)
    left = _scale(measured)
    factor = 1.0
    if kind == "constant":
        right = _scale(claims.normalise(str(rule["value"]), rule.get("unit") or ""))
        right_words = f"{rule['value']} {rule.get('unit') or ''}".strip()
    else:
        other, why = _one(get(rule["right"]))
        if other is None or other.get("is_blank"):
            state = ("is not given" if (other is not None or why == "absent")
                     else "is stated twice with different values")
            return res(NEEDS_ENGINEER_REVIEW, _sentence(
                f"the {_pretty(rule['right']).lower()} it is checked against {state}"), fact)
        right = _scale(_measure(other))
        if kind == "percent_of":
            factor = float(rule["percent"]) / 100.0
        if kind == "above_by":
            right_words = (f"{_label(other, rule['right']).lower()} {_shown(other)} (page {other.get('page')}) "
                           f"plus the greater of {rule['percent']}% or {rule['at_least']} {rule['unit']}")
        right_words = ((f"{rule['percent']}% of " if kind == "percent_of" else "")
                       + f"{_label(other, rule['right']).lower()} {_shown(other)} (page {other.get('page')})")
    if (left is None or right is None or left[1] != right[1]
            or (left[2] and right[2] and left[2] != right[2])):
        return res(NEEDS_ENGINEER_REVIEW, _sentence(
            "the two values are not numbers on one scale and pressure basis"), fact)
    if kind == "above_by":
        # The margin's absolute part on the same scale as both values.
        floor = _scale(claims.normalise(str(rule["at_least"]), rule["unit"]))
        if floor is None or floor[1] != right[1]:
            return res(NEEDS_ENGINEER_REVIEW, _sentence(
                "the required margin is not on the same scale as the two values"), fact)
        margin = max(right[0] * float(rule["percent"]) / 100.0, floor[0])
        ok = left[0] >= right[0] + margin
        return res(COMPLIANT if ok else NON_COMPLIANT,
                   f"{where} is {'' if ok else 'not '}at least {right_words}.{noted}", fact)
    ok = _OPS[rule["op"]](left[0], right[0] * factor)
    return res(COMPLIANT if ok else NON_COMPLIANT,
               f"{where} is {'' if ok else 'not '}{_OP_WORDS[rule['op']]} {right_words}.{noted}", fact)


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
    # "Does not apply" is not a comment either (#746): the condition's reason
    # is in the result, never a CRS row.
    for r in (x for x in results if x["status"] not in (COMPLIANT, NOT_APPLICABLE)):
        status, detail = r["status"], r["detail"]
        absent = (r["rule_id"] in ("DS-M1", "DS-R1")
                  or (r.get("checklist") and r.get("fact_id") is None and not r.get("text_searched")))
        if absent and status == MISSING_INFORMATION:
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
            "severity": (r["severity"] if r.get("checklist") and status == NON_COMPLIANT
                         else "major" if status == NON_COMPLIANT else "minor"),
            "requirement": r["text"][:4000], "finding": f"{LABEL}: {detail}"[:4000],
            "required_action": ("Contractor to correct the datasheet." if status == NON_COMPLIANT
                                else "Contractor to provide the value." if status == MISSING_INFORMATION
                                else "Engineer to check." if status == NEEDS_ENGINEER_REVIEW
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
