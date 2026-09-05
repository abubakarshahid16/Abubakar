"""Does one fact give one answer, however it is worded?

The eval set held ONE phrasing per fact. That is how a confidently wrong
answer about zinc coating temperature reached a user before it reached the
suite: the one phrasing recorded happened to be a phrasing that worked.

This runs three phrasings of the same fact - the original, one close to the
document's own wording, one loose as a user actually types - and reports the
cited page for each. A fact whose phrasings disagree is a ranking defect, and
the LIST of those facts is the deliverable: it decides what is safe to ask in
front of a client.

    python eval/run_phrasings.py
    python eval/run_phrasings.py --md docs/demo-readiness-table.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import answer as answer_mod  # noqa: E402
from app import keyword  # noqa: E402
from app.db import init_db  # noqa: E402

QUESTIONS = ROOT / "eval" / "questions.json"
PHRASINGS = ROOT / "eval" / "phrasings.json"


def ask(question: str) -> dict:
    from app.search import every_document_id
    result = answer_mod.answer(
        question, allowed_document_ids=every_document_id())
    passages = result.get("answer_passages") or []
    pages: list[int] = []
    clauses: list[str] = []
    for p in passages:
        pages.extend(range(p["page_start"], p["page_end"] + 1))
        if p["section"]:
            clauses.append(p["section"].split()[0])
    text = " ".join(p["text"] for p in passages)
    return {
        "answer_type": result["answer_type"],
        "pages": sorted(set(pages)),
        "clauses": clauses,
        "text": text,
        "reason": result.get("reason"),
        "ms": round(result["seconds"] * 1000),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--md", type=Path, help="also write a markdown table here")
    args = ap.parse_args()

    init_db()
    keyword.ensure_schema()

    # Loaded through the harness's own reader, so both scripts accept either
    # a bare array or a set with its corpus provenance recorded.
    from run_eval import load_questions

    originals = {str(q["id"]): q for q in load_questions(QUESTIONS)["questions"]}
    spec = json.loads(PHRASINGS.read_text(encoding="utf-8"))["phrasings"]

    rows = []
    for entry in spec:
        original = originals[entry["of"]]
        expected = set(entry["expected_pages"])
        variants = [
            ("original", original["q"]),
            ("document-worded", entry["close"]),
            ("user-worded", entry["loose"]),
        ]
        results = []
        for label, question in variants:
            outcome = ask(question)
            hit = bool(set(outcome["pages"]) & expected)
            content = str(entry["expected_answer"]).split(";")[0].strip()
            # only the first expected token is checked here; the full check is
            # run_eval.py's job. This report is about AGREEMENT, not content.
            has_content = content.lower()[:12] in outcome["text"].lower()
            results.append({
                "label": label,
                "question": question,
                **outcome,
                "page_ok": hit,
                "content_ok": has_content,
            })
            print(
                f"  {entry['of']:>3} {label:16} pages={str(outcome['pages'])[:14]:14} "
                f"clause={','.join(outcome['clauses'])[:12]:12} "
                f"{'OK ' if hit else 'MISS'} {outcome['answer_type'][:14]:14} {outcome['ms']:>5} ms"
            )

        cited = [tuple(r["pages"]) for r in results]
        agree = len(set(cited)) == 1
        rows.append({
            "of": entry["of"],
            "fact": entry["fact"],
            "expected_pages": sorted(expected),
            "expected_clause": entry.get("expected_clause"),
            "results": results,
            "agree": agree,
            "all_correct": all(r["page_ok"] for r in results),
        })
        print(f"      -> {'AGREE' if agree else 'DISAGREE'}"
              f"{'' if all(r['page_ok'] for r in results) else '  (and at least one is on the wrong page)'}")
        print()

    disagreeing = [r for r in rows if not r["agree"]]
    wrong = [r for r in rows if not r["all_correct"]]

    print("=" * 78)
    print(f"{len(rows)} facts, {len(rows) * 3} questions")
    print(f"  facts where all three phrasings cite the SAME page : {len(rows) - len(disagreeing)}/{len(rows)}")
    print(f"  facts where all three phrasings are CORRECT        : {len(rows) - len(wrong)}/{len(rows)}")
    if disagreeing:
        print("\n  FACTS WHOSE PHRASINGS DISAGREE - do not ask these in front of a client:")
        for r in disagreeing:
            print(f"    {r['of']}. {r['fact']}")
            for res in r["results"]:
                print(f"         {res['label']:16} -> pages {res['pages']} "
                      f"clause {','.join(res['clauses']) or '-'}")
                print(f"           {res['question']}")
    else:
        print("\n  ALL THREE PHRASINGS OF ALL TEN FACTS CITE THE SAME PAGE.")

    if args.md:
        write_markdown(args.md, rows)
        print(f"\n  table written to {args.md}")
    return 0


def write_markdown(path: Path, rows: list[dict]) -> None:
    lines = [
        "| fact | phrasing | cited page | clause | outcome |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        for i, res in enumerate(r["results"]):
            fact = r["fact"] if i == 0 else ""
            mark = "OK" if res["page_ok"] else "**wrong page**"
            lines.append(
                f"| {fact} | {res['label']}: `{res['question']}` | "
                f"{res['pages'] or '-'} | {','.join(res['clauses']) or '-'} | {mark} |"
            )
    disagreeing = [r for r in rows if not r["agree"]]
    lines.append("")
    lines.append(
        f"**{len(rows) - len(disagreeing)} of {len(rows)} facts cite the same page "
        f"across all three phrasings.**"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
