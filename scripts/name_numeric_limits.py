"""Name the numeric limits of the held standards against the closed vocabulary (order 259.5).

OFFLINE PASS ON A COPY. For every numeric requirement of every COMPANY_STANDARD in the database given,
the LOCAL model answers one number of the closed vocabulary (`field_vocabulary.vocabulary()`: the
synonym table's canonical phrases plus the numeric checklist roles) and a quote; `field_naming`'s three
gates (and the synonym-aware third gate) keep or drop it; every answer, mapped or not, is stored in
`canonical_field_names` as model-named and unconfirmed, with provider, model and prompt hash. Nothing
else in the database changes. Re-running asks only what is not stored yet.

IT REFUSES THE LIVE DATABASE (a live-shaped path or this checkout's live file), exactly as
`rehearse_requirement_reextraction.py` does: make the copy first (`live_guard.diagnostic_copy()`).
IT USES THE LOCAL ENGINE ONLY (`OllamaProvider`): no Claude, no document leaves the machine.

Output: counts only (asked, named, unmapped, by standard document id), never document text.

    python scripts/name_numeric_limits.py --db <copy>/rehearsal.sqlite [--doc ID] [--limit N] [--json out.json]
    python scripts/name_numeric_limits.py --db <copy> --dry-run       # counts the work, asks nothing
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
    *,
    doc: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    provider=None,
) -> dict:
    from app import field_naming, field_vocabulary
    from app.config import settings
    from app.db import connect

    settings.db_path = refuse_live(db_path)
    conn = connect()
    where = "r.requirement_type IN ('numeric_limit','table_row','relative_limit') AND d.id IS NOT NULL"
    args: list = []
    if doc:
        where += " AND r.standard_document_id = ?"
        args.append(doc)
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT r.id, r.standard_document_id, r.requirement_type, r.requirement_text FROM"
            " standard_requirements r JOIN documents d ON d.id = r.standard_document_id"
            " JOIN document_classification c ON c.document_id = d.id"
            f" WHERE c.document_role = 'COMPANY_STANDARD' AND r.superseded_at IS NULL AND {where}"
            " ORDER BY r.standard_document_id, r.id",
            args,
        )
    ]
    if limit:
        rows = rows[:limit]
    vocab = field_vocabulary.vocabulary()
    stored = field_naming.stored_names(
        field_vocabulary.REQUIREMENT, [str(r["id"]) for r in rows], vocab
    )
    todo = [r for r in rows if str(r["id"]) not in stored]
    out = {
        "database": str(settings.db_path),
        "vocabulary": len(vocab),
        "numeric_requirements": len(rows),
        "already_stored": len(rows) - len(todo),
        "to_ask": len(todo),
        "asked": 0,
        "named": 0,
        "unmapped": 0,
        "by_standard": {},
        "refused": None,
    }
    if dry_run or not todo:
        return out
    if provider is None:
        from app.reasoning_provider import OllamaProvider

        provider = OllamaProvider()  # the LOCAL engine only
    try:
        field_vocabulary.name_requirements(todo, provider)
    except Exception as exc:  # noqa: BLE001 - a refused or failed batch keeps what was stored so far
        out["refused"] = type(exc).__name__
    after = field_naming.stored_names(
        field_vocabulary.REQUIREMENT, [str(r["id"]) for r in rows], vocab
    )
    for r in rows:
        sid = r["standard_document_id"]
        bucket = out["by_standard"].setdefault(sid, {"numeric": 0, "named": 0})
        bucket["numeric"] += 1
        if (after.get(str(r["id"])) or {}).get("field_name"):
            bucket["named"] += 1
    out["asked"] = sum(1 for r in todo if str(r["id"]) in after)
    out["named"] = sum(b["named"] for b in out["by_standard"].values())
    out["unmapped"] = len(after) - out["named"]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--doc")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    result = run(args.db, doc=args.doc, limit=args.limit, dry_run=args.dry_run)
    text = json.dumps(result, indent=1)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
