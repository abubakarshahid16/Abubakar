"""Order 262.1: which FIELD OF THE FORM a standard's numeric rule limits, per equipment type.

The extractor already gives every numeric rule an operator, value, unit and condition, each checked
against the clause text. What it never says is which field of a datasheet the rule limits (258.1:
27 of 28 unpaired SAES-G-005 limits had no sheet field name). This module closes that one gap:

  * the DICTIONARY is the type's own form (`form_reader_fields.field_list_for`): only the numeric
    fields a sheet of that type is asked for, each with the unit kind its role has in the data;
  * `propose` asks the local model (offline, on a diagnostic copy) for ONE form field and a quote per
    rule, under `field_vocabulary`'s four gates (the number indexes the list, the quote is in the
    sentence, the quote names exactly the quantity, the sentence's own number follows the name and
    is in the field's kind of unit). Unproven = no mapping = the engineer;
  * `export` writes the kept mappings to `reference/rule_roles/<type>.json`: DRAFT, no document
    text (a standard label, a clause number, a hash of the normalised rule text, the form field);
    the operator, value, unit and condition are re-read from the library at run time, never copied;
  * `reviewed_names` gives a review the mappings whose rule text still hashes the same and whose
    unit still fits the field. A pairing from it rides `comparison.match_by_field_name`, so it
    never carries a verdict (NEEDS_ENGINEER_REVIEW) until a hand check of 27 of 30 is on record.

Nothing here calls a model by itself, reads a document, or writes a value.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import field_links, field_naming, field_vocabulary, form_reader_fields

DIR = Path(__file__).parent / "reference" / "rule_roles"
STATUS = "draft"

#: Unit families a numeric role's `kind` allows (the families `field_vocabulary` checks).
_KIND_FAMILIES = {
    "pressure": ("pressure",),
    "temperature": ("temperature",),
    "flow": ("volumetric_flow", "mass_flow"),
    "length": ("length",),
    "area": ("area",),
    "density": ("density",),
    "viscosity": ("viscosity",),
    "percent": ("percent",),
}
#: Roles whose data kind is only "number": the unit family they take, where one exists. A numeric
#: role in neither table cannot have its unit checked, so no rule is ever mapped to it.
_ROLE_FAMILIES = {
    "rated_speed": ("rotation",),
    "absorbed_power": ("power",),
    "driver_rating": ("power",),
    "heat_duty": ("power",),
    "empty_weight": ("mass",),
    "operating_weight": ("mass",),
}


def text_hash(text: str | None) -> str:
    """The hash a mapping is keyed by: the rule text, whitespace-folded and lower-cased."""
    return hashlib.sha256(" ".join((text or "").lower().split()).encode()).hexdigest()


def form(
    equipment_type: str,
) -> tuple[list[str], dict[str, str], dict[str, tuple[str, ...]]]:
    """(dictionary, {name: role}, {name: unit families}) of the numeric fields whose unit can be
    checked, from the type's own form."""
    names: dict[str, str] = {}
    families: dict[str, tuple[str, ...]] = {}
    for f in form_reader_fields.field_list_for(equipment_type):
        wanted = _ROLE_FAMILIES.get(f.key) or _KIND_FAMILIES.get(f.unit_kind or "")
        if not wanted:
            continue
        name = field_links.canonical(f.key.replace("_", " "))
        names[name], families[name] = f.key, wanted
    return sorted(names), names, families


def propose(
    requirements: list[dict], equipment_type: str, provider, stats: dict | None = None
) -> dict[str, dict]:
    """Ask for the form field each numeric rule limits and store every answer (the offline pass).
    {requirement id: {field_name | None, quote | None}} for all of them."""
    dictionary, _roles, families = form(equipment_type)
    return field_vocabulary.name_requirements(
        requirements, provider, stats, dictionary=dictionary, families=families
    )


def entries(requirements: list[dict], equipment_type: str, label_of) -> list[dict]:
    """The mappings to keep, from the stored answers: one per rule that has a field. `label_of`
    turns a standard document id into the label shown to the reviewer."""
    dictionary, roles, families = form(equipment_type)
    ids = [str(r["id"]) for r in requirements]
    stored = field_naming.stored_names(field_naming.REQUIREMENT, ids, dictionary)
    out = []
    for r in requirements:
        got = stored.get(str(r["id"])) or {}
        name = got.get("field_name")
        if not name or name not in roles:
            continue
        text = " ".join((r.get("requirement_text") or "").split())[
            : field_naming.REQUIREMENT_CHARS
        ]
        raw_unit = r.get("raw_unit") or r.get("unit")
        if not field_vocabulary.names_the_quantity(got.get("quote"), name):
            continue
        if not field_vocabulary.number_fits(
            text, got.get("quote"), name, r.get("raw_value"), raw_unit, families
        ):
            continue
        out.append(
            {
                "standard": label_of(r.get("standard_document_id")),
                "clause": r.get("clause"),
                "text_sha256": text_hash(r.get("requirement_text")),
                "field": roles[name],
            }
        )
    return sorted(
        out, key=lambda e: (e["standard"] or "", e["clause"] or "", e["text_sha256"])
    )


def slug(equipment_type: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", equipment_type.lower()).strip("_")


def export(equipment_type: str, kept: list[dict], path: Path | None = None) -> Path:
    """Write the kept mappings as the reviewed file for the type (DRAFT, no document text)."""
    path = path or DIR / f"{slug(equipment_type)}.json"
    body = {
        "_about": "Order 262.1: the form field each numeric rule of a held standard limits. DRAFT: "
        "an engineer approves it before a pairing from it carries more than NEEDS_ENGINEER_REVIEW. "
        "No document text: a label, a clause number, a hash of the normalised rule text, a field. "
        "The operator, value, unit and condition are read from the library at run time.",
        "equipment_type": equipment_type,
        "status": STATUS,
        "entries": kept,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def load(files: list[Path] | None = None) -> list[tuple[str, dict]]:
    """[(equipment type, entry)] from the given reviewed files, or from every file in `DIR`."""
    if files is None:
        files = sorted(DIR.glob("*.json")) if DIR.is_dir() else []
    out = []
    for f in files:
        data = json.loads(Path(f).read_text(encoding="utf-8"))
        out.extend((data["equipment_type"], e) for e in data.get("entries", []))
    return out


def same_type(a: str | None, b: str | None) -> bool:
    """Do two equipment types name the same checklist table (the engine's own key)? Neither
    known = no: a mapping never applies to a review whose type is unknown."""
    from . import datasheet_checks

    if not a or not b:
        return False
    table = datasheet_checks.load_rules().get("checklists") or {}
    ka, kb = datasheet_checks.table_key(a, table), datasheet_checks.table_key(b, table)
    return ka == kb and ka != datasheet_checks.GENERIC


def reviewed_names(
    requirements: list[dict],
    equipment_type: str | None,
    files: list[Path] | None = None,
) -> dict[str, str]:
    """{requirement id: canonical field name} for the numeric rules a reviewed file maps FOR THIS
    EQUIPMENT TYPE (a pump mapping never applies to a vessel review) and whose text still hashes
    the same and whose unit still fits the field. Anything else is dropped."""
    by_hash: dict[str, tuple[str, str]] = {}
    for file_type, entry in load(files):
        if same_type(file_type, equipment_type):
            by_hash[entry["text_sha256"]] = (file_type, entry["field"])
    out: dict[str, str] = {}
    for r in requirements:
        if r.get("requirement_type") not in field_naming.NUMERIC_TYPES:
            continue
        hit = by_hash.get(text_hash(r.get("requirement_text")))
        if not hit:
            continue
        file_type, role = hit
        _dictionary, roles, families = form(file_type)
        name = next((n for n, k in roles.items() if k == role), None)
        if name is None:
            continue
        have = field_vocabulary._unit_families(r.get("raw_unit") or r.get("unit"))
        if have & set(families[name]):
            out[str(r["id"])] = name
    return out
