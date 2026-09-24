"""Field-by-field report of one datasheet's CURRENT facts, read-only (master order B4).

For every current fact: field, value, unit, page, and ONE status, decided by rules written
down here rather than by a reader's judgement, so a before/after comparison is like for like:

  duplicate  the same (page, field, value) as an earlier row
  garbled    the label carries clause-number residue (two or more standalone numbers),
             is only unit words, has fewer than 3 letters, or a YES/NO answer sits on a
             label naming a quantity (pressure, temperature, flow, ...)
  blank      the extractor marked the slot blank (a slot the sheet leaves to be filled)
  filled     everything else

`numeric` is counted separately: a filled row whose value parsed to a number.

    python scripts/fact_report.py --db <copy.sqlite> --doc <document id> [--out report.csv]

Local analysis output - it contains document values; never commit it or paste it anywhere.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

UNIT_WORDS = {"m3/h", "usgpm", "gpm", "bar", "barg", "bar g", "psi", "psig", "kpa", "mpa", "m",
              "mm", "c", "°c", "f", "°f", "kw", "hp", "rpm", "kg/m3", "cp", "cst", "m3", "l/s",
              "%", "ft", "in", "kg", "mbar", "kg/h", "t/h"}
QUANTITY_WORDS = re.compile(
    r"\b(pressure|temperature|temp|flow|capacity|head|speed|power|density|viscosity|"
    r"diameter|weight|npsh|efficiency|volume|thickness|rate|relative density)\b", re.I)
CHECKBOX = re.compile(r"^\s*(yes|no|required|not required)\s*$", re.I)


def status(row: dict, seen: set) -> str:
    label = (row["field_name"] or "").strip()
    value = (row["field_value"] or "").strip()
    key = (row["page"], label.lower(), value.lower())
    if key in seen:
        return "duplicate"
    seen.add(key)
    tokens = label.lower().split()
    if len(re.findall(r"(?<![\w.])\d+(?![\w.])", label)) >= 2:
        return "garbled"
    if tokens and all(t in UNIT_WORDS for t in tokens):
        return "garbled"
    if len(re.sub(r"[^a-z]", "", label.lower())) < 3:
        return "garbled"
    if CHECKBOX.match(value) and QUANTITY_WORDS.search(label):
        return "garbled"
    if row["is_blank"]:
        return "blank"
    return "filled"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--doc", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    conn = sqlite3.connect(f"file:{Path(args.db).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    current = (" AND superseded_at IS NULL" if "superseded_at" in
               {r[1] for r in conn.execute("PRAGMA table_info(submittal_facts)")} else "")
    rows = [dict(r) for r in conn.execute(
        "SELECT field_name, field_value, raw_value, raw_unit, value_min, value_max, page,"
        " is_blank FROM submittal_facts WHERE submittal_document_id = ?" + current +
        " ORDER BY page, rowid", (args.doc,))]
    seen: set = set()
    counts: Counter = Counter()
    numeric = 0
    for row in rows:
        row["status"] = status(row, seen)
        counts[row["status"]] += 1
        has_number = row["raw_value"] not in (None, "") or row["value_min"] is not None
        row["numeric"] = int(row["status"] == "filled" and has_number)
        numeric += row["numeric"]
    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["page", "field", "value", "unit", "status", "numeric"])
            for r in rows:
                w.writerow([r["page"], r["field_name"], r["field_value"], r["raw_unit"] or "",
                            r["status"], r["numeric"]])
    print(json.dumps({"document": args.doc, "rows": len(rows),
                      **{k: counts.get(k, 0) for k in ("filled", "blank", "duplicate", "garbled")},
                      "numeric_filled": numeric}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
