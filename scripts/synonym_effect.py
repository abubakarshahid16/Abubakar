"""What did a change to `reference/field_synonyms.json` do to THESE field names? COUNTS, read-only, local.

`field_synonyms.json` is read by the datasheet's rule readers (it is part of `datasheets.rule_reader_version`), so
a change to it makes stored facts "stale" and a review re-read the sheet. When a re-read loses a value (order 308,
the relief-case value after #1438), the first question is whether any label of the sheet folds differently now.
Give it the two files and the sheet's own field names (one per line or a CSV column); it prints, counts only:

  * how many names fold to a different text under the new table;
  * how many groups of names that folded APART under the old table fold TOGETHER under the new one (a merge: two
    labels of one sheet read as one field, which a reader may then drop or collapse as a double read);
  * with --show, the changed names and merged groups, to YOUR terminal only (they come from a sheet).

    git show origin/main:backend/app/reference/field_synonyms.json > old.json
    python scripts/synonym_effect.py --old old.json --new backend/app/reference/field_synonyms.json --names names.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app import field_links  # noqa: E402


def fold_with(path: Path, text: str) -> str:
    """`field_links.canonical` as it would read `path`."""
    folded = field_links._fold(text)
    pattern, to_canonical, _attributes = field_links._table(str(path))
    if not folded or pattern is None:
        return folded
    return pattern.sub(lambda m: to_canonical[m.group(0)], folded)


def effect(old: Path, new: Path, names: list[str]) -> dict:
    """{changed: [(name, old fold, new fold)], merged: [[names that now fold together but did not before]]}."""
    unique = sorted({n for n in names if n and n.strip()})
    before = {n: fold_with(old, n) for n in unique}
    after = {n: fold_with(new, n) for n in unique}
    changed = [(n, before[n], after[n]) for n in unique if before[n] != after[n]]
    together_after: dict[str, list[str]] = defaultdict(list)
    for n in unique:
        together_after[after[n]].append(n)
    merged = []
    for group in together_after.values():
        if len(group) > 1 and len({before[n] for n in group}) > 1:
            merged.append(group)
    return {"names": len(unique), "changed": changed, "merged": merged}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--old", type=Path, required=True)
    ap.add_argument("--new", type=Path, required=True)
    ap.add_argument(
        "--names",
        type=Path,
        required=True,
        help="a CSV (first column, or --column) or a text file",
    )
    ap.add_argument("--column", default=None)
    ap.add_argument(
        "--show", action="store_true", help="print the changed names to this terminal"
    )
    args = ap.parse_args(argv)
    with args.names.open(encoding="utf-8-sig", newline="") as fh:
        rows = (
            list(csv.DictReader(fh))
            if args.column or args.names.suffix == ".csv"
            else None
        )
        if rows is None:
            fh.seek(0)
            names = [line.strip() for line in fh]
        else:
            column = args.column or next(iter(rows[0]))
            names = [str(r[column]).strip() for r in rows]
    result = effect(args.old, args.new, names)
    print(f"names: {result['names']}")
    print(f"fold to a different text: {len(result['changed'])}")
    print(f"groups that now fold together (merges): {len(result['merged'])}")
    if args.show:
        for name, was, now in result["changed"]:
            print(f"changed: {name!r}: {was!r} -> {now!r}")
        for group in result["merged"]:
            print("merged:", group)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
