"""Re-chunk and re-extract ONE rule book with the current chunker, carrying its AI rule labels (order 14 lane C).

    python scripts/reextract_book.py --db <database> --doc <book id> --dry-run
    python scripts/reextract_book.py --db <COPY> --doc <book id>                      # a copy: the rehearsal
    python scripts/reextract_book.py --db <live> --doc <book id> --owner-yes "<who, when, where recorded>"

WHY: CHUNKER_VERSION 12 reads code paragraph ids ("UG-150", "44-2") as clauses. A stored book gets the new labels only
when it is re-chunked and re-extracted. Nothing does that by itself. This script does it for ONE book, and nothing else.

WHAT IT DOES, IN ORDER (no model call, no network: sockets are refused for the whole run):
  0. GO / NO-GO: the database and the book exist; the book has stored pages; nothing else holds the database open
     (`lsof`); free disk >= 3 x the database; a live database only with --owner-yes; the code is CHUNKER_VERSION 12.
     Any NO-GO stops here (exit 2). --dry-run stops after the checks and the BEFORE counts (it writes nothing).
  1. BACKUP: a live database goes through `live_guard.prepare_live_write` (the project's A5 steps: backup with the
     SQLite backup API, integrity_check, live-vs-backup table counts, restore drill); its three raw files (the database,
     -wal, -shm) are also copied beside it. A copy is backed up the same way (`backup_db.backup` + `verify`).
  2. RE-CHUNK the book (`chunker.chunk_document(force=True)`): its chunks are rebuilt from the stored page text.
  3. RE-EXTRACT its rules (`standards.extract_requirements`): unchanged rules keep their id; the others are superseded
     (kept, never deleted); AI labels are carried to identical successors (`standards.carry_labels`); then table values.
  4. AFTER COUNTS, compared with BEFORE: rules (current, superseded, kept, new), labels on current rules, findings
     naming the book and how many no longer resolve their rule (must be 0), current rules per clause range, and the
     CRS counts (completeness check: page = database = file rows) of the papers named with --paper (must be unchanged
     and agree). Any failure: exit 1 and the restore lines are printed.
  THE WAY BACK: stop the server, copy the backup over the database and delete the -wal and -shm files (lines printed).
After a LIVE run: start the server (`python run.py`): its worker rebuilds the keyword index and the vectors of the
re-chunked book (the vectors use the local embedding model on this machine; nothing leaves it).
Prints ids and counts only, never document text.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

DEFAULT_PAPERS = (
    "doc_d30f4c63d481",
    "doc_da3fcc0aaacc",
    "doc_2ec2934f8d3f",
    "doc_b4f0d52bf927",
    "doc_0d5c6f72ad0d",
)  # valve, pump, vessel, HAZOP procedure, second procedure
RANGES = {"UG-150..UG-156": r"^UG-15[0-6]\b", "UW-51/UW-52": r"^UW-5[12]\b"}


class NoGo(SystemExit):
    pass


def _print(msg: str) -> None:
    print(msg, flush=True)


def _block_network():
    """Refuse every socket until the returned function is called (the run's own guarantee: no model, no network)."""
    saved = (socket.socket.connect, socket.create_connection)

    def refused(*_a, **_k):
        raise RuntimeError("reextract_book: no network in this run")

    socket.socket.connect = refused  # type: ignore[method-assign]
    socket.create_connection = refused  # type: ignore[assignment]

    def restore() -> None:
        socket.socket.connect, socket.create_connection = saved  # type: ignore[method-assign]

    return restore


def go_no_go(
    db: Path, doc: str, live: bool, owner_yes: str | None
) -> list[tuple[str, bool, str]]:
    import sqlite3

    from app import chunker

    checks: list[tuple[str, bool, str]] = []
    checks.append(("database exists", db.is_file(), str(db.name)))
    if not db.is_file():
        return checks
    ro = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    row = ro.execute("SELECT filename FROM documents WHERE id = ?", (doc,)).fetchone()
    checks.append(("the book exists", row is not None, doc))
    pages = ro.execute(
        "SELECT COUNT(*) FROM pages WHERE document_id = ?", (doc,)
    ).fetchone()[0]
    checks.append(("the book has stored pages", pages > 0, f"{pages} pages"))
    rules = ro.execute(
        "SELECT COUNT(*) FROM standard_requirements WHERE standard_document_id = ?",
        (doc,),
    ).fetchone()[0]
    checks.append(("the book holds rules", rules > 0, f"{rules} rule rows"))
    ro.close()
    checks.append(
        (
            "code is CHUNKER_VERSION 12",
            chunker.CHUNKER_VERSION == "12",
            f"CHUNKER_VERSION {chunker.CHUNKER_VERSION}",
        )
    )
    holders = subprocess.run(
        ["lsof", "-t", str(db)], capture_output=True, text=True, check=False
    ).stdout.split()
    others = [p for p in holders if p != str(__import__("os").getpid())]
    checks.append(
        (
            "nothing else holds the database open (server stopped)",
            not others,
            f"pids {others or 'none'}",
        )
    )
    free = shutil.disk_usage(db.parent).free
    checks.append(
        (
            "free disk >= 3 x database",
            free >= 3 * db.stat().st_size,
            f"{free // 2**30} GB free, database {db.stat().st_size // 2**20} MB",
        )
    )
    if live:
        from app import live_guard

        target = live_guard.default_backup_dir(db)
        checks.append(("live backup folder exists", target.is_dir(), str(target)))
        checks.append(
            (
                "live database: the owner's yes is given",
                bool(owner_yes and owner_yes.strip()),
                owner_yes or "missing --owner-yes",
            )
        )
    return checks


def counts(conn, doc: str, papers: list[str]) -> dict:
    from app import access, crs_completeness

    q = conn.execute
    rows = q(
        "SELECT id, clause, superseded_at FROM standard_requirements WHERE standard_document_id = ?",
        (doc,),
    ).fetchall()
    current = [r for r in rows if not r[2]]
    labelled = {
        r[0] for r in q("SELECT rule_ref FROM rule_label WHERE source = 'requirement'")
    }
    approved = {
        r[0]
        for r in q(
            "SELECT rule_ref FROM rule_label WHERE source = 'requirement' AND state = 'ai_approved'"
        )
    }
    named, resolved = q(
        "SELECT COUNT(*), COALESCE(SUM(requirement_id IN (SELECT id FROM standard_requirements)), 0)"
        " FROM review_findings WHERE standard_document_id = ?",
        (doc,),
    ).fetchone()
    out = {
        "rules_total": len(rows),
        "rules_current": len(current),
        "rules_superseded": len(rows) - len(current),
        "current_labelled": sum(1 for r in current if r[0] in labelled),
        "current_ai_approved": sum(1 for r in current if r[0] in approved),
        "findings_naming_the_book": named,
        "findings_orphaned": named - resolved,
        "current_by_range": {
            k: sum(1 for r in current if r[1] and re.match(p, r[1]))
            for k, p in RANGES.items()
        },
        "current_no_clause": sum(1 for r in current if not r[1]),
        "chunks": q(
            "SELECT COUNT(*) FROM chunks WHERE document_id = ?", (doc,)
        ).fetchone()[0],
        "crs": {},
    }
    for paper in papers:
        try:
            got = crs_completeness.checked_files(paper, access.unrestricted_scope())
            team, contractor = got["team"][1], got["contractor"][1]
            out["crs"][paper] = {
                "page": team["page"],
                "database": team["database"]["total"],
                "team_rows": team["rows_in_file"],
                "contractor_rows": contractor["rows_in_file"],
                "agree": bool(team["ok"] and contractor["ok"]),
            }
            out.setdefault("crs_cells", {})[paper] = {
                copy: cell_hashes(got[copy][0]) for copy in ("team", "contractor")
            }
        except Exception as exc:  # noqa: BLE001 - a paper the database cannot build is reported, not hidden
            out["crs"][paper] = {"error": type(exc).__name__}
    return out


_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def cell_hashes(workbook: bytes) -> dict:
    """{sheet: {"<row>|<column header>": short hash of the cell}} of one CRS file: hashes only, never the text. A cell
    that holds a date-time (the file's own made-at stamp) is left out: it differs at every build."""
    import hashlib
    import io

    import openpyxl

    out: dict[str, dict[str, str]] = {}
    wb = openpyxl.load_workbook(io.BytesIO(workbook), read_only=True)
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        # the header is the first row with three or more text cells (the sheet's title lines come before it)
        at = next(
            (
                i
                for i, row in enumerate(rows)
                if sum(isinstance(v, str) and v.strip() != "" for v in row) >= 3
            ),
            0,
        )
        header = (
            [str(h or f"col{i + 1}") for i, h in enumerate(rows[at])] if rows else []
        )
        cells: dict[str, str] = {}
        for r, row in enumerate(rows[at + 1 :], start=at + 2):
            for c, value in enumerate(row):
                text = "" if value is None else str(value)
                if _STAMP.match(text):
                    continue
                name = header[c] if c < len(header) else f"col{c + 1}"
                cells[f"{r}|{name}"] = hashlib.sha256(text.encode()).hexdigest()[:12]
        out[ws.title] = cells
    return out


def cell_changes(before: dict, after: dict) -> dict:
    """Per paper and copy: the sheets, rows and column headers whose cells changed (no text)."""
    out: dict = {}
    for paper, copies in before.items():
        for copy, sheets in copies.items():
            now = (after.get(paper) or {}).get(copy) or {}
            for sheet, cells in sheets.items():
                new = now.get(sheet) or {}
                changed = sorted(
                    k for k in set(cells) | set(new) if cells.get(k) != new.get(k)
                )
                if changed:
                    rows = sorted({int(k.split("|", 1)[0]) for k in changed})
                    cols: dict[str, int] = {}
                    for k in changed:
                        col = k.split("|", 1)[1]
                        cols[col] = cols.get(col, 0) + 1
                    out.setdefault(paper, {}).setdefault(copy, {})[sheet] = {
                        "rows_changed": len(rows),
                        "rows": rows[:50],
                        "cells_by_column": cols,
                    }
    return out


def backup(db: Path, live: bool, reason: str) -> dict:
    from app import live_guard

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    if live:
        clearance = live_guard.prepare_live_write(db, reason=reason)
        raw_dir = Path(clearance.backup_path).parent / f"raw-{stamp}"
        raw_dir.mkdir(parents=True, exist_ok=False)
        raw = [
            str(shutil.copy2(f, raw_dir))
            for f in (db, Path(f"{db}-wal"), Path(f"{db}-shm"))
            if f.exists()
        ]
        return {
            "backup": clearance.backup_path,
            "verified": "integrity ok, tables compared "
            f"{clearance.tables_compared}, restore drill ok",
            "raw_files": raw,
            "manifest": clearance.manifest_path,
        }
    tool = live_guard._backup_tool()
    target = db.parent / f"{db.stem}-backup-{stamp}"
    target.mkdir(parents=False, exist_ok=False)
    path = tool.backup(str(db), str(target))
    report = tool.verify(path)
    if not report.get("ok"):
        raise NoGo(f"backup failed integrity_check: {report.get('integrity')}")
    return {
        "backup": path,
        "verified": f"integrity {report.get('integrity')}, {len(report['tables'])} tables",
    }


def main(argv: list[str] | None = None) -> int:
    restore = _block_network()
    try:
        return _main(argv)
    finally:
        restore()


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--doc", required=True, help="the rule book's document id")
    ap.add_argument(
        "--paper",
        action="append",
        help="a paper whose CRS counts must not change (default: valve, pump, vessel)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="checks and BEFORE counts only; writes nothing",
    )
    ap.add_argument(
        "--owner-yes",
        help="required for a live database: who said yes, when, where it is recorded",
    )
    ap.add_argument("--report", help="write the whole report as JSON here")
    args = ap.parse_args(argv)
    from app import live_guard
    from app.config import settings

    db = Path(args.db).resolve()
    live = live_guard.is_live_shaped(db)
    papers = list(args.paper or DEFAULT_PAPERS)
    report: dict = {
        "db": db.name,
        "live": live,
        "doc": args.doc,
        "dry_run": args.dry_run,
        "started": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _print(
        f"database {db.name} ({'LIVE' if live else 'a copy'}), book {args.doc}, {'DRY RUN' if args.dry_run else 'APPLY'}"
    )
    if live and not args.dry_run and not (args.owner_yes or "").strip():
        _print(
            "REFUSED: a live database is written only with --owner-yes (the owner's yes and a verified backup)"
        )
        return 3
    checks = go_no_go(db, args.doc, live and not args.dry_run, args.owner_yes)
    report["go_no_go"] = [{"check": c, "ok": ok, "detail": d} for c, ok, d in checks]
    for c, ok, d in checks:
        _print(f"  {'GO   ' if ok else 'NO-GO'} {c}: {d}")
    if not all(ok for _c, ok, _d in checks):
        _print("NO-GO: nothing was written")
        return 2
    settings.data_dir, settings.db_path = db.parent, db
    settings.startup_warmup = False
    if args.dry_run:
        import sqlite3

        if live:  # the CRS builders open the app's own connection, which refuses a live file: read a temporary copy
            from app import live_guard as guard

            copy = guard.diagnostic_copy(db)
            settings.data_dir, settings.db_path = copy.parent, copy
            _print(
                f"DRY RUN on a live database: counts read from a temporary copy {copy} (backup API, read only); "
                "remove it afterwards"
            )
            db_read = copy
        else:
            db_read = db
        conn = sqlite3.connect(f"{db_read.as_uri()}?mode=ro", uri=True)
        report["before"] = counts(conn, args.doc, papers)
        cells_before = report["before"].pop("crs_cells", {})
        _print("BEFORE " + json.dumps(report["before"]))
        _print("DRY RUN: nothing was written")
        _write(args.report, report)
        return 0
    timing: dict[str, float] = {}
    t = time.monotonic()
    report["backup"] = backup(
        db,
        live,
        f"reextract_book {args.doc}: chunker 12 + label carry ({args.owner_yes or 'copy'})",
    )
    timing["backup_s"] = round(time.monotonic() - t, 1)
    _print(f"BACKUP {json.dumps(report['backup'])}")
    from app.db import connect

    conn = connect()
    report["before"] = counts(conn, args.doc, papers)
    cells_before = report["before"].pop("crs_cells", {})
    _print("BEFORE " + json.dumps(report["before"]))
    allowed = frozenset(r[0] for r in conn.execute("SELECT id FROM documents"))
    way_back = [
        "stop the server",
        f"cp '{report['backup']['backup']}' '{db}'",
        f"rm -f '{db}-wal' '{db}-shm'",
        "start the server",
    ]
    try:
        return _steps(args, report, papers, allowed, timing, cells_before, way_back)
    except Exception as exc:  # noqa: BLE001 - a step that fails halfway still shows the way back, and the report is kept
        report["failed"] = (
            f"{type(exc).__name__} during the steps; part of the change may be written"
        )
        report["restore"] = way_back
        _print(f"FAILED HALFWAY: {report['failed']}")
        _print("WAY BACK (do it now): " + " ; ".join(way_back))
        _write(args.report, report)
        return 1


def _steps(args, report, papers, allowed, timing, cells_before, way_back) -> int:
    from app import chunker, standards
    from app.db import connect

    t = time.monotonic()
    chunked = chunker.chunk_document(
        args.doc, force=True, acknowledge_orphaned_findings=True
    )
    timing["rechunk_s"] = round(time.monotonic() - t, 1)
    t = time.monotonic()
    extracted = standards.extract_requirements(
        args.doc,
        allowed_document_ids=allowed,
        replace=True,
        acknowledge_orphaned_findings=True,
    )
    tables = standards.extract_table_values(args.doc, allowed_document_ids=allowed)
    timing["reextract_s"] = round(time.monotonic() - t, 1)
    report["steps"] = {
        "rechunk": {
            k: chunked.get(k)
            for k in ("chunks", "chunks_retrievable", "tables_kept_whole")
        },
        "reextract": {
            k: v
            for k, v in extracted.items()
            if not isinstance(v, (list, dict)) or k == "labels_carried"
        },
        "table_values": {
            k: v for k, v in tables.items() if not isinstance(v, (list, dict))
        },
        "timing": timing,
    }
    _print("STEPS " + json.dumps(report["steps"]))
    report["after"] = counts(connect(), args.doc, papers)
    cells_after = report["after"].pop("crs_cells", {})
    _print("AFTER  " + json.dumps(report["after"]))
    problems = []
    if report["after"]["findings_orphaned"]:
        problems.append(
            f"{report['after']['findings_orphaned']} findings no longer resolve their rule"
        )
    for paper, before in report["before"]["crs"].items():
        after = report["after"]["crs"].get(paper)
        if after != before:
            problems.append(f"CRS counts of {paper} changed: {before} -> {after}")
        elif not before.get("agree", False):
            problems.append(
                f"CRS counts of {paper} do not agree (before and after): {before}"
            )
    report["crs_cell_changes"] = cell_changes(cells_before, cells_after)
    for paper, copies in report["crs_cell_changes"].items():
        for copy, sheets in copies.items():
            for sheet, ch in sheets.items():
                _print(
                    f"CRS CELLS CHANGED (stored CRS reads differently; for the owner): {paper} {copy} sheet "
                    f"'{sheet}': {ch['rows_changed']} rows, cells by column {ch['cells_by_column']}"
                )
    if not report["crs_cell_changes"]:
        _print("CRS CELLS: no cell of the stored CRS files changed")
    report["problems"] = problems
    report["restore"] = way_back
    _print(
        "CHECKS "
        + (
            "all after-counts hold"
            if not problems
            else "FAILED: " + "; ".join(problems)
        )
    )
    _print("WAY BACK (only if needed): " + " ; ".join(report["restore"]))
    _write(args.report, report)
    return 1 if problems else 0


def _write(path: str | None, report: dict) -> None:
    if path:
        Path(path).write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
