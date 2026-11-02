"""#1584: compile held standards into version 2 rules with Claude, OFFLINE, on a COPY of the database.

Every proposal is verified by code (`standards_compiler.verify`); the rules are stored apart and held until the
owner approves them: nothing here changes a verdict. Version 1 (`standard_requirements`) is not written.

    python scripts/compile_standards.py --db <copy> --standard SAES-X-000 --estimate-only
    python scripts/compile_standards.py --db <copy> --standard SAES-X-000 --max-usd 25
    python scripts/compile_standards.py --db <copy> --standard SAES-X-000 --side-by-side

Needs STANDARDS_COMPILER_ENABLED, REASONING_PROVIDER=claude or per_task, both STANDARDS_READER_* flags, a key, and
each standard on the approved list. A run that stops while a batch is open is run again with the same command: it
polls that batch and does not pay again. A live-shaped --db is refused. Output: counts only, never document text.

Exit: 0 done; 3 lane shut or switch off; 4 refused or over a budget (nothing sent); 5 a batch is still running
(run it again); 6 a create is unconfirmed (see --resend-unconfirmed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

from convert_standards import _documents  # noqa: E402
from rehearse_requirement_reextraction import refuse_live  # noqa: E402

EXIT_CLOSED, EXIT_REFUSED, EXIT_WAITING, EXIT_UNCONFIRMED = 3, 4, 5, 6
ESTIMATE_WORDS = (
    "worst case before sending, one standard, every prompt token a cache write and every "
    "allowed output token spent, batch price: "
)


def _chosen(conn, wanted: list[str]) -> dict[str, str]:
    """{document id: label} for each name: a document id as it stands, else a standard's number."""
    out: dict[str, str] = {}
    for name in wanted:
        row = conn.execute(
            "SELECT d.id, COALESCE(c.document_number, d.filename) AS label FROM documents d"
            " LEFT JOIN document_classification c ON c.document_id = d.id WHERE d.id = ?",
            (name,),
        ).fetchone()
        if row is not None:
            out[row["id"]] = row["label"]
            continue
        found = _documents(conn, [name])
        if not found:
            raise SystemExit(f"no standard named {name!r} in this database")
        out.update(found)
    return out


def run(
    db_path: Path,
    wanted: list[str],
    *,
    max_usd: float | None = None,
    estimate_only: bool = False,
    side_by_side: bool = False,
    poll_seconds: float = 60.0,
    max_wait_s: float = 86400.0,
    resend_unconfirmed: bool = False,
    client=None,
    sleep=None,
    emit=print,
) -> int:
    from app.config import settings

    if not settings.standards_compiler_enabled:
        emit("STANDARDS_COMPILER_ENABLED is off: nothing was read or sent.")
        return EXIT_CLOSED
    settings.db_path = refuse_live(db_path)
    from app import (
        claude_spend,
        reasoning_provider,
        standards_compiler,
        standards_converter,
    )
    from app.db import connect

    conn = connect()
    documents = _chosen(conn, wanted)
    if side_by_side:
        emit(
            json.dumps(
                standards_compiler.side_by_side(conn, documents),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if not estimate_only:
        code, why = reasoning_provider.claude_unavailable_for_task("claude")
        if code is not None:
            emit(f"the Claude lane is shut ({code}: {why}); nothing was sent.")
            return EXIT_CLOSED
    kw = {"sleep": sleep} if sleep is not None else {}
    worst = 0
    for document_id, label in sorted(documents.items(), key=lambda kv: kv[1]):
        try:
            report = standards_compiler.compile_standard(
                conn,
                document_id,
                label,
                client=client,
                max_usd=max_usd,
                estimate_only=estimate_only,
                on_estimate=lambda e: emit(
                    ESTIMATE_WORDS + json.dumps(e, sort_keys=True)
                ),
                poll_seconds=poll_seconds,
                max_wait_s=max_wait_s,
                resend_unconfirmed=resend_unconfirmed,
                **kw,
            )
        except (
            claude_spend.StopRun,
            standards_converter.FamilyNotAllowed,
            standards_converter.NotStandardsText,
            reasoning_provider.ProviderRefused,
        ) as exc:
            emit(f"{label}: refused, nothing further was sent: {exc}")
            return EXIT_REFUSED
        emit(json.dumps(report, indent=2, sort_keys=True))
        if report["status"] == "waiting":
            worst = max(worst, EXIT_WAITING)
        elif report["status"] == "unconfirmed":
            worst = max(worst, EXIT_UNCONFIRMED)
    return worst


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", maxsplit=1)[0])
    ap.add_argument(
        "--db", required=True, type=Path, help="a COPY; a live-shaped path is refused"
    )
    ap.add_argument(
        "--standard",
        action="append",
        required=True,
        help="a document id or a standard's number",
    )
    ap.add_argument(
        "--max-usd",
        type=float,
        help="limit on today's compile spend plus this send's worst case; default the owner's USD 100 a day",
    )
    ap.add_argument(
        "--estimate-only",
        action="store_true",
        help="print the worst case and send nothing",
    )
    ap.add_argument(
        "--side-by-side",
        action="store_true",
        help="version 1 beside version 2, counts only",
    )
    ap.add_argument("--poll-seconds", type=float, default=60.0)
    ap.add_argument("--max-wait-minutes", type=float, default=1440.0)
    ap.add_argument(
        "--resend-unconfirmed",
        action="store_true",
        help="send again the requests whose create was never confirmed (the API may bill both)",
    )
    args = ap.parse_args(argv)
    return run(
        args.db,
        args.standard,
        max_usd=args.max_usd,
        estimate_only=args.estimate_only,
        side_by_side=args.side_by_side,
        poll_seconds=args.poll_seconds,
        max_wait_s=args.max_wait_minutes * 60,
        resend_unconfirmed=args.resend_unconfirmed,
    )


if __name__ == "__main__":
    sys.exit(main())
