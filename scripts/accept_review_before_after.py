"""#600 acceptance: the same review, re-run on database COPIES, side by side.

For each copy given (for example the library before and after a
re-extraction), re-runs one review run with the current code and reports, as
counts only:

  * checks: the findings the run wrote, by status, and the share needing an
    engineer WITH its denominator;
  * the three-way split (#678): checked / applies but not checked / does not
    apply, and the requirements in scope;
  * CRS rows (internal copy, the same `crs_mapping.build_crs_rows` the export
    uses), by row kind, and how many rest on a requirement the run's own scope
    ledger says does NOT apply - the done-when is 0.

A live-shaped database path is refused. No model is called (the AI tiers stay
as the settings say; the defaults are off). Ids and counts only - never
document text.

    python scripts/accept_review_before_after.py --run 26fd20bc \\
        --db before=<copy1.sqlite> --db after=<copy2.sqlite> --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

NEEDS_ENGINEER = "NEEDS_ENGINEER_REVIEW"


def summarise(findings: list[dict], rows: list[dict], decisions: dict[str, str]) -> dict:
    """Counts for one run. `decisions`: requirement id -> its stored state.
    Pure: no database."""
    status = Counter(f.get("compliance_status") or "none" for f in findings)
    total = sum(status.values())
    by_id = {f.get("id"): f for f in findings}
    kinds: Counter = Counter()
    on_not_applying = 0
    for row in rows:
        kinds[row.get("kind") or row.get("row_kind") or "row"] += 1
        finding = by_id.get(row.get("finding_id")) or {}
        if decisions.get(finding.get("requirement_id")) == "does_not_apply":
            on_not_applying += 1
    return {
        "checks": total,
        "checks_by_status": dict(status),
        "needs_engineer": {"count": status.get(NEEDS_ENGINEER, 0), "of": total},
        "crs_rows": len(rows),
        "crs_rows_by_kind": dict(kinds),
        "crs_rows_on_a_requirement_that_does_not_apply": on_not_applying,
    }


def measure(path: Path, run_prefix: str) -> dict:
    from app import (access, comparison, crs_mapping, db, live_guard, scope_ledger,
                     submittal_review)
    from app.config import settings

    path = path.resolve()
    if live_guard.is_live_shaped(path):
        raise SystemExit(f"refusing: {path} is a live database path. Measure on a copy.")
    settings.db_path = path
    settings.data_dir = path.parent / "s1_data"
    settings.data_dir.mkdir(exist_ok=True)
    settings.auth_mode = access.AUTH_DISABLED
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    conn = db.connect()
    every = frozenset(r["id"] for r in conn.execute("SELECT id FROM documents"))
    run = conn.execute("SELECT id, submittal_document_id FROM review_runs WHERE id LIKE ?",
                       (run_prefix + "%",)).fetchone()
    if run is None:
        raise SystemExit(f"no review run {run_prefix!r} in {path.name}")
    result = comparison.run_comparison(run["id"], allowed_document_ids=every, replace=True)
    findings = submittal_review.list_run_findings(run["id"], allowed_document_ids=every)
    comparison.attach_crs_context(findings)
    outcome = comparison.run_outcome(run["id"], allowed_document_ids=every) or {}
    unread = (outcome.get("page_coverage") or {}).get("pages_not_read_into_fields") or []
    rows = crs_mapping.build_crs_rows(findings, [], "submittal", unread_pages=unread)
    decisions = {d["requirement_id"]: d["state"] for d in scope_ledger.decisions_for(run["id"])}
    out = summarise(findings, rows, decisions)
    scope = result.get("scope") or {}
    out["three_way"] = {k: scope.get(k) for k in (
        "in_scope", scope_ledger.CHECKED, scope_ledger.APPLIES_NOT_CHECKED,
        scope_ledger.DOES_NOT_APPLY)}
    out["database"] = path.name
    db.reset_connection()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True, help="review run id or prefix")
    ap.add_argument("--db", action="append", required=True, metavar="LABEL=PATH",
                    help="a labelled copy; give two or more")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    report = {"run": args.run[:8], "copies": {}}
    for item in args.db:
        label, _, path = item.partition("=")
        if not path:
            raise SystemExit(f"--db wants LABEL=PATH, got {item!r}")
        report["copies"][label] = measure(Path(path), args.run)
    print(json.dumps(report, indent=1))
    if args.json:
        args.json.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
