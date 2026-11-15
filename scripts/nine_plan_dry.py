#!/usr/bin/env python3
"""FREE DRY RUN of the nine-role review's plan on a COPY (no call, no model, nothing started; a placeholder in the key variable only opens the plan's switches).

    python scripts/nine_plan_dry.py --copy <a COPY of the data folder> --paper <document id> --run <an earlier AI run, for the cost estimate>

Prints (ids, kinds, counts and sizes only; no title, no text): what the one Review button's plan says for engine "claude" (does text leave, which
documents WOULD leave with kind and why; a book the starter may not read is a count; what will not be sent), the nine roles as planned (engine,
step name, design budget, whether a model call is made), and the cost ESTIMATE per role (from stored sizes; an estimate, not a price)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--copy", required=True)
    ap.add_argument("--paper", required=True)
    ap.add_argument("--run")
    args = ap.parse_args(argv)
    data = Path(args.copy).resolve()
    for k, v in {
        "REASONING_PROVIDER": "claude", "AGENT_REVIEW_ENGINE": "claude", "STANDARDS_READER_ENABLED": "true",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS": "true", "AGENT_REVIEW_ENABLED": "true", "AGENT_REVIEW_NINE_ROLES_ENABLED": "true",
        "AGENT_REVIEW_TWO_READER_VERDICT_ENABLED": "true", "CLAUDE_AUTO_APPROVE_REVIEWS_ENABLED": "true", "AUTH_MODE": "disabled",
        "OLLAMA_URL": "http://127.0.0.1:1", "ANTHROPIC_API_KEY": "dry-plan-placeholder-not-a-key",
    }.items():
        os.environ[k] = v
    from app.config import settings

    settings.data_dir, settings.upload_dir, settings.db_path = data, data / "uploads", data / "rag_intelligence.sqlite"
    settings.startup_warmup = False
    from fastapi.testclient import TestClient

    from app import nine_call
    from app.main import app
    from app.nine_contract import ROLE_NAMES, STEP_OF_ROLE

    with TestClient(app, base_url="http://localhost") as client:  # the lifespan runs: registries freeze after every role module registered
        r = client.get("/api/reviews/plan", params={"submittal_document_id": args.paper, "engine": "claude"})
    print(f"plan route: HTTP {r.status_code}")
    if r.status_code != 200:
        print("  body:", str(r.text)[:300])
    plan = r.json() if r.status_code == 200 else {}
    docs = (plan.get("documents") or {})
    print(f"engine choice {plan.get('choice')}; text leaves: {plan.get('text_leaves')}; refused: {plan.get('refused')}; needs the owner's yes: {plan.get('needs_yes')}")
    for p in plan.get("parts") or []:
        print(f"  part {p.get('name')}: {p.get('engine')} ({p.get('why')})")
    leaving = docs.get("leaving") or []
    print(f"documents that WOULD leave: {len(leaving)}")
    for d in leaving:
        print(f"  id {d.get('id')} | kind {d.get('kind')} | why {d.get('why')}")
    print(f"documents the starter may not read (counted, not named): {docs.get('not_readable', 0)}")
    for d in docs.get("not_sent") or []:
        print(f"  NOT sent: id {d.get('id')} | kind {d.get('kind')} | {d.get('reason')}")
    print("the nine roles as planned (engine on the one Review button's choice, switch on, writer switch off):")
    for n, name in ROLE_NAMES.items():
        step = STEP_OF_ROLE.get(n)
        budget = nine_call.ROLE_BUDGET_USD.get(n)
        calls = "model call(s) through the one seam" if step else "code only, no model call"
        if n == 9:
            calls = "code only in this version (the writer's setting is off: no call)"
        print(f"  {n} {name}: step {step or '-'}; design budget {budget if budget is not None else '-'} USD; {calls}")
    cost = (plan.get("cost") or {})
    print(f"the plan's own upper bound (an estimate): {cost.get('at_most_usd')} USD; basis: {cost.get('basis')}")
    import nine_dry_run

    conn = nine_dry_run.open_copy(data)
    rows = nine_dry_run.plan(conn, args.paper, args.run)
    rows = [x for x in rows if not x["role"].startswith("9")]
    print("ESTIMATE per role from stored sizes (not a price): role | calls | input tokens | worst USD | expected USD")
    for x in rows:
        print(f"  {x['role']} | {x['calls']} | {x['tokens_in']} | {x['worst']:.2f} | {x['expected']:.2f}")
    print(f"  TOTAL expected {sum(x['expected'] for x in rows):.2f}, worst {sum(x['worst'] for x in rows):.2f} (run cap 15, step cap 5)")
    return 0 if r.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
