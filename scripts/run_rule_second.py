#!/usr/bin/env python
"""The second-model approval pass over needs_human rules, its blind sample judge and the gate (planner, 25 Nov 2026, item A),
on a database COPY. Nothing is sent without an order cap (`--max-usd`, an in-process hard stop).
    AGENT_REVIEW_ENABLED=1 python scripts/run_rule_second.py estimate --db <copy> [--model M] [--limit N]
    AGENT_REVIEW_ENABLED=1 python scripts/run_rule_second.py run --db <copy> --model M --max-usd 18 [--limit N]
    AGENT_REVIEW_ENABLED=1 python scripts/run_rule_second.py sample --db <copy> [--n 200] [--seed S]
    AGENT_REVIEW_ENABLED=1 python scripts/run_rule_second.py judge --db <copy> --sample ID --model J --max-usd 3
    AGENT_REVIEW_ENABLED=1 python scripts/run_rule_second.py measure --db <copy> --sample ID
    AGENT_REVIEW_ENABLED=1 python scripts/run_rule_second.py gate --db <copy>
    AGENT_REVIEW_ENABLED=1 python scripts/run_rule_second.py export --db <copy> --out <data dir>/labels/second.json
The live app takes the file through POST /api/admin/rule-second/import (dry_run first; refused while a review runs).
Refuses a live-shaped database path. Printed lines hold counts, ids and cause words only; never a quote.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app import rule_label_job as job  # noqa: E402
from app import rule_second_approval as RS  # noqa: E402
from app.rule_label_schema import require_on  # noqa: E402

DEFAULT_MODEL = "claude-opus-5-5"


def _needs_human(conn, limit: int) -> list:
    """The needs_human requirement rules, in the label job's stable order (`--limit` the first N)."""
    ids = [
        r[0]
        for r in conn.execute(
            "SELECT rule_ref FROM rule_label WHERE state = 'needs_human' AND source = 'requirement'"
        )
    ]
    return job.select_rules(conn, ids=ids, limit=limit) if ids else []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "cmd",
        choices=("estimate", "run", "sample", "judge", "measure", "gate", "export"),
    )
    ap.add_argument("--db", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-usd", type=float, default=0.0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--n", type=int, default=RS.SAMPLE_N)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--sample")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    require_on()
    conn = job.open_copy(a.db, read_only=a.cmd in ("estimate", "gate", "export"))
    if a.cmd == "estimate":
        out = RS.estimate(_needs_human(conn, a.limit), a.model)
    elif a.cmd == "gate":
        out = RS.gate(conn)
    elif a.cmd == "export":
        data = RS.export(conn)
        Path(a.out).write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        out = {k: len(v) for k, v in data.items() if isinstance(v, list)}
    elif a.cmd in ("run", "judge"):
        if a.max_usd <= 0:
            print("refused: a paid step needs --max-usd (the order cap)")
            return 2
        lane = job.Lane(job.CapLedger(a.max_usd))
        if a.cmd == "run":
            out = RS.run_second(
                conn, _needs_human(conn, a.limit), model=a.model, lane=lane
            )
        else:
            refs = [
                r[0]
                for r in conn.execute(
                    "SELECT rule_ref FROM rule_second_sample WHERE sample_id = ?",
                    (a.sample,),
                )
            ]
            rules = {r.ref: r for r in job.select_rules(conn, ids=refs)} if refs else {}
            out = RS.judge_sample(
                conn, a.sample, judge_model=a.model, lane=lane, rules=rules
            )
    elif a.cmd == "sample":
        RS.create(conn)
        out = {"sample_id": RS.draw_sample(conn, a.n, a.seed)}
    else:
        out = RS.measure(conn, a.sample)
    print(json.dumps(out, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
