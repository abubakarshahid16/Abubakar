"""Order 304.1: how many stored rules the scope gate would hold back, COUNTS ONLY, read-only, on a COPY.

For each standard (or the ones whose number contains `--like`), counts the active statement and limit rules by what
`converter_gates.scope_refusal` says: `scope_in_appendix` (an appendix or annex), `scope_clause_not_printed` (the
stored clause is not a heading of the rule's own chunk), `no_chunk_text` (the gate cannot see the page and stays
silent), or `ok`. It prints counts and a standard's label only: no sentence, no clause number, no page, no file name.

    python scripts/scope_gate_count.py --db ~/project/library-clean/rag_intelligence.sqlite [--like "API 520"]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

from rehearse_requirement_reextraction import refuse_live  # noqa: E402

from app import converter_gates  # noqa: E402

TYPES = (
    "statement",
    "numeric_limit",
    "cross_field_limit",
    "range_limit",
    "table_value",
    "table_row",
)


def classify(row: dict) -> str:
    if not str(row.get("chunk_text") or "").strip():
        return "no_chunk_text"
    return converter_gates.scope_refusal(row) or "ok"


def count(conn: sqlite3.Connection, like: str | None = None) -> dict[str, Counter]:
    conn.row_factory = sqlite3.Row
    marks = ",".join("?" for _ in TYPES)
    sql = (
        "SELECT r.clause, r.requirement_text, r.source_text, c.text AS chunk_text, c.section AS section,"
        " COALESCE(k.document_number, d.filename) AS label"
        " FROM standard_requirements r"
        " LEFT JOIN chunks c ON c.id = r.chunk_id"
        " LEFT JOIN documents d ON d.id = r.standard_document_id"
        " LEFT JOIN document_classification k ON k.document_id = r.standard_document_id"
        f" WHERE r.superseded_at IS NULL AND r.requirement_type IN ({marks})"
    )
    out: dict[str, Counter] = {}
    for row in conn.execute(sql, TYPES):
        label = str(row["label"] or "unknown")
        if like and like.lower() not in label.lower():
            continue
        out.setdefault(label, Counter())[classify(dict(row))] += 1
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument(
        "--like", default=None, help="only standards whose label contains this text"
    )
    args = ap.parse_args(argv)
    path = refuse_live(args.db)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = count(conn, args.like)
    finally:
        conn.close()
    for label in sorted(result):
        counts = result[label]
        total = sum(counts.values())
        parts = ", ".join(
            f"{k}: {counts[k]}"
            for k in (
                "ok",
                "scope_in_appendix",
                "scope_clause_not_printed",
                "no_chunk_text",
            )
        )
        print(f"{label}: {total} rules ({parts})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
