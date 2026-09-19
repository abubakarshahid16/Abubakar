"""Score the extractor against a hand-written gold sheet.

THE QUESTION THIS ANSWERS: "how right is it?" - which nothing has been able to
answer. `coverage_report.py` answers the neighbouring question, "what did it
walk past", by counting candidate sentences the extractor produced no row for.
That is an upper bound on what was lost and it needs no human. This needs a
human, and in exchange it gives the thing the other cannot: whether the rows
that WERE produced say what the standard says.

Everything before this was found by reading rows at random. That is how the
129 flipped comparators surfaced - four wrong answers in a sample of fifteen,
on 2026-09-20. A sample of fifteen out of 34,938 is 0.04% of the corpus, and
the next defect is only found if it happens to be in the next fifteen.

THREE NUMBERS, AND THE THIRD IS THE ONE THAT MATTERS

  recall          of the rules the engineer wrote down, how many were found
  precision       of the rules found, how many are right
  wrong direction the right clause and the right number with the operator
                  reversed

The third is reported separately and never folded into the other two. A
flipped comparator scores as one miss and one false positive, which buries it
among ordinary errors - and it is not an ordinary error. It passes a
non-compliant value and fails a compliant one, with a correct clause and page
attached, so checking the citation does not reveal it. A run with 95%
precision and three flipped operators is worse than one with 80% and none.

WHAT IT DOES NOT DO. It does not judge a standard nobody has written a sheet
for, and it does not guess which gold row a stored row "probably" meant: a
gold row matches a stored row on clause and value, or it does not match. A
looser rule would let the scorer paper over the disagreements it exists to
show.

Read-only. Takes a database path, so it runs against a copy.

    python scripts/gold_score.py backend/data/rag_intelligence.sqlite gold/*.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

#: The four words `docs/gold-set.md` asks an engineer to use.
KINDS = ("limit", "statement", "table", "trigger")

#: What the database calls each of them. `trigger` and `table` are listed so a
#: disagreement about KIND is reported rather than silently scored as a miss.
STORED_KIND = {
    "limit": {"numeric_limit", "relative_limit"},
    "statement": {"statement"},
    "table": {"table_row", "table_value"},
    "trigger": {"applicability_trigger"},
}

OPPOSITE = {"<=": {">=", ">"}, "<": {">=", ">"},
            ">=": {"<=", "<"}, ">": {"<=", "<"}}


def number(text: str | None) -> float | None:
    """The value as a number, or None. "6,900" is six thousand nine hundred;
    "9,0" is nine - NORSOK writes decimals that way and `claims.parse_value`
    owns that rule. This is deliberately the simpler reading, because a gold
    sheet is typed by a person into Excel and Excel will not produce "9,0"."""
    if text is None:
        return None
    cleaned = str(text).strip().replace(",", "").replace(" ", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def clause_key(text: str | None) -> str:
    """"5.3.3 Noise" and " 5.3.3 " are the same clause. A trailing dot is
    dropped so "5.3.3." matches too - an engineer typing into Excel will
    produce both spellings and neither is a mistake."""
    if not text:
        return ""
    head = str(text).strip().split()[0] if str(text).strip() else ""
    return head.rstrip(".").lower()


def unit_key(text: str | None) -> str:
    """Case and spacing folded; everything else kept. `dB(A)` and `dBA` stay
    DIFFERENT, because they are: the A-weighting is the whole point of the
    corpus's noise limits, and folding them would hide a real disagreement."""
    return re.sub(r"\s+", "", str(text or "")).lower()


def read_gold(paths: list[Path]) -> list[dict]:
    """Every data row of every sheet. A row whose first cell is empty or
    begins with '#' is a comment or the template's own examples."""
    rows: list[dict] = []
    for path in paths:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for line_no, raw in enumerate(csv.DictReader(handle), start=2):
                standard = (raw.get("standard") or "").strip()
                if not standard or standard.startswith("#"):
                    continue
                kind = (raw.get("kind") or "").strip().lower()
                if kind not in KINDS:
                    print(f"  ! {path.name} line {line_no}: kind "
                          f"{kind!r} is not one of {', '.join(KINDS)} - row skipped")
                    continue
                rows.append({
                    "sheet": path.name, "line": line_no,
                    "standard": standard,
                    "clause": clause_key(raw.get("clause")),
                    "page": (raw.get("page") or "").strip(),
                    "kind": kind,
                    "operator": (raw.get("operator") or "").strip(),
                    "value": number(raw.get("value")),
                    "unit": unit_key(raw.get("unit")),
                    "notes": (raw.get("notes") or "").strip(),
                })
    return rows


def read_stored(conn: sqlite3.Connection, filenames: set[str]) -> dict[str, list[dict]]:
    """Every stored requirement for the standards the sheets cover, keyed by
    filename. A standard named in a sheet and absent from the database is
    reported by the caller rather than scored as a total miss."""
    out: dict[str, list[dict]] = {}
    for name in sorted(filenames):
        doc = conn.execute(
            "SELECT id FROM documents WHERE lower(filename) = lower(?)",
            (name,)).fetchone()
        if doc is None:
            out[name] = []
            continue
        out[name] = [
            {"clause": clause_key(r["clause"]), "page": r["page"],
             "kind": r["requirement_type"], "operator": r["operator"],
             "value": number(r["raw_value"]), "unit": unit_key(r["raw_unit"])}
            for r in conn.execute(
                "SELECT clause, page, requirement_type, operator, raw_value,"
                " raw_unit FROM standard_requirements"
                " WHERE standard_document_id = ?", (doc["id"],))
        ]
    return out


def score_standard(gold: list[dict], stored: list[dict]) -> dict:
    """One standard. A gold LIMIT is matched against a stored row on clause
    and value; everything else is compared on clause and kind alone."""
    gold_limits = [g for g in gold if g["kind"] == "limit"]
    stored_limits = [s for s in stored if s["kind"] in STORED_KIND["limit"]]

    unmatched = list(stored_limits)
    found, flipped, wrong_unit, missed = [], [], [], []

    for want in gold_limits:
        same = [s for s in unmatched
                if s["clause"] == want["clause"] and s["value"] == want["value"]]
        if not same:
            missed.append(want)
            continue
        # Prefer a row that agrees on the operator, so two limits sharing a
        # clause and a value cannot be paired into a false disagreement.
        hit = next((s for s in same if s["operator"] == want["operator"]), same[0])
        unmatched.remove(hit)
        if hit["operator"] != want["operator"]:
            (flipped if hit["operator"] in OPPOSITE.get(want["operator"], set())
             else missed).append({**want, "stored_operator": hit["operator"]})
        elif want["unit"] and hit["unit"] != want["unit"]:
            wrong_unit.append({**want, "stored_unit": hit["unit"]})
        else:
            found.append(want)

    # A gold row that is NOT a limit: did the system agree about what it is?
    kind_right = kind_wrong = 0
    for want in (g for g in gold if g["kind"] != "limit"):
        here = [s for s in stored if s["clause"] == want["clause"]]
        if any(s["kind"] in STORED_KIND[want["kind"]] for s in here):
            kind_right += 1
        else:
            kind_wrong += 1

    return {
        "gold_limits": len(gold_limits), "stored_limits": len(stored_limits),
        "found": found, "flipped": flipped, "wrong_unit": wrong_unit,
        "missed": missed, "spurious": unmatched,
        "kind_right": kind_right, "kind_wrong": kind_wrong,
    }


def percent(part: int, whole: int) -> str:
    """Never a percentage without a denominator, and never one at all when the
    denominator is zero - `0%` of nothing reads as a failure."""
    return f"{100 * part / whole:.0f}% ({part}/{whole})" if whole else f"n/a (0/{whole})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("database")
    parser.add_argument("sheets", nargs="+")
    parser.add_argument("--verbose", action="store_true",
                        help="list every disagreement, not just the counts")
    args = parser.parse_args(argv)

    paths = [Path(p) for p in args.sheets if Path(p).suffix.lower() == ".csv"]
    paths = [p for p in paths if p.name != "TEMPLATE.csv"]
    if not paths:
        print("no gold sheets given (TEMPLATE.csv is skipped)")
        return 2

    gold = read_gold(paths)
    if not gold:
        print("the sheets hold no data rows")
        return 2

    conn = sqlite3.connect(f"file:{args.database}?mode=ro", uri=True, timeout=20)
    conn.row_factory = sqlite3.Row
    stored = read_stored(conn, {g["standard"] for g in gold})

    totals = Counter()
    print(f"\ngold sheets: {len(paths)}    rules written down: {len(gold)}\n")
    print(f"  {'standard':<34}{'found':>12}{'flipped':>9}{'missed':>8}"
          f"{'spurious':>10}{'unit':>6}")
    print("  " + "-" * 79)

    for name in sorted({g["standard"] for g in gold}):
        rows = [g for g in gold if g["standard"] == name]
        if not stored.get(name):
            print(f"  {name:<34}   NOT IN THE DATABASE - not scored")
            continue
        s = score_standard(rows, stored[name])
        print(f"  {name:<34}{len(s['found']):>12}{len(s['flipped']):>9}"
              f"{len(s['missed']):>8}{len(s['spurious']):>10}"
              f"{len(s['wrong_unit']):>6}")
        for key in ("gold_limits", "stored_limits", "kind_right", "kind_wrong"):
            totals[key] += s[key]
        for key in ("found", "flipped", "missed", "spurious", "wrong_unit"):
            totals[key] += len(s[key])
        if args.verbose:
            for row in s["flipped"]:
                print(f"       FLIPPED  clause {row['clause']} value {row['value']}"
                      f"  sheet says {row['operator']}  stored {row['stored_operator']}")
            for row in s["wrong_unit"]:
                print(f"       UNIT     clause {row['clause']} value {row['value']}"
                      f"  sheet says {row['unit']!r}  stored {row['stored_unit']!r}")
            for row in s["missed"]:
                print(f"       MISSED   clause {row['clause']} value {row['value']}"
                      f" ({row['sheet']} line {row['line']})")
            for row in s["spurious"]:
                print(f"       EXTRA    clause {row['clause']} value {row['value']}"
                      f" {row['operator']} - no row on the sheet")

    print("\n  RECALL     " + percent(totals["found"], totals["gold_limits"])
          + "   of the rules written down, found and correct")
    print("  PRECISION  " + percent(totals["found"], totals["stored_limits"])
          + "   of the limits stored, right")
    print(f"  WRONG DIRECTION  {totals['flipped']}"
          "   right clause, right number, operator reversed")
    if totals["flipped"]:
        print("             ^ these pass a non-compliant value and fail a"
              " compliant one, with a citation attached. Fix before anything else.")
    print(f"  wrong unit       {totals['wrong_unit']}")
    print(f"  missed           {totals['missed']}")
    print(f"  stored but not on the sheet  {totals['spurious']}"
          "   (check the sheet before the code - it may be right)")
    print("  non-limit rules agreed on kind  "
          + percent(totals["kind_right"], totals["kind_right"] + totals["kind_wrong"]))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
