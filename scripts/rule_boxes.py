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
from rule_box_tools import (  # noqa: E402
    rule_box_check,
    rule_box_fields,
    rule_box_judge,
    rule_box_run,
    rule_box_scope,
)
from rule_box_tools import rule_box_labels as rule_boxes  # noqa: E402

from app import (  # noqa: E402
    claude_approved,
    claude_spend,
    reasoning_provider,
    standards_compiler,
    standards_converter,
)
from app.config import settings  # noqa: E402

ENGINE_ENV = "RULE_BOXES_ENGINE"
#: Typical answer sizes in tokens, for the ESTIMATE line only (the worst case does not use them).
TYPICAL_OUT = {
    "label": 45,
    "check": 450,
    "second": 70,
    "fields": 1200,
    "identity": 40,
    "judge": 1000,
}


def lane_refusal() -> str | None:
    code, why = reasoning_provider.claude_unavailable_for_task(
        os.environ.get(ENGINE_ENV)
    )
    return f"{code}: {why}" if code is not None else None


EXCEPTIONS_FILE = "rule_boxes_family_exceptions.json"


def family_exceptions() -> frozenset[str]:
    """Document ids the OWNER allowed past the family list for this job: `{"document_ids": [...]}` in the data folder of
    the copy (outside git). It lifts only the family test; the role and the approved-list tests still apply."""
    path = Path(settings.data_dir) / EXCEPTIONS_FILE
    try:
        return frozenset(
            str(x)
            for x in json.loads(path.read_text(encoding="utf-8")).get(
                "document_ids", []
            )
        )
    except (OSError, ValueError, AttributeError):
        return frozenset()


def _approved_without_family(conn, document_id: str) -> None:
    standards_converter.require_role(conn, document_id)
    found = conn.execute(
        "SELECT sha256 FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    digest = (found["sha256"] or "").strip().lower() if found else ""
    if not digest or digest not in claude_approved.approved_hashes():
        raise claude_spend.DocumentNotApproved(
            claude_approved.NOT_APPROVED,
            f"document {document_id} is not on the approved list; nothing was sent",
        )


def make_gate(conn):
    allowed = family_exceptions()

    def gate(document_id: str, label: str) -> str | None:
        try:
            standards_compiler.require_allowed(conn, document_id, label)
        except standards_converter.FamilyNotAllowed as exc:
            if document_id not in allowed:
                return type(exc).__name__
            try:
                _approved_without_family(conn, document_id)
            except Exception as other:  # noqa: BLE001
                return type(other).__name__
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
    out["advanced_by_type"] = rule_box_scope.advanced_by_type(conn)
    return out


def run_step(
    conn, step: str, send: bool, model: str | None, per_prompt: int, emit, args=None
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
    elif step == "fields":
        model = model or rule_box_check.check_model()
        rule_box_fields.ensure_schema(conn)
        if args is None or args.cfihos is None:
            raise SystemExit("--cfihos <folder> is needed for the fields step")
        jobs, members, extra = rule_box_fields.jobs(
            conn, rule_box_fields.Cfihos(args.cfihos), gate
        )
        apply = rule_box_fields.storer(conn, members, model)
        prefix, version = "rule_box_fields", rule_box_fields.PROMPT_VERSION
    elif step == "check":
        model = model or rule_box_check.check_model()
        calls = (
            rule_box_check.settle_without_a_call(conn)
            if has_labels(conn) and send
            else {}
        )
        if has_labels(conn):
            jobs, members, counts = rule_box_check.check_jobs(
                conn, gate, getattr(args, "only", None)
            )
            extra = {
                **counts,
                "estimate": False,
                "rules_with_a_figure_by_type": rule_box_check.todo_by_type(conn),
            }
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
    elif step == "identity":
        model = model or rule_box_check.second_model()
        rule_box_scope.ensure_schema(conn)
        jobs, members, extra = rule_box_scope.identity_jobs(
            conn, gate, model, rule_boxes.standard_labels(conn)
        )
        apply = rule_box_scope.identity_storer(
            conn, members, model, rule_box_check._parse_object
        )
        prefix, version = "rule_box_identity", rule_box_scope.IDENTITY_VERSION
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


def run_judge(conn, args, emit) -> int:
    if not args.document:
        raise SystemExit("--document <submittal id> is needed for the judge step")
    rule_box_judge.ensure_schema(conn)
    model = args.model or rule_box_check.check_model()
    labels = rule_boxes.standard_labels(conn)
    pages = rule_box_judge.pages_of(conn, args.document)
    if not pages:
        raise SystemExit("that document has no pages in this database")
    gate = make_gate(conn)
    rows = [
        r
        for r in rule_box_judge.relevant_rules(conn, args.document)
        if gate(r["standard_document_id"], labels.get(r["standard_document_id"], ""))
        is None
    ]
    units, incomplete, merged = rule_box_judge.prepare(rows)
    jobs, members = rule_box_judge.build_jobs(args.document, units, labels, pages)
    extra = {
        "document_pages": len(pages),
        "rules_to_judge": len(rows),
        "distinct_rules_asked": len(units),
        "duplicates_merged": len(merged),
        "rule_text_incomplete_not_sent": len(incomplete),
        "of_which_scoped": sum(
            1 for u in units if u["rep"]["status"] != rule_box_check.BY_KIND
        ),
        "calls_per_rule": 2,
    }
    report = dry_report("judge", model, jobs, extra)
    if not args.send:
        emit(json.dumps(report, sort_keys=True))
        return 0
    refused = lane_refusal()
    if refused:
        emit(
            json.dumps(
                {**report, "status": "refused", "why": refused, "sent": 0},
                sort_keys=True,
            )
        )
        return 3
    rule_box_judge.settle_unsent(conn, args.document, incomplete, labels, model)
    apply = rule_box_judge.make_storer(
        conn, args.document, pages, model, members, labels
    )
    docs = frozenset().union(*(j.docs for j in jobs)) if jobs else frozenset()
    with claude_approved.carrying(docs):
        result = rule_box_run.run(
            jobs,
            model=model,
            step_prefix="rule_box_judge",
            version=rule_box_judge.JUDGE_VERSION,
            apply=apply,
        )
    apply.flush()
    if args.export_crs:
        result["rows_exported"] = rule_box_judge.export_crs(
            conn, args.document, args.export_crs
        )
    emit(json.dumps({**report, **result, **apply.tally}, sort_keys=True))
    return 0 if result["status"] in (rule_box_run.DONE, rule_box_run.NOTHING) else 5


def main(argv: list[str] | None = None, *, emit=print) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "step",
        choices=(
            "label",
            "fields",
            "check",
            "second",
            "identity",
            "scope",
            "judge",
            "status",
        ),
    )
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--send", action="store_true", help="ask Claude; this spends")
    ap.add_argument("--model", default=None)
    ap.add_argument(
        "--document", default=None, help="judge step: the submittal's document id"
    )
    ap.add_argument(
        "--export-crs",
        type=Path,
        default=None,
        help="judge step: write the judged rows as a CRS workbook",
    )
    ap.add_argument(
        "--only",
        choices=("fixed", "ai"),
        default=None,
        help="check step: types with an approved list, or with an AI-built one",
    )
    ap.add_argument(
        "--cfihos",
        type=Path,
        default=None,
        help="folder of the CFIHOS CORE csv files (fields step)",
    )
    ap.add_argument(
        "--export",
        type=Path,
        default=None,
        help="write the AI-built field lists here as JSON",
    )
    ap.add_argument("--per-prompt", type=int, default=rule_boxes.PER_PROMPT)
    args = ap.parse_args(argv)

    from app.db import connect, reset_connection

    settings.db_path = refuse_live(args.db)
    reset_connection()
    conn = connect()
    if args.step == "judge":
        return run_judge(conn, args, emit)
    if args.step == "scope":
        rule_boxes.ensure_schema(conn)
        rule_box_check.ensure_schema(conn)
        moved = rule_box_check.apply_scope_gate(conn)
        emit(
            json.dumps(
                {
                    "checked_moved_to_scoped": moved,
                    **rule_box_check.settle_without_a_call(conn),
                },
                sort_keys=True,
            )
        )
        return 0
    if args.step == "status":
        emit(json.dumps(status(conn), sort_keys=True))
        return 0
    return run_step(conn, args.step, args.send, args.model, args.per_prompt, emit, args)


if __name__ == "__main__":
    sys.exit(main())
