"""Import the client's Engineering Deliverables register.

    python scripts/import_register.py <register.pdf> <revision>
    python scripts/import_register.py <register.pdf> rev-D --expect 1354
    python scripts/import_register.py <register.pdf> rev-D --dry-run

THE REGISTER PDF IS CLIENT MATERIAL. It is taken as an ARGUMENT and never
copied into this repository, never committed, and no test depends on it - the
same rule as client PDFs. Every test for this importer builds its own fixture.

WHY THE COLUMNS ARE NOT SPLIT ON X POSITIONS. Column widths vary by page in
this register, so a fixed x boundary learned from page 1 mis-splits page 7 -
and it mis-splits it QUIETLY, producing a discipline like "Process (AXE" and a
title beginning "NS)". An hour was lost to exactly that.

So the split is done twice and the answers must agree with each other:

  1. Words are clustered into columns PER PAGE by horizontal gap, so a page
     with different widths is measured on its own terms rather than on the
     first page's.
  2. The middle column is then matched against the DISCIPLINE VOCABULARY. A
     value that is not in the vocabulary is not accepted as a discipline; the
     row is reported instead of being guessed at.

THE VOCABULARY IS LEARNED FROM THIS REGISTER, not hardcoded here. I do not
have the client's 24 values and inventing them would be worse than reading
them: the importer collects the middle-column strings that recur across the
document, keeps those that appear at least MIN_DISCIPLINE_OCCURRENCES times,
and refuses if the resulting count is implausible. A one-off typo in one row
therefore cannot become a 25th discipline.

THE VENDOR STAYS INSIDE THE LABEL. "Process (AXENS)" is one discipline, as
the register writes it. `vendor` is extracted alongside for display only,
never as a filter axis: vendor is already inside the discipline string and
splitting it would create two sources of truth for one field.

REFUSING IS THE POINT. A half-parsed register imported silently is worse than
a failed import, because everything downstream then classifies against a
corpus that is quietly missing a third of its rows. The import refuses if the
row count is not within TOLERANCE of the expected total, if a type outside the
register's three appears, or if fewer than MIN_SUBJECTS subjects were derived.
Nothing is written until every check has passed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import pymupdf  # noqa: E402  - after the path insert

from app import classification  # noqa: E402
from app import live_guard  # noqa: E402
from app.db import connect, init_db  # noqa: E402

# --------------------------------------------------------------- the guards

#: The register's own three types. A fourth value means the parse has gone
#: wrong or the register has genuinely changed, and both need a human.
KNOWN_TYPES = frozenset(classification.DOC_TYPES)

#: Rows expected. Overridable, because the fixture tests import 40.
DEFAULT_EXPECTED_ROWS = 1354

#: How far off the expected total is tolerable. A few percent covers a
#: re-issued revision adding or dropping deliverables; a third missing is a
#: broken parse.
TOLERANCE = 0.05

#: Below this, the subject vocabulary has not really been derived and every
#: comparison built on it would be thin without saying so.
MIN_SUBJECTS = 20

#: A middle-column string must recur this often to be a discipline. One
#: occurrence is a typo or a mis-split; a real discipline labels dozens of
#: deliverables in a 1,354-row register.
MIN_DISCIPLINE_OCCURRENCES = 3

#: Plausible bounds for the learned vocabulary. The register has 24; well
#: outside this range means the middle column was not found.
MIN_DISCIPLINES, MAX_DISCIPLINES = 8, 60

#: Horizontal gap, in points, that separates one column from the next. Chosen
#: well above inter-word spacing and well below the narrowest column gutter
#: observed; the clustering is per page, so it does not need to be exact.
COLUMN_GAP = 12.0


class RegisterRefused(SystemExit):
    """The import did not happen, and says why. Nothing was written."""


# ----------------------------------------------------- the subject candidates

#: CANDIDATE subject terms. What gets EMITTED is only what the register titles
#: actually contain - this is the list of things looked FOR, not the
#: vocabulary. Stated plainly because it is the one place this importer holds
#: knowledge the register did not give it: the client named some of these
#: (hot oil, firewater, MEG, flare, substation, beach valve station, produced
#: water, diesel) and the rest are ordinary systems for a facility of this
#: kind. Extend with --subjects when a revision introduces one.
#:
#: A term that appears in no title is NOT emitted, so this list being too long
#: costs nothing and a term missing from it shows up as a lower derived count.
CANDIDATE_SYSTEMS = (
    "hot oil", "firewater", "fire water", "MEG", "flare", "substation",
    "beach valve station", "produced water", "diesel", "seawater",
    "sea water", "cooling water", "potable water", "instrument air",
    "utility air", "nitrogen", "fuel gas", "condensate", "crude",
    "sour water", "wastewater", "waste water", "drainage", "sewage",
    "chemical injection", "corrosion inhibitor", "methanol", "glycol",
    "steam", "power generation", "emergency power", "UPS", "earthing",
    "lighting", "telecom", "fire alarm", "gas detection", "HVAC",
    "pipeline", "manifold", "separator", "compressor", "pump station",
    "storage tank", "loading", "metering", "wellhead", "water injection",
    "gas lift", "slug catcher", "desalination", "boiler", "generator",
)

#: Facility names and site codes ARE client identifiers - unlike the generic
#: systems above, they name the client's own sites. Read from a LOCAL,
#: git-ignored file (scripts/register_facilities.local.json) so none is ever
#: committed; see scripts/register_facilities.local.example.json for the
#: shape. A missing file yields an empty tuple rather than a crash - fewer
#: subjects are then derived, and MIN_SUBJECTS below still refuses the import
#: if that leaves too few to be useful, so the omission cannot pass silently.
_FACILITIES_CONFIG_ENV = "REGISTER_FACILITIES_CONFIG"
_DEFAULT_FACILITIES_CONFIG = Path(__file__).resolve().parent / "register_facilities.local.json"


def _load_candidate_facilities() -> tuple[str, ...]:
    path = Path(os.environ.get(_FACILITIES_CONFIG_ENV, _DEFAULT_FACILITIES_CONFIG))
    if not path.is_file():
        print(f"register import: no local facility config at {path} - "
              "facility subjects will not be derived. See "
              "scripts/register_facilities.local.example.json.", file=sys.stderr)
        return ()
    return tuple(json.loads(path.read_text(encoding="utf-8")))


CANDIDATE_FACILITIES = _load_candidate_facilities()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


# -------------------------------------------------------------- the parsing

def columns_on_page(page) -> list[list[tuple[float, str]]]:
    """Rows of `(x, text)` cells, clustered PER PAGE by horizontal gap.

    Words are grouped into lines by their y position, then into cells by
    looking for a horizontal gap wider than `COLUMN_GAP`. Because the
    clustering is done for each page from that page's own words, a page whose
    columns are narrower than the first page's is split correctly - which a
    fixed x boundary does not do, and does not do silently.
    """
    words = page.get_text("words")          # (x0, y0, x1, y1, word, ...)
    if not words:
        return []
    lines: dict[int, list] = {}
    for x0, y0, x1, _y1, word, *_rest in words:
        # Round the baseline so words on one visual line group together
        # despite sub-point differences.
        lines.setdefault(round(y0 / 3.0), []).append((x0, x1, word))

    out: list[list[tuple[float, str]]] = []
    for _key, items in sorted(lines.items()):
        items.sort(key=lambda t: t[0])
        cells: list[tuple[float, str]] = []
        current: list[str] = []
        start = items[0][0]
        previous_end = None
        for x0, x1, word in items:
            if previous_end is not None and (x0 - previous_end) > COLUMN_GAP:
                cells.append((start, " ".join(current)))
                current, start = [], x0
            current.append(word)
            previous_end = x1
        if current:
            cells.append((start, " ".join(current)))
        out.append(cells)
    return out


def learn_disciplines(rows: list[list[tuple[float, str]]]) -> list[str]:
    """The discipline vocabulary, LEARNED from the middle column.

    Only strings recurring at least `MIN_DISCIPLINE_OCCURRENCES` times are
    kept, so a mis-split or a typo in one row cannot become a discipline. A
    value appearing once is exactly what a broken parse produces.
    """
    counts: Counter[str] = Counter()
    for cells in rows:
        if len(cells) < 3:
            continue
        first = cells[0][1].strip()
        if first in KNOWN_TYPES:
            counts[cells[1][1].strip()] += 1
    return sorted(v for v, n in counts.items()
                  if v and n >= MIN_DISCIPLINE_OCCURRENCES)


VENDOR = re.compile(r"\(([^)]+)\)\s*$")


def split_vendor(discipline: str) -> tuple[str, str | None]:
    """`(label as written, vendor or None)`.

    The label is returned UNCHANGED - "Process (AXENS)" stays "Process
    (AXENS)". The vendor is pulled out for display only. Splitting the label
    itself would make two fields disagree the first time a register revision
    renamed a vendor.
    """
    match = VENDOR.search(discipline.strip())
    return discipline.strip(), (match.group(1).strip() if match else None)


def parse(pdf_path: Path) -> tuple[list[dict], list[str], list[str], list[str]]:
    """`(rows, disciplines, problems, unknown_types)`. Reads; writes nothing.

    `unknown_types` IS RETURNED SEPARATELY, and that is not tidiness. A row
    whose first cell is not one of the three has to be skipped - most such
    rows are headers, page numbers and wrapped titles, and refusing on them
    would refuse every register. But a row that is SHAPED like a data row -
    its middle cell is a learned discipline - and carries a fourth type is a
    different thing entirely, and the spec says to refuse it.

    Folded into the row count it disappears: dropping one row of 1,354 is
    0.07%, far inside the 5% tolerance, so a register that had quietly grown a
    "Datasheet" type would import clean and nobody would learn about it. So it
    is reported on its own and `check` refuses by name.
    """
    document = pymupdf.open(pdf_path)
    try:
        page_rows = [cells for page in document
                     for cells in columns_on_page(page)]
    finally:
        document.close()

    disciplines = learn_disciplines(page_rows)
    vocabulary = set(disciplines)

    rows: list[dict] = []
    problems: list[str] = []
    unknown_types: list[str] = []
    for cells in page_rows:
        if len(cells) < 3:
            continue
        doc_type = cells[0][1].strip()
        if doc_type not in KNOWN_TYPES:
            # Not a data row (a header, a page number, a wrapped title) unless
            # it looks like one, in which case it is a problem worth naming.
            if len(cells) >= 3 and cells[1][1].strip() in vocabulary:
                # Shaped like a data row - its discipline is a real one - so
                # this is a fourth TYPE and not a header.
                if doc_type not in unknown_types:
                    unknown_types.append(doc_type)
                problems.append(
                    f"type {doc_type!r} is not one of {sorted(KNOWN_TYPES)}"
                    f" (title began {cells[2][1][:40]!r})")
            continue
        discipline = cells[1][1].strip()
        if discipline not in vocabulary:
            # THE CHECK THAT CATCHES A MIS-SPLIT. A truncated "Process (AXE"
            # is not in the learned vocabulary, so the row is reported rather
            # than imported with a broken discipline and a broken title.
            problems.append(
                f"discipline {discipline!r} is not in the learned vocabulary "
                f"(title began {cells[2][1][:40]!r})")
            continue
        title = " ".join(c[1] for c in cells[2:]).strip()
        if not title:
            problems.append(f"row with no title: {doc_type} / {discipline}")
            continue
        label, vendor = split_vendor(discipline)
        rows.append({"doc_type": doc_type, "discipline": label,
                     "vendor": vendor, "title": title})
    return rows, disciplines, problems, unknown_types


# ----------------------------------------------------- the subject derivation

def derive_subjects(titles: list[str], extra: list[str]) -> list[dict]:
    """The subject vocabulary, DERIVED: only terms the titles actually contain.

    Plus "Project-wide" ALWAYS and explicitly, because it is not a term that
    appears in titles - it is the kind that covers philosophies, design
    criteria and overall block diagrams, 18% of the register, and exactly the
    group gap analysis should hold as baselines. Deriving it from text would
    miss it; asserting it is correct.
    """
    haystack = " || ".join(classification.normalise(t) for t in titles)
    found: list[dict] = []
    seen: set[str] = set()

    def consider(name: str, kind: str) -> None:
        key = classification.normalise(name)
        if not key or key in seen:
            return
        if f" {key} " in f" {haystack} ":
            found.append({"name": name, "kind": kind})
            seen.add(key)

    for name in (*CANDIDATE_SYSTEMS, *extra):
        consider(name, "system")
    for name in CANDIDATE_FACILITIES:
        consider(name, "facility")

    found.append({"name": classification.PROJECT_WIDE, "kind": "project_wide"})
    return found


# ------------------------------------------------------------------ the write

def store(rows: list[dict], subjects: list[dict], revision: str) -> dict:
    """Replace this revision's rows. IDEMPOTENT PER REVISION.

    Re-importing the same revision replaces only that revision's rows, so a
    corrected import does not duplicate. An EARLIER revision is left alone:
    documents already classified against it must keep the register they were
    classified against, or the record of what they were compared with changes
    underneath them.
    """
    now = _now()
    conn = connect()
    with conn:
        conn.execute("DELETE FROM deliverables_register WHERE"
                     " register_revision = ?", (revision,))
        conn.execute("DELETE FROM subjects WHERE register_revision = ?",
                     (revision,))
        for row in rows:
            conn.execute(
                "INSERT OR IGNORE INTO deliverables_register (id, doc_type,"
                " discipline, vendor, title, register_revision, imported_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (f"reg_{uuid.uuid4().hex[:12]}", row["doc_type"],
                 row["discipline"], row["vendor"], row["title"], revision, now))
        for subject in subjects:
            conn.execute(
                "INSERT OR IGNORE INTO subjects (id, name, kind,"
                " register_revision) VALUES (?,?,?,?)",
                (f"sub_{uuid.uuid4().hex[:12]}", subject["name"],
                 subject["kind"], revision))
    stored = conn.execute(
        "SELECT COUNT(*) FROM deliverables_register WHERE register_revision=?",
        (revision,)).fetchone()[0]
    return {"rows": stored, "subjects": len(subjects)}


def check(rows: list[dict], disciplines: list[str], subjects: list[dict],
          problems: list[str], expected: int,
          unknown_types: list[str] | None = None) -> None:
    """Every guard, before anything is written. Refuses with a reason."""
    bad_types = sorted(
        ({r["doc_type"] for r in rows} | set(unknown_types or ())) - KNOWN_TYPES)
    if bad_types:
        raise RegisterRefused(
            f"REFUSED: type(s) outside the register's three: {bad_types}. "
            f"Either the parse has gone wrong or the register has genuinely "
            f"changed, and both need a human - a fourth type silently skipped "
            f"is a class of deliverable missing from every count downstream.")

    if not (MIN_DISCIPLINES <= len(disciplines) <= MAX_DISCIPLINES):
        raise RegisterRefused(
            f"REFUSED: learned {len(disciplines)} disciplines, expected "
            f"{MIN_DISCIPLINES}-{MAX_DISCIPLINES}. The middle column was "
            f"probably not found. Learned: {disciplines[:8]}")

    low, high = expected * (1 - TOLERANCE), expected * (1 + TOLERANCE)
    if not (low <= len(rows) <= high):
        raise RegisterRefused(
            f"REFUSED: parsed {len(rows)} rows, expected about {expected} "
            f"(tolerance {TOLERANCE:.0%}, so {low:.0f}-{high:.0f}). A "
            f"half-parsed register imported silently is worse than a failed "
            f"import: everything downstream would classify against a corpus "
            f"quietly missing rows."
            + (f"\n  first problems: {problems[:5]}" if problems else ""))

    if len(subjects) < MIN_SUBJECTS:
        raise RegisterRefused(
            f"REFUSED: derived only {len(subjects)} subjects, need at least "
            f"{MIN_SUBJECTS}. Subject is the comparison axis, and a thin "
            f"vocabulary would make every comparison thin without saying so. "
            f"Add terms with --subjects.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, help="the register PDF (never committed)")
    parser.add_argument("revision", help='e.g. "rev-D"')
    parser.add_argument("--expect", type=int, default=DEFAULT_EXPECTED_ROWS)
    parser.add_argument("--subjects", type=Path, default=None,
                        help="extra candidate subject terms, one per line")
    parser.add_argument("--dry-run", action="store_true",
                        help="parse and check, write nothing")
    args = parser.parse_args(argv)

    if not args.pdf.exists():
        raise RegisterRefused(f"REFUSED: no such file: {args.pdf}")

    extra: list[str] = []
    if args.subjects is not None:
        extra = [line.strip() for line in
                 args.subjects.read_text(encoding="utf-8").splitlines()
                 if line.strip()]

    rows, disciplines, problems, unknown_types = parse(args.pdf)
    subjects = derive_subjects([r["title"] for r in rows], extra)

    print(f"parsed          : {len(rows)} rows")
    print(f"disciplines     : {len(disciplines)} learned")
    for name in disciplines:
        label, vendor = split_vendor(name)
        print(f"    {label}" + (f"    [vendor: {vendor}]" if vendor else ""))
    print(f"types           : {sorted({r['doc_type'] for r in rows})}")
    print(f"subjects derived: {len(subjects)}")
    for subject in subjects:
        print(f"    {subject['kind']:<13} {subject['name']}")
    if problems:
        print(f"problems        : {len(problems)}")
        for line in problems[:10]:
            print(f"    {line}")

    check(rows, disciplines, subjects, problems, args.expect,
          unknown_types)

    if args.dry_run:
        print("\ndry run: nothing written")
        return 0

    live_guard.clear_if_live(f"import_register {args.revision}")
    init_db()
    result = store(rows, subjects, args.revision)
    print(f"\nimported revision {args.revision!r}: "
          f"{result['rows']} rows, {result['subjects']} subjects")
    return 0


if __name__ == "__main__":
    sys.exit(main())
