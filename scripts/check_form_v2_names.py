"""Order 299.1: do the field names a reader stored map to the converter's form boxes? COUNTS ONLY.

Run it on YOUR machine on the CSV of field names (first column, or the column named by --column). It reads the
file, prints how many names map to exactly one box of the type's form (the type's own numeric boxes plus form v2),
to none, and to more than one, and for the unmapped ones how many carry a unit family. A name is printed only
with --show-unmapped, to your terminal; nothing is written and nothing leaves the machine.

    python scripts/check_form_v2_names.py names.csv --type "Pressure Safety Valve" [--unit-column "unit family"]

A name maps to a box when its canonical spelling (`field_links.canonical`) equals the box's name or one of the
box's listed spellings. No sheet layout is known here: a reader's wording that no box lists is shown as unmapped.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app import field_links, form_reader_fields, rule_roles  # noqa: E402


def box_spellings(equipment_type: str) -> dict[str, set[str]]:
    """{box name: every canonical spelling that names it}."""
    _dictionary, names, _families = rule_roles.form(equipment_type)
    spellings = {name: {name} for name in names}
    for f in form_reader_fields.field_list_for(
        equipment_type
    ):  # the type's own boxes' listed spellings
        own = field_links.canonical(f.key.replace("_", " "))
        if own in spellings:
            spellings[own] |= {field_links.canonical(x) for x in f.synonyms}
    for box in rule_roles.extra_boxes(equipment_type):
        name = field_links.canonical(box["name"])
        spellings[name] |= {
            field_links.canonical(s) for s in box.get("spellings") or []
        }
    return spellings


def map_names(names: list[str], equipment_type: str) -> dict[str, list[str]]:
    """{name as given: the boxes it names}: one box is a match, none is unmapped, several is ambiguous."""
    table = box_spellings(equipment_type)
    out = {}
    for raw in names:
        folded = field_links.canonical(raw)
        out[raw] = sorted(box for box, words in table.items() if folded in words)
    return out


def counts(
    mapping: dict[str, list[str]], has_unit: dict[str, bool] | None = None
) -> dict:
    has_unit = has_unit or {}
    unmapped = [n for n, boxes in mapping.items() if not boxes]
    return {
        "names": len(mapping),
        "one_box": sum(1 for b in mapping.values() if len(b) == 1),
        "no_box": len(unmapped),
        "several_boxes": sum(1 for b in mapping.values() if len(b) > 1),
        "no_box_with_unit_family": sum(1 for n in unmapped if has_unit.get(n)),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("csv_path", type=Path)
    ap.add_argument("--type", dest="equipment_type", default="Pressure Safety Valve")
    ap.add_argument(
        "--column",
        default=None,
        help="name of the column with the field names (default: the first)",
    )
    ap.add_argument(
        "--unit-column",
        default=None,
        help="column that is non-empty when the field has a unit family",
    )
    ap.add_argument(
        "--show-unmapped",
        action="store_true",
        help="print the unmapped names to this terminal",
    )
    args = ap.parse_args(argv)
    with args.csv_path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print("no rows")
        return 1
    column = args.column or next(iter(rows[0]))
    names = [str(r[column]).strip() for r in rows if str(r.get(column) or "").strip()]
    has_unit = (
        {
            str(r[column]).strip(): bool(str(r.get(args.unit_column) or "").strip())
            for r in rows
        }
        if args.unit_column
        else None
    )
    mapping = map_names(names, args.equipment_type)
    for key, value in counts(mapping, has_unit).items():
        print(f"{key}: {value}")
    if args.show_unmapped:
        for name, boxes in mapping.items():
            if not boxes:
                print("unmapped:", name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
