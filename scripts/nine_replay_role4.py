#!/usr/bin/env python3
"""FREE replay of role 4 (the Reviewer) on a COPY, from a stored nine-role run: no key, no network, no model (the sender is a stub).

    python scripts/nine_replay_role4.py --copy <a CLONE of the data folder: it is WRITTEN> --paper <id> --run <the stored run>

It builds role 4's requests the way the job does (the stored fact sheet of that run, the chapters role 3 handed over, the paper's pages), sends them
to a stub that records each request and answers an empty, valid list, and prints counts and ids only: how many requests, which chapters of which
books, the size of each request (characters sent and an input-token estimate), the cost ESTIMATE at the model's price, and what the seam held.
Exit 0 when role 4 built and sent at least one request, 1 when it could not, 2 when the replay could not run."""

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
USAGE = {
    "input_tokens": 1000,
    "output_tokens": 100,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
}
NEW_RUN = "replay-role4"


def _empty_chapters_reply(url, *, headers, body, timeout):  # noqa: ARG001
    """A stub transport for the librarian's title step: an empty list of chapters."""
    return {
        "model": body["model"],
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": '{"chapters": []}'}],
        "usage": dict(USAGE),
    }


class Stub:
    """The only transport: records the size of each request and answers an empty, valid list of findings."""

    def __init__(self) -> None:
        self.sizes: list[int] = []

    def __call__(self, url, *, headers, body, timeout):  # noqa: ARG002
        self.sizes.append(len(json.dumps(body)))
        return {
            "model": body["model"],
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": '{"findings": []}'}],
            "usage": dict(USAGE),
        }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--copy", required=True)
    ap.add_argument("--paper", required=True)
    ap.add_argument(
        "--run",
        required=True,
        help="the stored nine-role run whose fact sheet and reading list are used",
    )
    args = ap.parse_args(argv)
    data = Path(args.copy).resolve()
    from app.config import settings

    settings.data_dir, settings.upload_dir, settings.db_path = (
        data,
        data / "uploads",
        data / "rag_intelligence.sqlite",
    )
    settings.startup_warmup, settings.auth_mode = False, "disabled"
    settings.claude_spend_log, settings.claude_cache_dir = (
        data / "replay-spend.jsonl",
        data / "replay-cache",
    )
    settings.claude_approved_list_enforced = False
    for name, val in (
        ("claude_budget_usd_per_step", 50.0),
        ("claude_budget_usd_total", 200.0),
    ):
        if hasattr(settings, name):
            setattr(settings, name, val)
    from app import (
        agent_review_request,
        db,
        nine_call,
        nine_chapters,
        nine_facts,
        nine_record,
        nine_resume,
        nine_reviewer,
        nine_support,
        review_engine,
        review_shown,
    )

    conn = db.connect()
    sheet = nine_facts.load(conn, args.run)
    chosen_raw = nine_resume.handover_load(args.run, "chosen")
    if sheet is None or not chosen_raw:
        print("the stored run has no fact sheet or no reading list handed over")
        return 2
    with conn:  # a NEW run on the copy: its own rows, the stored facts copied to it (the seam looks each fact id up among the call's run)
        conn.execute("INSERT OR IGNORE INTO review_runs (id, submittal_document_id, status, created_at, updated_at) VALUES (?,?,?,?,?)", (NEW_RUN, args.paper, "running", "2026-11-16T00:00:00Z", "2026-11-16T00:00:00Z"))  # fmt: skip
        review_shown.ensure_schema(conn)
        ids = [r[0] for r in conn.execute("SELECT id FROM documents")]
        review_shown.record_in(conn, NEW_RUN, ids, "2026-11-16T00:00:00Z")
        review_engine.record_in(conn, NEW_RUN, {"choice": "claude", "text_leaves": True, "parts": []}, "replay", then_ai=False, bar_claude=False, now="2026-11-16T00:00:00Z")  # fmt: skip
        conn.execute("DELETE FROM agent_review_fact WHERE run_id = ?", (NEW_RUN,))
        conn.execute("INSERT INTO agent_review_fact SELECT ?, fact_id, page, field_label, field_role, value, unit, quote, quote_verified, tag, cell_ref, source, state, page_text_sha, model FROM agent_review_fact WHERE run_id = ?", (NEW_RUN, args.run))  # fmt: skip
    nine_record.start_run(NEW_RUN)
    pages = dict(agent_review_request.DbPages(conn, args.paper).pages)
    scope = frozenset(ids)
    pairs = [(b, c) for b, c in chosen_raw]
    books = list(dict.fromkeys(b for b, _c in pairs))
    _inputs, cuts = nine_support._book_inputs(
        conn, books, scope, nine_chapters.CLAUDE_CALL_TOKENS
    )
    chosen = [
        (b, cuts[b].chapter(c))
        for b, c in pairs
        if b in cuts and cuts[b].chapter(c) is not None
    ]
    groups = nine_reviewer.group_chapters(nine_support._chapter_texts(chosen, cuts))
    blocks = [nine_call.Block("paper", args.paper, (int(n),)) for n in sorted(pages)]
    digest, counts = nine_facts.digest_blocks(sheet, pages)
    blocks.extend(digest)
    if blocks:
        import dataclasses

        blocks[-1] = dataclasses.replace(blocks[-1], cache=True)
    stub, log = Stub(), []

    def ask(*a, **kw):
        ans = nine_call.ask(*a, **kw)
        log.append(ans)
        return ans

    ran = nine_reviewer.review(
        NEW_RUN,
        blocks,
        groups,
        ask=ask,
        engine="claude",
        no_context_available=True,
        send=stub,
        env=ENV,
        concurrency=1,
    )
    print(f"facts in the sheet {len(sheet.facts)}; digest rows passed {counts['rows_tagged'] + counts['rows_untagged']}; rows cut for size {counts['rows_cut_for_size']}; left out {counts['left_out_reasons']}")  # fmt: skip
    print(
        f"chapters chosen {len(chosen)} of {len(pairs)} handed over; books {len(books)}; chapter groups {len(groups)}"
    )
    for n, ans in enumerate(log, 1):
        chap = [
            f"{r.document_id}:{r.chapter_id}.{r.part_no}"
            for r in ans.reads
            if r.document_kind == "rule_book"
        ]
        held = [f"{k}:{why}" for k, why in ans.not_sent]
        size = stub.sizes[n - 1] if n <= len(stub.sizes) else 0
        print(f"request {n}: state {ans.state} {ans.error_code or ''}; paper pages {sum(1 for r in ans.reads if r.document_kind == 'paper')}; rule-book parts {len(chap)}; characters {size}; estimate usd {ans.usd}; held {held}")  # fmt: skip
        print("   chapters:", ", ".join(chap))
    chars = sum(stub.sizes)
    est = (
        chars / 3 / 1e6 * 3.0 + 8000 * len(stub.sizes) / 1e6 * 15.0
    )  # ROUGH: input at chars/3 tokens x USD 3 per million, output at the 8000-token cap x USD 15 per million
    print(f"requests {len(log)} (sent {len(stub.sizes)}); characters {chars}; cost ESTIMATE (upper, rough) usd {est:.2f}; reviewer state {ran.state()}; errors {sorted(set(ran.errors))}")  # fmt: skip
    from app import nine_librarian

    reading = nine_librarian.plan_reading(NEW_RUN, _inputs, rules=[nine_librarian.RuleRef(b, None, None, i) for i, b in enumerate(books, 1)], context=[], equipment_words=[], shown=scope, allowed=scope, engine="claude", wanted_not_listed=0)  # fmt: skip
    title_ask = nine_librarian.seam_ask(NEW_RUN, engine="claude", send=_empty_chapters_reply, env=ENV)  # fmt: skip
    title_ask(nine_librarian.titles_for_model(reading, _inputs))
    print(f"role 3 title step: {'accepted by the seam' if nine_librarian.model_step_refusal(title_ask) is None else 'REFUSED ' + str(nine_librarian.model_step_refusal(title_ask))}")  # fmt: skip
    return 0 if stub.sizes else 1


if __name__ == "__main__":
    sys.exit(main())
