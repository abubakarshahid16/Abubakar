#!/usr/bin/env python3
"""Judge system A's CRS rows with the agent, on a COPY of the database (#1690, part of #805).

    AGENT_REVIEW_ENABLED=1 python scripts/run_agent_judge.py --a-xlsx A.xlsx --db-copy COPY.sqlite --document DOC_ID \\
        --provider claude --documents DOC_ID,STD_ID --second-opinion local --local-model TAG --rows 1-5 --dry-run

Each row of A's workbook is a claim; the agent records CONFIRM, REMOVE (with a closed reason and code-verified evidence)
or UNSURE. A REMOVE also needs the local second opinion, else the row stays. The input workbook is never changed; the
judged workbook, decisions.json and RESULTS.md go to the local run directory. Refuses to run unless AGENT_REVIEW_ENABLED
is set in the PROCESS environment; refuses the live database; for provider claude the configured DB_PATH must be the copy.
`--dry-run` calls no model. `--rows` (ids or ranges) and `--limit N` make a small cost check; the cost projector prints
after the first rows, and `--budget-usd` stops the run (resumable) when the projection passes it.
Exit codes: 0 done, 2 refused or failed to start, 3 stopped (resumable), 75 busy.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_agent_review import (
    LEAD_MODEL,
    _editions,
    _ids,
    make_second_opinion,
)

from app import (
    agent_judge,
    agent_judge_rows,
    agent_run,
    agent_trace,
    heavy_lock,
)


class SmokeJudge:
    """`--provider fake`: every row ends UNSURE. Proves the plumbing; says nothing about quality."""

    def complete(self, _messages: list[dict], _tool_specs: list[dict]) -> dict:
        return {
            "tool": "judge_row",
            "args": {
                "decision": "UNSURE",
                "reason": "smoke run with the fake provider",
            },
            "reason": "smoke",
            "usd": 0.0,
            "model": "fake",
        }


def make_judge_provider(kind: str, budget: float | None = None):
    """The lead provider, built ONCE per run. A missing module or a wrong constructor fails loudly (no fallback)."""
    if kind == "fake":
        return SmokeJudge()
    try:
        from app.agent_claude import ClaudeProvider
    except ImportError as exc:
        raise SystemExit(
            f"provider 'claude' is not built yet: app.agent_claude is missing ({type(exc).__name__})"
        ) from None
    # with a budget the provider's OWN meter stops the run (AgentBudgetStop, resumable) the moment it would be passed
    return ClaudeProvider(
        model=LEAD_MODEL, system=agent_judge.JUDGE_SYSTEM, total_cap_usd=budget
    )


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--a-xlsx", required=True, help="system A's CRS workbook (read only)"
    )
    ap.add_argument(
        "--db-copy", required=True, help="a COPY of the database (never the live file)"
    )
    ap.add_argument("--document", required=True, help="document id the rows are about")
    ap.add_argument("--provider", choices=("fake", "claude"), required=True)
    ap.add_argument(
        "--documents",
        default=None,
        help="Claude runs only: comma-separated ids the run may carry",
    )
    ap.add_argument("--rows", default=None, help="row ids or ranges, e.g. 1-5,9")
    ap.add_argument(
        "--limit", type=int, default=None, help="only the first N selected rows"
    )
    ap.add_argument(
        "--second-opinion",
        choices=("none", "local"),
        default="none",
        help="local: the local Qwen model (never Claude)",
    )
    ap.add_argument(
        "--local-model", default=None, help="model tag for --second-opinion local"
    )
    ap.add_argument(
        "--editions", default=None, help="local JSON file: standard -> contract edition"
    )
    ap.add_argument(
        "--run-dir",
        default=None,
        help="local run directory (outside the git work tree)",
    )
    ap.add_argument(
        "--budget-usd",
        type=float,
        default=None,
        help="stop (resumable) when the projected cost passes this",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="list the rows and the bounds; call no model",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None, env: dict | None = None, out=print) -> int:
    args = parse(argv)
    if not agent_run.enabled(env):
        out(
            f"refused: {agent_run.ENABLE_ENV} is not set in the process environment (it is off by default)"
        )
        return 2
    try:
        return _run(args, out)
    except heavy_lock.HeavyJobBusy as exc:
        out(f"BUSY: {exc}")
        return heavy_lock.EXIT_BUSY
    except (
        agent_run.LiveDatabaseRefused,
        agent_run.DocumentsNotDeclared,
        agent_run.DbPathMismatch,
        agent_trace.UnsafeRoot,
        agent_judge_rows.WorkbookLayout,
    ) as exc:
        out(f"refused: {exc}")
    except (LookupError, FileNotFoundError, SystemExit, ValueError) as exc:
        out(f"cannot start: {exc}")
    return 2


def _dry_run(args: argparse.Namespace, rows: list[dict], out) -> int:
    conn = agent_run.open_readonly(args.db_copy)  # refuses the live file even here
    try:
        edition_map = _editions(args.editions)
        if edition_map is None and args.run_dir:
            edition_map = agent_run.load_editions(Path(args.run_dir).expanduser(), None)
        allowed, held, missing = agent_run.build_scope(
            conn, args.document, edition_map or {}
        )
    finally:
        conn.close()
    claude = args.provider == "claude"
    plan = agent_run.plan(
        [{"id": r["id"]} for r in rows],
        total_cap=agent_run.USD_CAP_TOTAL if claude else None,
    )
    if claude:
        declared = agent_run.declared_documents(
            allowed, args.document, _ids(args.documents)
        )
        out(
            f"documents that WOULD be declared to Claude: {', '.join(sorted(declared))}"
        )
    out(f"DRY RUN: {len(rows)} rows to judge")
    out(
        f"documents in scope: {len(allowed)} (standards held: {len(held)}, named but not held: {len(missing)})"
    )
    out(
        f"at most {plan['max_steps']} steps and USD {plan['max_usd']:.2f} ({plan['note']})"
    )
    out("rows: " + ", ".join(plan["items"]))
    out("no model was called")
    return 0


def _run(args: argparse.Namespace, out) -> int:
    a_rows = agent_judge_rows.read_rows(args.a_xlsx)
    want = agent_judge_rows.parse_row_ids(args.rows, len(a_rows))
    rows = [r for r in a_rows if want is None or r["id"] in want][
        : args.limit if args.limit and args.limit > 0 else None
    ]
    if args.second_opinion == "local" and not args.local_model:
        raise SystemExit("--second-opinion local needs --local-model (the model tag)")
    if args.provider == "claude":
        agent_run.check_db_path(
            args.db_copy
        )  # refuses before any model call (and in a dry run)
        out("database path check: DB_PATH is the copy")
    if args.dry_run:
        return _dry_run(args, rows, out)
    provider = make_judge_provider(args.provider, args.budget_usd)
    opinion = (
        make_second_opinion(args.local_model)
        if args.second_opinion == "local"
        else None
    )
    summary = agent_judge.run_judge(
        args.a_xlsx,
        args.db_copy,
        args.document,
        provider,
        second_opinion=opinion,
        rows=args.rows,
        limit=args.limit,
        run_dir=args.run_dir,
        editions=_editions(args.editions),
        claude=args.provider == "claude",
        documents=_ids(args.documents),
        budget_usd=args.budget_usd,
        on_status=lambda trace: out(agent_run.status_box(trace)),
        say=out,
    )
    out(summary["status_box"])
    out(
        f"results are in {summary['run_dir']} (RESULTS.md, decisions.json, judged.xlsx)"
    )
    return 0 if not summary["stopped"] else 3


if __name__ == "__main__":
    raise SystemExit(main(env=None))
