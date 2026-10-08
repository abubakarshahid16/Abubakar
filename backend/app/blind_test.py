"""Score one review run against an engineer's answer key - the blind test.

WHY THIS EXISTS. The project's own rules name the blind test as the only real
proof that the review "reads any datasheet": an engineer writes the comments
they would raise on a datasheet nobody on the project has seen, the key is
stored BEFORE the upload, and the machine's output is compared with it. Test
counts, code review and demos cannot answer "are the comments right?"; this
can. The existing gold sheets (`gold/TEMPLATE.csv`, `PAIRS-TEMPLATE.csv`)
score two earlier stages - what a standard says, and which clause governs a
field. Nothing scored the FINDINGS. This does.

WHAT IS SCORED: THE MACHINE'S OWN OUTPUT. Every row this run produced on the
internal copy of its CRS, confirmed or not - an engineer's confirmation is
human help, and a blind test scores the machine. Rows that are not this run's
machine output are left out and counted as such: an engineer's own chat
comments, and comments carried forward from an earlier review.

HOW A KEY LINE MATCHES A ROW (strict, and stated, because a lenient matcher
would paper over exactly the disagreements a blind test exists to show):
  page   - when the key gives one, it must be one of the row's datasheet
           pages. A row with no page (a value not found anywhere) is not held
           to a page.
  field  - every word of the key's field must appear in the row's datasheet
           field and comment.
  tag    - when given, must appear in the row.
Each row answers at most one key line, and a row of the expected type is
preferred over one of another type.

THE NUMBERS, EACH WITH ITS DENOMINATOR:
  found            key comments the machine raised, of the type expected
  found, other type  raised, but as a different kind of comment
  missed           key comments the machine did not raise at all
  false alarms     a comment raised where the engineer wrote "none"
  extra rows       machine rows no key line accounts for - a false positive
                   ONLY if the engineer's key covers the whole sheet, which
                   the procedure asks for (docs/blind-test.md)
A false alarm is reported apart from "extra": the engineer checked that field
and said there is nothing to raise, so it is a wrong comment, not an
unjudged one.

Pure: no database, no network. `scripts/blind_score.py` supplies the rows.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

#: The words an engineer writes in the "expected" column, and what they mean.
EXPECTED = ("breach", "missing", "review", "none")
_FAMILY_OF_KIND = {
    "non_compliant": "breach",
    "missing_information": "missing",
    "datasheet_check": "missing",
    "needs_engineer_review": "review",
    "ai_engineering_check": "review",
    "web_standard_check": "review",
}
#: Row kinds that are NOT this run's machine output.
NOT_MACHINE_OUTPUT = frozenset({"engineer_comment", "carried_forward"})

COLUMNS = ("submittal", "page", "field", "tag", "expected", "standard", "clause", "notes")


class AnswerKeyError(ValueError):
    """The answer key cannot be scored as written. The message names the line."""


def _fold(text) -> str:
    return " ".join(re.sub(r"[^a-z0-9.]+", " ", str(text or "").lower()).split())


def _words(text) -> list[str]:
    return [w for w in _fold(text).replace(".", " ").split() if len(w) >= 2 or w.isdigit()]


def read_key(path: str | Path) -> list[dict]:
    """The answer key's lines, as dicts with their 1-based file line number.
    Rows starting with '#' are comments. Raises AnswerKeyError naming the line
    on anything that cannot be scored honestly."""
    lines = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None or [h.strip().lower() for h in header[:len(COLUMNS)]] != list(COLUMNS):
            raise AnswerKeyError(f"line 1: the header must be {','.join(COLUMNS)}")
        for number, cells in enumerate(reader, start=2):
            if not cells or not "".join(cells).strip() or cells[0].lstrip().startswith("#"):
                continue
            row = dict(zip(COLUMNS, (c.strip() for c in cells + [""] * len(COLUMNS))))
            expected = row["expected"].lower()
            if expected not in EXPECTED:
                raise AnswerKeyError(
                    f"line {number}: expected must be one of {', '.join(EXPECTED)}, "
                    f"not {row['expected']!r}")
            if not row["field"]:
                raise AnswerKeyError(f"line {number}: field is empty")
            page = row["page"]
            if page and not page.isdigit():
                raise AnswerKeyError(f"line {number}: page must be a number or empty")
            lines.append({**row, "expected": expected, "line": number,
                          "page": int(page) if page else None})
    return lines


def _row_pages(page_section: str) -> set[int]:
    m = re.match(r"\s*p\.\s*([0-9,\s\-–]+)", page_section or "")
    if not m:
        return set()
    pages: set[int] = set()
    for part in re.split(r"[,\s]+", m.group(1).strip()):
        span = re.split(r"[-–]", part)
        if all(s.isdigit() for s in span if s) and span[0]:
            lo = int(span[0])
            hi = int(span[-1]) if span[-1] else lo
            pages.update(range(lo, hi + 1))
    return pages


def _matches(line: dict, row: dict) -> bool:
    if line["page"] is not None and row["pages"] and line["page"] not in row["pages"]:
        return False
    text = row["text"]
    if not all(w in text.split() or w in text for w in _words(line["field"])):
        return False
    if line["tag"] and _fold(line["tag"]) not in text:
        return False
    return True


def score(key: list[dict], crs_rows: list[dict], submittal_name: str) -> dict:
    """Score one run's CRS rows against one answer key."""
    rows = []
    left_out = 0
    for i, r in enumerate(crs_rows):
        kind = r.get("row_kind") or ""
        if kind in NOT_MACHINE_OUTPUT:
            left_out += 1
            continue
        rows.append({
            "index": i, "family": _FAMILY_OF_KIND.get(kind, "review"),
            "pages": _row_pages(r.get("page_section") or ""),
            "text": _fold(" ".join(str(r.get(k) or "") for k in (
                "page_section", "comment", "ai_review_comment"))),
            "standard_reference": _fold(r.get("standard_reference")),
        })

    own = _fold(Path(submittal_name).stem)
    other_submittal = [ln for ln in key
                       if ln["submittal"] and _fold(Path(ln["submittal"]).stem) != own]
    key = [ln for ln in key if ln not in other_submittal]

    used: set[int] = set()
    outcomes = []
    # "none" lines last: a comment the engineer expects should claim its row
    # before a "nothing here" line can call that row a false alarm.
    for line in sorted(key, key=lambda ln: ln["expected"] == "none"):
        candidates = [r for r in rows if r["index"] not in used and _matches(line, r)]
        same = [r for r in candidates if r["family"] == line["expected"]]
        pick = (same or candidates or [None])[0]
        if pick is not None:
            used.add(pick["index"])
        if line["expected"] == "none":
            outcome = "false alarm" if pick else "correctly silent"
        elif pick is None:
            outcome = "missed"
        elif pick["family"] == line["expected"]:
            outcome = "found"
        else:
            outcome = f"found, as {pick['family']}"
        clause = _fold(line["clause"])
        cited = (None if not clause or pick is None or line["expected"] == "none"
                 else clause in pick["standard_reference"])
        outcomes.append({"line": line["line"], "field": line["field"],
                         "expected": line["expected"], "outcome": outcome,
                         "row": pick["index"] + 1 if pick else None, "clause_cited": cited})
    outcomes.sort(key=lambda o: o["line"])

    expected = [o for o in outcomes if o["expected"] != "none"]
    nones = [o for o in outcomes if o["expected"] == "none"]
    return {
        "key_lines_scored": len(outcomes),
        "key_lines_for_another_submittal": len(other_submittal),
        "expected_comments": len(expected),
        "found": sum(1 for o in expected if o["outcome"] == "found"),
        "found_other_type": sum(1 for o in expected if o["outcome"].startswith("found, as")),
        "missed": sum(1 for o in expected if o["outcome"] == "missed"),
        "none_lines": len(nones),
        "false_alarms": sum(1 for o in nones if o["outcome"] == "false alarm"),
        "machine_rows": len(rows),
        "extra_rows": len(rows) - len(used),
        "rows_not_machine_output": left_out,
        "clause_checked": sum(1 for o in outcomes if o["clause_cited"] is not None),
        "clause_agreed": sum(1 for o in outcomes if o["clause_cited"] is True),
        "lines": outcomes,
    }
