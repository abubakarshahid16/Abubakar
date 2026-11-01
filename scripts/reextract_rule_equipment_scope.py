"""Fill each rule's equipment scope on a COPY of the database (never the live one).

Reads every active rule's own clause text and heading chain
(`app.rule_equipment_scope`), counts how many rules are scoped to each equipment type,
how many are unknown and how many name several types, per standard. Writes
`equipment_type` and `equipment_scope_evidence` ONLY to the copy, and only when
`--dry-run` is not given. A rule whose `equipment_type` a human set (no evidence) is left.

    python scripts/reextract_rule_equipment_scope.py --db COPY.sqlite --dry-run --out s.json
    python scripts/reextract_rule_equipment_scope.py --db COPY.sqlite --out s.json

REFUSES a live-shaped path (`live_guard.is_live_shaped`). Takes the heavy lock itself
(kind "rule-scope"; exits 75 when it cannot get it). The optional local-model pass runs
only with RULE_EQUIPMENT_SCOPE_MODEL_ENABLED, through `model_transport` (local Ollama), and
the model is unloaded at the end (#666). Output carries counts and ids only, no rule text.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

KIND = "rule-scope"


def _unload_models() -> None:
    from app import model_transport

    for model in model_transport.models_used():
        try:
            with model_transport.keep_alive_override(0):
                model_transport.post_json(
                    "/api/generate", {"model": model, "prompt": "", "stream": False}, timeout=30.0)
        except Exception as exc:  # noqa: BLE001 - unloading is a courtesy
            print(f"model {model} could not be unloaded ({type(exc).__name__})", file=sys.stderr)


def run(path: Path, *, dry_run: bool, out: Path | None, say=print) -> dict:
    from app import rule_equipment_scope as res

    use_model = res.model_enabled()
    uri = f"file:{path}?mode={'ro' if dry_run else 'rw'}"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(standard_requirements)")}
    if not dry_run and "equipment_scope_evidence" not in cols:
        conn.execute("ALTER TABLE standard_requirements ADD COLUMN equipment_scope_evidence TEXT")
        cols.add("equipment_scope_evidence")
    has_evidence = "equipment_scope_evidence" in cols
    sections: dict[str, dict[str, str]] = {}
    for r in conn.execute("SELECT DISTINCT document_id, section FROM chunks WHERE section IS NOT NULL"):
        sections.setdefault(r["document_id"], {})
    for doc in sections:
        sections[doc] = res.headings_from_sections(
            r["section"] for r in conn.execute(
                "SELECT DISTINCT section FROM chunks WHERE document_id = ?", (doc,)))
    sql = ("SELECT r.id, r.standard_document_id, r.clause, r.page, r.requirement_text,"
           " r.equipment_type, c.section AS chunk_section"
           + (", r.equipment_scope_evidence" if has_evidence else ", NULL AS equipment_scope_evidence")
           + " FROM standard_requirements r LEFT JOIN chunks c ON c.id = r.chunk_id"
           " WHERE r.superseded_at IS NULL")
    per_type: dict[str, int] = {}
    per_standard: dict[str, dict[str, int]] = {}
    unknown = multi = human_kept = written = 0
    for row in conn.execute(sql).fetchall():
        std = per_standard.setdefault(row["standard_document_id"], {"rules": 0, "scoped": 0, "unknown": 0})
        std["rules"] += 1
        if row["equipment_type"] and not row["equipment_scope_evidence"]:
            human_kept += 1  # a person's value: never overwritten
            continue
        scope = res.scope_of(dict(row), sections.get(row["standard_document_id"], {}))
        if not scope["types"] and use_model:
            scope = res.ask_local_model(dict(row)) or scope
        if not scope["types"]:
            unknown += 1
            std["unknown"] += 1
        else:
            std["scoped"] += 1
            multi += len(scope["types"]) > 1
            for t in scope["types"]:
                per_type[t] = per_type.get(t, 0) + 1
        if not dry_run:
            fields = res.stored_fields(scope)
            conn.execute(
                "UPDATE standard_requirements SET equipment_type = ?, equipment_scope_evidence = ?"
                " WHERE id = ?", (fields.get("equipment_type"), fields.get("equipment_scope_evidence"), row["id"]))
            written += 1
    if not dry_run:
        conn.commit()
    conn.close()
    total = sum(s["rules"] for s in per_standard.values())
    summary = {"dry_run": dry_run, "rules": total, "rules_scoped_to_type": dict(sorted(per_type.items())),
               "unknown": unknown, "multi_type": multi, "kept_human_value": human_kept,
               "rows_written": written, "model_pass": use_model, "per_standard": per_standard,
               "note": "counts are of the active rules of the database given; a rule naming several "
                       "types is counted under each"}
    say(json.dumps({k: v for k, v in summary.items() if k != "per_standard"}, indent=1))
    if out:
        out.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, required=True, help="a COPY of the database")
    ap.add_argument("--dry-run", action="store_true", help="count only; the file is not opened for writing")
    ap.add_argument("--out", type=Path, help="write the JSON summary here")
    args = ap.parse_args(argv)
    from app import heavy_lock, live_guard

    path = args.db.resolve()
    if live_guard.is_live_shaped(path):
        print("REFUSED: that path is shaped like the live database. Work on a copy.", file=sys.stderr)
        return 2
    if not path.is_file():
        print(f"no database at {path}", file=sys.stderr)
        return 2

    def work() -> int:
        try:
            run(path, dry_run=args.dry_run, out=args.out)
        finally:
            _unload_models()
        return 0

    return heavy_lock.run_locked(KIND, work, say=lambda m: print(m, file=sys.stderr))


if __name__ == "__main__":
    sys.exit(main())
