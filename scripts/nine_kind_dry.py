#!/usr/bin/env python3
"""FREE PROOF of the nine-role job for a paper of a kind with no field list, on a COPY (WRITTEN: give it a clone, never the live folder).

    python scripts/nine_kind_dry.py --copy <a clone of the data folder> --paper <document id> --shown <id> [--shown <id> ...] [--out <file>]

The lane is closed (the real transport is replaced by a recorder that opens no socket and needs no key), no model is loaded. The whole job
runs through `agent_review_jobs.run` with the nine-role switch and `AGENT_REVIEW_GENERAL_RULES_ENABLED` ON (the route a procedure needs), an
engine choice "claude" and the shown list you give, so the seam gate lets through only those documents. Every request is answered with one
empty but valid reply, so the requests are those the code builds (the reviewer's are built from the stored pages and the chosen chapters).
Prints ids, kinds, counts and sizes only; no title, no text. Per role: its state and reason; the reviewer's requests (how many, which books
and chapters by id and part, the characters of each: all must be at most the per-request ceiling); the documents that WOULD leave; the cost
ESTIMATE per role from those sizes at `claude_spend.PRICES` (an estimate, not a price)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

ENV = {
    "REASONING_PROVIDER": "claude",
    "AGENT_REVIEW_ENGINE": "claude",
    "STANDARDS_READER_ENABLED": "1",
    "STANDARDS_READER_ALLOW_PUBLIC_EGRESS": "1",
    "ANTHROPIC_API_KEY": "dry-proof-key-not-real",
}
USAGE = {"input_tokens": 1000, "output_tokens": 100, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
EMPTY = json.dumps({"findings": [], "answers": [], "standards": [], "overrides": [], "chapters": [], "comments": []})


class Recorder:
    """The only transport: records the size of each request body and answers empty. No socket, no key."""

    def __init__(self) -> None:
        self.sizes: list[int] = []
        self.seam: list[int] = []  # the sizes of the requests the nine roles made through the seam (the reviewer's and the librarian's)

    def __call__(self, url, *, headers, body, timeout):  # noqa: ARG002
        text = len(json.dumps(body.get("system") or "")) + sum(
            len(c.get("text", "")) for m in body["messages"] for c in m["content"] if c.get("type") == "text"
        )
        self.sizes.append(text)
        flat = json.dumps(body.get("system") or "") + json.dumps(body["messages"][0]["content"])[:6000]
        if "signs the review of a" in flat or "lists chapter titles" in flat or "Read the project document" in flat:
            self.seam.append(text)
        return {"model": body["model"], "stop_reason": "end_turn", "content": [{"type": "text", "text": EMPTY}], "usage": dict(USAGE)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--copy", required=True)
    ap.add_argument("--paper", required=True)
    ap.add_argument("--shown", action="append", required=True, help="a document id on the shown list (the paper and each book that may leave)")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    data = Path(args.copy).resolve()
    from app.config import settings

    settings.data_dir, settings.upload_dir, settings.db_path = data, data / "uploads", data / "rag_intelligence.sqlite"
    settings.startup_warmup, settings.auth_mode = False, "disabled"
    settings.agent_review_enabled, settings.review_page_v2_enabled = True, True
    settings.agent_review_nine_roles_enabled = True
    settings.agent_review_general_rules_enabled = True
    settings.agent_review_two_reader_verdict_enabled = True
    settings.claude_spend_log, settings.claude_cache_dir = data / "dry-spend.jsonl", data / "dry-cache"
    settings.claude_approved_list_enforced = False
    for name, val in (("claude_budget_usd_per_step", 50.0), ("claude_budget_usd_total", 200.0)):
        if hasattr(settings, name):
            setattr(settings, name, val)
    from app import access, agent_review_jobs, db, nine_call, nine_record, review_engine, review_shown

    recorder = Recorder()
    agent_review_jobs.lane = lambda: (recorder, ENV)  # the only transport
    conn = db.connect()
    scope = access.unrestricted_scope()
    run_id, _job = agent_review_jobs.enqueue(args.paper, allowed_document_ids=scope.allowed_document_ids, requested_by=None, fresh=True)
    now = "2026-11-16T00:00:00Z"
    with conn:
        review_shown.ensure_schema(conn)
        review_shown.record_in(conn, run_id, list(args.shown), now)
        review_engine.record_in(conn, run_id, {"choice": "claude", "text_leaves": True, "parts": []}, "dry", then_ai=False, bar_claude=False, now=now)
    claimed = agent_review_jobs.claim_next("dry")
    state = agent_review_jobs.run(claimed, "dry") if claimed else "not claimed"
    lines = [f"job state {state}; run {run_id}; requests made to the recorder {len(recorder.sizes)} (no socket, no key, no model)"]
    record = nine_record.load_record(run_id)
    lines.append("ROLES (state, reason, calls):")
    for r in record.roles if record else ():
        lines.append(f"  {r.role_no} {r.role}: {r.state}{' - ' + r.why if r.why else ''}; calls {r.calls}")
    rows = conn.execute(
        "SELECT c.role_no, c.call_id, c.state, c.question_id, r.document_id, r.document_kind, r.chapter_id, r.part_no, r.part_of, r.chars, r.pages_json"
        " FROM agent_review_role_call c LEFT JOIN agent_review_role_read r ON r.run_id = c.run_id AND r.call_id = c.call_id WHERE c.run_id = ? ORDER BY c.sent_at, r.seq",
        (run_id,),
    ).fetchall()
    calls: dict[str, dict] = {}
    for r in rows:
        c = calls.setdefault(r["call_id"], {"role": r["role_no"], "state": r["state"], "q": r["question_id"], "chars": 0, "reads": []})
        if r["document_id"]:
            c["chars"] += int(r["chars"] or 0)
            c["reads"].append((r["document_id"], r["document_kind"], r["chapter_id"], r["part_no"], r["part_of"], int(r["chars"] or 0)))
    by_role: dict[int, list] = {}
    for c in calls.values():
        by_role.setdefault(c["role"], []).append(c)
    lines.append(f"REQUESTS by role (per-request ceiling {nine_call.MAX_REQUEST_CHARS:,} characters, document characters only):")
    for role, cs in sorted(by_role.items()):
        lines.append(f"  role {role}: {len(cs)} call(s); document characters per call {[c['chars'] for c in cs][:12]}")
    for c in by_role.get(4, []):
        parts = ", ".join(f"{d}:{ch or '-'}" + (f"#{p}/{of}" if of and of > 1 else "") + f"({n})" for d, k, ch, p, of, n in c["reads"] if k == "rule_book")
        lines.append(f"    reviewer request: paper chars {sum(n for _d, k, _c, _p, _o, n in c['reads'] if k == 'paper')}; chapters {parts or 'none'}")
    over = [s for s in recorder.seam if s > nine_call.MAX_REQUEST_CHARS]
    lines.append(f"nine-role seam requests (reviewer, librarian, context): {len(recorder.seam)}; largest {max(recorder.seam, default=0):,} characters; over the ceiling: {len(over)}")
    other = [s for s in recorder.sizes]
    for s_ in recorder.seam:
        other.remove(s_)
    lines.append(f"requests of today's batch path (rule items, second reader; not the seam, their own limits): {len(other)}; largest {max(other, default=0):,}")
    leave = sorted({(d, k) for c in calls.values() for d, k, *_ in c["reads"] if k != "review_record"})
    derived = sorted({d for c in calls.values() for d, k, *_ in c["reads"] if k == "review_record"})
    lines.append(f"DOCUMENTS THAT WOULD LEAVE: {len(leave)}")
    for d, k in leave:
        lines.append(f"  id {d} | kind {k}")
    lines.append(f"derived-block sources (documents their tokens came from): {derived}")
    lines.append("cost ESTIMATE per role at claude_spend.PRICES (input tokens = characters / 3; output expected 2000, worst = max_tokens; not a price):")
    import nine_dry_run as nd

    total_e = total_w = 0.0
    for role, cs in sorted(by_role.items()):
        model = nd.SONNET if role != 6 else nd.OPUS
        t_in = sum(max(c["chars"], 1) for c in cs) // 3
        out_exp = {1: nd.OUT_READER, 4: nd.OUT_REVIEWER // 4, 5: nd.OUT_CHECK, 6: nd.OUT_SECOND}.get(role, 600)
        out_worst = {1: nd.OUT_READER, 4: nd.OUT_REVIEWER, 5: nd.OUT_CHECK, 6: nd.OUT_SECOND}.get(role, 1000)
        exp, worst = nd._usd(model, t_in, out_exp * len(cs)), nd._usd(model, t_in, out_worst * len(cs))
        total_e, total_w = total_e + exp, total_w + worst
        lines.append(f"  role {role}: calls {len(cs)}; input tokens {t_in}; expected {exp:.2f} USD; worst {worst:.2f} USD")
    if other:
        t_in = sum(other) // 3
        exp, worst = nd._usd(nd.SONNET, t_in, 600 * len(other)), nd._usd(nd.SONNET, t_in, 1000 * len(other))
        total_e, total_w = total_e + exp, total_w + worst
        lines.append(f"  roles 5 and 6 (today's batch path: {len(other)} rule-item requests, each answered once; the stub's empty reviewer leaves every item to ask, so this is an UPPER bound; the second reader is on top for items the first reader answers): input tokens {t_in}; expected {exp:.2f} USD; worst {worst:.2f} USD")
    lines.append(f"  TOTAL expected {total_e:.2f} USD, worst {total_w:.2f} USD (role 6's second-reader calls are not priced: none happened with the stub's empty answers)")
    text = "\n".join(lines)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    return 0 if state == "done" or "done" in str(state) else 1


if __name__ == "__main__":
    sys.exit(main())
