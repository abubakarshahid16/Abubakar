"""#1584: the material reference table for a proof run, on a COPY. Sends no document text and no sheet value.

    python scripts/propose_material_reference.py --db <copy> --estimate-only
    python scripts/propose_material_reference.py --db <copy> --max-usd 100
    python scripts/propose_material_reference.py --db <copy> --add-sheet <checklist.xlsx>
    python scripts/propose_material_reference.py --db <copy> --count-on <sheet copy> --document <id> --role body_material

The estimate sends nothing and needs no key. A send needs MATERIAL_REFERENCE_ENGINE=claude and the Claude lane open; every
entry lands unsigned. --add-sheet adds the "Material reference" sheet to a checklist; the owner's ticks there come back
through scripts/import_rule_approvals.py. --count-on says how many of a document's values match the table: counts only.
A live-shaped --db is refused. Stdout is one line of JSON, never a value or document text.

Exit: 0 done; 3 engine off; 4 over a budget or no usable answer; 5 a batch is still running (run it again).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

import openpyxl  # noqa: E402
from rehearse_requirement_reextraction import refuse_live  # noqa: E402


def count_on(conn, sheet: Path, document: str, role: str, equipment_type: str) -> dict:
    """How many of this document's values for this role the table holds: every entry, and only what is signed."""
    from app import datasheet_checks, datasheet_roles
    from app import material_reference as ref

    values = sqlite3.connect(f"file:{refuse_live(sheet)}?mode=ro", uri=True)
    values.row_factory = sqlite3.Row
    rules = datasheet_checks.load_rules()
    wanted = datasheet_roles.wanted_roles(equipment_type, rules)
    found = [
        str(f["field_value"] or f["raw_value"] or "")
        for f in values.execute(
            "SELECT * FROM submittal_facts WHERE submittal_document_id = ? AND superseded_at IS NULL AND is_blank = 0",
            (document,),
        )
        if datasheet_checks.role_of(f["field_name"] or "", rules, wanted) == role
    ]
    every = ref.Table(
        "all",
        tuple(
            ref.Entry(
                r[ref.C_SPEC], r[ref.C_GRADE], r[ref.C_FAMILY], r[ref.C_BARE] == "yes"
            )
            for r in (ref.sheet_rows(conn) if ref.has_schema(conn) else [])
        ),
    )
    table = ref.signed(conn)

    def known(among, value) -> bool:
        families = ref.families_of(among, value)
        return bool(families) and None not in families

    return {
        "role": role,
        "values": len(found),
        "parts_per_value": sorted(len(ref.parts_of(v)) for v in found),
        "every_part_in_the_table_signed_or_not": sum(
            1 for v in found if known(every, v)
        ),
        "every_part_in_the_signed_table": sum(1 for v in found if known(table, v)),
        "entries": len(every.entries),
        "signed_entries": len(table.entries),
    }


def run(args, emit=print, **kw) -> int:
    from app import claude_spend, material_reference, reasoning_provider
    from app.config import settings
    from app.db import connect, reset_connection

    settings.db_path = refuse_live(args.db)
    reset_connection()
    conn = connect()
    if args.count_on:
        emit(
            json.dumps(
                count_on(conn, args.count_on, args.document, args.role, args.type),
                sort_keys=True,
            )
        )
        return 0
    if args.add_sheet:
        book = openpyxl.load_workbook(args.add_sheet)
        material_reference.ensure_schema(conn)
        written = material_reference.add_sheet(book, conn)
        book.save(args.add_sheet)
        emit(json.dumps({"rows_on_the_sheet": written}))
        return 0
    try:
        report = material_reference.propose(
            conn, estimate_only=args.estimate_only, max_usd=args.max_usd, **kw
        )
    except material_reference.SwitchedOff as exc:
        emit(json.dumps({"status": "off", "why": str(exc)}))
        return 3
    except (claude_spend.StopRun, reasoning_provider.ProviderRefused) as exc:
        emit(json.dumps({"status": "refused", "why": str(exc)}))
        return 4
    emit(json.dumps(report, sort_keys=True))
    return {"waiting": 5, "over_budget": 4, "no_usable_answer": 4}.get(
        report["status"], 0
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", maxsplit=1)[0])
    ap.add_argument("--db", required=True, type=Path, help="a COPY")
    ap.add_argument("--estimate-only", action="store_true", help="send nothing")
    ap.add_argument("--max-usd", type=float)
    ap.add_argument("--add-sheet", type=Path)
    ap.add_argument("--count-on", type=Path)
    ap.add_argument("--document")
    ap.add_argument("--role", default="body_material")
    ap.add_argument("--type", default="Pressure Safety Valve")
    args = ap.parse_args(argv)
    real_stdout = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        return run(args, emit=lambda line: print(line, file=real_stdout))


if __name__ == "__main__":
    sys.exit(main())
