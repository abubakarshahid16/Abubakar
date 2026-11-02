"""#1584: compile held standards into version 2 rules with Claude, OFFLINE, on a COPY of the database.

Every proposal is verified by code (`standards_compiler.verify`); the rules are stored apart and held until the
owner approves them: nothing here changes a verdict. Version 1 (`standard_requirements`) is not written.

    python scripts/compile_standards.py --db <copy> --standard SAES-X-000 --estimate-only
    python scripts/compile_standards.py --db <copy> --standard SAES-X-000 --max-usd 25
    python scripts/compile_standards.py --db <copy> --standard SAES-X-000 --side-by-side

Needs STANDARDS_COMPILER_ENABLED, REASONING_PROVIDER=claude or per_task, both STANDARDS_READER_* flags, a key, and
each standard on the approved list. A run that stops while a batch is open is run again with the same command: it
polls that batch and does not pay again. A live-shaped --db is refused. Output: counts only, never document text.

Stdout is exactly one line of JSON, the result, whatever happens. The estimate and every log line go to stderr.

Exit: 0 done; 3 lane shut or switch off; 4 refused or over a budget (nothing sent); 5 a batch is still running
(run it again); 6 a create is unconfirmed (see --resend-unconfirmed); 7 a standard has no usable page: not compiled;
8 a cap stopped a standard part way: partial, its pages not read are listed; run it again later.
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

from convert_standards import _documents  # noqa: E402
from rehearse_requirement_reextraction import refuse_live  # noqa: E402

EXIT_CLOSED, EXIT_REFUSED, EXIT_WAITING, EXIT_UNCONFIRMED = 3, 4, 5, 6
EXIT_NOT_COMPILED, EXIT_PARTIAL = 7, 8
EXIT_BY_STATUS = {
    "waiting": EXIT_WAITING,
    "unconfirmed": EXIT_UNCONFIRMED,
    "not_compiled": EXIT_NOT_COMPILED,
    "partial": EXIT_PARTIAL,
}
BOUNDARY = "the standards named on this command line, this database copy only"
ESTIMATE_WORDS = (
    "worst case before sending, one standard, every prompt token a cache write and every "
    "allowed output token spent, batch price: "
)


def _to_stderr(words: str) -> None:
    print(words, file=sys.stderr)


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


def _compile_all(conn, documents, note, **kw) -> tuple[list[dict], int, str | None]:
    """(reports, exit code, why it stopped). All the named standards go in one batch; a refusal sends nothing further."""
    from app import (
        claude_spend,
        reasoning_provider,
        standards_compiler,
        standards_converter,
    )

    try:
        reports = standards_compiler.compile_many(
            conn,
            documents,
            on_estimate=lambda e: note(ESTIMATE_WORDS + json.dumps(e, sort_keys=True)),
            **kw,
        )
    except (
        claude_spend.StopRun,
        standards_converter.FamilyNotAllowed,
        standards_converter.NotStandardsText,
        reasoning_provider.ProviderRefused,
    ) as exc:
        return [], EXIT_REFUSED, f"refused, nothing further was sent: {exc}"
    code = max((EXIT_BY_STATUS.get(r["status"], 0) for r in reports), default=0)
    return reports, code, None


def _final_line(reports: list[dict], stopped: str | None) -> str:
    """THE one line on stdout: counts only, every total with its boundary."""
    from app import claude_batch_run

    estimates = [r.get("estimate") or {} for r in reports]
    worst = sum(float(e.get("worst_usd") or 0) for e in estimates)
    normal = sum(float(e.get("worst_usd_normal_price") or 0) for e in estimates)
    capped = sum(float(e.get("normal_price_stops_at_usd") or 0) for e in estimates)
    requests = sum(int(e.get("requests") or 0) for e in estimates)
    chars = sum(int(e.get("request_chars") or 0) for e in estimates)
    return json.dumps(
        {
            "boundary": BOUNDARY,
            "standards": reports,
            "requests_total": requests,
            "batches_needed": claude_batch_run.batches_needed(requests, chars * 3),
            "worst_usd_total": round(worst, 4),
            "fallback_worst_usd_normal_price_total": round(normal, 4),
            "fallback_stops_at_usd_total": round(capped, 4),
            "stopped": stopped,
        },
        sort_keys=True,
    )


def run(
    db_path: Path,
    wanted: list[str],
    *,
    max_usd: float | None = None,
    estimate_only: bool = False,
    side_by_side: bool = False,
    reverify: bool = False,
    prompt_version: str | None = None,
    poll_seconds: float = 60.0,
    max_wait_s: float = 86400.0,
    resend_unconfirmed: bool = False,
    client=None,
    send=None,
    clock=None,
    fallback_after_s: float | None = None,
    release_holds: bool = False,
    sleep=None,
    emit=print,
    note=_to_stderr,
) -> int:
    """`emit` gets exactly one line of JSON, whatever happens; `note` gets the words on the way."""
    from app.config import settings

    if not settings.standards_compiler_enabled:
        emit(
            _final_line(
                [], "STANDARDS_COMPILER_ENABLED is off: nothing was read or sent."
            )
        )
        return EXIT_CLOSED
    settings.db_path = refuse_live(db_path)
    from app import reasoning_provider, standards_compiler
    from app.db import connect

    conn = connect()
    documents = _chosen(conn, wanted)
    if side_by_side:
        emit(
            json.dumps(standards_compiler.side_by_side(conn, documents), sort_keys=True)
        )
        return 0
    if reverify:  # sends nothing: no lane, no key, no budget
        try:
            reports = [
                standards_compiler.reverify_stored(conn, d, label, prompt_version)
                for d, label in sorted(documents.items(), key=lambda kv: kv[1])
            ]
        except standards_compiler.NotHeld as exc:
            emit(_final_line([], f"refused: {exc}"))
            return EXIT_REFUSED
        emit(_final_line(reports, None))
        return max((EXIT_BY_STATUS.get(r["status"], 0) for r in reports), default=0)
    if not estimate_only:
        code, why = reasoning_provider.claude_unavailable_for_task("claude")
        if code is not None:
            emit(
                _final_line(
                    [], f"the Claude lane is shut ({code}: {why}); nothing was sent."
                )
            )
            return EXIT_CLOSED
    reports, exit_code, stopped = _compile_all(
        conn,
        documents,
        note,
        client=client,
        send=send,
        fallback_after_s=fallback_after_s,
        release_holds=release_holds,
        max_usd=max_usd,
        estimate_only=estimate_only,
        poll_seconds=poll_seconds,
        max_wait_s=max_wait_s,
        resend_unconfirmed=resend_unconfirmed,
        **({"sleep": sleep} if sleep is not None else {}),
        **({"clock": clock} if clock is not None else {}),
    )
    emit(_final_line(reports, stopped))
    return exit_code


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
        "--fallback-after-minutes",
        type=float,
        help="off by default. A batch older than this is cancelled and, once it has ended, what it did not answer is sent "
        "at the normal price (about twice), inside the same caps; what does not fit is not sent and is named",
    )
    ap.add_argument(
        "--release-left-over-holds",
        action="store_true",
        help="release holds on these standards that nothing in this copy owns, at any age; only when no other copy is running",
    )
    ap.add_argument(
        "--reverify",
        action="store_true",
        help="prove the stored answers again with the current code; sends nothing, USD 0",
    )
    ap.add_argument(
        "--prompt-version",
        help="with --reverify: read the stored answers of this prompt version",
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
    real_stdout = sys.stdout
    with contextlib.redirect_stdout(
        sys.stderr
    ):  # anything else printed is a log line, not the result
        return _run_args(args, lambda line: print(line, file=real_stdout))


def _run_args(args, emit) -> int:
    return run(
        args.db,
        args.standard,
        max_usd=args.max_usd,
        estimate_only=args.estimate_only,
        side_by_side=args.side_by_side,
        release_holds=args.release_left_over_holds,
        fallback_after_s=args.fallback_after_minutes * 60
        if args.fallback_after_minutes
        else None,
        reverify=args.reverify,
        prompt_version=args.prompt_version,
        poll_seconds=args.poll_seconds,
        max_wait_s=args.max_wait_minutes * 60,
        resend_unconfirmed=args.resend_unconfirmed,
        emit=emit,
    )


if __name__ == "__main__":
    sys.exit(main())
