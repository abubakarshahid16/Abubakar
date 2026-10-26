"""THE FORM: which fields a datasheet of one equipment type must state, and how
the model is asked to fill them.

OWNER RULE (binding): no code here knows any datasheet's table shape, label
spelling or layout. The field list is DERIVED ONLY from the reference data the
review already checks against:

  * `reference/datasheet_checks.json` - the type's mandatory list
    (`datasheet_checks.mandatory_list_key`), the roles its review checklist
    items name (`datasheet_checks.checklist_for`), and each role's `kind`
    (pressure, temperature, flow, ...) and `printed_as` spellings;
  * `reference/field_synonyms.json` - other spellings of the same quantity.

An unknown or unanticipated equipment type gets the `_generic` list - the
same fallback the mandatory-field check uses. A new layout needs no change
here; a new FIELD is a data change in those files, never code.

The answer shape is FLAT: one object with one array of flat objects, no
`$defs`, no nesting beyond that. Small local models fail on nested schemas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import datasheet_checks
from .datasheets import normalise_field_name

#: The most fields one model call is asked to fill. A long list is cut into
#: batches of at most this many, each its own call (and its own two runs).
MAX_BATCH = 25
#: Longest quote a field may carry - `claude_datasheet.MAX_QUOTE_CHARS`.
MAX_QUOTE_CHARS = 240
FOUND = "found"
NOT_ON_PAGE = "not_on_page"
#: The field's row is printed but its value is left to the vendor ("By
#: Contractor", "TBA"): a BLANK fact with its marker, not "not on the page".
LEFT_BLANK = "left_blank"
STATUSES = (FOUND, NOT_ON_PAGE, LEFT_BLANK)
PROMPT_VERSION = "form-reader-2"


@dataclass(frozen=True)
class Field:
    """One line of the form.

    `key` is the checklist role ("design_pressure"); `name` is a spelling the
    review's own `datasheet_checks.role_of` maps back to that role, so a fact
    written under it is found by the mandatory and checklist checks;
    `unit_kind` is the role's `kind` from the reference data (None when the
    data names none); `synonyms` are the other spellings from the data."""

    key: str
    name: str
    unit_kind: str | None
    synonyms: tuple[str, ...]


def _roles_named_in(rule: object, roles: dict) -> list[str]:
    """Every role a checklist item's `rule` names, in order, whatever its
    keys are called (`field`, `left`, `right`, a list ...): the data decides."""
    found: list[str] = []
    if isinstance(rule, str):
        return [rule] if rule in roles else []
    if isinstance(rule, dict):
        for value in rule.values():
            found.extend(_roles_named_in(value, roles))
    elif isinstance(rule, list):
        for value in rule:
            found.extend(_roles_named_in(value, roles))
    return found


def _role_keys(equipment_type: str | None, rules: dict) -> list[str]:
    key = datasheet_checks.mandatory_list_key(equipment_type, rules)
    keys = list(rules["mandatory"].get(key) or rules["mandatory"][datasheet_checks.GENERIC])
    checklist = datasheet_checks.checklist_for(equipment_type, rules)
    for item in (checklist or {}).get("items", []):
        # The rule AND its condition: a role a condition reads ("sour
        # service") is a field the review needs the sheet to state.
        keys.extend(_roles_named_in({k: v for k, v in item.items() if k not in ("text", "source")},
                                    rules["roles"]))
    return [k for k in dict.fromkeys(keys) if k in rules["roles"]]


def _synonyms_of(role: str, rules: dict, groups: dict) -> tuple[str, ...]:
    spellings = list(groups.get(role.replace("_", " ")) or [])
    spellings += list(rules["roles"][role].get("printed_as") or [])
    return tuple(dict.fromkeys(s for s in spellings if s))


def _sub_phrases(words: list[str]) -> list[str]:
    """Contiguous word runs of the role's own name, longest first."""
    runs = []
    for size in range(len(words), 0, -1):
        runs.extend(" ".join(words[i:i + size]) for i in range(len(words) - size + 1))
    return runs


def display_name(role: str, rules: dict, synonyms: tuple[str, ...]) -> str:
    """The first spelling - the role's words, a synonym, then a run of the
    role's words - that `datasheet_checks.role_of` maps back to `role`.
    Falls back to the role's words when none does (still the field's name;
    the comparison then reads it like any other label)."""
    words = role.split("_")
    for candidate in (" ".join(words), *synonyms, *_sub_phrases(words)):
        if datasheet_checks.role_of(normalise_field_name(candidate), rules) == role:
            return candidate[:1].upper() + candidate[1:]
    return " ".join(words).capitalize()


def field_list_for(equipment_type: str | None, rules: dict | None = None) -> list[Field]:
    """The equipment type's form, from the reference data only."""
    rules = rules or datasheet_checks.load_rules()
    groups = datasheet_checks._synonyms()
    out = []
    for role in _role_keys(equipment_type, rules):
        synonyms = _synonyms_of(role, rules, groups)
        kind = rules["roles"][role].get("kind")
        out.append(Field(key=role, name=display_name(role, rules, synonyms),
                         unit_kind=kind or None, synonyms=synonyms))
    return out


#: The most fields one sheet's form carries: the type's reference roles first,
#: then what its standards ask for, up to this many (planner, 14 Oct 2026).
MAX_FORM_FIELDS = 60


def _fold(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def with_requirement_fields(base: list[Field], subjects: list[str],
                            cap: int = MAX_FORM_FIELDS) -> list[Field]:
    """`base` plus a field for each SUBJECT the sheet's included standards ask
    for ("outlet size", "set pressure"), deduplicated against the base's names
    and synonyms and against each other, capped at `cap` in all. The base is
    never cut. A requirement field has no unit kind of its own (the unit must
    still be a recognised one printed in the quote): every other check of the
    form reader applies to it unchanged."""
    out = list(base)
    seen = {_fold(f.name) for f in base} | {_fold(s) for f in base for s in f.synonyms}
    for subject in subjects:
        folded = _fold(subject)
        if len(out) >= cap:
            break
        if not folded or folded in seen:
            continue
        seen.add(folded)
        out.append(Field(key="req_" + folded.replace(" ", "_"), name=subject[:1].upper() + subject[1:],
                         unit_kind=None, synonyms=(subject.lower(),)))
    return out


def batches(fields: list[Field], size: int = MAX_BATCH) -> list[list[Field]]:
    size = max(1, min(int(size), MAX_BATCH))
    return [fields[i:i + size] for i in range(0, len(fields), size)]


def schema_for(fields: list[Field]) -> dict:
    """The FLAT answer schema: `{"fields": [{field_key, value, unit, quote,
    status}]}`. `field_key` is limited to this batch's keys."""
    return {
        "type": "object",
        "properties": {"fields": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "field_key": {"type": "string", "enum": [f.key for f in fields]},
                "value": {"type": "string"},
                "unit": {"type": "string"},
                "quote": {"type": "string", "maxLength": MAX_QUOTE_CHARS},
                "status": {"type": "string", "enum": list(STATUSES)},
            },
            "required": ["field_key", "value", "unit", "quote", "status"]}}},
        "required": ["fields"],
    }


PROMPT = """You are filling in a FORM from ONE PAGE of an equipment datasheet
submitted by a vendor. The page may be laid out in any way: label and value
lines, a table, columns, or sentences. Read it the way an engineer would.

For EVERY field in the list below, return exactly one object:
  field_key - the key exactly as listed
  value     - the value the vendor states for that field, copied exactly as
              printed (a number, a range, or a short answer). No unit here.
  unit      - the unit printed with the value, copied exactly; "" if none
  quote     - the EXACT words from the page (at most 240 characters, one
              span, copied character for character) that contain BOTH the
              field's label (or one of its other names) AND the value
  status    - "found"; "not_on_page" when this page does not show the
              field at all (then value, unit and quote are ""); or
              "left_blank" when the field's row IS printed but its value is
              left to the vendor ("TBA", "By vendor", "By Contractor",
              "later"): then value is that marker exactly as printed, unit
              is "", and quote holds the label AND the marker
Never guess. Never write a quote that is not on the page. "TBA", "By vendor"
or "later" is not a value: answer "left_blank", never "found".

Answer with JSON only: {"fields": [ ... ]}

FIELDS:
"""


def _field_line(f: Field) -> str:
    extra = f"; also printed as: {', '.join(f.synonyms[:6])}" if f.synonyms else ""
    kind = f"; expected unit kind: {f.unit_kind}" if f.unit_kind and f.unit_kind != "text" else ""
    return f"  - {f.key}: {f.name}{extra}{kind}\n"


def build_prompt(fields: list[Field], page_text: str, page_no: int) -> str:
    """The prompt for one batch of fields on one page."""
    parts = [PROMPT, *(_field_line(f) for f in fields), f"\nPAGE {page_no}:\n",
             re.sub(r"[ \t]+\n", "\n", page_text or "").strip()]
    return "".join(parts)


__all__ = [
    "FOUND",
    "LEFT_BLANK",
    "MAX_BATCH",
    "NOT_ON_PAGE",
    "PROMPT_VERSION",
    "STATUSES",
    "Field",
    "batches",
    "build_prompt",
    "display_name",
    "field_list_for",
    "schema_for",
]
