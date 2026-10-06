"""Run the P1 question set. Usage (from the repo root, models staged):

    python eval/p1/run_p1.py                    # compare with baseline.json
    python eval/p1/run_p1.py --write-baseline   # record what passes right now
    python eval/p1/run_p1.py --show             # print every question's result

Uses a throwaway database in a temp folder. Never touches the live one.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--questions", type=Path, default=harness.QUESTIONS)
    args = ap.parse_args()

    from app import access, db, keyword
    from app.config import settings

    questions = harness.load_questions(args.questions)
    problems = harness.check_labels(questions) if args.questions == harness.QUESTIONS else []
    if problems:
        print("LABEL PROBLEMS (the set is wrong, not the system):")
        for p in problems:
            print("  ", p)
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        settings.data_dir = tmp
        settings.upload_dir = tmp / "uploads"
        settings.db_path = tmp / "p1.sqlite"
        settings.auth_mode = access.AUTH_DISABLED
        db.reset_connection()
        db.init_db()
        keyword.ensure_schema()
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        harness.ingest_corpus(tmp / "corpus")
        rows = harness.run_questions(questions)
        db.reset_connection()

    summary = harness.summarise_by_category(rows)
    print(f"P1 score: {summary['total'][0]} of {summary['total'][1]}")
    print(f"  clause label right: {summary['clause_label_right'][0]} of {summary['clause_label_right'][1]}")
    for cat, (ok, n) in summary["categories"].items():
        print(f"  {cat:13} {ok} of {n}")
    if True:
        for r in rows:
            if not r["passed"]:
                print(f"  FAIL {r['id']} [{r['category']}] {r['answer_type']} "
                      f"cited {r['cited_document']} p{r['cited_pages']} "
                      f"clause {r['cited_clause']} | {r['question']}")
    if args.write_baseline:
        out = {"passing": sorted(r["id"] for r in rows if r["passed"]),
               "clause_passing": sorted(r["id"] for r in rows if r.get("clause_ok")),
               "failing_known": sorted(r["id"] for r in rows if not r["passed"]),
               "total": summary["total"]}
        harness.BASELINE.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
        print("baseline written:", out["total"])
        return 0
    reasons = harness.compare_with_baseline(rows, harness.load_baseline())
    if reasons:
        print("BLOCKED: the score dropped")
        for r in reasons:
            print("  -", r)
        return 1
    print("OK: nothing that passed in the baseline fails now")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
