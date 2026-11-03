"""#805 rule boxes: label every compiled rule (step 1), write a tested check for the number and condition rules (step 2),
and ask a different model to confirm it (step 3), on a COPY of the database.

    python scripts/rule_boxes.py label  --db <copy>            # dry: prompts and the worst case in USD, sends nothing
    python scripts/rule_boxes.py label  --db <copy> --send     # asks Claude; this spends
    python scripts/rule_boxes.py check  --db <copy> [--send]   # step 2: one rule per prompt, reasoning model
    python scripts/rule_boxes.py second --db <copy> [--send]   # step 3: a different model, fresh context
    python scripts/rule_boxes.py status --db <copy>            # counts only

DRY BY DEFAULT. A dry run builds every prompt, prints the worst case (the most the caps could be asked for) and a typical
estimate, and says which gate would refuse. It sends nothing and needs no key. A send needs the lane open for this
process (`RULE_BOXES_ENGINE=claude` in the process environment, under `REASONING_PROVIDER`), the standards compiler's
gates per standard (its switch, family, role, the approved list), both egress flags and a key. Every group of prompts is
its own spend step with a worst case under USD 4.5; the owner's per-step, per-day and November caps stop it in code, and
a stop is clean: what was received is kept and a second run takes up where it stopped. A live-shaped --db is refused.

Exit: 0 dry or done; 3 refused by a gate; 5 partial or stopped. Stdout is one line of JSON, counts only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

from rehearse_requirement_reextraction import refuse_live  # noqa: E402
from rule_box_tools import rule_box_check, rule_box_run  # noqa: E402
from rule_box_tools import rule_box_labels as rule_boxes  # noqa: E402

from app import (  # noqa: E402
    claude_approved,
    claude_spend,
    reasoning_provider,
    standards_compiler,
)
from app.config import settings  # noqa: E402

ENGINE_ENV = "RULE_BOXES_ENGINE"
#: Typical answer sizes in tokens, for the ESTIMATE line only (the worst case does not use them).
TYPICAL_OUT = {"label": 45, "check": 450, "second": 70}


def lane_refusal() -> str | None:
    code, why = reasoning_provider.claude_unavailable_for_task(
        os.environ.get(ENGINE_ENV)
    )
    return f"{code}: {why}" if code is not None else None


def make_gate(conn):
    def gate(document_id: str, label: str) -> str | None:
        try:
            standards_compiler.require_allowed(conn, document_id, label)
        except Exception as exc:  # noqa: BLE001 - the reason is the exception's type; ids only, never text
            return type(exc).__name__
        return None

    return gate


def typical_usd(model: str, jobs, step: str) -> float:
    total = 0.0
    for job in jobs:
        p_in, p_out, _w, _r = claude_spend.price_for(model, len(job.prompt) // 3 + 1)
        out_tokens = TYPICAL_OUT[step] * (
            max(1, (job.max_tokens - 200) // rule_boxes.TOKENS_PER_RULE)
            if step == "label"
            else 1
        )
        total += ((len(job.prompt) // 4 + 1) * p_in + out_tokens * p_out) / 1_000_000
    return total


def dry_report(step: str, model: str, jobs, extra: dict) -> dict:
    batches, too_big = rule_box_run.groups(model, jobs)
    worst = [sum(rule_box_run.worst_of(model, j) for j in b) for b in batches]
    return {
        "step": step,
        "model": model,
        **extra,
        "prompts": len(jobs),
        "groups_each_under_usd": rule_box_run.GROUP_CAP_USD,
        "groups": len(batches),
        "dearest_group_worst_usd": round(max(worst, default=0.0), 4),
        "worst_case_usd": round(sum(worst), 4),
        "typical_estimate_usd": round(
            typical_usd(model, [j for b in batches for j in b], step), 3
        ),
        "prompts_too_big_to_send": len(too_big),
        "dearest_prompt_worst_usd": round(
            max((rule_box_run.worst_of(model, j) for j in jobs), default=0.0), 4
        ),
        "calls_in_flight": rule_box_run.WORKERS,
        "status": "dry",
        "would_refuse": lane_refusal(),
    }


def _estimate_check_jobs(conn, numeric_only: bool):
    """Before step 1 has run: every rule (or every rule with a stored figure) as if it were a box a or c rule of a
    pressure vessel. An upper bound for the prompt count and a good measure of prompt size; not a prediction."""
    labels = rule_boxes.standard_labels(conn)
    fields = rule_box_check.fields_for("pressure vessel")
    where = " WHERE limit_value IS NOT NULL" if numeric_only else ""
    rows = conn.execute(
        "SELECT id, standard_document_id, clause, field, comparator, limit_value, unit, condition_text, exception_text,"
        f" quote FROM compiled_rules{where}"
    ).fetchall()
    jobs = [
        rule_box_run.Job(
            f"chk:{r['id']}",
            rule_box_check.check_prompt(
                r, labels.get(r["standard_document_id"], ""), "pressure vessel", fields
            ),
            frozenset({r["standard_document_id"]}),
            rule_box_check.CHECK_TOKENS,
        )
        for r in rows
    ]
    return jobs


def _second_estimate_jobs(conn):
    labels = rule_boxes.standard_labels(conn)
    fields = rule_box_check.fields_for("pressure vessel")
    rows = conn.execute(
        "SELECT id, standard_document_id, clause, quote FROM compiled_rules"
    ).fetchall()
    return [
        rule_box_run.Job(
            f"sec:{r['id']}",
            rule_box_check.second_prompt(
                r, labels.get(r["standard_document_id"], ""), "pressure vessel", fields
            ),
            frozenset({r["standard_document_id"]}),
            rule_box_check.SECOND_TOKENS,
        )
        for r in rows
    ]


def has_labels(conn) -> bool:
    try:
        return (
            conn.execute(f"SELECT COUNT(*) FROM {rule_boxes.TABLE}").fetchone()[0] > 0
        )
    except Exception:  # noqa: BLE001 - no table yet
        return False


def status(conn) -> dict:
    out: dict = {
        "rules": conn.execute("SELECT COUNT(*) FROM compiled_rules").fetchone()[0]
    }
    rule_boxes.ensure_schema(conn)
    rule_box_check.ensure_schema(conn)
    out["labelled"] = conn.execute(
        f"SELECT COUNT(*) FROM {rule_boxes.TABLE}"
    ).fetchone()[0]
    out["by_box"] = {
        r[0]: r[1]
        for r in conn.execute(
            f"SELECT box, COUNT(*) FROM {rule_boxes.TABLE} GROUP BY box ORDER BY box"
        )
    }
    out["checks_by_status"] = {
        r[0]: r[1]
        for r in conn.execute(
            f"SELECT status, COUNT(*) FROM {rule_box_check.CHECKS} GROUP BY status ORDER BY status"
        )
    }
    out["second_agree"] = {
        str(r[0]): r[1]
        for r in conn.execute(
            f"SELECT agree, COUNT(*) FROM {rule_box_check.SECOND} GROUP BY agree ORDER BY agree"
        )
    }
    out["advanced"] = rule_box_check.advanced(conn)
    return out


def run_step(
    conn, step: str, send: bool, model: str | None, per_prompt: int, emit
) -> int:
    rule_boxes.ensure_schema(conn)
    rule_box_check.ensure_schema(conn)
    gate = make_gate(conn)
    if step == "label":
        model = model or rule_boxes.model_name()
        jobs, members, counts = rule_boxes.jobs(conn, gate, per_prompt)
        apply = rule_boxes.storer(conn, members, model)
        prefix, version = "rule_box_label", rule_boxes.PROMPT_VERSION
        extra = counts
    elif step == "check":
        model = model or rule_box_check.check_model()
        calls = (
            rule_box_check.settle_without_a_call(conn)
            if has_labels(conn) and send
            else {}
        )
        if has_labels(conn):
            jobs, members, counts = rule_box_check.check_jobs(conn, gate)
            extra = {**counts, "estimate": False}
        else:
            jobs, members = _estimate_check_jobs(conn, numeric_only=False), {}
            numeric = _estimate_check_jobs(conn, numeric_only=True)
            extra = {
                "estimate": True,
                "note": "step 1 has not run: an upper bound, every rule taken as a box a or c rule",
                "if_only_rules_with_a_stored_figure": dry_report(
                    step, model, numeric, {}
                )["worst_case_usd"],
            }
        extra.update(settled_without_a_call=calls)
        apply = rule_box_check.check_storer(conn, members, model)
        prefix, version = "rule_box_check", rule_box_check.CHECK_VERSION
    elif step == "second":
        model = model or rule_box_check.second_model()
        if has_labels(conn):
            jobs, members, counts = rule_box_check.second_jobs(conn, gate, model)
            extra = {**counts, "estimate": False}
        else:
            jobs, members = _second_estimate_jobs(conn), {}
            extra = {
                "estimate": True,
                "note": "steps 1 and 2 have not run: an upper bound, every rule with a figure",
            }
        apply = rule_box_check.second_storer(conn, members, model)
        prefix, version = "rule_box_second", rule_box_check.SECOND_VERSION
    else:
        raise SystemExit(f"unknown step {step!r}")
    if (
        step != "label"
        and model == settings.claude_reasoning_model
        and step == "second"
    ):
        raise SystemExit(
            "the second check must use a model other than the reasoning model"
        )
    report = dry_report(step, model, jobs, extra)
    if not send:
        emit(json.dumps(report, sort_keys=True))
        return 0
    refused = lane_refusal()
    if refused or extra.get("estimate"):
        emit(
            json.dumps(
                {
                    **report,
                    "status": "refused",
                    "why": refused or "step 1 must run first",
                    "sent": 0,
                },
                sort_keys=True,
            )
        )
        return 3
    docs = frozenset().union(*(j.docs for j in jobs)) if jobs else frozenset()
    with claude_approved.carrying(docs):
        result = rule_box_run.run(
            jobs, model=model, step_prefix=prefix, version=version, apply=apply
        )
    emit(
        json.dumps({**report, **result, **getattr(apply, "tally", {})}, sort_keys=True)
    )
    return 0 if result["status"] in (rule_box_run.DONE, rule_box_run.NOTHING) else 5


def main(argv: list[str] | None = None, *, emit=print) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=("label", "check", "second", "status"))
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--send", action="store_true", help="ask Claude; this spends")
    ap.add_argument("--model", default=None)
    ap.add_argument("--per-prompt", type=int, default=rule_boxes.PER_PROMPT)
    args = ap.parse_args(argv)

    from app.db import connect, reset_connection

    settings.db_path = refuse_live(args.db)
    reset_connection()
    conn = connect()
    if args.step == "status":
        emit(json.dumps(status(conn), sort_keys=True))
        return 0
    return run_step(conn, args.step, args.send, args.model, args.per_prompt, emit)


if __name__ == "__main__":
    sys.exit(main())
