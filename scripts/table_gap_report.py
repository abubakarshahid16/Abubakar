"""Order 271.4: why do pages with text give no rule? Counts per standard, on a COPY.

For each standard (a document with stored requirements) this prints how many of its pages have text, how
many of those gave no requirement, and for the ones that gave none whether the extractor recorded a table
(`pages.tables_json`), recorded a FAILURE (the slug), or recorded nothing. It also counts the cells of the
recorded tables that are a number (a `table_value` can be made from them), text, or empty: a table of
material names has cells and no number, and `extract_table_values` skips every cell that is not a number.

With `--probe` it reopens each such page's PDF (the copy must hold the file at `documents.stored_path`) and
counts, for the pages with no recorded table, how many the extractor's own ruled-lines finder (`lines`)
finds a table on (a page with fewer than `extract.MIN_TABLE_PATHS` drawn paths is never asked) and
how many ONLY the aligned-text finder (`text`, the one the datasheet reader also
scores) finds one on, using the same size and fragment guards as the extractor. That is the count that says
whether borderless tables are the cause. A finder that raises is counted, not hidden.

Counts only: no text, filename or page number is printed (CLAUDE.md rule 1). Read-only, and on a COPY only
(a live-shaped path is refused).

    python scripts/table_gap_report.py --db <copy.sqlite> [--document-id ID ...] [--probe]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))


def _recorded(tables_json: str | None) -> tuple[list[list[list[str]]], str | None]:
    """(the stored tables' rows, the stored failure slug) of one page."""
    if not tables_json:
        return [], None
    try:
        data = json.loads(tables_json)
    except ValueError:
        return [], "tables_json_unreadable"
    tables = [t.get("rows") or [] for t in data.get("tables") or []]
    return tables, data.get("failed")


def cell_kinds(tables: list[list[list[str]]]) -> dict[str, int]:
    """Cells of recorded tables by what `extract_table_values` can do with them."""
    from app import requirements_3b

    out = {"number": 0, "text": 0, "empty": 0}
    for rows in tables:
        for row in rows[1:]:
            for cell in row[
                1:
            ]:  # the first column is the row label, the first row the header
                raw = (cell or "").strip()
                if not raw:
                    out["empty"] += 1
                elif (
                    requirements_3b.cell_reading(raw) is not None
                    or requirements_3b.cell_range(raw) is not None
                ):
                    out["number"] += 1
                else:
                    out["text"] += 1
    return out


def probe_page(page) -> dict[str, int]:
    """Tables the lines finder and the aligned-text finder find on one page, after the extractor's guards."""
    from app import extract
    from app import tables as tables_mod

    found = {}
    for strategy in ("lines", "text"):
        # the extractor never asks the lines finder about a page with too few drawn paths
        if strategy == "lines" and len(page.get_drawings()) < extract.MIN_TABLE_PATHS:
            found[strategy] = 0
            continue
        try:
            tables = page.find_tables(strategy=strategy).tables
        except Exception:  # noqa: BLE001 - a finder that raises is counted, not hidden
            found[strategy] = -1
            continue
        kept = 0
        for table in tables:
            rows = [[tables_mod._clean(c) for c in row] for row in table.extract()]
            rows = [r for r in rows if any(r)]
            if not rows:
                continue
            width = max(len(r) for r in rows)
            if len(rows) < tables_mod.MIN_ROWS or width < tables_mod.MIN_COLUMNS:
                continue
            if width > tables_mod.MAX_COLUMNS or tables_mod._is_fragmented(rows):
                continue
            kept += 1
        found[strategy] = kept
    return found


def _probe(path: str | None, pages: list[int]) -> dict[str, int]:
    out = {
        "probed": 0,
        "pdf_missing": 0,
        "finder_raised": 0,
        "lines_finds": 0,
        "text_only_finds": 0,
    }
    if not path or not Path(path).exists():
        out["pdf_missing"] = len(pages)
        return out
    import pymupdf

    with pymupdf.open(path) as doc:
        for number in pages:
            if not 1 <= number <= doc.page_count:
                continue
            found = probe_page(doc[number - 1])
            out["probed"] += 1
            if -1 in found.values():
                out["finder_raised"] += 1
            if found["lines"] > 0:
                out["lines_finds"] += 1
            elif found["text"] > 0:
                out["text_only_finds"] += 1
    return out


def report_document(
    conn: sqlite3.Connection, document_id: str, probe: bool = False
) -> dict:
    pages = conn.execute(
        "SELECT page_no, char_count, needs_ocr, tables_json FROM pages WHERE document_id = ?",
        (document_id,),
    ).fetchall()
    with_rule = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT page FROM standard_requirements WHERE standard_document_id = ?"
            " AND superseded_at IS NULL",
            (document_id,),
        )
        if r[0] is not None
    }
    out = {
        "pages": len(pages),
        "pages_read_by_ocr": sum(1 for p in pages if p[2]),
        "pages_with_text": 0,
        "pages_with_text_and_rule": 0,
        "pages_with_text_no_rule": 0,
        "no_rule_with_recorded_table": 0,
        "no_rule_with_recorded_failure": 0,
        "no_rule_with_nothing_recorded": 0,
        "recorded_failures_by_slug": {},
        "table_chunks": conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE document_id = ? AND kind = 'table'",
            (document_id,),
        ).fetchone()[0],
        "table_value_requirements": conn.execute(
            "SELECT COUNT(*) FROM standard_requirements WHERE standard_document_id = ? "
            "AND requirement_type = 'table_value' AND superseded_at IS NULL",
            (document_id,),
        ).fetchone()[0],
        "requirements": conn.execute(
            "SELECT COUNT(*) FROM standard_requirements WHERE standard_document_id = ?"
            " AND superseded_at IS NULL",
            (document_id,),
        ).fetchone()[0],
    }
    recorded_tables: list[list[list[str]]] = []
    bare: list[int] = []
    for number, chars, _ocr, tables_json in pages:
        if not chars:
            continue
        out["pages_with_text"] += 1
        tables, failed = _recorded(tables_json)
        recorded_tables.extend(tables)
        if number in with_rule:
            out["pages_with_text_and_rule"] += 1
            continue
        out["pages_with_text_no_rule"] += 1
        if failed:
            out["no_rule_with_recorded_failure"] += 1
            by = out["recorded_failures_by_slug"]
            by[failed] = by.get(failed, 0) + 1
        elif tables:
            out["no_rule_with_recorded_table"] += 1
        else:
            out["no_rule_with_nothing_recorded"] += 1
            bare.append(number)
    out["recorded_table_cells"] = cell_kinds(recorded_tables)
    if probe:
        path = conn.execute(
            "SELECT stored_path FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        out["probe_of_pages_with_nothing_recorded"] = _probe(
            path[0] if path else None, bare
        )
    return out


def main(argv: list[str] | None = None) -> int:
    from app import live_guard

    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--db", required=True, type=Path)
    p.add_argument("--document-id", action="append", default=[])
    p.add_argument("--probe", action="store_true")
    args = p.parse_args(argv)
    path = args.db.resolve()
    if live_guard.is_live_shaped(path) or not path.exists():
        raise SystemExit(
            f"refusing: {path} is a live database or does not exist. Use a copy."
        )
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        ids = args.document_id or [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT standard_document_id FROM standard_requirements"
                " WHERE superseded_at IS NULL"
            )
        ]
        report = {i: report_document(conn, i, args.probe) for i in sorted(ids)}
    finally:
        conn.close()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
