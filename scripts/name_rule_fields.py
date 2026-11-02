"""#805 plan change 6: name each compiled rule's field from the equipment type's fixed list, on a COPY.

    python scripts/name_rule_fields.py --db <copy> --type "Pressure Safety Valve" --standard API-520-I --estimate-only
    python scripts/name_rule_fields.py --db <copy> --type "Pressure Safety Valve" --standard API-520-I --max-usd 100

The estimate sends nothing and needs no key. A send needs RULE_FIELD_NAMING_ENGINE=claude, every gate of the compiler and
the standard on the approved list. Run again it polls an open batch and does not pay again. A live-shaped --db is refused.
Stdout is one line of JSON, counts only, never document text.

    python scripts/name_rule_fields.py --db <copy> --type "Pressure Safety Valve" --standard API-520-I --counts-on <sheet copy> --document <id>

reads both copies, sends nothing, and says per standard how many rules pair with that document's read values, how many are
not on a datasheet, and how many could decide if approved.

Add --checks for the typed check step: the same flags, after the field step, on rules with a verified role and no figure.

Exit: 0 every rule answered, or an estimate; 3 engine off; 4 refused, over a budget or partial: the report says why;
5 a batch is still running (run it again).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

from compile_standards import _chosen  # noqa: E402
from rehearse_requirement_reextraction import refuse_live  # noqa: E402

EXIT_OFF, EXIT_REFUSED, EXIT_WAITING = 3, 4, 5


def run(
    db_path: Path,
    equipment_type: str,
    wanted: list[str],
    *,
    emit=print,
    checks: bool = False,
    **kw,
) -> int:
    from app import (
        claude_spend,
        reasoning_provider,
        rule_field_naming,
        rule_typed_check,
        standards_compiler,
        standards_converter,
    )
    from app.config import settings
    from app.db import connect, reset_connection

    settings.db_path = refuse_live(db_path)
    reset_connection()
    conn = connect()
    try:
        step = rule_typed_check.name_checks if checks else rule_field_naming.name_fields
        reports = step(conn, _chosen(conn, wanted), equipment_type, **kw)
    except (rule_field_naming.SwitchedOff, standards_compiler.SwitchedOff) as exc:
        emit(json.dumps({"status": "off", "why": str(exc)}))
        return EXIT_OFF
    except (
        rule_field_naming.NoFieldList,
        claude_spend.StopRun,
        standards_converter.FamilyNotAllowed,
        standards_converter.NotStandardsText,
        reasoning_provider.ProviderRefused,
    ) as exc:
        emit(json.dumps({"status": "refused", "why": str(exc)}))
        return EXIT_REFUSED
    emit(json.dumps({"reports": reports}, sort_keys=True))
    said = {r["status"] for r in reports}
    if "waiting" in said:
        return EXIT_WAITING
    return EXIT_REFUSED if said & {"over_budget", "unconfirmed", "partial"} else 0


def rule_of_compiled(row) -> dict:
    """A stored compile row in the shape of an approved rule, before any approval. For the counts: no verdict."""
    row = dict(row)
    return {
        **row,
        "value": row.get("limit_value"),
        "conditions": [row["condition_text"]] if row.get("condition_text") else [],
        "exceptions": [row["exception_text"]] if row.get("exception_text") else [],
    }


def could_decide(rule: dict, facts: list[dict], equipment_type: str) -> tuple:
    """(tags that would get a verdict, tags, what stops the first that would not), if a person approved it. Never the
    verdict. The review's own steps, with no approval asked."""
    from app import rulebook_v2_review as review

    rows = [
        review._judge(rule, found, facts, equipment_type)
        for found in review.pairs(rule, facts, equipment_type)
    ]
    held = [r.reason for r in rows if r.status not in review.DECIDED]
    return len(rows) - len(held), len(rows), held[0] if held else None


def counts_for_document(rows, facts: list[dict], equipment_type: str) -> dict:
    """Per standard, against one document's read values: how many rules pair, how many are not on a datasheet, how many
    could decide. Counts and fixed reason names only: no value, no verdict, no document text."""
    from app import material_reference
    from app import rulebook_v2_review as review
    from app.config import settings
    from app.db import connect

    table = (
        material_reference.signed(connect())
        if settings.material_reference_enabled
        else None
    )
    rules = [{**rule_of_compiled(r), "_reference": table} for r in rows]
    found = [review.pairs(rule, facts, equipment_type) for rule in rules]
    deciding = [could_decide(rule, facts, equipment_type) for rule in rules]
    stopped: dict[str, int] = {}
    for yes, of, reason in deciding:
        if yes < of and reason:
            stopped[reason] = stopped.get(reason, 0) + 1
    return {
        "rules": len(rules),
        "pair_with_a_value": sum(
            1 for f in found if any(p.fact is not None for p in f)
        ),
        "not_on_datasheet": sum(
            1 for f in found if f[0].reason == review.NOT_ON_DATASHEET
        ),
        "hold_a_figure": sum(1 for rule in rules if rule["value"] is not None),
        "hold_a_typed_check": sum(1 for rule in rules if review._check_of(rule)[0]),
        "could_decide_if_approved": sum(1 for yes, of, _r in deciding if yes == of),
        "could_decide_on_some_tags": sum(1 for yes, of, _r in deciding if 0 < yes < of),
        "stopped_by": dict(sorted(stopped.items())),
    }


def counts(
    db_path: Path,
    equipment_type: str,
    wanted: list[str],
    sheet: Path,
    document: str,
    emit=print,
) -> int:
    """Read only: the rules from one copy, the document's read values from another."""
    import sqlite3

    from app import compiled_rule_report
    from app.config import settings
    from app.db import connect, reset_connection

    settings.db_path = refuse_live(db_path)
    reset_connection()
    conn = connect()
    rows = {
        label: compiled_rule_report.compiled_rows(
            conn, compiled_rule_report.latest_compile(conn, doc)["id"]
        )
        for doc, label in _chosen(conn, wanted).items()
    }
    values = sqlite3.connect(f"file:{refuse_live(sheet)}?mode=ro", uri=True)
    values.row_factory = sqlite3.Row
    facts = [
        dict(r)
        for r in values.execute(
            "SELECT * FROM submittal_facts WHERE submittal_document_id = ? AND superseded_at IS NULL"
            " ORDER BY page, field_name",
            (document,),
        )
    ]
    emit(
        json.dumps(
            {
                label: counts_for_document(found, facts, equipment_type)
                for label, found in rows.items()
            },
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", maxsplit=1)[0])
    ap.add_argument("--db", required=True, type=Path, help="a COPY")
    ap.add_argument("--type", required=True, dest="equipment_type")
    ap.add_argument("--standard", action="append", required=True)
    ap.add_argument("--estimate-only", action="store_true", help="send nothing")
    ap.add_argument(
        "--max-usd",
        type=float,
        help="limit on today's whole Claude spend plus this send's worst case, as in compile_standards; default the"
        " owner's USD 100 a day. Below what today has spent, nothing is sent and the report says so",
    )
    ap.add_argument("--poll-seconds", type=float, default=60.0)
    ap.add_argument("--resend-unconfirmed", action="store_true")
    ap.add_argument(
        "--checks",
        action="store_true",
        help="the typed check step (field-check-v1), after the field step has run",
    )
    ap.add_argument(
        "--counts-on",
        type=Path,
        help="a copy holding the document's read values; sends nothing",
    )
    ap.add_argument("--document", help="with --counts-on: the document id")
    args = ap.parse_args(argv)
    real_stdout = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        if args.counts_on:
            return counts(
                args.db,
                args.equipment_type,
                args.standard,
                args.counts_on,
                args.document,
                emit=lambda line: print(line, file=real_stdout),
            )
        return run(
            args.db,
            args.equipment_type,
            args.standard,
            emit=lambda line: print(line, file=real_stdout),
            checks=args.checks,
            estimate_only=args.estimate_only,
            max_usd=args.max_usd,
            poll_seconds=args.poll_seconds,
            resend_unconfirmed=args.resend_unconfirmed,
        )


if __name__ == "__main__":
    sys.exit(main())
