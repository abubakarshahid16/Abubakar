"""Propose which field of one equipment type's form each numeric rule of chosen standards limits (order 262.1).

OFFLINE PASS ON A COPY. For every numeric requirement of the named COMPANY_STANDARDs, the LOCAL model
answers one field of the type's own form (`rule_roles.form`) and a quote; the four gates of
`field_vocabulary` keep or drop each answer; every answer is stored in `canonical_field_names`; the
kept mappings are written to `backend/app/reference/rule_roles/<type>.json` as a DRAFT with no
document text (a label, a clause number, a hash of the rule text, a form field).

IT REFUSES THE LIVE DATABASE, exactly as `rehearse_requirement_reextraction.py` does: make the copy
first (`live_guard.diagnostic_copy()`). IT USES THE LOCAL ENGINE ONLY (`OllamaProvider`).
Output: counts only, never document text.

    python scripts/propose_rule_roles.py --db <copy> --type "Centrifugal Pump" --standard "SAES-G-005" --standard "SAES-K-503"
    python scripts/propose_rule_roles.py --db <copy> --type "Centrifugal Pump" --standard ... --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

from rehearse_requirement_reextraction import refuse_live  # noqa: E402


def run(
    db_path: Path,
    equipment_type: str,
    standards: list[str],
    *,
    limit: int | None = None,
    dry_run: bool = False,
    out_file: Path | None = None,
    provider=None,
) -> dict:
    from app import field_naming, rule_roles, standard_ids, statement_roles
    from app.config import settings
    from app.db import connect

    settings.db_path = refuse_live(db_path)
    conn = connect()
    docs = {
        r["id"]: r["document_number"] or r["filename"]
        for r in conn.execute(
            "SELECT d.id, d.filename, c.document_number FROM documents d"
            " JOIN document_classification c ON c.document_id = d.id"
            " WHERE c.document_role = 'COMPANY_STANDARD'"
        )
    }
    chosen = {
        doc_id: label
        for doc_id, label in docs.items()
        if any(standard_ids.same_standard(s, label) for s in standards)
    }
    rows: list[dict] = []
    for doc_id in sorted(chosen):
        rows += [
            dict(r)
            for r in conn.execute(
                "SELECT id, standard_document_id, clause, requirement_type, requirement_text,"
                " raw_value, raw_unit, unit FROM standard_requirements"
                " WHERE standard_document_id = ? AND superseded_at IS NULL"
                " AND requirement_type IN ('numeric_limit','table_row','relative_limit','statement')"
                " ORDER BY id",
                (doc_id,),
            )
        ]
    if limit:
        rows = rows[:limit]
    numeric = [r for r in rows if r["requirement_type"] != statement_roles.STATEMENT]
    statements = [r for r in rows if r["requirement_type"] == statement_roles.STATEMENT]
    num_dict, _roles, _families = rule_roles.form(equipment_type)
    stmt_dict, _stmt_roles = statement_roles.form(equipment_type)

    def pending(group, kind, dictionary):
        stored = field_naming.stored_names(
            kind, [str(r["id"]) for r in group], dictionary
        )
        return [r for r in group if str(r["id"]) not in stored]

    todo_num = pending(numeric, field_naming.REQUIREMENT, num_dict)
    todo_stmt = pending(statements, statement_roles.KIND, stmt_dict)
    out = {
        "database": str(settings.db_path),
        "equipment_type": equipment_type,
        "form_fields": len(num_dict),
        "text_fields": len(stmt_dict),
        "standards_found": len(chosen),
        "numeric_rules": len(numeric),
        "statement_rules": len(statements),
        "to_ask": len(todo_num) + len(todo_stmt),
        "mapped_numeric": 0,
        "mapped_statements": 0,
        "unreadable": 0,
        "refused": None,
        "file": None,
    }
    if dry_run or not rows:
        return out
    if todo_num or todo_stmt:
        if provider is None:
            from app.reasoning_provider import OllamaProvider

            provider = OllamaProvider()  # the LOCAL engine only
        stats: dict = {}
        try:
            if todo_num:
                rule_roles.propose(todo_num, equipment_type, provider, stats)
            if todo_stmt:
                statement_roles.propose(todo_stmt, equipment_type, provider, stats)
        except Exception as exc:  # noqa: BLE001 - a refused or failed batch keeps what was stored so far
            out["refused"] = type(exc).__name__
        out["unreadable"] = stats.get("unreadable", 0)
    label = lambda doc_id: chosen.get(doc_id)  # noqa: E731
    kept_num = rule_roles.entries(numeric, equipment_type, label)
    kept_stmt = statement_roles.entries(statements, equipment_type, label)
    out["mapped_numeric"], out["mapped_statements"] = len(kept_num), len(kept_stmt)
    out["file"] = str(rule_roles.export(equipment_type, kept_num + kept_stmt, out_file))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--type", required=True, dest="equipment_type")
    ap.add_argument("--standard", action="append", required=True)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--out",
        type=Path,
        help="the JSON file (default: reference/rule_roles/<type>.json)",
    )
    args = ap.parse_args(argv)
    result = run(
        args.db,
        args.equipment_type,
        args.standard,
        limit=args.limit,
        dry_run=args.dry_run,
        out_file=args.out,
    )
    print(json.dumps(result, indent=1))
    return 2 if (result["refused"] or result["unreadable"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
