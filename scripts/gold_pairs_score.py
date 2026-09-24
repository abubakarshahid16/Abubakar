"""Score a matcher against a hand-written gold PAIRS sheet.

THE QUESTION THIS ANSWERS: "is it pairing the right things?" - which nothing
has been able to answer. `gold_score.py` answers the neighbouring question,
"did it read the standard right", and stops at the standard. A rule read
perfectly and then attached to the wrong datasheet field is still a wrong
answer on an engineer's screen, and the two failures have never been
distinguishable because only one of them was measurable.

Everything before this was found by reading pairings at random. That is how the
battery clause surfaced - `design life = 25 years` on a pressure vessel filed
under SAES-P-103 5.2.5, "the design life of the battery shall be at least 20
years" - and beside it SAES-X-500 6.6.3, degrees Celsius filed under a limit in
ohm-cm. Two provably wrong pairings, found by eye, with no way to tell whether
a fix helped.

THREE NUMBERS, AND THE THIRD IS NOT A RATIO

  recall          of the pairings the engineer wrote down, how many were made
  precision       of the pairings made, how many were right
  FALSE PAIRINGS  the COUNT of values attached to a rule the sheet says is not
                  theirs

The third is reported separately, as a count, and is never folded into
precision. Precision is a ratio, and a ratio improves when the matcher pairs
less; a matcher that makes one fewer correct pairing and one fewer false one
has not stood still, it has got better, and only the count says so.

They are also not the same KIND of error. A missed pairing is silence: the
engineer reads the datasheet themselves, as they do today. A false pairing
leaves the building with a real clause number and a real page attached, looking
exactly like a correct one, and if it says a submittal fails then somebody has
to answer it. Averaging the two into one score would let a matcher trade
silence for disputes and call it an improvement.

WHY THE `NONE` ROWS ARE THE IMPORTANT ONES. Precision cannot be computed from
matches alone. A sheet that only records correct pairings can only ever credit
a matcher; it is the fields an engineer wrote `NONE` against that make a false
pairing detectable at all. A sheet with no `NONE` rows is reported as such and
its precision is refused rather than printed.

WHAT IT DOES NOT DO. It does not judge a datasheet nobody has written a sheet
for. It does not guess which gold row a pairing "probably" meant: a pairing
matches the sheet on field and clause, or it does not. And it does not decide
which standards were applicable - that is `review_applicable_standards`, and
scoring against a different set of standards than production feeds the matcher
would measure something nobody ships.

Read-only. Takes a database path, so it runs against a copy.

    python scripts/gold_pairs_score.py backend/data/rag_intelligence.sqlite \
        gold/PAIRS-*.csv

    # the stress test: every standard in the corpus, not just the applicable
    # ones. This is the scope the battery clause was found in.
    python scripts/gold_pairs_score.py <db> gold/PAIRS-*.csv --scope all

    # a candidate matcher, same contract: (requirement, facts) -> {"fact": ...}
    python scripts/gold_pairs_score.py <db> gold/PAIRS-*.csv \
        --matcher app.comparison:match_by_semantic_subject
"""

from __future__ import annotations

import argparse
import csv
import datetime as _datetime
import importlib
import os
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"

#: The word an engineer writes when NOTHING governs a field. Deliberately a
#: word and not a blank: a blank means "I did not decide" and is skipped, and
#: collapsing the two would turn every row somebody ran out of time for into a
#: claim that the matcher must stay silent there.
NONE_WORD = "none"

#: The default matcher, as `module:function`. It takes a requirement row and
#: the document's facts and returns `{"fact": <row or None>, ...}` - the
#: contract `comparison.match_by_containment` already has, so the current
#: matcher scores with no arguments and any replacement scores by name.
DEFAULT_MATCHER = "app.comparison:match_by_containment"


def _ensure_datetime_utc() -> None:
    """`datetime.UTC` for Python 3.10, which the app modules assume.

    The backend targets 3.11. Adding the alias here rather than asking for a
    different interpreter keeps this script runnable on the machine the gold
    sheets are actually kept on. It changes nothing on 3.11+.
    """
    if not hasattr(_datetime, "UTC"):
        # The alias is what is MISSING here; ruff assumes 3.11 and would
        # "simplify" the right-hand side into itself.
        _datetime.UTC = _datetime.timezone.utc  # type: ignore[attr-defined]  # noqa: UP017


def load_matcher(spec: str):
    """The matcher named by `module:function`, imported from `backend/`.

    NAMED, NEVER DEFAULTED SILENTLY. The whole point of this script is to
    compare one matcher against another, so which one ran is printed in the
    header of every report - a score with no matcher beside it says nothing.
    """
    _ensure_datetime_utc()
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    module_name, _, attribute = spec.partition(":")
    if not attribute:
        raise SystemExit(f"--matcher must be module:function, got {spec!r}")
    module = importlib.import_module(module_name)
    try:
        return getattr(module, attribute)
    except AttributeError:
        raise SystemExit(f"{module_name} has no {attribute!r}") from None


def clause_key(text: str | None) -> str:
    """"6.2.3 Design Pressure" and " 6.2.3 " are the same clause. A trailing
    dot is dropped so "6.2.3." matches too - `gold_score.clause_key`'s rule,
    for `gold_score.clause_key`'s reason: Excel produces both spellings and
    neither is a mistake."""
    if not text:
        return ""
    head = str(text).strip().split()[0] if str(text).strip() else ""
    return head.rstrip(".").lower()


def field_key(text: str | None) -> str:
    """A datasheet field name, folded for comparison.

    Case and punctuation only. Nothing else is folded: `internal design
    pressure` and `external design pressure` stay DIFFERENT, because they are,
    and a looser rule would let the scorer paper over exactly the confusion it
    exists to show.
    """
    folded = re.sub(r"[^\w\s]", " ", str(text or "").lower())
    return re.sub(r"\s+", " ", folded).strip()


def standard_key(text: str | None) -> str:
    """A standard's file name, case-folded. The corpus spells them
    `SAES-W-016.PDF` and `SAES-D-001.pdf` in the same directory."""
    return str(text or "").strip().lower()


def read_gold(paths: list[Path]) -> tuple[list[dict], list[dict], list[dict]]:
    """Every data row of every sheet, split three ways: pairings, `NONE` rows,
    and rows the engineer left blank.

    A row whose first cell is empty or begins with '#' is a comment or the
    template's own examples.
    """
    pairs: list[dict] = []
    nones: list[dict] = []
    unsure: list[dict] = []
    for path in paths:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for line_no, raw in enumerate(csv.DictReader(handle), start=2):
                submittal = (raw.get("submittal") or "").strip()
                if not submittal or submittal.startswith("#"):
                    continue
                row = {
                    "sheet": path.name, "line": line_no,
                    "submittal": submittal,
                    "tag": (raw.get("equipment_tag") or "").strip(),
                    "field": field_key(raw.get("field")),
                    "field_raw": (raw.get("field") or "").strip(),
                    "value": (raw.get("value") or "").strip(),
                    "unit": (raw.get("unit") or "").strip(),
                    "standard": standard_key(raw.get("standard")),
                    "clause": clause_key(raw.get("clause")),
                    "notes": (raw.get("notes") or "").strip(),
                }
                if not row["field"]:
                    print(f"  ! {path.name} line {line_no}: no field name"
                          " - row skipped")
                    continue
                if not row["standard"]:
                    unsure.append(row)
                elif row["standard"] == NONE_WORD:
                    nones.append(row)
                elif not row["clause"]:
                    print(f"  ! {path.name} line {line_no}: {row['field_raw']!r}"
                          f" names {row['standard']} with no clause - a pairing"
                          " needs both, row skipped")
                else:
                    pairs.append(row)
    return pairs, nones, unsure


def document_id(conn: sqlite3.Connection, filename: str) -> str | None:
    row = conn.execute("SELECT id FROM documents WHERE lower(filename) = lower(?)",
                       (filename,)).fetchone()
    return row["id"] if row else None


def scope_standards(conn: sqlite3.Connection, submittal_id: str,
                    scope: str) -> tuple[list[str], str]:
    """The standards the matcher is run over, and one line saying which.

    `review` is the default and is what production does: the standards
    `review_applicable_standards` marked included on this submittal's most
    recent review run. `all` is every standard in the database - the stress
    test, and the scope the battery clause was found in. They give very
    different precision, so the scope is printed with the numbers and never
    inferred.
    """
    if scope == "all":
        rows = conn.execute("SELECT DISTINCT standard_document_id AS id"
                            " FROM standard_requirements").fetchall()
        return [r["id"] for r in rows], "every standard in the database"

    run = conn.execute(
        "SELECT id FROM review_runs WHERE submittal_document_id = ?"
        " ORDER BY COALESCE(completed_at, created_at) DESC LIMIT 1",
        (submittal_id,)).fetchone()
    if run is None:
        return [], "NO REVIEW RUN for this submittal"
    rows = conn.execute(
        "SELECT standard_document_id AS id FROM review_applicable_standards"
        " WHERE review_run_id = ? AND included = 1", (run["id"],)).fetchall()
    return ([r["id"] for r in rows],
            f"the {len(rows)} standards included on review run {run['id'][:12]}")


def run_matcher(matcher, conn: sqlite3.Connection, submittal_id: str,
                standard_ids: list[str]) -> list[dict]:
    """Every pairing the matcher makes: one row per (requirement, fact).

    The matcher is handed the SAME two things `run_comparison` hands it - the
    requirement row and the whole document's facts - so a pairing scored here
    is the pairing an engineer would have seen, not a reconstruction of it.

    CURRENT FACTS ONLY (#193, honesty audit 52). Since ADR-0024 a re-read
    SUPERSEDES the old rows instead of deleting them, and production reads
    `superseded_at IS NULL`. This read took every row, so after the #179
    re-extraction each vessel field was present twice, the matcher saw a tie
    and paired nothing - the scorer reported 0/3 while production made 1/3.
    A copy made before the column existed has no superseded rows to skip.
    """
    current = (" AND superseded_at IS NULL"
               if "superseded_at" in {r[1] for r in conn.execute(
                   "PRAGMA table_info(submittal_facts)")} else "")
    facts = [dict(r) for r in conn.execute(
        "SELECT * FROM submittal_facts WHERE submittal_document_id = ?" + current,
        (submittal_id,))]
    made: list[dict] = []
    for standard_id in standard_ids:
        for row in conn.execute(
                "SELECT sr.*, d.filename FROM standard_requirements sr"
                " JOIN documents d ON d.id = sr.standard_document_id"
                " WHERE sr.standard_document_id = ?", (standard_id,)):
            requirement = dict(row)
            result = matcher(requirement, facts)
            fact = result.get("fact") if isinstance(result, dict) else None
            if fact is None:
                continue
            made.append({
                "field": field_key(fact.get("field_name")),
                "field_raw": fact.get("field_name"),
                "fact_value": fact.get("raw_value"),
                "fact_unit": fact.get("raw_unit"),
                "standard": standard_key(requirement.get("filename")),
                "clause": clause_key(requirement.get("clause")),
                "req_type": requirement.get("requirement_type"),
                "req_value": requirement.get("raw_value"),
                "req_unit": requirement.get("raw_unit"),
                "subject": requirement.get("subject"),
            })
    return made


def reachable(conn: sqlite3.Connection, want: dict) -> bool:
    """Could ANY matcher have made this pairing?

    A gold row can name a clause the database holds only as an unnumbered
    `statement` - SAES-D-001 9.1.6 states the allowable concrete bearing stress
    in its sentence and the extractor stored no value for it. No matcher pairs
    a value with a requirement that carries no value, so counting that as a
    matching defect would send somebody to fix the wrong module. It stays a
    miss in recall, because the engineer's answer is still not on the screen,
    and it is reported separately so the miss is attributed to the right place.
    """
    standard_id = document_id(conn, want["standard"])
    if standard_id is None:
        return False
    rows = conn.execute(
        "SELECT clause, raw_value FROM standard_requirements"
        " WHERE standard_document_id = ?", (standard_id,)).fetchall()
    return any(clause_key(row["clause"]) == want["clause"]
               and row["raw_value"] not in (None, "") for row in rows)


def percent(part: int, whole: int) -> str:
    """Never a percentage without a denominator, and never one at all when the
    denominator is zero - `0%` of nothing reads as a failure."""
    return f"{100 * part / whole:.0f}% ({part}/{whole})" if whole else f"n/a (0/{whole})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("database")
    parser.add_argument("sheets", nargs="+")
    parser.add_argument("--matcher", default=DEFAULT_MATCHER,
                        help=f"module:function, default {DEFAULT_MATCHER}")
    parser.add_argument("--scope", choices=("review", "all"), default="review",
                        help="which standards the matcher is run over")
    parser.add_argument("--verbose", action="store_true",
                        help="list every disagreement, not just the counts")
    args = parser.parse_args(argv)

    paths = [Path(p) for p in args.sheets if Path(p).suffix.lower() == ".csv"]
    paths = [p for p in paths if p.name != "PAIRS-TEMPLATE.csv"]
    if not paths:
        print("no gold pair sheets given (PAIRS-TEMPLATE.csv is skipped)")
        return 2

    pairs, nones, unsure = read_gold(paths)
    if not pairs and not nones:
        print("the sheets hold no decided rows")
        return 2

    # The app's own connection is used by the matcher to read an engineer's
    # recorded pair rejections. Point it at the SAME database, so a rejection
    # the engineer made is honoured here exactly as it is in a review.
    os.environ.setdefault("DB_PATH", str(Path(args.database).resolve()))
    matcher = load_matcher(args.matcher)

    conn = sqlite3.connect(f"file:{args.database}?mode=ro", uri=True, timeout=20)
    conn.row_factory = sqlite3.Row

    print(f"\ngold sheets: {len(paths)}    matcher: {args.matcher}")
    print(f"pairings written down: {len(pairs)}    "
          f"fields marked NONE: {len(nones)}    left blank: {len(unsure)}\n")

    if not nones:
        print("  ! no NONE rows on any sheet. PRECISION CANNOT BE COMPUTED -")
        print("    a sheet that records only matches can only ever credit a")
        print("    matcher. See docs/gold-pairs.md.\n")

    totals = Counter()
    disagreements: list[str] = []

    for submittal in sorted({r["submittal"] for r in pairs + nones + unsure}):
        submittal_id = document_id(conn, submittal)
        if submittal_id is None:
            print(f"  {submittal:<44} NOT IN THE DATABASE - not scored")
            continue
        standard_ids, described = scope_standards(conn, submittal_id, args.scope)
        if not standard_ids:
            print(f"  {submittal:<44} {described} - not scored")
            continue

        want = [r for r in pairs if r["submittal"] == submittal]
        deny = {r["field"] for r in nones if r["submittal"] == submittal}
        skip = {r["field"] for r in unsure if r["submittal"] == submittal}
        accepted: dict[str, set[tuple[str, str]]] = {}
        for row in want:
            accepted.setdefault(row["field"], set()).add(
                (row["standard"], row["clause"]))

        made = run_matcher(matcher, conn, submittal_id, standard_ids)

        found: set[tuple[str, str, str]] = set()
        false_none = false_clause = off_sheet = skipped = 0
        for pairing in made:
            key = (pairing["standard"], pairing["clause"])
            shown = (f"{pairing['field_raw']} [{pairing['fact_value']} "
                     f"{pairing['fact_unit']}] <- {pairing['standard']} "
                     f"{pairing['clause']} [{pairing['req_type']} "
                     f"{pairing['req_value']} {pairing['req_unit']}]")
            if pairing["field"] in accepted:
                if key in accepted[pairing["field"]]:
                    found.add((pairing["field"], *key))
                else:
                    false_clause += 1
                    disagreements.append(f"       FALSE (wrong clause)  {shown}")
            elif pairing["field"] in deny:
                false_none += 1
                disagreements.append(f"       FALSE (sheet says NONE)  {shown}")
            elif pairing["field"] in skip:
                skipped += 1
                disagreements.append(f"       not scored (sheet blank)  {shown}")
            else:
                off_sheet += 1
                disagreements.append(f"       not scored (field not on sheet)  {shown}")

        missed = [r for r in want
                  if (r["field"], r["standard"], r["clause"]) not in found]
        unreachable = [r for r in missed if not reachable(conn, r)]
        silent_ok = len(deny - {p["field"] for p in made})

        for row in missed:
            note = ("  (the clause carries no number - no matcher can pair it)"
                    if row in unreachable else "")
            disagreements.append(
                f"       MISSED  {row['field_raw']} [{row['value']} {row['unit']}]"
                f" -> {row['standard']} {row['clause']}{note}")

        print(f"  {submittal}")
        print(f"      scope: {described}")
        print(f"      pairings made: {len(made)}    correct: {len(found)}"
              f"    FALSE: {false_none + false_clause}"
              f"    missed: {len(missed)}")

        totals["gold_pairs"] += len(want)
        totals["found"] += len(found)
        totals["false_none"] += false_none
        totals["false_clause"] += false_clause
        totals["missed"] += len(missed)
        totals["unreachable"] += len(unreachable)
        totals["off_sheet"] += off_sheet
        totals["skipped"] += skipped
        totals["none_rows"] += len(deny)
        totals["silent_ok"] += silent_ok

    if args.verbose:
        print()
        for line in disagreements:
            print(line)

    false_total = totals["false_none"] + totals["false_clause"]
    scored = totals["found"] + false_total

    print("\n  RECALL     " + percent(totals["found"], totals["gold_pairs"])
          + "   of the pairings written down, made")
    if totals["none_rows"]:
        print("  PRECISION  " + percent(totals["found"], scored)
              + "   of the pairings made and scoreable, right")
    else:
        print("  PRECISION  refused - the sheets carry no NONE rows")
    print(f"\n  FALSE PAIRINGS   {false_total}"
          "   a value attached to a rule that is not its own")
    print(f"      of which, the field should have had NO rule   "
          f"{totals['false_none']}")
    print(f"      of which, the field has a rule but not that one   "
          f"{totals['false_clause']}")
    if false_total:
        print("      ^ each one leaves the building with a real clause and page"
              " attached and\n        is answerable by the contractor. This is"
              " the count that matters; it is\n        NOT part of precision"
              " above, and must not be averaged with anything.")
    print(f"\n  missed (silence)   {totals['missed']}"
          "   the engineer's pairing was not made")
    print(f"      of which the clause carries no number   "
          f"{totals['unreachable']}   (an extraction defect, not a matching one)")
    print(f"  correctly silent   {totals['silent_ok']}/{totals['none_rows']}"
          "   fields marked NONE that were left alone")
    print(f"  not scored         {totals['skipped']} blank on the sheet,"
          f" {totals['off_sheet']} paired on a field the sheet does not list")
    if totals["off_sheet"]:
        print("      ^ the sheet is incomplete for this datasheet; those"
              " pairings could be\n        anything and are credited as"
              " neither right nor wrong.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
