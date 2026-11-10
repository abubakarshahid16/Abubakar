#!/usr/bin/env python
"""Run the rule finishing line (steps a, b, c, d, g) for one rule or one whole standard, on a COPY of the database.

    python scripts/rule_finish_run.py --standard SAES-J-600.pdf
    python scripts/rule_finish_run.py --rule-key 1fbd6002

Reads the compile database READ ONLY (`--source`, default the compile copy) and the standard's page text READ ONLY
(`--pages-db`, default the private agent copy). It writes only: the steps into `--work-db` (a copy of the source, made
on first use; refused if it is the source or the pages database), one journey JSON per rule, one JSON log line per rule.
Nothing from a standard is written to a journey or a log: cues, offsets, hashes, counts and ids only.

Exit code 0 only when no rule raised an error. An error is printed in red and counted; it is never swallowed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import rule_finish as rf  # noqa: E402
from app import rule_finish_guard as guard  # noqa: E402
from app import rule_finish_record as record  # noqa: E402
from app import rule_finish_store as st  # noqa: E402

HOME = Path.home()
DEFAULT_SOURCE = HOME / "project/mirror/proof/db/compile/psv-all.sqlite"
DEFAULT_WORK = HOME / "project/mirror/proof/db/compile/lane1-work.sqlite"
DEFAULT_PAGES = HOME / "project/mirror/proof/agent-test/db/agent-copy.sqlite"
DEFAULT_TRACE = HOME / "project/mirror/trace"
PKT = ZoneInfo("Asia/Karachi")
RED, RESET = "\033[31m", "\033[0m"
LANE = "1"
RUN_ID = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def write_private(path: Path, text: str) -> None:
    """A local file only the owner reads (journeys and logs hold numbers of a standard): mode 0600, even over an old file."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    path.chmod(0o600)


def open_private(path: Path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    path.chmod(0o600)
    return os.fdopen(fd, "a", encoding="utf-8")


def pkt_now() -> str:
    return datetime.now(PKT).strftime("%Y-%m-%d %H:%M:%S PKT")


def open_ro(path: Path) -> sqlite3.Connection:
    conn = guard.open_read_only(path)
    conn.row_factory = sqlite3.Row
    return conn


def prepare_work_db(source: Path, pages: Path, work: Path) -> Path:
    """The marked copy the steps are written to. A new copy is made and marked; an existing file that is a verified copy of
    the source and has no marker yet is marked once (adopted); anything else, and every protected database (the source,
    the pages copy, the app's and the live one), is refused."""
    try:
        guard.refuse_live(work)  # before anything opens it, even read only
        if work.exists() and not guard.is_marked(work):
            return guard.adopt_copy(source, work, [pages])
        return guard.prepare_work_copy(source, work, [pages])
    except guard.NotAWorkCopy as exc:
        raise SystemExit(str(exc)) from exc


def write_journey(
    trace: Path,
    rule: dict,
    steps: dict,
    saved: dict,
    run_id: str,
    current: dict | None = None,
) -> Path:
    out_dir = trace / "rules"
    out_dir.mkdir(parents=True, exist_ok=True)
    at = pkt_now()
    journey_steps = {}
    for name in rf.STEPS:
        if name in steps:
            result, reason, evidence = steps[name]
            journey_steps[name] = {
                "result": result,
                "reason": reason,
                "evidence": evidence,
                "at": at,
            }
        elif name in saved:  # e and f are written by their own processes
            row = saved[name]
            journey_steps[name] = {
                "result": row["result"],
                "reason": row["reason"],
                "evidence": row["evidence"],
                "at": row["at"],
                "checker": row["checker"],
            }
    flat = {n: v["result"] for n, v in journey_steps.items()}
    flat.update(
        {n: r for n, r in (current or {}).items() if n in ("e", "f")}
    )  # a stale e or f never counts
    for n in ("e", "f"):
        if flat.get(n) == record.STALE and n in journey_steps:
            journey_steps[n]["result"] = record.STALE
    status = rf.finish_status(flat)
    journey = {
        "rule_id": rule["rule_id"],
        "rule_key": rule["rule_key"],
        "rule_version_id": rule["version_id"],
        "standard": rule["standard"],
        "clause": rule.get("clause"),
        "page": rule.get("page"),
        "run_id": run_id,
        "steps": journey_steps,
        "may_decide": rf.may_decide(flat),
        "finish_status": status.status,
        "blocking_step": status.blocking,
    }
    path = out_dir / f"{rule['rule_key']}.json"
    write_private(path, json.dumps(journey, indent=2, sort_keys=True, default=str))
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--standard", help="rulebook_rule.standard, e.g. SAES-J-600.pdf"
    )
    target.add_argument("--rule-key", help="a rule_key or its prefix")
    ap.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="compile DB, opened read only",
    )
    ap.add_argument(
        "--work-db",
        type=Path,
        default=DEFAULT_WORK,
        help="the COPY the steps are written to",
    )
    ap.add_argument(
        "--pages-db",
        type=Path,
        default=DEFAULT_PAGES,
        help="DB with the standard's pages, read only",
    )
    ap.add_argument("--trace-dir", type=Path, default=DEFAULT_TRACE)
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args(argv)
    if not args.trace_dir.resolve().is_relative_to(DEFAULT_TRACE.resolve()):
        raise SystemExit(f"refused: --trace-dir must be inside {DEFAULT_TRACE}")
    guard.register_protected(args.source)
    guard.register_protected(args.pages_db)

    run_id = args.run_id or datetime.now(PKT).strftime("rf-%Y%m%d-%H%M%S")
    if not RUN_ID.fullmatch(run_id) or run_id.strip(".") == "":
        raise SystemExit(
            "refused: --run-id must be 1 to 64 characters of letters, digits, _ . - (no separators)"
        )
    work = prepare_work_db(args.source, args.pages_db, args.work_db)
    source = open_ro(args.source)
    rules = st.load_rules(source, standard=args.standard, key_prefix=args.rule_key)
    if not rules:
        print(
            f"{RED}no rule found for {args.standard or args.rule_key}{RESET}",
            file=sys.stderr,
        )
        return 2
    log_dir = args.trace_dir / "logs" / "lane1"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{run_id}.jsonl"
    work_conn = guard.open_work_copy(work, [args.source, args.pages_db])
    st.ensure_table(work_conn)

    counts: dict[str, Counter] = {s: Counter() for s in rf.CODE_STEPS}
    errors: list[str] = []
    done = 0
    with open_private(log_path) as log:
        for rule in rules:
            done += 1
            short = rule["rule_key"][:8]
            try:
                rule = st.overlay_applied(work_conn, rule)
                steps = {}
                for name in rf.CODE_STEPS:  # each step is recomputed and written by the store; nothing is handed in
                    steps[name] = record.record_code_step(
                        work_conn,
                        rule["version_id"],
                        name,
                        run_id=run_id,
                        pages_db=args.pages_db,
                    )
                    counts[name][steps[name][0]] += 1
                saved = st.latest_steps(work_conn, rule["version_id"])
                path = write_journey(
                    args.trace_dir,
                    rule,
                    steps,
                    saved,
                    run_id,
                    record.current_steps(work_conn, rule["version_id"]),
                )
                results = {n: r[0] for n, r in steps.items()}
                bad = [n for n, r in results.items() if r == rf.FAIL]
                worst = (
                    rf.FAIL
                    if bad
                    else (
                        rf.INCOMPLETE if rf.INCOMPLETE in results.values() else rf.PASS
                    )
                )
                reason = (
                    "; ".join(
                        f"{n}:{steps[n][1]}"
                        for n in rf.CODE_STEPS
                        if results[n] in (rf.FAIL, rf.INCOMPLETE)
                    )
                    or "all steps pass or not applicable"
                )
                line = {
                    "pkt_time": pkt_now(),
                    "lane": LANE,
                    "step": "a,b,c,d,g",
                    "rule_id": rule["rule_key"],
                    "model": rf.MODEL_NONE,
                    "result": worst,
                    "reason": reason,
                    "steps": results,
                    "counts_so_far": {s: dict(c) for s, c in counts.items()},
                    "rules_done": done,
                    "spend_usd": 0,
                    "journey": str(path),
                }
            except Exception as exc:  # noqa: BLE001 - never swallowed: printed, logged, counted, and the run exits non-zero
                errors.append(f"{rule['rule_key'][:8]}: {type(exc).__name__}: {exc}")
                line = {
                    "pkt_time": pkt_now(),
                    "lane": LANE,
                    "step": "a,b,c,d,g",
                    "rule_id": rule["rule_key"],
                    "model": rf.MODEL_NONE,
                    "result": "error",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "counts_so_far": {s: dict(c) for s, c in counts.items()},
                    "rules_done": done,
                    "spend_usd": 0,
                }
            log.write(json.dumps(line, sort_keys=True, default=str) + "\n")
            text = f"{line['pkt_time']} | lane {LANE} | {line['step']} | {short} | model {rf.MODEL_NONE} | {line['result']} | {line['reason']} | done {done}/{len(rules)} | spend 0"
            red = line["result"] in ("fail", "error")
            print(f"{RED}{text}{RESET}" if red else text)
    work_conn.close()

    print(f"run {run_id}: {len(rules)} rules; log {log_path}")
    for name in rf.CODE_STEPS:
        print(
            f"  step {name} {rf.STEP_NAMES[name]}: "
            + ", ".join(f"{r}={counts[name][r]}" for r in rf.RESULTS)
        )
    if errors:
        print(f"{RED}Problems: {len(errors)} rule(s) raised an error{RESET}")
        for e in errors:
            print(f"{RED}  {e}{RESET}")
        return 1
    print("Problems: none (no rule raised an error)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
