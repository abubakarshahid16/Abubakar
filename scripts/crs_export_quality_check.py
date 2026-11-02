"""#1503: re-export stored runs as CRS workbooks and COUNT what is wrong in them.

    python scripts/crs_export_quality_check.py --db <COPY of the database> \\
        --out <folder outside the repo> RUN_ID[=label] [RUN_ID[=label] ...]

READ-ONLY on the copy you pass: every export runs on its own throw-away copy of
it, with every model and Claude call refused (the AI wording is read from what
the run stored, never asked again). Refuses the live database - take a copy
first (`live_guard.diagnostic_copy()`). The workbooks hold document text: they
are written ONLY under --out, which must not be inside this repository. What
is printed is counts and labels, never document text.

Per run, per copy and per switch setting (CRS_EXPORT_QUALITY_ENABLED off/on):
  internal          the internal review copy
  client            the contractor copy as the app builds it (engineer-confirmed
                    rows only: a run nobody has confirmed has none)
  client-simulated  the contractor copy with every row treated as confirmed IN
                    MEMORY (nothing is stored), so the rules are measured on a
                    client copy that has rows. Labelled as a simulation. It mints no
                    number, so its rows still merge: its duplicate count is NOT what
                    a really confirmed client copy shows (A-1633).
Counts, read back from the saved workbook itself:
  duplicate rows    rows sharing (document, Page No./Section, Standard Reference)
                    with another row
  empty rows        rows whose COMPANY comment is blank or the placeholder
  no page           rows whose page cell has no page and no "page not found (reason)"
  internal words    cells holding "not yet proven", "Reasoning (internal)" or
                    "Rule trust (internal)" (client copies only are meant to be 0)
  over 350          comments longer than 350 characters
  considered        "Considered, not applied" rows on the Applicable standards sheet
  bad priority      Priority cells outside Missing value / Engineer to check / Fail / Pass
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

INTERNAL_PHRASES = ("not yet proven", "reasoning (internal)", "rule trust (internal)")
PRIORITIES = ("Missing value", "Engineer to check", "Fail", "Pass")
PLACEHOLDER = "No comment text was produced for this row"
_PAGE = re.compile(r"(?<![A-Za-z0-9])(?:pp?\.\s*|pages?\s+)\d", re.I)


def measure(workbook_path: Path) -> dict:
    """The counts of one saved workbook."""
    import openpyxl

    from app import crs_export

    wb = openpyxl.load_workbook(workbook_path)
    ws = wb["CRS"]
    header = [c.value for c in ws[crs_export.COLUMN_HEADER_ROW]]
    col = {name: i for i, name in enumerate(header) if name}
    rows = []
    r = crs_export.FIRST_DATA_ROW
    while ws.cell(row=r, column=2).value not in (
        None,
        "",
    ):  # the notice and code rows have no document name
        rows.append([c.value or "" for c in ws[r]])
        r += 1
    key = [
        (
            row[col["Document Name"]],
            row[col["Page No./Section"]],
            row[col["Standard Reference"]],
        )
        for row in rows
    ]
    counted = collections.Counter(key)
    comments = [str(row[col["COMPANY Comments"]]) for row in rows]
    pages = [str(row[col["Page No./Section"]]) for row in rows]
    words = 0
    for sheet in wb.worksheets:
        if (
            sheet.title == "Internal"
        ):  # the engineer's own sheet; the client copy has none
            continue
        for cells in sheet.iter_rows(values_only=True):
            for value in cells:
                low = str(value or "").lower()
                words += sum(p in low for p in INTERNAL_PHRASES)
    standards = wb["Applicable standards"]
    considered = sum(
        1
        for cells in standards.iter_rows(min_row=2, values_only=True)
        if (cells[1] or "") == "Considered, not applied"
    )
    return {
        "rows": len(rows),
        "duplicate_rows": sum(n for k, n in counted.items() if n > 1 and k[2]),
        "empty_rows": sum(1 for c in comments if not c.strip() or PLACEHOLDER in c),
        "no_page": sum(
            1
            for p in pages
            if not _PAGE.search(p) and not p.startswith("page not found (")
        ),
        "internal_words": words,
        "over_350": sum(1 for c in comments if len(c) > 350),
        "considered_rows": considered,
        "bad_priority": sum(
            1 for row in rows if row[col["Priority"]] not in PRIORITIES
        ),
        "sheets": wb.sheetnames,
    }


def export_all(
    db_path: Path, runs: dict[str, str], out: Path, strict: bool = False
) -> list[dict]:
    from tools import crs_bench

    from app import access, crs_export, db, live_guard, main
    from app.config import settings

    if live_guard.is_live_shaped(db_path):
        raise PermissionError("never opens the live database; pass a copy")
    out.mkdir(parents=True, exist_ok=True)
    results = []
    with crs_bench._on_copy(db_path), crs_bench._models_refused([0]):
        ids = frozenset(
            r["id"] for r in db.connect().execute("SELECT id FROM documents")
        )
        scope = access.AccessScope(user_id="crs-quality", allowed_document_ids=ids)
        saved = settings.crs_export_quality_enabled
        saved_strict = settings.crs_export_quality_strict_enabled
        try:
            for label, run in runs.items():
                for copy in ("internal", "client", "client-simulated"):
                    for on in (False, True):
                        settings.crs_export_quality_enabled = on
                        settings.crs_export_quality_strict_enabled = on and strict
                        which = "internal" if copy == "internal" else "issue"
                        rows, meta, _name, _stamp = main._crs_content(run, scope, which)
                        if copy == "client-simulated":
                            rows = [{**r, "engineer_confirmed": True} for r in rows]
                        data = crs_export.build_crs(rows, meta)
                        path = out / f"{label}_{copy}_{'on' if on else 'off'}.xlsx"
                        path.write_bytes(data)
                        results.append(
                            {
                                "run": label,
                                "copy": copy,
                                "switch": "on" if on else "off",
                                **measure(path),
                            }
                        )
        finally:
            settings.crs_export_quality_enabled = saved
            settings.crs_export_quality_strict_enabled = saved_strict
    return results


def table(results: list[dict]) -> str:
    cols = (
        "rows",
        "duplicate_rows",
        "empty_rows",
        "no_page",
        "internal_words",
        "over_350",
        "considered_rows",
        "bad_priority",
    )
    lines = [
        "| run | copy | switch | " + " | ".join(cols) + " |",
        "|---|---|---|" + "---|" * len(cols),
    ]
    for r in results:
        lines.append(
            f"| {r['run']} | {r['copy']} | {r['switch']} | "
            + " | ".join(str(r[c]) for c in cols)
            + " |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--db", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="switch on also means CRS_EXPORT_QUALITY_STRICT_ENABLED",
    )
    parser.add_argument("runs", nargs="+", help="RUN_ID or RUN_ID=label")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    if REPO in (out, *out.parents):
        print(
            "refused: the workbooks hold document text; --out must be outside the repository"
        )
        return 2
    runs = {}
    for item in args.runs:
        run, _, label = item.partition("=")
        runs[label or run[:8]] = run
    try:
        results = export_all(Path(args.db), runs, out, args.strict)
    except PermissionError as exc:
        print(f"refused: {exc}")
        return 2
    print(json.dumps(results, indent=1) if args.json else table(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
