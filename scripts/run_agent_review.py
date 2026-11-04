#!/usr/bin/env python3
"""Run the agent proof test on a COPY of the database (#1690, part of #805).

    AGENT_REVIEW_ENABLED=1 python scripts/run_agent_review.py --db-copy COPY.sqlite --document DOC_ID \\
        --skill datasheet --provider fake --dry-run

Refuses to run unless AGENT_REVIEW_ENABLED is set in the PROCESS environment (never read from .env). Refuses the live
database. `--dry-run` loads everything and lists the items and the upper bounds on steps and cost; it calls no model.
The STATUS box is printed at the end and every 10 items. Exit codes: 0 done, 2 refused or failed to start, 75 busy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import agent_run, agent_trace, heavy_lock

LEAD_MODEL = "claude-sonnet-5-5"


class SmokeProvider:
    """`--provider fake`: every item ends in a YELLOW ask. Proves the plumbing; says nothing about quality."""

    def complete(self, _messages: list[dict], _tool_specs: list[dict]) -> dict:
        return {
            "final": {
                "color": "YELLOW",
                "action": "ask the engineer",
                "priority": "should",
                "reason": "smoke run with the fake provider",
            },
            "usd": 0.0,
            "model": "fake",
        }


def make_provider(kind: str):
    """The lead provider for `kind`, built ONCE per run. The real ones are imported lazily; a missing module or a
    wrong constructor fails loudly (no fallback)."""
    if kind == "fake":
        return SmokeProvider()
    module, cls = {
        "claude": ("agent_claude", "ClaudeProvider"),
        "local": ("agent_local", "LocalProvider"),
    }[kind]
    try:
        mod = __import__(f"app.{module}", fromlist=[cls])
        klass = getattr(mod, cls)
    except (ImportError, AttributeError) as exc:
        raise SystemExit(
            f"provider '{kind}' is not available: app.{module}.{cls} is missing ({type(exc).__name__})"
        ) from None
    return klass(model=LEAD_MODEL) if kind == "claude" else klass()


def load_skill(value: str) -> tuple[str, dict | None]:
    """`--skill`: a kind for `agent_skills.load_skill`, or a path to a local .json skill file."""
    path = Path(value).expanduser()
    if value.endswith(".json") and path.is_file():
        skill = json.loads(path.read_text(encoding="utf-8"))
        return str(skill.get("kind") or path.stem), skill
    return value, None


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--db-copy", required=True, help="a COPY of the database (never the live file)"
    )
    ap.add_argument("--document", required=True, help="document id to review")
    ap.add_argument(
        "--skill", required=True, help="skill kind, or a local skill .json file"
    )
    ap.add_argument("--provider", choices=("fake", "claude", "local"), required=True)
    ap.add_argument("--limit", type=int, default=None, help="only the first N items")
    ap.add_argument("--items", default=None, help="comma-separated skill item ids")
    ap.add_argument("--second-opinion", choices=("none", "claude"), default="none")
    ap.add_argument(
        "--run-dir",
        default=None,
        help="local run directory (outside the git work tree)",
    )
    ap.add_argument(
        "--documents",
        default=None,
        help="Claude runs only: comma-separated ids the run may carry (no default 'all')",
    )
    ap.add_argument(
        "--editions", default=None, help="local JSON file: standard -> contract edition"
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="list the items and the bounds; call no model",
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
    except (
        agent_run.LiveDatabaseRefused,
        agent_run.SkillMissing,
        agent_run.DocumentsNotDeclared,
        agent_trace.UnsafeRoot,
    ) as exc:
        out(f"refused: {exc}")
    except (LookupError, FileNotFoundError, SystemExit) as exc:
        out(f"cannot start: {exc}")
    return 2


def _ids(value: str | None) -> list[str]:
    return [d.strip() for d in (value or "").split(",") if d.strip()]


def _editions(path: str | None) -> dict | None:
    return (
        json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        if path
        else None
    )


def _run(args: argparse.Namespace, out) -> int:
    kind, given = load_skill(args.skill)
    skill = agent_run.get_skill(kind, given)
    ids = [s for s in args.items.split(",") if s] if args.items else None
    chosen = agent_run.select_items(skill, ids, args.limit)
    if args.second_opinion == "claude" and args.provider != "claude":
        raise SystemExit(
            "--second-opinion claude needs --provider claude (one shared meter)"
        )
    if args.dry_run:
        conn = agent_run.open_readonly(args.db_copy)  # refuses the live file even here
        try:
            edition_map = _editions(args.editions)
            if edition_map is None and args.run_dir:
                edition_map = agent_run.load_editions(
                    Path(args.run_dir).expanduser(), None
                )
            allowed, held, missing = agent_run.build_scope(
                conn,
                args.document,
                agent_run.load_editions(Path(), edition_map or {}),
            )
        finally:
            conn.close()
        claude = "claude" in (args.provider, args.second_opinion)
        report = agent_run.plan(
            chosen, total_cap=agent_run.USD_CAP_TOTAL if claude else None
        )
        if claude:
            declared = agent_run.declared_documents(
                allowed, args.document, _ids(args.documents)
            )
            out(
                f"documents that WOULD be declared to Claude: {', '.join(sorted(declared))}"
            )
        out(
            f"DRY RUN: skill {skill.get('kind')} v{skill.get('version')}, {report['item_count']} items"
        )
        out(
            f"documents in scope: {len(allowed)} (standards held: {len(held)}, named but not held: {len(missing)})"
        )
        out(
            f"at most {report['max_steps']} steps and USD {report['max_usd']:.2f} ({report['note']})"
        )
        out("items: " + ", ".join(report["items"]))
        out("no model was called")
        return 0
    provider = make_provider(args.provider)
    # the second opinion is the SAME provider object's second_opinion(): a different model, one shared meter
    opinion = provider if args.second_opinion == "claude" else None

    def status(trace: agent_trace.TraceWriter) -> None:
        out(agent_run.status_box(trace))

    try:
        summary = agent_run.run_review(
            args.db_copy,
            args.document,
            kind,
            provider,
            second_opinion=opinion,
            items=ids,
            limit=args.limit,
            run_dir=args.run_dir,
            skill=skill,
            editions=_editions(args.editions),
            local=args.provider == "local",
            claude="claude" in (args.provider, args.second_opinion),
            documents=_ids(args.documents),
            on_status=status,
        )
    except heavy_lock.HeavyJobBusy as exc:
        out(f"BUSY: {exc}")
        return heavy_lock.EXIT_BUSY
    out(summary["status_box"])
    out(f"results are in {summary['run_dir']} (RESULTS.md, EXAMPLES.md, crs.xlsx)")
    return 0 if not summary["stopped"] else 3


if __name__ == "__main__":
    raise SystemExit(main(env=None))
