#!/usr/bin/env python3
"""DRY RUN of the nine-role review on a COPY of the database (SPEC G.6 step 4). Sends nothing, writes nothing, loads no model.

    python scripts/nine_dry_run.py --copy <folder with rag_intelligence.sqlite> --paper <document id> [--run <an earlier AI run of the paper>]

It builds, from the stored pages and the rules of an earlier AI run of the paper, the requests of the wired roles (the Reader's pages, the
Librarian's chapter titles, the Reviewer's chapter groups, the Checklist's items, the Second reader's candidates) and prints, per role, the
number of calls, the input tokens (characters / 3, the cap estimator's ratio; a page picture by the app's image rule) and the worst-case and
expected USD at `claude_spend.PRICES`. Counts and sizes only: no title, no text. STOP LINE (owner / SPEC G.6): do not pay when the expected
total is over USD 5 or the worst case over USD 12; the exit code is 1 then.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

STOP_EXPECTED, STOP_WORST = 5.0, 12.0
SONNET, OPUS = "claude-sonnet-5-5", "claude-opus-5-5"
PICTURE_TOKENS = 2_100  # a page picture (SPEC C, measured)
OUT_READER, OUT_REVIEWER, OUT_CHECK, OUT_SECOND = (
    2_000,
    8_000,
    600,
    300,
)  # expected output tokens per call (worst = the call's max_tokens)
PER_ITEM_USD = 0.0102  # measured on the paper's last real run: one checklist item


def _usd(model: str, tokens_in: int, tokens_out: int) -> float:
    from app import claude_spend

    p_in, p_out, p_write, _ = claude_spend.price_for(model, tokens_in)
    return (tokens_in * p_in + tokens_out * p_out) / 1_000_000


def _worst(model: str, tokens_in: int, max_tokens: int) -> float:
    from app import claude_spend

    return claude_spend.worst_case_usd(model, tokens_in * 3, max_tokens)


def open_copy(folder: Path) -> sqlite3.Connection:
    db = folder / "rag_intelligence.sqlite"
    conn = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def plan(conn: sqlite3.Connection, paper: str, run: str | None) -> list[dict]:
    from app import (
        agent_review_request,
        agent_review_standards,
        nine_chapters,
        nine_librarian,
        nine_reviewer,
    )

    pages = dict(agent_review_request.DbPages(conn, paper).pages)
    rows: list[dict] = []
    # role 1: one call per page, text + picture
    reader_in = [(len(t) // 3 + 1) + PICTURE_TOKENS for t in pages.values()]
    rows.append({
        "role": "1 Reader", "calls": len(reader_in), "tokens_in": sum(reader_in), "model": SONNET,
        "worst": sum(_worst(SONNET, n, 8_000) for n in reader_in), "expected": sum(_usd(SONNET, n, OUT_READER) for n in reader_in),
    })  # fmt: skip
    # the rules of an earlier AI run of the paper stand for the rules the review will ask
    run = (
        run
        or (
            conn.execute(
                "SELECT run_id FROM agent_review_run WHERE submittal_document_id = ? ORDER BY started_at DESC LIMIT 1",
                (paper,),
            ).fetchone()
            or [None]
        )[0]
    )
    rules = (
        conn.execute(
            "SELECT rule_key, standard_document_id, clause, quote_page, equipment FROM agent_review_rule WHERE run_id = ? AND asked = 1 ORDER BY rowid",
            (run,),
        ).fetchall()
        if run
        else []
    )
    by_book: dict[str, list] = {}
    for r in rules:
        if r["standard_document_id"]:
            by_book.setdefault(r["standard_document_id"], []).append(r)
    inputs, texts = [], {}
    for b in by_book:
        book = agent_review_standards.read_book(conn, b)
        cut = nine_chapters.cut(
            b,
            sorted((n, t) for n, t in book.pages.items() if t.strip()),
            scanned=book.ocr,
        )
        texts[b] = cut
        inputs.append(
            nine_librarian.BookInput(
                b, cut, why=("holds a rule chosen for this paper",)
            )
        )
    # the stored order of the asked rules is the rank the job asked them in (the librarian's own rank adds the cited and context reasons)
    refs = [
        nine_librarian.RuleRef(
            r["standard_document_id"], r["clause"], r["quote_page"], n
        )
        for n, r in enumerate([r for r in rules if r["standard_document_id"]], 1)
    ]
    words = sorted(
        {
            w
            for r in rules
            for w in str(r["equipment"] or "").replace(",", " ").split()
            if len(w) > 3
        }
    )[:20]
    listed = [*by_book, paper]
    reading = nine_librarian.plan_reading(
        run or "dry",
        inputs,
        rules=refs,
        equipment_words=words,
        shown=listed,
        allowed=listed,
        engine="claude",
    )
    titles = nine_librarian.titles_for_model(reading, inputs)
    t_in = sum(len(f"{b}|{c}|{t}") for b, c, t in titles) // 3 + 200
    rows.append({
        "role": "3 Librarian", "calls": 1 if titles else 0, "tokens_in": t_in if titles else 0, "model": SONNET,
        "worst": _worst(SONNET, t_in, 2_000) if titles else 0.0, "expected": _usd(SONNET, t_in, 500) if titles else 0.0,
    })  # fmt: skip
    # role 4: the chosen chapters in groups, behind the cached prefix (the paper and the digest)
    chosen = [
        (b.book_id, i.chapter) for b in reading.books for i in b.items if i.chosen
    ]
    chapters = [
        nine_reviewer.ChapterText(book, ch.chapter_id, p.part_no, p.part_of, tuple(range(p.page_from, p.page_to + 1)), p.chars)
        for book, ch in chosen for p in ch.parts
    ]  # fmt: skip
    groups = nine_reviewer.group_chapters(chapters)
    prefix_tokens = sum(len(t) for t in pages.values()) // 3 + 2_000
    g_tokens = [sum(nine_reviewer.estimate_tokens(c.chars) for c in g) for g in groups]
    rows.append({
        "role": "4 Reviewer", "calls": len(groups), "tokens_in": sum(g_tokens) + prefix_tokens * min(1, len(groups)), "model": SONNET,
        "worst": sum(_worst(SONNET, prefix_tokens + g, 8_000) for g in g_tokens),
        "expected": sum(_usd(SONNET, prefix_tokens + g, OUT_REVIEWER) for g in g_tokens) - max(0, len(groups) - 1) * prefix_tokens * 1.8 / 1_000_000,
    })  # fmt: skip
    # role 5: today's batch path over the items the reviewer did not cover (worst case: all of them)
    n_items = len(rules)
    calls = -(-n_items // 8) if n_items else 0
    rows.append({
        "role": "5 Checklist", "calls": calls, "tokens_in": calls * 6_000, "model": SONNET,
        "worst": calls * _worst(SONNET, 6_000, 4_000), "expected": n_items * PER_ITEM_USD,
    })  # fmt: skip
    # role 6: a second reader for the lines that can become a decision (worst case: every rule)
    cand = (
        sum(
            1
            for r in conn.execute(
                "SELECT line_json FROM agent_review_line WHERE run_id = ?", (run,)
            )
            if '"two_reader"' in (r["line_json"] or "")
        )
        if run
        else 0
    )
    cand = cand or n_items
    c6 = -(-cand // 8) if cand else 0
    rows.append({
        "role": "6 Second reviewer", "calls": c6, "tokens_in": c6 * 16_000, "model": OPUS,
        "worst": c6 * _worst(OPUS, 16_000, 4_000), "expected": c6 * _usd(OPUS, 16_000, 4_000) * 0.5,
    })  # fmt: skip
    # role 9: ONE call over short tokens (a row per comment: number, field, status, pages, clause); the answer is one comment per row
    w_in = 600 + 25 * max(1, len(rules))
    rows.append({"role": "9 Writer", "calls": 1, "tokens_in": w_in, "model": SONNET, "worst": _worst(SONNET, w_in, 8_000), "expected": _usd(SONNET, w_in, 40 * max(1, len(rules)))})  # fmt: skip
    for r in rows:
        r["worst"] = max(
            r["worst"], r["expected"]
        )  # a worst case is never below the expected
    rows[0]["note"] = (
        f"{len(pages)} page(s); pictures counted at {PICTURE_TOKENS} tokens each"
    )
    rows[2]["note"] = (
        f"{len(chosen)} chapter(s) chosen, {len(chapters)} part(s), {len(groups)} group(s); {len(reading.books)} book(s)"
    )
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--copy", required=True)
    ap.add_argument("--paper", required=True)
    ap.add_argument("--run")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    conn = open_copy(Path(args.copy))
    rows = plan(conn, args.paper, args.run)
    worst, expected = sum(r["worst"] for r in rows), sum(r["expected"] for r in rows)
    if args.json:
        print(
            json.dumps(
                {"roles": rows, "worst_usd": worst, "expected_usd": expected},
                default=float,
            )
        )
    else:
        print(
            f"{'role':<20}{'calls':>6}{'tokens in':>12}{'worst USD':>11}{'expected USD':>14}  note"
        )
        for r in rows:
            print(
                f"{r['role']:<20}{r['calls']:>6}{r['tokens_in']:>12}{r['worst']:>11.2f}{r['expected']:>14.2f}  {r.get('note', '')}"
            )
        print(
            f"{'TOTAL':<20}{sum(r['calls'] for r in rows):>6}{sum(r['tokens_in'] for r in rows):>12}{worst:>11.2f}{expected:>14.2f}"
        )
    stop = expected > STOP_EXPECTED or worst > STOP_WORST
    print(
        ("STOP: " if stop else "within the stop line: ")
        + f"expected {expected:.2f} (limit {STOP_EXPECTED}), worst {worst:.2f} (limit {STOP_WORST})"
    )
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(main())
