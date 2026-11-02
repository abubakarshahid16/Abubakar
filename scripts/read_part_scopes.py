"""Ask Claude for each Part's scope sentence of one standard, on a COPY, so `rule_part_scope` can read it.

    python scripts/read_part_scopes.py --db <copy> --standard <name or id> --type "<equipment type>"
    python scripts/read_part_scopes.py --db <copy> --standard <name or id> --type "<equipment type>" --send

Without --send it is dry: it prints the worst case and what would refuse, sends nothing and needs no key. --send asks,
under a hard job cap in code (`JOB_CAP_USD`), and stops before sending if the worst case is above it. Run
again it asks only what has no stored answer. A live-shaped --db is refused. Stdout is one line of JSON, counts only.

Exit: 0 dry, or every Part answered; 3 refused by a gate; 4 worst case above the cap; 5 partial: the report says what.

AI READS, CODE VERIFIES. A reply is checked against its passage before it is stored (`CLAUDE_READ_TASK.check`), with one
corrective ask, and `rule_part_scope` verifies the sentence on the Part's page exactly as for a local answer. It is one
more reading, not a better one: a reading that disagrees with a stored one leaves the rule UNKNOWN (a Query), and this
says how many.

DRY BY DEFAULT. A dry run builds every prompt, prints the worst case and says which gate would refuse. It sends nothing
and needs no key. A send takes `AI_DIVISION_SCOPE_ENGINE=claude` under the provider switch, `standards_compiler`'s gates
(its switch, the family, the role, the approved list), and both egress flags and a key, checked again per request.

THE CAP IS THE JOB'S, IN CODE. The worst case of every first ask must fit before anything leaves, or nothing does. Before
each ask, what this job's step has spent on the ledger plus that ask's worst case must fit, so a corrective ask or a failed
call can never carry the job over, and a second run shares the same cap. Each call goes `reader_transport` through
`claude_spend.metered`: reserved first, settled after, stored answers free, the owner's caps on top.

ON A COPY, once per Part: a stored answer is not asked again or overwritten. Standards text only. Counts only in a report.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

from compile_standards import _chosen  # noqa: E402
from rehearse_requirement_reextraction import refuse_live  # noqa: E402

from app import (  # noqa: E402
    ai_task_runner,
    claude_approved,
    claude_spend,
    reader_api,
    reasoning_provider,
    rule_part_scope,
    standards_compiler,
)
from app.ai.json_reply import unfenced  # noqa: E402
from app.config import settings  # noqa: E402
from app.rule_part_scope import CLAUDE_READ_TASK  # noqa: E402

#: The owner's limit for this job, USD (2 Nov 2026). No flag raises it.
JOB_CAP_USD = 3.73
STEP_PREFIX = "part_scope_read:"
TIMEOUT_S = 120.0
#: The corrective sentence is fixed words and a few fixed reasons; this covers it in a worst case.
_CORRECTIVE_CHARS = 400
DRY, OVER_CAP, DONE, PARTIAL, REFUSED = (
    "dry",
    "over_cap",
    "done",
    "partial",
    "refused",
)


def _prompt(passage: str) -> str:
    schema = json.dumps(CLAUDE_READ_TASK.schema, separators=(",", ":"))
    return (
        f"{CLAUDE_READ_TASK.prompt(passage)}\n\nReturn ONLY one JSON value that satisfies this JSON schema, with no"
        f" other text:\n{schema}"
    )


def _worst(model: str, chars: int) -> float:
    return claude_spend.worst_case_usd(model, chars, CLAUDE_READ_TASK.num_predict)


def _worst_of_prompt(model: str, prompt: str) -> float:
    messages = [{"role": "user", "content": prompt}]
    return _worst(model, len(json.dumps(messages, ensure_ascii=False)) + 2)


def _stored(conn, model: str, passage: str) -> bool:
    key = ai_task_runner.cache_key(CLAUDE_READ_TASK, model, passage)
    return (
        conn.execute("SELECT 1 FROM ai_task_cache WHERE key = ?", (key,)).fetchone()
        is not None
    )


def _store(conn, model: str, passage: str, data: dict) -> None:
    spec = CLAUDE_READ_TASK
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO ai_task_cache (key, task, version, model, result_json, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (
                ai_task_runner.cache_key(spec, model, passage),
                spec.name,
                spec.version,
                model,
                json.dumps(data, sort_keys=True),
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            ),
        )


def _capped(send, step: str, cap: float):
    """`send` that refuses a call whose worst case, on what this job's step has spent, could cross the job's cap."""

    def guarded(url, *, headers, body, timeout):
        chars = len(
            json.dumps(body.get("messages") or [], ensure_ascii=False, default=str)
        ) + len(json.dumps(body.get("system") or "", ensure_ascii=False, default=str))
        worst = claude_spend.worst_case_usd(
            str(body.get("model") or ""), chars, int(body.get("max_tokens") or 0)
        )
        spent = claude_spend.step_spent(step)
        if spent + worst > cap:
            raise claude_spend.BudgetExceeded(
                f"this job's cap of USD {cap} would be crossed; the call was not made"
            )
        return send(url, headers=headers, body=body, timeout=timeout)

    return guarded


def _gate_refusal(conn, document_id: str, label: str) -> str | None:
    """What would refuse this job, or None. Sends nothing."""
    try:
        standards_compiler.require_allowed(conn, document_id, label)
    except Exception as exc:  # noqa: BLE001 - each of the gate's refusals carries its reason, with ids only
        return f"{type(exc).__name__}: {exc}"
    code, why = reasoning_provider.claude_unavailable_for_task(
        settings.ai_division_scope_engine
    )
    return f"{code}: {why}" if code is not None else None


def _sender(document_id: str, cap: float, keep_if, send):
    """A `(prompt) -> text` on the metered lane. `send`: a test's transport; else `reader_transport`'s."""
    from app import reader_transport

    transport = send or reader_transport.transport()
    if transport is None:
        raise reasoning_provider.ProviderRefused(
            "claude: egress is disabled (STANDARDS_READER_ENABLED / STANDARDS_READER_ALLOW_PUBLIC_EGRESS)"
        )
    step = f"{STEP_PREFIX}{document_id}"
    metered = claude_spend.metered(
        transport,
        step,
        unbilled=reader_transport.unbilled,
        version=CLAUDE_READ_TASK.version,
        keep_if=keep_if,
    )
    guarded = _capped(metered, step, cap)
    return guarded


def _parsed(text: str, passage: str) -> tuple[dict | None, list[str]]:
    try:
        data = json.loads(unfenced(text))
    except (ValueError, TypeError):
        return None, ["the reply was not JSON"]
    if not isinstance(data, dict) or data.get("limited") not in ("yes", "no", "unsure"):
        return None, ["the reply did not answer the question"]
    return data, CLAUDE_READ_TASK.check(data, passage)


def _read_one(conn, part: dict, model: str, cfg, make_send, counts: dict) -> None:
    """One Part: an ask, one corrective ask after a code rejection, and the answer stored only when code accepts it."""
    passage = part["passage"]

    def accepts(reply: str) -> bool:
        return not _parsed(reply, passage)[1]

    send = make_send(accepts)
    problems: list[str] = []
    for _attempt in range(1 + CLAUDE_READ_TASK.claude_retries):
        prompt = _prompt(passage)
        if problems:
            prompt += (
                "\nYour previous answer was rejected: "
                + "; ".join(problems)
                + ". Answer again with only valid JSON that fixes this.\n"
            )
        counts["asks"] += 1
        text = reader_api.call_claude(prompt, transport=send, cfg=cfg)
        data, problems = _parsed(text, passage)
        if data is not None and not problems:
            _store(conn, model, passage, data)
            counts["stored"] += 1
            return
        counts["rejected_by_code"] += 1
    counts["not_stored"] += 1


def rule_counts(conn, document_id: str, equipment_type: str) -> dict:
    """This standard's compiled rules by scope state, with how many a disagreement holds. Counts only."""
    states: dict[str, int] = {}
    disagreeing = 0
    parts: set[str] = set()
    for clause, page, quote in conn.execute(
        "SELECT clause, page, quote FROM compiled_rules WHERE standard_document_id = ?",
        (document_id,),
    ).fetchall():
        rule = {
            "document_id": document_id,
            "clause": clause,
            "page": page,
            "quote": quote,
        }
        said = rule_part_scope.of_rule(conn, rule, equipment_type)
        states[said.state] = states.get(said.state, 0) + 1
        if said.disagreement:
            disagreeing += 1
            parts.add(said.division or "")
    return {
        "rules_by_state": dict(sorted(states.items())),
        "rules_held_by_a_disagreement": disagreeing,
        "parts_with_a_disagreement": len(parts),
    }


def read_standard(
    conn,
    document_id: str,
    label: str,
    equipment_type: str,
    *,
    dry_run: bool = True,
    send=None,
    cap: float = JOB_CAP_USD,
    model: str | None = None,
) -> dict:
    """The worst case and, unless dry, the read. One report, counts and fixed words only."""
    if cap > JOB_CAP_USD:
        raise ValueError(f"the cap of this job is at most USD {JOB_CAP_USD}")
    model = model or settings.standards_compiler_model
    ai_task_runner.ensure_schema()
    parts = rule_part_scope.parts_of(conn, document_id)
    todo = [p for p in parts if not _stored(conn, model, p["passage"])]
    step = f"{STEP_PREFIX}{document_id}"
    spent = claude_spend.step_spent(step)
    first = sum(_worst_of_prompt(model, _prompt(p["passage"])) for p in todo)
    corrective = sum(
        _worst_of_prompt(model, _prompt(p["passage"]) + "x" * _CORRECTIVE_CHARS)
        for p in todo
    )
    refused = _gate_refusal(conn, document_id, label)
    report = {
        "standard_document_id": document_id,
        "model": model,
        "parts": len(parts),
        "parts_to_ask": len(todo),
        "worst_usd": round(first, 4),
        "worst_usd_if_every_part_also_needs_a_corrective_ask": round(
            first + corrective, 4
        ),
        "cap_usd": cap,
        "spent_on_this_job_usd": round(spent, 4),
    }
    over = spent + first > cap
    if dry_run:
        return {
            **report,
            "status": OVER_CAP if over else DRY,
            "would_refuse": refused,
            **rule_counts(conn, document_id, equipment_type),
        }
    if over:
        return {**report, "status": OVER_CAP, "sent": 0}
    if refused:
        return {**report, "status": REFUSED, "why": refused, "sent": 0}
    cfg = dataclasses.replace(
        reader_api.ReaderSettings.from_env(),
        model=model,
        max_tokens=CLAUDE_READ_TASK.num_predict,
        timeout_seconds=TIMEOUT_S,
    )
    counts = {
        "asks": 0,
        "stored": 0,
        "rejected_by_code": 0,
        "not_stored": 0,
        "failed_calls": 0,
    }
    status = DONE
    with claude_approved.carrying({document_id}):
        for part in todo:
            try:
                _read_one(
                    conn,
                    part,
                    model,
                    cfg,
                    lambda accepts: _sender(document_id, cap, accepts, send),
                    counts,
                )
            except claude_spend.StopRun:
                status = PARTIAL
                break
            except (OSError, ValueError, reasoning_provider.ProviderRefused):
                counts["failed_calls"] += 1
                status = PARTIAL
    if counts["not_stored"]:
        status = PARTIAL
    return {
        **report,
        **counts,
        "status": status,
        "spent_on_this_job_usd": round(claude_spend.step_spent(step), 4),
        **rule_counts(conn, document_id, equipment_type),
    }


EXIT = {"dry": 0, "done": 0, "refused": 3, "over_cap": 4, "partial": 5}


def main(argv: list[str] | None = None, *, send=None, emit=print) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--standard", required=True)
    ap.add_argument("--type", required=True, dest="equipment_type")
    ap.add_argument("--send", action="store_true", help="ask Claude; this spends")
    ap.add_argument("--model", default=None)
    args = ap.parse_args(argv)

    from app.db import connect, reset_connection

    settings.db_path = refuse_live(args.db)
    reset_connection()
    conn = connect()
    chosen = _chosen(conn, [args.standard])
    if len(chosen) != 1:
        raise SystemExit(f"{args.standard!r} names {len(chosen)} documents, not one")
    document_id, label = next(iter(chosen.items()))
    report = read_standard(
        conn,
        document_id,
        label,
        args.equipment_type,
        dry_run=not args.send,
        send=send,
        model=args.model,
    )
    emit(json.dumps(report, sort_keys=True))
    return EXIT[report["status"]]


if __name__ == "__main__":
    sys.exit(main())
