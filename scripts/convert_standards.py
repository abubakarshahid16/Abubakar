"""Convert the sentences of chosen standards into proven checks (orders 270.3, 277.1), OFFLINE, on a COPY.

For every stored requirement of each named standard a model says whether it applies to the equipment type and,
for a numeric limit, which field of the type's own form, comparator, limit, unit and the exact clause words.
Code verifies every answer (`standards_converter.verify`); the rest is "unproven": "engineer, please look",
never a verdict.

TWO LANES, ONE PROOF (owner, 28 Oct, order 277: no Claude API for now):
  --lane local   (the default) the Mac's own engine, through `reasoning_provider.OllamaProvider` and
                 `model_transport`. `--engine-url` names the TEST engine (never the live app's port 11434);
                 the model is the one the engine reports as running (`/api/ps`), or `--model`; never `.env`.
                 `claude_spend`, the approved-documents list and `reader_transport` are not used.
  --lane claude  built and kept, OFF unless asked for: Claude Sonnet through `ClaudeProvider` under
                 `claude_spend` (USD 25 per standard), SAES and ISO standards text only, the owner's
                 approved-documents list, REASONING_PROVIDER=claude, both STANDARDS_READER_* flags and a key.
A refused, failed or capped call stops the run CLEANLY: what was finished is written, the rest is
"not asked: <why>", and the run never retries into the other lane (exit code 4).

The database must be a COPY (`live_guard`: the live path is refused, as in `rehearse_requirement_reextraction.py`).
The drafts (JSON + CSV per standard) go to `--out-dir`, which must be OUTSIDE the repository: they hold clause
quotes. Every file names the lane, the model tag the engine reports and the sha of the pump form's source
(`--form-sha`, the head of #1352 as read). OUTPUT HERE: counts only, never document text.

    python scripts/convert_standards.py --db <copy> --type "Centrifugal Pump" --standard "SAES-K-503" \\
        --engine-url http://127.0.0.1:11435 --out-dir ~/project/mirror/converter --form-sha b54474a2
    python scripts/convert_standards.py --db <copy> --type "Centrifugal Pump" --standard "SAES-K-503" --dry-run
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

from rehearse_requirement_reextraction import refuse_live  # noqa: E402

EXIT_STOPPED = 4
EXIT_LANE_CLOSED = 3
#: The port of the live app's engine: the converter never uses it.
LIVE_ENGINE_PORT = 11434
#: Requirements per call. The local 35B reads a few sentences a call; Claude a dozen.
LOCAL_BATCH, CLAUDE_BATCH = 6, 12
#: Seconds one local call may take before it counts as failed (the run then stops, nothing is retried).
LOCAL_TIMEOUT_S = 900.0


def running_model() -> str:
    """The one model the engine says is loaded (`/api/ps`); anything else is the operator's to name."""
    from app import model_transport

    ps = model_transport.get_json("/api/ps", timeout=10.0, required=False) or {}
    names = [str(m.get("name") or m.get("model") or "") for m in ps.get("models") or []]
    names = [n for n in names if n]
    if len(names) != 1:
        raise ValueError(
            f"the engine reports {len(names)} loaded models; name the one to use with --model"
        )
    return names[0]


def local_provider(engine_url: str, model: str | None, timeout: float):
    """`OllamaProvider` on the named engine. Refuses the live app's port and any URL
    `config.check_model_url` refuses (loopback only); the model comes from the engine, not from `.env`."""
    from app import reasoning_provider
    from app.config import check_model_url, settings

    if urlsplit(engine_url).port == LIVE_ENGINE_PORT:
        raise ValueError(
            f"refusing: port {LIVE_ENGINE_PORT} is the live app's engine; name the test engine"
        )
    check_model_url(engine_url)
    settings.ollama_url = engine_url
    return reasoning_provider.OllamaProvider(model or running_model(), timeout=timeout)


def _documents(conn, standards: list[str]) -> dict[str, str]:
    """{document id: label} of the company standards named."""
    from app import standard_ids

    docs = {
        r["id"]: r["document_number"] or r["filename"]
        for r in conn.execute(
            "SELECT d.id, d.filename, c.document_number FROM documents d"
            " JOIN document_classification c ON c.document_id = d.id"
            " WHERE c.document_role = 'COMPANY_STANDARD'"
        )
    }
    chosen: dict[str, str] = {}
    for wanted in standards:
        found = {i: n for i, n in docs.items() if standard_ids.same_standard(wanted, n)}
        if len(found) > 1:
            # a name that fits several standards must not pick them all (s2's dry run: "ISO-15156-3" fit 3)
            exact = {
                i: n
                for i, n in found.items()
                if standard_ids.flat_key(n) == standard_ids.flat_key(wanted)
            }
            if len(exact) != 1:
                raise ValueError(
                    f"{wanted!r} matches {len(found)} standards ({', '.join(sorted(found.values()))});"
                    " name exactly one of them"
                )
            found = exact
        chosen.update(found)
    return chosen


def _caps() -> dict:
    """The Claude caps this process READ (backend/.env wins over the code defaults)."""
    from app import claude_spend
    from app.config import settings

    caps = claude_spend.Caps.from_settings()
    return {
        "per_standard": float(settings.claude_budget_usd_per_standard),
        "per_other_step": caps.per_step,
        "total": caps.total,
        "total_raised_until": str(claude_spend.TOTAL_RAISED_UNTIL),
    }


def _provider_for(lane: str, engine_url, model, timeout, out: dict):
    """The lane's provider, or None (with `out["lane_closed"]` set) when the Claude lane is not open."""
    if lane == "local":
        if not engine_url:
            raise ValueError(
                "--engine-url is required on the local lane (the test engine, not port 11434)"
            )
        return local_provider(engine_url, model, timeout)
    from app import reasoning_provider

    code, _why = reasoning_provider.claude_unavailable()
    if code is not None:
        out["lane_closed"] = code
        return None
    return reasoning_provider.ClaudeProvider()


def _run_one(
    conn, doc_id, label, equipment_type, provider, lane, out_dir, form_sha, limit, batch
) -> tuple[dict, bool]:
    from app import standards_converter as sc

    result = sc.convert(
        conn,
        doc_id,
        label,
        equipment_type,
        provider,
        limit=limit,
        batch=batch,
        lane=lane,
    )
    files = sc.write(result, out_dir, form_sha=form_sha)
    if result.stopped_at_cap:
        run = sc.STOPPED_AT_CAP
    else:
        run = f"refused: {result.refused}" if result.refused else "complete"
    row = {
        "standard": label,
        "run": run,
        "lane": lane,
        "model": result.model,
        "usd_spent": result.usd,
        "calls": result.calls,
        **result.counts(),
        "files": [f.name for f in files.values()],
    }
    return row, bool(result.stopped_at_cap or result.refused)


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
    lane: str = "local",
    engine_url: str | None = None,
    model: str | None = None,
    batch: int | None = None,
    call_timeout: float = LOCAL_TIMEOUT_S,
) -> dict:
    from app import standards_converter
    from app.config import settings
    from app.db import connect

    if lane not in standards_converter.LANES:
        raise ValueError(
            f"unknown lane {lane!r}; expected one of {standards_converter.LANES}"
        )
    claude = lane == "claude"
    if claude:  # before the database is even opened: a family not allowed sends nothing
        for s in standards:
            standards_converter.require_family(s)
    settings.db_path = refuse_live(db_path)
    conn = connect()
    chosen = _documents(conn, standards)
    if claude:
        for label in chosen.values():
            standards_converter.require_family(label)
    size = batch or (CLAUDE_BATCH if claude else LOCAL_BATCH)
    out: dict = {
        "equipment_type": equipment_type,
        "lane": lane,
        "standards_found": len(chosen),
        "batch": size,
        # the caps this process read matter only to the Claude lane
        "caps": _caps() if claude else None,
        "lane_closed": None,
        "results": [],
        "stopped": False,
    }
    ordered = sorted(chosen.items(), key=lambda kv: kv[1])
    if dry_run:
        for doc_id, label in ordered:
            n = len(standards_converter.requirements_of(conn, doc_id))
            n = min(n, limit) if limit else n
            out["results"].append(
                {"standard": label, "requirements": n, "calls": math.ceil(n / size)}
            )
        return out
    if form_sha is None or out_dir is None:
        raise SystemExit("--form-sha and --out-dir are required for a real run")
    standards_converter.refuse_out_dir(out_dir)
    provider = provider or _provider_for(lane, engine_url, model, call_timeout, out)
    if provider is None:
        return out
    for doc_id, label in ordered:
        row, stopped = _run_one(
            conn,
            doc_id,
            label,
            equipment_type,
            provider,
            lane,
            out_dir,
            form_sha,
            limit,
            size,
        )
        out["results"].append(row)
        if stopped:
            out["stopped"] = True
            break  # the same limit would stop the next standard: report, do not retry, never another lane
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--type", required=True, dest="equipment_type")
    ap.add_argument("--standard", action="append", required=True)
    ap.add_argument("--lane", choices=("local", "claude"), default="local")
    ap.add_argument(
        "--engine-url",
        help="the TEST engine's URL (local lane), e.g. http://127.0.0.1:11435",
    )
    ap.add_argument(
        "--model",
        help="the model to use when the engine reports none or several loaded",
    )
    ap.add_argument("--batch", type=int, help="requirements per call")
    ap.add_argument("--call-timeout", type=float, default=LOCAL_TIMEOUT_S)
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
            lane=args.lane,
            engine_url=args.engine_url,
            model=args.model,
            batch=args.batch,
            call_timeout=args.call_timeout,
        )
    except Exception as exc:
        if type(exc).__name__ in ("FamilyNotAllowed", "ValueError", "ModelHostRefused"):
            print(
                json.dumps(
                    {"refused": type(exc).__name__, "message": str(exc)}, indent=1
                )
            )
            return 2
        raise
    print(json.dumps(result, indent=1))
    if result["lane_closed"]:
        return EXIT_LANE_CLOSED
    return EXIT_STOPPED if result["stopped"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
