"""Order 14 lane E (owner, 16 Nov 2026): give a contract's files the CONTRACT kind and the CONTRACT_DOCUMENT role, with the app's
own code, on a COPY first; on the live database only with the owner's yes, a verified backup and a way back.

    python scripts/e14_contract_role.py --db <copy.sqlite> --docs <file of document ids> --out <manifest.json>
    python scripts/e14_contract_role.py --db <live.sqlite> --docs <ids> --out <manifest.json> --live --owner-yes "<his words>"
    python scripts/e14_contract_role.py --db <same db> --undo <manifest.json> [--live --owner-yes "<his words>"]

WHAT IT DOES, per document: `document_kind.classify_contract` (stores the suggested kind "contract" only when the app's general
decision says contract; anything else keeps its kind), then `classification.set_role(..., "CONTRACT_DOCUMENT")` (which runs the
app's own role hooks; a contract never joins the Claude approved list by an automatic route). Before and after, it records each
document's kind row and role in the manifest, and checks that none of the documents is on the approved list.
A LIVE DATABASE goes through `app.live_guard.prepare_live_write` (verified backup, restore drill) and needs --live AND
--owner-yes; without them it is refused. --undo puts back every value the manifest recorded (updates only, nothing deleted).
Prints ids, kinds, roles and counts only.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

ROLE = "CONTRACT_DOCUMENT"


def _state(conn, doc: str) -> dict:
    k = conn.execute(
        "SELECT kind, state, evidence, router_version, routed_at FROM document_kinds WHERE document_id = ?",
        (doc,),
    ).fetchone()
    r = conn.execute(
        "SELECT document_role FROM document_classification WHERE document_id = ?",
        (doc,),
    ).fetchone()
    return {
        "kind_row": dict(k) if k else None,
        "has_classification_row": r is not None,
        "role": r["document_role"] if r else None,
    }


def _approved(docs: list[str]) -> list[str]:
    """The documents among `docs` whose checksum is on the Claude approved list."""
    from app import claude_approved
    from app.db import connect

    hashes = claude_approved.approved_hashes()
    rows = (
        connect()
        .execute(
            f"SELECT id, sha256 FROM documents WHERE id IN ({','.join('?' * len(docs))})",
            docs,
        )
        .fetchall()
    )
    return [r["id"] for r in rows if (r["sha256"] or "").lower() in hashes]


def _open(db: Path, live: bool, owner_yes: str | None, reason: str) -> str | None:
    from app import db as dbmod
    from app import live_guard
    from app.config import settings

    backup = None
    if live_guard.is_live_shaped(db):
        if not live or not (owner_yes or "").strip():
            raise SystemExit(
                'refusing: a live database needs --live and --owner-yes "<the owner\'s words>"'
            )
        backup = live_guard.prepare_live_write(db, reason=reason).backup_path
    elif live:
        raise SystemExit("refusing: --live given but this is not a live database")
    settings.db_path, settings.data_dir = db, db.parent
    dbmod.reset_connection()
    return backup


def apply(
    db: Path, docs: list[str], out: Path, live: bool, owner_yes: str | None
) -> dict:
    backup = _open(
        db,
        live,
        owner_yes,
        "order 14 lane E: contract kind and CONTRACT_DOCUMENT role on the contract's files",
    )
    from app import classification, document_kind
    from app.config import settings
    from app.db import connect

    settings.claude_auto_approve_reviews_enabled = (
        True  # the worst case: even with the standing approval on
    )
    conn = connect()
    before = {d: _state(conn, d) for d in docs}
    decided = {}
    for d in docs:
        ev = document_kind.classify_contract(d)
        decided[d] = ev.method if ev else None
        classification.set_role(d, ROLE)
    conn = connect()
    after = {d: _state(conn, d) for d in docs}
    manifest = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "db": str(db),
        "live": bool(backup),
        "backup": backup,
        "owner_yes": owner_yes,
        "documents": docs,
        "before": before,
        "after": after,
        "kind_decided_by": decided,
        "approved_for_claude_after": _approved(docs),
    }
    out.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def undo(db: Path, manifest_path: Path, live: bool, owner_yes: str | None) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _open(db, live, owner_yes, f"order 14 lane E: undo {manifest_path.name}")
    from app.db import connect

    conn = connect()
    with conn:
        for d, was in manifest["before"].items():
            k = was["kind_row"]
            if k is not None:
                conn.execute(
                    "UPDATE document_kinds SET kind = ?, state = ?, evidence = ?, router_version = ?, routed_at = ?"
                    " WHERE document_id = ?",
                    (
                        k["kind"],
                        k["state"],
                        k["evidence"],
                        k["router_version"],
                        k["routed_at"],
                        d,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE document_kinds SET kind = NULL, state = 'needs_engineer' WHERE document_id = ?",
                    (d,),
                )
            conn.execute(
                "UPDATE document_classification SET document_role = ? WHERE document_id = ?",
                (was["role"], d),
            )
    conn = connect()
    return {d: _state(conn, d) for d in manifest["before"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--docs", type=Path, help="a file with one document id per line")
    ap.add_argument(
        "--out", type=Path, help="the manifest (before, after, backup) to write"
    )
    ap.add_argument("--undo", type=Path, help="a manifest to put back")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--owner-yes")
    a = ap.parse_args(argv)
    db = a.db.resolve()
    if a.undo:
        back = undo(db, a.undo, a.live, a.owner_yes)
        for d, s in back.items():
            print(f"{d} kind {(s['kind_row'] or {}).get('kind')} role {s['role']}")
        return 0
    if not a.docs or not a.out:
        ap.error("--docs and --out are needed")
    docs = [x.strip() for x in a.docs.read_text(encoding="utf-8").split() if x.strip()]
    m = apply(db, docs, a.out, a.live, a.owner_yes)
    for d in docs:
        b, f = m["before"][d], m["after"][d]
        print(
            f"{d} kind {(b['kind_row'] or {}).get('kind')}/{(b['kind_row'] or {}).get('state')} -> "
            f"{(f['kind_row'] or {}).get('kind')}/{(f['kind_row'] or {}).get('state')} role {b['role']} -> {f['role']}"
        )
    print(
        f"approved for Claude after: {m['approved_for_claude_after'] or 'none'}; backup: {m['backup'] or 'not live'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
