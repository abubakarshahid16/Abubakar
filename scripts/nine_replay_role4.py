#!/usr/bin/env python3
"""FREE replay of role 4 (the Reviewer) on a COPY, from a stored nine-role run: no key, no network, no model (the sender is a stub).

    python scripts/nine_replay_role4.py --copy <a CLONE of the data folder: it is WRITTEN> --paper <id> --run <the stored run>

It builds role 4's requests the way the job does: role 1's fact sheet from the paper's CURRENT stored facts (the rule check's own selection,
`datasheets.list_facts`), the chapters role 3 handed over, the paper's pages, and `nine_support._prefix` (the digest shared, or the facts of each
chapter's fields, or in parts). The stub records each request and answers an empty, valid list. Prints counts and ids only: the facts taken, how
many requests, which chapters of which books, the size of each request, the cost ESTIMATE, and what the seam held.
Exit 0 when role 4 sent at least one request, 1 when it could not, 2 when the replay could not run."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
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


def _reply(body: dict, text: str) -> dict:
    return {
        "model": body["model"],
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": text}],
        "usage": dict(USAGE),
    }


def _reader_stub(url, *, headers, body, timeout):  # noqa: ARG001
    """Role 1's transport: an empty, valid reply to every page."""
    return _reply(body, '{"facts": []}')


def _titles_stub(url, *, headers, body, timeout):  # noqa: ARG001
    return _reply(body, '{"chapters": []}')


class Stub:
    """Role 4's transport: records the size of each request and answers an empty, valid list of findings. With `cut_first` the FIRST request answers
    as a call that hit the output cap: `kept` complete (synthetic) findings and one cut in the middle."""

    def __init__(self, cut_first: int = 0) -> None:
        self.sizes: list[int] = []
        self.cut_first = cut_first

    def __call__(self, url, *, headers, body, timeout):  # noqa: ARG002
        self.sizes.append(len(json.dumps(body)))
        if self.cut_first and len(self.sizes) == 1:
            fs = [
                {
                    "issue": f"synthetic {n}",
                    "verdict": "cannot_tell",
                    "paper_quote": "",
                    "clause_quote": "",
                }
                for n in range(self.cut_first)
            ]
            text = (
                '{"findings": ['
                + ", ".join(json.dumps(f) for f in fs)
                + ', {"issue": "cut'
            )
            out = _reply(body, text)
            out["stop_reason"] = "max_tokens"
            return out
        return _reply(body, '{"findings": []}')


def _roles_of_stored_plan(conn, run: str) -> dict[str, set]:
    """{rule book id: the field roles of the rules asked from it}, from the stored run's lines."""
    out: dict[str, set] = {}
    for r in conn.execute(
        "SELECT line_json FROM agent_review_line WHERE run_id = ?", (run,)
    ):
        d = json.loads(r[0])
        if d.get("standard_document_id"):
            out.setdefault(str(d["standard_document_id"]), set()).update(
                d.get("field_roles") or []
            )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--copy", required=True)
    ap.add_argument("--paper", required=True)
    ap.add_argument(
        "--run",
        required=True,
        help="the stored nine-role run whose reading list is used",
    )
    ap.add_argument(
        "--cut-first",
        type=int,
        default=0,
        help="the first request answers as if cut at the output cap after this many complete findings",
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
        datasheets,
        db,
        nine_call,
        nine_chapters,
        nine_facts,
        nine_job,
        nine_librarian,
        nine_reader,
        nine_record,
        nine_resume,
        nine_reviewer,
        nine_support,
        review_engine,
        review_shown,
    )

    conn = db.connect()
    chosen_raw = nine_resume.handover_load(args.run, "chosen")
    if not chosen_raw:
        print("the stored run has no reading list handed over")
        return 2
    with conn:  # a NEW run on the copy: its own rows
        conn.execute("INSERT OR IGNORE INTO review_runs (id, submittal_document_id, status, created_at, updated_at) VALUES (?,?,?,?,?)", (NEW_RUN, args.paper, "running", "2026-11-16T00:00:00Z", "2026-11-16T00:00:00Z"))  # fmt: skip
        review_shown.ensure_schema(conn)
        ids = [r[0] for r in conn.execute("SELECT id FROM documents")]
        review_shown.record_in(conn, NEW_RUN, ids, "2026-11-16T00:00:00Z")
        review_engine.record_in(conn, NEW_RUN, {"choice": "claude", "text_leaves": True, "parts": []}, "replay", then_ai=False, bar_claude=False, now="2026-11-16T00:00:00Z")  # fmt: skip
    nine_record.start_run(NEW_RUN)
    pages = dict(agent_review_request.DbPages(conn, args.paper).pages)
    stored = datasheets.list_facts(
        args.paper, allowed_document_ids=frozenset({args.paper})
    )
    every = conn.execute(
        "SELECT COUNT(*) FROM submittal_facts WHERE submittal_document_id = ?",
        (args.paper,),
    ).fetchone()[0]
    print(
        f"submittal_facts rows for the paper {every}; CURRENT rows taken by role 1 {len(stored)}"
    )
    res = nine_reader.read_paper(run_id=NEW_RUN, paper_id=args.paper, pages=pages, stored_facts=stored, engine="claude", pages_total=max([*pages, 0]), pictures=False, conn=conn, send=_reader_stub, env=ENV)  # fmt: skip
    sheet = res.sheet
    with conn:
        nine_facts.store(conn, sheet, res.produced)
    scope = frozenset(ids)
    pairs = [(b, c) for b, c in chosen_raw]
    books = list(dict.fromkeys(b for b, _c in pairs))
    inputs, cuts = nine_support._book_inputs(
        conn, books, scope, nine_chapters.CLAUDE_CALL_TOKENS
    )
    chosen = [
        (b, cuts[b].chapter(c))
        for b, c in pairs
        if b in cuts and cuts[b].chapter(c) is not None
    ]
    plan = {"items": [{"item_id": f"R-{n}", "standard_document_id": b, "field_roles": sorted(roles)} for n, (b, roles) in enumerate(_roles_of_stored_plan(conn, args.run).items(), 1)]}  # fmt: skip
    ctx = nine_job.RoleContext(NEW_RUN, args.paper, None, plan, {}, lambda *_a: None)
    ctx.store["fact_sheet"] = sheet
    budget = nine_support.chapter_budget(ctx, pages)
    texts = nine_support._chapter_texts(chosen, cuts, max_chars=budget)
    groups = nine_reviewer.group_chapters(texts, limit_chars=budget)
    print(f"chapter budget per request {budget} characters (ceiling {nine_call.MAX_REQUEST_CHARS}); chapter parts {len(texts)} (cut by the ceiling: {len(texts) - sum(len(ch.parts) for _b, ch in chosen)})")  # fmt: skip
    prefix, groups, _no_context = nine_support._prefix(ctx, pages, groups)
    counts = ctx.store.get("digest_counts") or {}
    for i, g in enumerate(groups, 1):
        used = prefix(i - 1, g) if callable(prefix) else prefix
        sizes = {
            b.name: (len(b.items), sum(len(c) + 3 for r in b.items for c in r))
            for b in used
            if b.document_kind == "review_record"
        }
        print(f"request {i} fact blocks (rows, characters; limit {nine_call.MAX_DERIVED_CHARS}): {sizes}")  # fmt: skip
    stub, log = Stub(args.cut_first), []

    def ask(*a, **kw):
        ans = nine_call.ask(*a, **kw)
        log.append(ans)
        return ans

    ran = nine_reviewer.review(NEW_RUN, prefix, groups, ask=ask, engine="claude", no_context_available=True, send=stub, env=ENV, concurrency=1)  # fmt: skip
    print(f"facts in the sheet {len(sheet.facts)} {dict(Counter(f.state for f in sheet.facts))}; digest rows {counts.get('rows')}; fact parts {counts.get('parts')}; fact rows never sent {counts.get('never_sent')} {counts.get('left_out_reasons')}")  # fmt: skip
    print(
        f"chapters chosen {len(chosen)} of {len(pairs)} handed over; books {len(books)}; requests planned {len(groups)}"
    )
    for n, ans in enumerate(log, 1):
        chap = [
            f"{r.document_id}:{r.chapter_id}.{r.part_no}"
            for r in ans.reads
            if r.document_kind == "rule_book"
        ]
        held = [f"{k}:{why}" for k, why in ans.not_sent]
        size = stub.sizes[n - 1] if n <= len(stub.sizes) else 0
        print(f"request {n}: state {ans.state} {ans.error_code or ''}; paper pages {sum(1 for r in ans.reads if r.document_kind == 'paper')}; fact blocks {sum(1 for r in ans.reads if r.document_kind == 'review_record')}; rule-book parts {len(chap)}; characters {size}; held {held}")  # fmt: skip
        print("   chapters:", ", ".join(chap))
    chars = sum(stub.sizes)
    est = (
        chars / 3 / 1e6 * 3.0 + 8000 * len(stub.sizes) / 1e6 * 15.0
    )  # ROUGH: input at chars/3 tokens x USD 3 per million, output at the 8000-token cap x USD 15 per million
    print(f"requests {len(log)} (sent {len(stub.sizes)}); characters {chars}; cost ESTIMATE (upper, rough) usd {est:.2f}; reviewer state {ran.state()}; errors {sorted(set(ran.errors))}; cut answers {ran.cut_answers}, findings kept from them {ran.cut_kept}, retried {ran.retried}, split {ran.split}, raw findings {len(ran.raw)}")  # fmt: skip
    reading = nine_librarian.plan_reading(NEW_RUN, inputs, rules=[nine_librarian.RuleRef(b, None, None, i) for i, b in enumerate(books, 1)], context=[], equipment_words=[], shown=scope, allowed=scope, engine="claude", wanted_not_listed=0)  # fmt: skip
    title_ask = nine_librarian.seam_ask(
        NEW_RUN, engine="claude", send=_titles_stub, env=ENV
    )
    title_ask(nine_librarian.titles_for_model(reading, inputs))
    refusal = nine_librarian.model_step_refusal(title_ask)
    print(
        f"role 3 title step: {'accepted by the seam' if refusal is None else 'REFUSED ' + str(refusal)}"
    )
    return 0 if stub.sizes else 1


if __name__ == "__main__":
    sys.exit(main())
