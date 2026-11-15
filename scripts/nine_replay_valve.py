#!/usr/bin/env python3
"""NEVER WEAKER THAN TODAY, on real data (nine-role design; B5): replay a stored AI review through the nine-role job and compare its lines.

    python scripts/nine_replay_valve.py --copy <a CLONE of the data folder: it is WRITTEN> --paper <id> --run <the stored AI run> \
        [--engine-decision] [--nine]

The stored run's own trace (`agent_reviews/<run>/trace.jsonl`) holds the first reader's and the second reader's recorded answers. A fake
Messages transport replays them (and answers every request of a NEW role with an empty, valid reply), the review is run again on the copy with
the nine-role switch ON (or OFF with no `--nine`), and each stored line (item id, class, word, verdict) is compared with the new run's line.
With roles 1 to 4 returning nothing, the lines must EQUAL the stored run's. No network, no key, no model: a model call is refused outright.
Prints counts and item ids only. Exit 0 when every stored line is reproduced, 1 otherwise, 2 when the replay could not run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

ENV = {
    "REASONING_PROVIDER": "claude",
    "AGENT_REVIEW_ENGINE": "claude",
    "STANDARDS_READER_ENABLED": "1",
    "STANDARDS_READER_ALLOW_PUBLIC_EGRESS": "1",
    "ANTHROPIC_API_KEY": "replay-key-not-real",
}
USAGE = {"input_tokens": 1000, "output_tokens": 100, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}


def recorded(trace: Path) -> tuple[dict, dict]:
    """({item id: the lead's answer}, {item id: the second reader's answer}) from the stored run's trace."""
    lead, second = {}, {}
    for line in trace.read_text().splitlines():
        row = json.loads(line)
        if row.get("type") != "item":
            continue
        if isinstance(row.get("lead_answer"), dict):
            lead[row["item_id"]] = row["lead_answer"]
        if isinstance(row.get("second_opinion_answer"), dict):
            second[row["item_id"]] = row["second_opinion_answer"]
    return lead, second


class Replay:
    """The fake transport: answers from the recorded trace; counts what it was asked."""

    def __init__(self, lead: dict, second: dict, context: dict):
        self.lead, self.second, self.context = lead, second, context
        self.kinds: list[str] = []
        self.unmatched = 0
        self.used: set[str] = set()

    def _quote_in(self, item_id: str, content: str) -> bool:
        """The second reader's request carries the item's requirement words: match them (escaped as in the body) when its id is not there."""
        got = self.lead.get(item_id) or {}
        snippets = [str(got.get(k) or "")[:50] for k in ("clause_quote", "paper_quote")]
        snippets = [json.dumps(json.dumps(x)[1:-1])[1:-1] for x in snippets if x.strip()]  # the request holds a JSON text inside the message: escaped twice
        return bool(snippets) and all(x in content for x in snippets)

    def _reply(self, body: dict, text: str) -> dict:
        return {"model": body["model"], "stop_reason": "end_turn", "content": [{"type": "text", "text": text}], "usage": dict(USAGE)}

    def __call__(self, url, *, headers, body, timeout):  # noqa: ARG002
        system = json.dumps(body.get("system"))
        content = json.dumps(body["messages"][0]["content"])
        if "CONTEXT CHECK" in system:
            self.kinds.append("context")
            found = next((i for i in self.context if i in content), None)
            return self._reply(body, json.dumps({"limits": bool(self.context.get(found))}))
        if "independent senior engineer" in system:
            self.kinds.append("second")
            import os

            if os.environ.get("REPLAY_DUMP"):
                Path(os.environ["REPLAY_DUMP"]).open("a").write(content[:1500] + "\n=====\n")
            matches = [i for i in self.second if i in content or self._quote_in(i, content)]
            found = next((i for i in matches if i not in self.used), matches[0] if matches else None)  # one recorded answer per request
            if found is not None:
                self.used.add(found)
            if found is None:
                self.unmatched += 1
                return self._reply(body, json.dumps({"agree": False, "reason": "no recorded second answer"}))
            return self._reply(body, json.dumps(self.second[found]))
        if "senior engineer reviewing a supplier paper" in system and "item_id" in content:
            self.kinds.append("lead")
            ids = [i for i in self.lead if i in content]
            return self._reply(body, json.dumps({"answers": [self.lead[i] for i in ids]}))
        self.kinds.append("new-role")
        return self._reply(body, "{}")  # an empty, valid reply for every request of a new role


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--copy", required=True)
    ap.add_argument("--paper", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", help="write the new run's lines (item id -> class, word) here, to compare two replays")
    ap.add_argument("--nine", action="store_true", help="the nine-role switch ON (default: OFF, the control)")
    ap.add_argument("--engine-decision", action="store_true", help="store an engine choice and a shown list, so roles 1 to 4 DO call the seam")
    args = ap.parse_args(argv)
    data = Path(args.copy).resolve()
    from app.config import settings

    settings.data_dir, settings.upload_dir, settings.db_path = data, data / "uploads", data / "rag_intelligence.sqlite"
    settings.startup_warmup, settings.auth_mode = False, "disabled"
    settings.agent_review_enabled, settings.review_page_v2_enabled = True, True
    settings.agent_review_nine_roles_enabled = bool(args.nine)
    settings.claude_spend_log, settings.claude_cache_dir = data / "replay-spend.jsonl", data / "replay-cache"
    settings.claude_approved_list_enforced = False
    for name, val in (("claude_budget_usd_per_step", 50.0), ("claude_budget_usd_total", 200.0)):
        if hasattr(settings, name):
            setattr(settings, name, val)
    from app import access, agent_review_jobs, db

    conn = db.connect()
    stored = {r["item_id"]: dict(r) for r in conn.execute("SELECT item_id, verdict_class, word FROM agent_review_line WHERE run_id = ?", (args.run,))}
    trace = data / "agent_reviews" / args.run / "trace.jsonl"
    if not stored or not trace.is_file():
        print("the stored run or its trace is missing")
        return 2
    lead, second = recorded(trace)
    context = {i: json.loads(r["line_json"]).get("context_limits") for i, r in ((r["item_id"], r) for r in conn.execute("SELECT item_id, line_json FROM agent_review_line WHERE run_id = ?", (args.run,)))}
    replay = Replay(lead, second, context)
    agent_review_jobs.lane = lambda: (replay, ENV)  # the only transport: the replay
    scope = access.unrestricted_scope()
    run_id, job_id = agent_review_jobs.enqueue(args.paper, allowed_document_ids=scope.allowed_document_ids, requested_by=None, fresh=True)
    if args.engine_decision:
        from app import review_engine, review_shown

        with conn:
            review_shown.ensure_schema(conn)
            ids = [r[0] for r in conn.execute("SELECT id FROM documents")]
            review_shown.record_in(conn, run_id, ids, "2026-11-16T00:00:00Z")
            review_engine.record_in(conn, run_id, {"choice": "claude", "text_leaves": True, "parts": []}, "replay", then_ai=False, bar_claude=False, now="2026-11-16T00:00:00Z")
    claimed = agent_review_jobs.claim_next("replay")
    state = agent_review_jobs.run(claimed, "replay") if claimed else "not claimed"
    new = {r["item_id"]: dict(r) for r in conn.execute("SELECT item_id, verdict_class, word FROM agent_review_line WHERE run_id = ?", (run_id,))}
    same = [i for i in stored if i in new and all(stored[i][k] == new[i][k] for k in ("verdict_class", "word"))]
    diff = [i for i in stored if i in new and i not in same]
    missing = [i for i in stored if i not in new]
    extra = [i for i in new if i not in stored]
    if args.out:
        Path(args.out).write_text(json.dumps(new, sort_keys=True))
    print(f"job state {state}; switch {'ON' if args.nine else 'OFF'}; engine decision {'stored' if args.engine_decision else 'none'}")
    print(f"stored lines {len(stored)}; new lines {len(new)}; equal {len(same)}; differ {len(diff)}; missing {len(missing)}; extra {len(extra)}")
    print(f"requests: {len(replay.kinds)} ({', '.join(f'{k} {replay.kinds.count(k)}' for k in sorted(set(replay.kinds)))}); second answers not found {replay.unmatched}")
    for i in diff[:20]:
        print("  differs:", i, stored[i]["verdict_class"], "->", new[i]["verdict_class"])
    for i in (missing + extra)[:20]:
        print("  not in both:", i)
    return 0 if len(same) == len(stored) and not extra else 1


if __name__ == "__main__":
    sys.exit(main())
