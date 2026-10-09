"""Measure the AI applicability tier (#647) on review runs, on a COPY.

For each review run given, re-runs the review twice on the copy - the AI tier
OFF, then ON with the model named - and reports, as counts only:

  * the three states (checked / applies but not checked / does not apply)
    without and with the tier;
  * how many clauses the model was asked; how many "does not apply" code
    CONFIRMED (by reason); how many suggestions code could not confirm; how
    many the model was unsure about - none of these is ever dropped;
  * the model's name and the time taken.

A live-shaped database path is refused. The tier itself takes the shared
heavy-job lock (it never waits; "not run" is reported if another job holds
it) and unloads the model after each run. Ids, counts and reason codes only -
never document text.

    python scripts/measure_ai_applicability.py --db <copy.sqlite> --model qwen3.5:2b \\
        --run 26fd20bc --run d186712d --limit 200 --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))


def main(argv: list[str] | None = None) -> int:
    from app import access, comparison, db, live_guard, scope_ledger, submittal_review
    from app.config import settings

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--model", required=True)
    ap.add_argument("--run", action="append", required=True, help="review run id or prefix")
    ap.add_argument("--limit", type=int, default=200, help="clauses asked per run")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    path = args.db.resolve()
    if live_guard.is_live_shaped(path):
        raise SystemExit(f"refusing: {path} is a live database path. Measure on a copy.")
    settings.db_path = path
    settings.data_dir = path.parent / "s1_data"
    settings.data_dir.mkdir(exist_ok=True)
    settings.auth_mode = access.AUTH_DISABLED
    settings.ai_task_model = args.model
    settings.ai_applicability_max_per_run = args.limit
    db.reset_connection()
    submittal_review.ensure_schema()
    conn = db.connect()
    every = frozenset(r["id"] for r in conn.execute("SELECT id FROM documents"))
    report = {"database": path.name, "model": args.model, "limit": args.limit, "runs": []}
    for prefix in args.run:
        run = conn.execute("SELECT id FROM review_runs WHERE id LIKE ?", (prefix + "%",)).fetchone()["id"]
        out = {"run": run[:8]}
        for label, on in (("off", False), ("on", True)):
            settings.ai_applicability_enabled = on
            started = time.time()
            result = comparison.run_comparison(run, allowed_document_ids=every, replace=True)
            out[label] = {k: result["scope"][k] for k in
                          ("in_scope", scope_ledger.CHECKED, scope_ledger.APPLIES_NOT_CHECKED,
                           scope_ledger.DOES_NOT_APPLY)}
            out[label]["seconds"] = round(time.time() - started, 1)
            if on:
                stored = scope_ledger.decisions_for(run)
                ai = result.get("ai_applicability") or {}
                out["ai"] = {
                    "asked": ai.get("asked"), "not_asked": ai.get("not_asked"),
                    "not_run": ai.get("not_run"), "model": ai.get("model"),
                    "confirmed_does_not_apply_by_reason": dict(Counter(
                        d["reason_code"] for d in stored if d["decided_by"].startswith("ai:"))),
                    "unconfirmed_suggestions": sum(
                        1 for d in stored if "code could not confirm" in d["reason"]),
                    "unsure": sum(1 for d in stored if "the model was unsure" in d["reason"]),
                }
        settings.ai_applicability_enabled = False
        report["runs"].append(out)
        print(json.dumps(out), flush=True)
    if args.json:
        args.json.write_text(json.dumps(report, indent=1), encoding="utf-8")
    db.reset_connection()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
