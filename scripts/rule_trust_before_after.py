"""rule_trust (#947) before/after, COUNTS ONLY, on a COPY of a database.

SPEED RULE 3 (planner, 14 Oct): a review-changing PR proves itself on PF1
counts-only - no model, no lock, both arms on the same facts. This re-runs
the comparison of each completed, undecided review run in the copy twice:
switch `rule_auto_use_enabled` OFF, then ON; and prints, per run, the
findings by status and the rule-trust counts (labels, verdicts held because
the rule is unproven, safety ticks, fields no rule checked). OFF must equal
the run's stored counts; that is the "no change with the switch off" proof.

    python scripts/rule_trust_before_after.py --db D:\\pf1-copy\\copy.sqlite [--run <id> ...] [--out result.json]

REFUSES the live database (`live_guard.is_live_shaped`): make a copy first
(`live_guard.diagnostic_copy`, or copy the .sqlite, -wal and -shm files with
the server stopped). The copy IS written (each arm replaces the run's
unconfirmed findings); delete it when done. A run with an engineer's final
code is skipped (a decided run is never re-run). Every model tier is OFF so
nothing waits on Ollama and both arms see the same facts. Output: ids and
counts only - never a field name, a value or a document name.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

MODEL_TIERS_OFF = ("match_enabled", "ai_clause_checks_enabled", "geometry_reader_enabled",
                   "ai_applicability_enabled", "rule_auto_use_enabled")
COUNTS = ("fields_read", "held_unproven", "safety_ticks", "auto_proven")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--db", required=True, help="a COPY of the database, never the live file")
    parser.add_argument("--run", action="append", default=[], help="review run id (default: every completed, undecided run)")
    parser.add_argument("--out", help="write the JSON result here as well")
    args = parser.parse_args(argv)

    from app import comparison, db, live_guard
    from app.config import settings

    path = Path(args.db).resolve()
    if live_guard.is_live_shaped(path):
        print(f"REFUSED: {path.name} is the live database; run this on a copy")
        return 2
    if not path.exists():
        print(f"REFUSED: {path} does not exist")
        return 2
    settings.db_path = path
    settings.data_dir = path.parent
    for name in MODEL_TIERS_OFF:
        setattr(settings, name, False)
    db.reset_connection()
    conn = db.connect()
    allowed = frozenset(r["id"] for r in conn.execute("SELECT id FROM documents"))
    runs = [dict(r) for r in conn.execute(
        "SELECT id, engineer_final_code FROM review_runs WHERE status = 'completed' ORDER BY created_at")]
    wanted = set(args.run)
    result = {"db": path.name, "runs": [], "skipped_decided": 0}
    for run in runs:
        if wanted and run["id"] not in wanted:
            continue
        if run["engineer_final_code"]:
            result["skipped_decided"] += 1
            continue
        arms = {}
        for arm, on in (("before_off", False), ("after_on", True)):
            settings.rule_auto_use_enabled = on
            out = comparison.run_comparison(run["id"], allowed_document_ids=allowed)
            trust = out.get("rule_trust") or {}
            arms[arm] = {
                "by_status": out["by_status"],
                "findings": len(out["findings"]),
                "rule_trust": ({**{k: trust.get(k) for k in COUNTS},
                                "labels": trust.get("labels"),
                                "uncovered_fields": len(trust.get("uncovered_fields") or []),
                                "audit_sample": len(trust.get("audit_sample") or [])}
                               if trust else None),
            }
        result["runs"].append({"review_run_id": run["id"], **arms})
    settings.rule_auto_use_enabled = False
    text = json.dumps(result, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
