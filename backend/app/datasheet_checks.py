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

from . import absence, blank_markers, claims, datasheet_roles, severity_rule
from .same_value import key as _key
from .stated_value import fact_value as _shown
from .stated_value import said as _said

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


def role_of(field_name: str, rules: dict, prefer=frozenset()) -> str | None:
    return datasheet_roles.role_of(field_name, rules, prefer)  # #900


#: #898: how many leading words may qualify a field name ("casing", "shell
#: side") before it stops being that field with a qualifier.
QUALIFIER_WORDS = 2
#: The mandatory-field check's id when the field is stated under a qualifier.
QUALIFIED_RULE = "DS-M1"


def qualified_role_of(field_name: str, rules: dict) -> str | None:
    """The role a field name states UNDER A LEADING QUALIFIER, or None.

    "Casing design pressure" and "Shell side design temperature" are a design
    pressure and a design temperature with a qualifier in front. PF1's first
    run (#881): four sheets printing such a row were told "Design pressure
    was not found". The qualifier is LEADING words only, at most two: "design
    pressure note" and "minimum design metal temperature" are other things.

    NOT A ROLE. A qualified field is never used in a comparison or a unit
    check: the shell side's design pressure against the tube side's operating
    pressure is not a check. It only changes what the mandatory-field check
    says: the sheet states something by that name, for an engineer to confirm.
    """
    words = _fold(field_name).split()
    if role_of(field_name, rules) is not None:
        return None
    for drop in range(1, min(QUALIFIER_WORDS, len(words) - 1) + 1):
        role = role_of(" ".join(words[drop:]), rules)
        if role is not None:
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
    qualified: dict[str | None, dict[str, list[dict]]] = {}  # #898: under a qualifier
    wanted = datasheet_roles.wanted_roles(equipment_type, rules)
    for fact in facts:
        role = role_of(fact.get("field_name") or "", rules, wanted)
        if role:
            by_tag.setdefault(fact.get("equipment_tag"), {}).setdefault(role, []).append(fact)
        elif (under := qualified_role_of(fact.get("field_name") or "", rules)) and not fact.get("is_blank"):
            qualified.setdefault(fact.get("equipment_tag"), {}).setdefault(under, []).append(fact)
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
            # #898: NOT "MISSING" WHEN THE SHEET STATES IT UNDER A QUALIFIER, AND
            # NOT SILENT EITHER. "Casing design pressure: 14 barg" may be the
            # design pressure, or one of two; code does not choose. The finding
            # stays, as an engineer's question that names the row.
            named = [] if found else (qualified.get(tag, {}).get(role) or qualified.get(None, {}).get(role) or [])
            if named:
                labels = ", ".join(sorted({f"'{_label(f, role)}' (page {f.get('page')})" for f in named}))
                out.append(_result(QUALIFIED_RULE, NEEDS_ENGINEER_REVIEW,
                                   f"{_pretty(role)} is a mandatory field for {equipment_phrase}.",
                                   f"{_pretty(role)} was not found under that name; the sheet states "
                                   f"{labels}. Engineer to confirm that it is the {_pretty(role).lower()}.",
                                   named[0], role, tag))
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
                                       f"{_label(fact, role)} is marked '{_said(fact) or fact.get('blank_marker')}' "
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
                                       f"{_label(fact, role)} is stated as '{_said(fact)}' on page "
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
            # #633: A PAIR THAT CANNOT BE COMPARED IS SAID, NOT SKIPPED (two
            # different values, a non-number, two scales or pressure bases):
            # an engineer's question with the reason, never a guess either way.
            # The same number and unit with a note is ONE value (order 223).
            if len({_key(f) for f in left}) != 1 or len({_key(f) for f in right}) != 1:
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
            calc = (f"{_label(left[0], rule['left'])} {_said(left[0])} (page {left[0].get('page')}) is "
                    f"{'' if ok else 'not '}{_OP_WORDS[rule['op']]} {_label(right[0], rule['right']).lower()} "
                    f"{_said(right[0])} (page {right[0].get('page')}).")
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
#: The words a DRAFT checklist's item carries (planner 11 Oct: a draft still
#: produces its findings, marked so the engineer sees they are unconfirmed;
#: the run trace counts them as `draft_checklist`). One home: written here,
#: read by `is_draft_checklist`.
DRAFT_MARK = "DRAFT checklist, not signed off"


def is_draft_checklist(text: str | None) -> bool:
    """Whether a stored finding's requirement came from a DRAFT checklist."""
    return DRAFT_MARK in str(text or "")
#: The local, git-ignored overlay (`<data_dir>/checklists/<type>.json`): items
#: not (yet) approved for the repo stay on the machine. Client standard items
#: approved by the owner (2026-10-10) are in the committed JSON, in our own words.
LOCAL_DIR_NAME = "checklists"
_RULE_KINDS = ("required", "compare", "constant", "percent_of", "allowed", "above_by", "calc")


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


def implausible(fact: dict, role: str, rules: dict) -> str | None:
    """Why a stated number cannot be right for its field, or None (R12, #776).

    The field's `plausible` range in the rules (only fields that carry one):
    a value outside it is a reading or entry error, so it is never "stated"
    and never fed to a calculation. A value that is not a number is not judged
    here."""
    bounds = (rules.get("roles", {}).get(role) or {}).get("plausible")
    if not bounds:
        return None
    from . import claims
    number = claims.parse_value(str(fact.get("raw_value")))
    if number is None:
        return None
    low, high = bounds.get("min"), bounds.get("max")
    if (low is not None and number < low) or (high is not None and number > high):
        span = (f"{low} to {high}" if low is not None and high is not None
                else f"at most {high}" if high is not None else f"at least {low}")
        return (f"{_label(fact, role)} {_said(fact)} (page {fact.get('page')}) is outside the "
                f"plausible range for this field ({span}); engineer to check the value")
    return None


def implied_phase(get, condition_role: str, rules: dict) -> tuple[str, dict, str] | None:
    """(phase, the fact that implies it, that fact's role) when the condition's own field is not
    stated but another field names one phase only - e.g. the fluid service
    'Cooling water' implies liquid (R12, #776). None when nothing is implied
    or the service names more than one phase. A guess: callers only use it to
    ask the engineer, never to decide."""
    spec = (rules.get("roles", {}).get(condition_role) or {}).get("implied_by")
    if not spec:
        return None
    fact, _why = _one(get(spec["role"]))
    if fact is None or fact.get("is_blank"):
        return None
    words = set(re.findall(r"[a-z0-9]+", _fold(_shown(fact))))
    phases = [phase for phase, names in spec["phases"].items()
              if any(name in words for name in names)]
    return (phases[0], fact, spec["role"]) if len(phases) == 1 else None


def _one(found: list[dict]) -> tuple[dict | None, str | None]:
    """The one value a field states, or why there is not one."""
    if not found:
        return None, "absent"
    if len({_key(f) for f in found}) != 1:
        return None, "two different values"
    return found[0], None



def coverage(results: list[dict]) -> dict | None:
    """The reader-coverage line of a review (planner 2026-10-10, roadmap R11):
    of the checklist's fields (each field once, across tags), how many were
    READ as a fact, and how many are on the sheet but were NOT read (a reader
    gap, with the pages): the to-do list for the datasheet reader. None when
    the review ran no checklist."""
    # A calculation compares a field the `required` items already count; it
    # is not a field of its own (R13), so the reader-coverage line is unchanged.
    items = [r for r in results if r.get("checklist") and not r.get("calc")]
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
    text = f"{item['text']} ({cite}{'; ' + DRAFT_MARK if draft else ''})"
    field = rule.get("field") or rule.get("left")

    def get(role):
        return roles.get(role) or common.get(role) or []

    def res(status, detail, fact=None, role=None):
        r = _result(item["id"], status, text, detail, fact, role or field, tag)
        return {**r, "source": cite, "severity": item.get("severity", "minor"),
                "checklist": True, "local": bool(item.get("local")),
                # Stored with the finding like any other citation (#805 Stage A).
                "standard": source["standard"], "clause": source["clause"], "draft": draft}

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
            if rule["kind"] == "calc":
                # R13: which formula applies is not known; the phase item asks.
                return {**res(NOT_CALCULATED, _sentence(
                    f"the {_pretty(condition['role']).lower()} is not stated, so the formula "
                    f"to use is not known")), "calc": True}
            implied = implied_phase(get, condition["role"], rules) if why == "absent" else None
            if implied and not any(_fold(word) in implied[0] for word in condition["any"]):
                # R12 (#776): the phase is not stated, but the service names the
                # OTHER phase - this item probably does not apply. Asked, never
                # decided: a guess is shown as a guess (CLAUDE.md rule 4).
                phase, hint, hint_role = implied
                return res(NEEDS_ENGINEER_REVIEW, _sentence(
                    f"the {_pretty(condition['role']).lower()} is not stated, and "
                    f"{_label(hint, hint_role).lower()} '{_said(hint)}' (page {hint.get('page')}) "
                    f"suggests {phase}, so this item probably does not apply; engineer to confirm "
                    f"the {_pretty(condition['role']).lower()}"), hint, hint_role)
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
                       f"'{_said(cond_fact)}' (page {cond_fact.get('page')}).",
                       cond_fact, condition["role"])
    kind = rule["kind"]
    if kind == "calc":
        return evaluate_calc(item, field, get, res, rules)
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
                        f"{_pretty(field)} was not read as a value; wording for it appears on "
                        f"page{'s' if len(searched) > 1 else ''} {pages}: engineer to check.")
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
                   f"{_label(fact, field)} is marked '{_said(fact) or fact.get('blank_marker')}' "
                   f"on page {fact.get('page')}; the contractor is to provide the value.", fact)
    if (doubt := implausible(fact, field, rules)) is not None:
        # R12 (#776): an impossible value is never "stated" or compared.
        return res(NEEDS_ENGINEER_REVIEW, _sentence(doubt), fact)
    noted = f" The sheet marks this value '{fact['value_note']}'." if fact.get("value_note") else ""
    where = f"{_label(fact, field)} {_said(fact)} (page {fact.get('page')})"
    if kind == "required":
        return res(COMPLIANT, f"{where} is stated.{noted}", fact)
    if kind == "allowed":
        stated = _fold(_shown(fact))
        ok = any(_fold(v) in stated for v in rule["values"])
        return res(COMPLIANT if ok else NON_COMPLIANT,
                   f"{where} is {'one of' if ok else 'not one of'}: {', '.join(rule['values'])}.{noted}",
                   fact)
    if kind == "percent_of" and rule.get("stated_as_percent") and _is_percent(fact):
        # R13: a value the sheet states AS a percentage of the right-hand
        # field ("built-up back pressure 8 %" of the set pressure) is compared
        # as that percentage; the right-hand value is not needed.
        stated = _number_of_or_none(fact)
        if stated is None:
            return res(NEEDS_ENGINEER_REVIEW, _sentence(f"'{_said(fact)}' is not a number"), fact)
        ok = _OPS[rule["op"]](stated, float(rule["percent"]))
        return res(COMPLIANT if ok else NON_COMPLIANT,
                   f"{where} is {'' if ok else 'not '}{_OP_WORDS[rule['op']]} {rule['percent']}% of the "
                   f"{_pretty(rule['right']).lower()}.{noted}", fact)
    if kind == "constant" and rule.get("percent_of_role") and not _is_percent(fact):
        # R13: a percentage limit on a value the sheet states as a PRESSURE
        # ("overpressure 1.2 barg" against 10 % of the set pressure): the
        # percentage is worked out from the set pressure, by code.
        reference = rule["percent_of_role"]
        try:
            amount = _converted(fact, field, "pressure_kpa", rules)
            ref_fact = _input(get, reference)
            ref_kpa = _gauge_kpa(ref_fact, reference, rules)
            if ref_kpa <= 0:
                raise _NotCalculated(f"the {_pretty(reference).lower()} is not above 0")
        except _NotCalculated as exc:
            return res(NEEDS_ENGINEER_REVIEW, _sentence(
                f"{exc.reason}, so the percentage was not worked out"), fact)
        percent = amount / ref_kpa * 100.0
        ok = _OPS[rule["op"]](percent, float(rule["value"]))
        return res(COMPLIANT if ok else NON_COMPLIANT,
                   f"{where} is {percent:.1f}% of {_quoted(ref_fact, reference)}, which is "
                   f"{'' if ok else 'not '}{_OP_WORDS[rule['op']]} {rule['value']}%.{noted}", fact)
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
            right_words = (f"{_label(other, rule['right']).lower()} {_said(other)} (page {other.get('page')}) "
                           f"plus the greater of {rule['percent']}% or {rule['at_least']} {rule['unit']}")
        right_words = ((f"{rule['percent']}% of " if kind == "percent_of" else "")
                       + f"{_label(other, rule['right']).lower()} {_said(other)} (page {other.get('page')})")
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


# ---------------------------------------------------------------- R13 calculations

#: A calculation item whose inputs the sheet does not give: skipped with its
#: reason, never a comment (the `required` items already ask for the field).
NOT_CALCULATED = "NOT_CALCULATED"
#: API 520-I takes atmospheric pressure as 101.325 kPa (14.7 psi) when it
#: turns a gauge relieving pressure into an absolute one. One home: `claims`.
ATMOSPHERIC_KPA = claims.STANDARD_ATMOSPHERE_KPA
#: Specific gravity is referred to water at 15.6 C (60 F).
WATER_DENSITY_KG_M3 = 999.0
#: The effective coefficients of discharge API 520-I gives for preliminary
#: sizing, the ones API 526 effective orifice areas are paired with.
KD_GAS = 0.975
KD_LIQUID = 0.65
MM2_PER_IN2 = 645.16
_GAUGE_WORDS = re.compile(r"(?<![a-z])(barg|psig|kpag|mpag)(?![a-z])|\(g\)|\bgauge\b")
_ABSOLUTE_WORDS = re.compile(r"(?<![a-z])(bara|psia|kpaa|mpaa)(?![a-z])|\(a\)|\babs(olute)?\b")
#: Order 141 B: the temperature scales have ONE home, `claims` (the review's
#: unit comparison reads the same table).
_TEMPERATURE = claims.TEMPERATURE_SCALES


class _NotCalculated(Exception):
    """An input the calculation needs is not on the sheet in a form it reads."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _unit_key(unit: str | None) -> str:
    return (str(unit or "").lower().replace(" ", "").replace("²", "2").replace("³", "3")
            .replace("°", "deg").replace("μ", "u").replace("µ", "u"))


def _printed_unit(fact: dict) -> tuple[str, str | None]:
    """(unit, gauge/absolute) as the sheet prints it: the value's own unit, else
    the unit the label names in brackets ("Set pressure (barg)")."""
    from . import claims
    raw = str(fact.get("raw_unit") or "").strip()
    if not raw:
        label = str(fact.get("field_label") or fact.get("field_name") or "")
        bracket = re.search(r"\(([^()]+)\)\s*$", label)
        raw = bracket.group(1).strip() if bracket else ""
    base, reference = claims.split_reference(raw) if raw else (None, None)
    return _unit_key(base or raw), reference


def _number_of_or_none(fact: dict) -> float | None:
    from . import claims
    return claims.parse_value(str(fact.get("raw_value")))


def _input(get, role: str) -> dict:
    fact, why = _one(get(role))
    if fact is None or fact.get("is_blank"):
        state = "has two different values" if why == "two different values" else "is not given"
        raise _NotCalculated(f"the {_pretty(role).lower()} {state}")
    return fact


def _number_of(fact: dict, role: str) -> float:
    from . import claims
    number = claims.parse_value(str(fact.get("raw_value")))
    if number is None:
        raise _NotCalculated(f"the {_pretty(role).lower()} '{_said(fact)}' is not a number")
    return number


def _converted(fact: dict, role: str, table: str, rules: dict) -> float:
    """The fact's number in the calculation's unit (`calc_units[table]`)."""
    number = _number_of(fact, role)
    unit, _reference = _printed_unit(fact)
    factor = rules["calc_units"][table].get(unit)
    if factor is None:
        raise _NotCalculated(f"the {_pretty(role).lower()} unit '{fact.get('raw_unit') or unit or 'none'}'"
                             f" is not one this calculation converts")
    return number * float(factor)


def _kelvin(fact: dict, role: str) -> float:
    number = _number_of(fact, role)
    unit, _reference = _printed_unit(fact)
    scale = _TEMPERATURE.get(unit)
    if scale is None:
        raise _NotCalculated(f"the {_pretty(role).lower()} unit '{fact.get('raw_unit') or 'none'}'"
                             f" is not a temperature unit this calculation converts")
    return number * scale[0] + scale[1]


def _basis(fact: dict) -> str | None:
    _unit, reference = _printed_unit(fact)
    if reference:
        return reference
    words = " ".join(str(fact.get(k) or "").lower() for k in ("raw_unit", "field_label", "field_name"))
    if _GAUGE_WORDS.search(words):
        return "gauge"
    if _ABSOLUTE_WORDS.search(words):
        return "absolute"
    return None


def _gauge_kpa(fact: dict, role: str, rules: dict) -> float:
    """A pressure in kPa gauge. A pressure that says neither gauge nor absolute
    is not guessed: the two differ by one atmosphere."""
    value = _converted(fact, role, "pressure_kpa", rules)
    basis = _basis(fact)
    if basis == "absolute":
        return value - ATMOSPHERIC_KPA
    if basis != "gauge":
        raise _NotCalculated(f"the {_pretty(role).lower()} does not say gauge or absolute")
    return value


def _is_percent(fact: dict) -> bool:
    unit = _unit_key(fact.get("raw_unit"))
    if unit == "%":
        return True
    label = str(fact.get("field_label") or fact.get("field_name") or "")
    return not unit and "%" in label


def _overpressure_kpa(get, set_kpa_g: float, rules: dict) -> tuple[float, dict]:
    fact = _input(get, "overpressure")
    if _is_percent(fact):
        return set_kpa_g * _number_of(fact, "overpressure") / 100.0, fact
    return _converted(fact, "overpressure", "pressure_kpa", rules), fact


def _back_pressure_kpa_g(get, rules: dict) -> tuple[float, list[dict], str | None]:
    """(superimposed + built-up back pressure in kPa gauge, the facts used,
    why the figure is only a lower bound). A back pressure the sheet does not
    give, or gives in a form not read, counts as 0 - which can only make the
    calculated area SMALLER than the true one - and says so."""
    total, used, doubt = 0.0, [], None
    for role in ("superimposed_back_pressure", "built_up_back_pressure"):
        fact, _why = _one(get(role))
        if fact is None or fact.get("is_blank"):
            doubt = doubt or f"the {_pretty(role).lower()} is not given (taken as 0)"
            continue
        if re.fullmatch(r"\s*(atm|atmos(pheric)?)\.?\s*", _shown(fact).lower()):
            used.append((role, fact))
            continue
        try:
            number = _number_of(fact, role)
            total += 0.0 if number == 0 else _gauge_kpa(fact, role, rules)
            used.append((role, fact))
        except _NotCalculated as exc:
            doubt = doubt or f"{exc.reason} (taken as 0)"
    return total, used, doubt


def _quoted(fact: dict, role: str) -> str:
    return f"{_label(fact, role).lower()} {_said(fact)} (page {fact.get('page')})"


def _conventional(get) -> str | None:
    """Why the valve's own correction factor (Kb for gas, Kw for liquid) is
    not exactly 1.0, or None when the sheet states a conventional valve."""
    fact, _why = _one(get("valve_type"))
    if fact is not None and "conventional" in _fold(_shown(fact)):
        return None
    return "the valve is not stated as conventional"


def api520_gas_area(get, rules: dict, selected_mm2: float | None = None) -> dict:
    """API 520-I critical flow sizing for gas or vapour (SI form):

        A = W / (C Kd P1 Kb Kc) * sqrt(T Z / M)
        C = 0.03948 * sqrt(k (2 / (k + 1)) ** ((k + 1) / (k - 1)))

    A in mm2, W in kg/h, P1 = set pressure + overpressure + 101.325 kPa (abs),
    T in K. Kd 0.975, Kb 1.0, Kc 1.0. Every simplification can only make A
    SMALLER than the true required area, and each one the sheet does not rule
    out is returned in `lower_bound` (subcritical flow, a non-conventional
    valve, an unknown back pressure)."""
    import math
    capacity = _input(get, "required_capacity")
    w = _converted(capacity, "required_capacity", "mass_flow_kg_h", rules)
    set_fact = _input(get, "set_pressure")
    set_g = _gauge_kpa(set_fact, "set_pressure", rules)
    over, over_fact = _overpressure_kpa(get, set_g, rules)
    p1 = set_g + over + ATMOSPHERIC_KPA
    temperature = _input(get, "relieving_temperature")
    t = _kelvin(temperature, "relieving_temperature")
    facts = {role: _input(get, role) for role in ("molecular_weight", "compressibility",
                                                  "specific_heat_ratio")}
    for role, input_fact in facts.items():
        if (doubt := implausible(input_fact, role, rules)) is not None:
            raise _NotCalculated(doubt)        # R12 (#776): never computed from it
    m = _number_of(facts["molecular_weight"], "molecular_weight")
    z = _number_of(facts["compressibility"], "compressibility")
    k = _number_of(facts["specific_heat_ratio"], "specific_heat_ratio")
    if w <= 0 or p1 <= 0 or t <= 0 or m <= 0 or z <= 0 or k <= 1:
        raise _NotCalculated("an input is outside the formula's range (capacity, pressure, "
                             "temperature, M and Z above 0; k above 1)")
    c = 0.03948 * math.sqrt(k * (2 / (k + 1)) ** ((k + 1) / (k - 1)))
    area = w / (c * KD_GAS * p1) * math.sqrt(t * z / m)
    lower_bound = []
    if (why := _conventional(get)) is not None:
        lower_bound.append(f"{why}, so Kb was taken as 1.0")
    back, back_facts, doubt = _back_pressure_kpa_g(get, rules)
    if doubt:
        lower_bound.append(f"{doubt}, so critical flow was assumed")
    elif back + ATMOSPHERIC_KPA > p1 * (2 / (k + 1)) ** (k / (k - 1)):
        lower_bound.append("the back pressure is above the critical flow pressure, so the flow "
                           "is subcritical and needs a larger area than this")
    inputs = [_quoted(capacity, "required_capacity"), _quoted(set_fact, "set_pressure"),
              _quoted(over_fact, "overpressure"), _quoted(temperature, "relieving_temperature"),
              *(_quoted(f, r) for r, f in facts.items()), *(_quoted(f, r) for r, f in back_facts)]
    return {"area_mm2": area, "inputs": inputs, "lower_bound": lower_bound,
            "coefficients": f"P1 {p1:,.1f} kPa(a), C {c:.4f}, Kd {KD_GAS}, Kb 1.0, Kc 1.0",
            "name": "critical flow sizing for gas or vapour"}


def api520_liquid_area(get, rules: dict, selected_mm2: float | None = None) -> dict:
    """API 520-I sizing for liquid relief (SI form, capacity-certified valves):

        A = 11.78 Q / (Kd Kw Kc Kv) * sqrt(G / (p1 - p2))

    A in mm2, Q in L/min, p1 = set pressure + overpressure (kPa gauge), p2 the
    total back pressure (kPa gauge), G = density / 999 kg/m3. Kd 0.65, Kw 1.0,
    Kc 1.0. Kv from the Reynolds number when the viscosity is given:

        R = Q 18800 G / (mu sqrt(A)),  Kv = 1 / (0.9935 + 2.878 / R**0.5 + 342.75 / R**1.5)

    with A the selected effective area when the sheet gives it, else the
    calculated one (iterated). Every simplification makes A SMALLER than the
    true required area; each one the sheet does not rule out is returned in
    `lower_bound`."""
    import math
    capacity = _input(get, "required_capacity")
    density_fact = _input(get, "density_relieving")
    rho = _converted(density_fact, "density_relieving", "density_kg_m3", rules)
    unit, _reference = _printed_unit(capacity)
    if unit in rules["calc_units"]["liquid_flow_l_min"]:
        q = _converted(capacity, "required_capacity", "liquid_flow_l_min", rules)
    else:
        # a mass flow: Q = W / rho (kg/h over kg/m3 is m3/h; 1 m3/h = 1000/60 L/min)
        w = _converted(capacity, "required_capacity", "mass_flow_kg_h", rules)
        q = w / rho * 1000.0 / 60.0 if rho > 0 else 0.0
    set_fact = _input(get, "set_pressure")
    set_g = _gauge_kpa(set_fact, "set_pressure", rules)
    over, over_fact = _overpressure_kpa(get, set_g, rules)
    back, back_facts, doubt = _back_pressure_kpa_g(get, rules)
    dp = set_g + over - back
    if q <= 0 or rho <= 0:
        raise _NotCalculated("the capacity or the density is not above 0")
    if dp <= 0:
        raise _NotCalculated("the back pressure is not below the relieving pressure")
    g = rho / WATER_DENSITY_KG_M3
    base = 11.78 * q / KD_LIQUID * math.sqrt(g / dp)
    lower_bound = []
    if (why := _conventional(get)) is not None:
        lower_bound.append(f"{why}, so Kw was taken as 1.0")
    if doubt:
        lower_bound.append(doubt)
    inputs = [_quoted(capacity, "required_capacity"), _quoted(density_fact, "density_relieving"),
              _quoted(set_fact, "set_pressure"), _quoted(over_fact, "overpressure"),
              *(_quoted(f, r) for r, f in back_facts)]
    viscosity_fact, _why = _one(get("viscosity_relieving"))
    kv = 1.0
    if viscosity_fact is None or viscosity_fact.get("is_blank"):
        lower_bound.append("the viscosity is not given, so Kv was taken as 1.0")
    else:
        unit, _reference = _printed_unit(viscosity_fact)
        if unit in ("cst", "mm2/s"):
            mu = _number_of(viscosity_fact, "viscosity_relieving") * rho / 1000.0
        else:
            mu = _converted(viscosity_fact, "viscosity_relieving", "viscosity_cp", rules)
        if mu <= 0:
            raise _NotCalculated("the viscosity is not above 0")
        area = selected_mm2 or base
        for _ in range(1 if selected_mm2 else 50):
            reynolds = q * 18800.0 * g / (mu * math.sqrt(area))
            kv = 1.0 / (0.9935 + 2.878 / reynolds ** 0.5 + 342.75 / reynolds ** 1.5)
            area = base / kv
        inputs.append(_quoted(viscosity_fact, "viscosity_relieving"))
    return {"area_mm2": base / kv, "inputs": inputs, "lower_bound": lower_bound,
            "coefficients": f"p1 - p2 {dp:,.1f} kPa, G {g:.3f}, Kd {KD_LIQUID}, Kw 1.0, Kc 1.0, Kv {kv:.3f}",
            "name": "sizing for liquid relief"}


#: The calculations a checklist item may name (`rule.formula`). Formulas are
#: code; which item runs which formula, on which field, is data.
CALCULATIONS = {formula.__name__: formula for formula in (api520_gas_area, api520_liquid_area)}


def evaluate_calc(item: dict, field: str, get, res, rules: dict) -> dict:
    """One calculation item: the sheet's stated area (`field`, the selected
    orifice area or the sheet's own required area) against the area the
    formula calculates from the sheet's own inputs. Below it: NON_COMPLIANT,
    with both numbers. At least it, with every input exact: COMPLIANT. At
    least it, but the calculated area is only a lower bound: an engineer's
    question, with why. An input missing: NOT_CALCULATED, with which."""
    rule = item["rule"]
    fact, _why = _one(get(field))
    if fact is None or fact.get("is_blank"):
        return {**res(NOT_CALCULATED, f"Not calculated: the {_pretty(field).lower()} to compare "
                                      f"with is not given."), "calc": True}
    try:
        stated = _converted(fact, field, "area_mm2", rules)
        calc = CALCULATIONS[rule["formula"]](get, rules, selected_mm2=stated)
    except _NotCalculated as exc:
        return {**res(NOT_CALCULATED, f"Not calculated: {exc.reason}.", fact), "calc": True}
    area = calc["area_mm2"]
    tolerance = float(rule.get("tolerance_percent") or 0)
    floor = area * (1 - tolerance / 100.0)
    source = item["source"]
    basis = (f"the required effective area {area:,.1f} mm2 ({area / MM2_PER_IN2:.4f} in2) calculated by "
             f"{source['standard']} {source['clause']} ({calc['name']}) from "
             f"{', '.join(calc['inputs'])}; {calc['coefficients']}")
    within = f" (within {tolerance:g}% for rounding)" if tolerance else ""
    where = f"{_label(fact, field)} {_said(fact)} (page {fact.get('page')})"
    if stated < floor:
        result = res(NON_COMPLIANT, f"{where} is below {basis}{within}.", fact)
    elif calc["lower_bound"]:
        result = res(NEEDS_ENGINEER_REVIEW,
                     f"{where} is at least {basis}{within}, but that area is a lower bound: "
                     f"{'; '.join(calc['lower_bound'])}. Engineer to check.", fact)
    else:
        result = res(COMPLIANT, f"{where} is at least {basis}{within}.", fact)
    return {**result, "calculated_mm2": round(area, 3), "calc": True}


# ---------------------------------------------------------------- store

def store(review_run_id: str, submittal_id: str, results: list[dict], *,
          pages_read: dict, label=None) -> list[dict]:
    """Write each result as a finding of the run (origin 'datasheet_check').

    `label` (rule_trust, #947; None with the switch off): applied to each
    result AFTER the choice of which results become rows, so a held pass
    does not turn into a row a plain pass never was."""
    from . import comparison, standard_clause_page
    from . import review as review_mod
    written = []
    # A CHECK AN ENGINEER REJECTED in this run is kept by the re-run's delete and
    # not written again beside it (audit 2026-09-30): same rule, field, tag, value.
    fold = lambda v: " ".join(str(v or "").lower().split())  # noqa: E731
    rejected = {(fold(f.get("requirement_source_text")), f.get("fact_id"),
                 fold(f.get("equipment_tag")), fold(f.get("contractor_section")))
                for f in review_mod.rejected_in_run(review_run_id, ORIGIN)}
    # A CHECKLIST PASS IS A RESULT (planner 11 Oct, #805 Stage A): a met
    # checklist item (an R13 calculation included) is stored as a COMPLIANT
    # finding with its item id, the fact, the page and the clause, so "Meets"
    # is visible like any result. It is never a CRS comment (`crs_mapping`
    # takes only breaches and gaps). Any OTHER check that held (a consistency
    # pair, the revision block) still adds no row. "Does not apply" is not a
    # result either (#746): the condition's reason is in the result, never a
    # row. NOT CALCULATED is not a row either (R13): the inputs it lacked are
    # asked for by their own `required` items.
    for r in (x for x in results if x["status"] not in (NOT_APPLICABLE, NOT_CALCULATED)
              and (x["status"] != COMPLIANT or x.get("checklist"))):
        if label is not None:
            r = label(r)
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
        # A9/#923: every field in ONE transaction. This used to create the
        # finding, then UPDATE it with review_run_id/origin/compliance_status
        # etc. in a second transaction - a crash between them left a finding
        # with no run and no origin, invisible to the run that made it.
        finding = review_mod.create({
            "document_id": submittal_id, "category": "technical_query",
            "severity": severity_rule.stored_severity(
                status, r["severity"] if r.get("checklist") else None),
            "requirement": r["text"][:4000], "finding": f"{LABEL}: {detail}"[:4000],
            "required_action": ("Contractor to correct the datasheet." if status == NON_COMPLIANT
                                else "Contractor to provide the value." if status == MISSING_INFORMATION
                                else "Engineer to check." if status == NEEDS_ENGINEER_REVIEW
                                else "None."),
            "status": "open", "approval_status": "pending",
            "review_run_id": review_run_id, "origin": ORIGIN, "compliance_status": status,
            "contractor_page": r["page"], "contractor_section": r["field"],
            "contractor_evidence_text": r["value"],
            "requirement_source_text": f"{LABEL} {r['rule_id']}: {r['text']}",
            "ai_rationale": (detail if detail.startswith(("UNREAD_PAGES", "PAGE_READER_ONLY"))
                            else f"{LABEL} {r['rule_id']}: {detail}"),
            "fact_id": r["fact_id"], "equipment_tag": r["equipment_tag"],
            "standard_clause": f"{r['standard']} {r['clause']}" if r.get("clause") else None,
            "trust_label": r.get("trust_label"), "tier": r.get("tier"),
            "show_for_engineer_tick": (int(bool(r["show_for_engineer_tick"]))
                                       if "trust_label" in r else None),
            "rule_said": r.get("rule_said"),
        }, created_by=None)
        written.append({**finding, "compliance_status": status, "origin": ORIGIN,
                        "contractor_page": r["page"], "ai_rationale": detail})
    standard_clause_page.attach(review_run_id, written)
    return written
