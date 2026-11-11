#!/usr/bin/env python
"""Label rules and let two different Claude models approve them (owner decision 1, 11 Nov 2026), on a database COPY.

    AGENT_REVIEW_ENABLED=1 python scripts/run_rule_labels.py estimate --db <copy> --book <standard> [--model-a M]
    AGENT_REVIEW_ENABLED=1 python scripts/run_rule_labels.py run --pass a --db <copy> --book <standard> --max-usd 5
    AGENT_REVIEW_ENABLED=1 python scripts/run_rule_labels.py run --pass b --db <copy> --book <standard> --max-usd 5
    AGENT_REVIEW_ENABLED=1 python scripts/run_rule_labels.py report --db <copy>
    AGENT_REVIEW_ENABLED=1 python scripts/run_rule_labels.py convert-lab --lab-db <lab copy> --out <file.json>
    AGENT_REVIEW_ENABLED=1 python scripts/run_rule_labels.py convert-boxes --lab-db <lab copy> --data-dir <data dir> --out <data dir>/labels/ocr-boxes.json
    AGENT_REVIEW_ENABLED=1 python scripts/run_rule_labels.py export --db <copy> --out <file.json>

Refuses a live-shaped database path. Writes only the copy (the tables `rule_label` and `rule_label_event`). The paid pass
spends only through the app's one Claude lane (`agent_claude`, `claude_spend` caps) and an order ledger: `--max-usd N`
(an in-process hard stop) or `--ledger-spec module:Class --ledger-path FILE` (a shared one; the class takes
`(path, tool=...)` and offers `reserve`/`settle`/`run_usd`). Without one the paid pass is refused. Printed lines hold
counts, ids and cause words only; never a quote.

The label file `export` writes holds no quote text. The live app takes it through POST /api/admin/rule-labels/import.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import rule_label_job as job  # noqa: E402
from app.config import settings  # noqa: E402
from app.rule_label_schema import SwitchedOff, require_on  # noqa: E402


def _ledger(a: argparse.Namespace):
    if a.ledger_spec:
        if not a.ledger_path:
            raise job.LabelError("--ledger-spec needs --ledger-path")
        mod, _, cls = a.ledger_spec.partition(":")
        return getattr(importlib.import_module(mod), cls)(
            a.ledger_path, tool=f"label-{a.pass_}"
        )
    if a.max_usd:
        return job.CapLedger(a.max_usd)
    raise job.LabelError(
        "a paid pass needs an order ledger: --max-usd N or --ledger-spec and --ledger-path"
    )


def _convert_lab(a: argparse.Namespace) -> int:
    from app import compiled_rule_report, rule_label_convert

    if not a.lab_db or not a.out:
        raise job.LabelError("convert-lab needs --lab-db and --out")
    require_on()
    conn = job.open_copy(a.lab_db, read_only=True)
    rows, counts = rule_label_convert.convert(
        conn,
        lambda sdid: compiled_rule_report.pages_of(conn, sdid),
        lambda sdid: compiled_rule_report.page_origin(conn, sdid),
    )
    rule_label_convert.write(rows, a.out)
    print("CONVERTED " + json.dumps(counts, sort_keys=True))
    return 0


def _convert_boxes(a: argparse.Namespace) -> int:
    from app import ocr_box_convert

    if not a.lab_db or not a.out:
        raise job.LabelError("convert-boxes needs --lab-db and --out")
    require_on()
    try:
        out = ocr_box_convert.check_out(a.out, a.data_dir)
    except ValueError as exc:
        raise job.LabelError(str(exc)) from None
    conn = job.open_copy(a.lab_db, read_only=True)
    pages, counts = ocr_box_convert.convert(conn)
    ocr_box_convert.write(pages, out)
    print("CONVERTED " + json.dumps(counts, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "command",
        choices=("estimate", "run", "report", "export", "convert-lab", "convert-boxes"),
    )
    ap.add_argument(
        "--db", default=None, help="the database COPY (a live-shaped path is refused)"
    )
    ap.add_argument(
        "--data-dir",
        default=None,
        help="convert-boxes: the data directory the box file must be written inside",
    )
    ap.add_argument(
        "--lab-db", default=None, help="convert-lab: the lab labeller's database COPY"
    )
    ap.add_argument("--source", choices=job.SOURCES, default="requirement")
    ap.add_argument(
        "--book",
        action="append",
        default=[],
        help="a standard's name or document id; repeat",
    )
    ap.add_argument("--ids-file", default=None, help="one rule id per line")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pass", dest="pass_", choices=("a", "b"), default=None)
    ap.add_argument("--model-a", default=job.DEFAULT_MODEL_A)
    ap.add_argument("--model-b", default=job.DEFAULT_MODEL_B)
    ap.add_argument("--batch", type=int, default=job.BATCH_RULES)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--max-usd", type=float, default=0.0)
    ap.add_argument("--ledger-spec", default=None)
    ap.add_argument("--ledger-path", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    try:
        if a.command == "convert-lab":
            return _convert_lab(a)
        if a.command == "convert-boxes":
            return _convert_boxes(a)
        if not a.db:
            raise job.LabelError("--db is needed")
        if a.command in ("report", "export"):
            conn = job.open_copy(a.db, read_only=True)
            if a.command == "report":
                print(json.dumps(job.report(conn), indent=1))
                return 0
            if not a.out:
                raise job.LabelError("export needs --out")
            print(f"EXPORTED {job.write_export(conn, a.out)} rows")
            return 0
        require_on()
        ids = (
            [
                ln.strip()
                for ln in Path(a.ids_file).read_text(encoding="utf-8").splitlines()
                if ln.strip()
            ]
            if a.ids_file
            else []
        )
        conn = job.open_copy(a.db, read_only=a.command == "estimate")
        rules = job.select_rules(
            conn, source=a.source, books=a.book, ids=ids, limit=a.limit
        )
        if a.command == "estimate":
            job.check_models(a.model_a, [a.model_b])
            for name, model in (("a", a.model_a), ("b", a.model_b)):
                print(
                    f"PASS {name} "
                    + json.dumps(job.estimate(rules, model, a.batch), sort_keys=True)
                )
            return 0
        if not a.pass_:
            raise job.LabelError("run needs --pass a or --pass b")
        from app import agent_run

        settings.db_path = Path(
            a.db
        ).resolve()  # the app's Claude gate reads the configured database: this copy
        agent_run.check_db_path(a.db)
        ledger = _ledger(a)
        lane = job.Lane(ledger)
        model = a.model_a if a.pass_ == "a" else a.model_b
        counts = job.run_pass(
            conn,
            rules,
            pass_=a.pass_,
            model=model,
            lane=lane,
            batch_size=a.batch,
            concurrency=a.concurrency,
        )
        print(
            "DONE "
            + json.dumps(counts, sort_keys=True)
            + f" | USD this run {ledger.run_usd:.4f}"
        )
        if counts.get("stopped"):
            print(f"STOPPED | {counts['stopped']}", flush=True)
            return 2
        return 0
    except (job.LabelError, SwitchedOff, ValueError) as exc:
        print(f"REFUSED | {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
