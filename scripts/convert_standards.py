"""Convert the sentences of chosen standards into proven checks (order 270.3), OFFLINE, on a COPY.

For every stored requirement of each named standard the CLOUD model (Claude Sonnet, the one approved lane:
`ClaudeProvider` -> `reader_transport`, metered in `claude_spend` under `standards_convert:<standard>` at
USD 25 per standard) says whether it applies to the equipment type and, for a numeric limit, which field of
the type's own form, comparator, limit, unit and the exact clause words. Code verifies every answer
(`standards_converter.verify`); the rest is "unproven": "engineer, please look", never a verdict.

STANDARDS TEXT ONLY goes out, and only for the allowed families (SAES, ISO). The database must be a COPY
(`live_guard`: the live path is refused, as in `rehearse_requirement_reextraction.py`). The drafts (JSON +
CSV per standard) go to `--out-dir`, which must be OUTSIDE the repository: they hold clause quotes. Every
file names the sha of the pump form's source (`--form-sha`, the head of #1352 as read).

The run needs the Claude lane open (REASONING_PROVIDER=claude, both STANDARDS_READER_* flags, a key), and
every standard on the owner's approved-documents list. A USD cap, a refusal or a failed call stops the run
CLEANLY: what was finished is written, marked "stopped at cap" or "refused: <code>", and the exit code is 4.
OUTPUT HERE: counts only, never document text.

    python scripts/convert_standards.py --db <copy> --type "Centrifugal Pump" --standard "SAES-G-005" \\
        --out-dir ~/project/mirror/converter --form-sha b54474a2
    python scripts/convert_standards.py --db <copy> --type "Centrifugal Pump" --standard "SAES-G-005" --dry-run
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

from rehearse_requirement_reextraction import refuse_live  # noqa: E402

EXIT_STOPPED = 4
EXIT_LANE_CLOSED = 3


def run(
    db_path: Path,
    equipment_type: str,
    standards: list[str],
    out_dir: Path | None,
    form_sha: str | None,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    provider=None,
) -> dict:
    from app import standard_ids, standards_converter
    from app.config import settings
    from app.db import connect

    for s in (
        standards
    ):  # before the database is even opened: a family not allowed sends nothing
        standards_converter.require_family(s)
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
    for label in chosen.values():
        standards_converter.require_family(label)
    from app import claude_spend

    caps = claude_spend.Caps.from_settings()
    out: dict = {
        "equipment_type": equipment_type,
        "standards_found": len(chosen),
        # the caps this process READ (backend/.env wins over the code defaults), posted with every run
        "caps": {
            "per_standard": float(settings.claude_budget_usd_per_standard),
            "per_other_step": caps.per_step,
            "total": caps.total,
            "total_raised_until": str(claude_spend.TOTAL_RAISED_UNTIL),
        },
        "lane": None,
        "results": [],
        "stopped": False,
    }
    if dry_run:
        for doc_id, label in sorted(chosen.items(), key=lambda kv: kv[1]):
            n = len(standards_converter.requirements_of(conn, doc_id))
            n = min(n, limit) if limit else n
            out["results"].append(
                {
                    "standard": label,
                    "requirements": n,
                    "calls": math.ceil(n / standards_converter.BATCH),
                }
            )
        return out
    if form_sha is None or out_dir is None:
        raise SystemExit("--form-sha and --out-dir are required for a real run")
    standards_converter.refuse_out_dir(out_dir)
    if provider is None:
        from app import reasoning_provider

        code, _why = reasoning_provider.claude_unavailable()
        if code is not None:
            out["lane"] = code
            return out
        provider = reasoning_provider.ClaudeProvider()
    for doc_id, label in sorted(chosen.items(), key=lambda kv: kv[1]):
        result = standards_converter.convert(
            conn, doc_id, label, equipment_type, provider, limit=limit
        )
        files = standards_converter.write(result, out_dir, form_sha=form_sha)
        out["results"].append(
            {
                "standard": label,
                "run": standards_converter.STOPPED_AT_CAP
                if result.stopped_at_cap
                else (f"refused: {result.refused}" if result.refused else "complete"),
                "usd_spent": result.usd,
                "calls": result.calls,
                **result.counts(),
                "files": [f.name for f in files.values()],
            }
        )
        if result.stopped_at_cap or result.refused:
            out["stopped"] = True
            break  # the same limit would stop the next standard: report, do not retry
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--type", required=True, dest="equipment_type")
    ap.add_argument("--standard", action="append", required=True)
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument(
        "--form-sha", help="sha of the pump form's source (the head of #1352 as read)"
    )
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    try:
        result = run(
            args.db,
            args.equipment_type,
            args.standard,
            args.out_dir,
            args.form_sha,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        if type(exc).__name__ in ("FamilyNotAllowed", "ValueError"):
            print(
                json.dumps(
                    {"refused": type(exc).__name__, "message": str(exc)}, indent=1
                )
            )
            return 2
        raise
    print(json.dumps(result, indent=1))
    if result["lane"]:
        return EXIT_LANE_CLOSED
    return EXIT_STOPPED if result["stopped"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
