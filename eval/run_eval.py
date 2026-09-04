"""Evaluation harness.

Consumes a question set written by someone else. It does NOT contain questions
and must never grow any: a system evaluated against questions its own author
chose is measuring the author, not the system. If eval/questions.json is
absent this script refuses to run rather than substituting anything.

Re-runnable by design. Every run writes a timestamped JSON result beside the
question set so any two runs can be diffed, which is the only way to know
whether a change helped or merely moved the failures around.

Usage, from the project root with the venv active:

    python eval/run_eval.py                       # against eval/questions.json
    python eval/run_eval.py --questions other.json
    python eval/run_eval.py --compare eval/results/<earlier>.json
    python eval/run_eval.py --tier generated      # Tier 2; slow, ~50s each

Expected question-set shape (see questions.schema.json):

    {
      "corpus": "NORSOK M-501 Rev. 5",
      "questions": [
        {
          "id": "Q1",
          "question": "...",
          "answerable": true,
          "expected_document": "NORSOKM501Rev5.pdf",
          "expected_pages": [17],
          "expected_clause": "A.1",
          "expected_answer_contains": ["280"]
        },
        { "id": "Q11", "question": "...", "answerable": false }
      ]
    }

Only `id`, `question` and `answerable` are required. Every other field is
scored when present and skipped when absent, so a partially specified set
still produces the metrics it can support rather than failing or guessing.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import answer as answer_mod  # noqa: E402
from app import keyword  # noqa: E402
from app.db import init_db  # noqa: E402

DEFAULT_QUESTIONS = Path(__file__).resolve().parent / "questions.json"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

REQUIRED_FIELDS = ("id", "question", "answerable")


def load_questions(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(
            f"No question set at {path}.\n\n"
            "This harness does not contain its own questions, on purpose: a\n"
            "system evaluated against questions its own author chose is\n"
            "measuring the author. Put the independently written set at that\n"
            "path (see the shape in this file's docstring, or\n"
            "eval/questions.schema.json) and run again."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise SystemExit(f"{path} has no 'questions' array.")
    for i, q in enumerate(questions):
        missing = [f for f in REQUIRED_FIELDS if f not in q]
        if missing:
            raise SystemExit(
                f"question {i} ({q.get('id', 'no id')}) is missing: {', '.join(missing)}"
            )
    return data


def _clause_matches(expected: str, actual: str | None) -> bool:
    """A clause matches when the answer cites that clause or one inside it.

    "A.1" is satisfied by "A.1 Coating system no. 1"; "10.2" is satisfied by
    "10.2.3". Scored this way because a citation to a subclause of the
    expected clause is right, not nearly right.
    """
    if not actual:
        return False
    actual_number = actual.split()[0]
    return actual_number == expected or actual_number.startswith(expected + ".")


def _pages_of(result: dict) -> list[int]:
    pages: list[int] = []
    for p in result.get("answer_passages") or ([result["passage"]] if result.get("passage") else []):
        pages.extend(range(p["page_start"], p["page_end"] + 1))
    return pages


def score_one(q: dict, result: dict) -> dict:
    """Score one question. Every metric is None when the set does not specify
    the ground truth for it, so an unscored dimension is never counted as a
    pass."""
    answered = result["answer_type"] in ("extract", "generated")
    row: dict = {
        "id": q["id"],
        "question": q["question"],
        "answerable": bool(q["answerable"]),
        "answer_type": result["answer_type"],
        "answered": answered,
        "seconds": round(result["seconds"], 3),
        "reason": result.get("reason"),
        "cited_clause": (result.get("passage") or {}).get("section"),
        "cited_document": (result.get("passage") or {}).get("filename"),
        "cited_pages": _pages_of(result),
        "passage_count": len(result.get("answer_passages") or []),
        "retrieval_correct": None,
        "citation_correct": None,
        "answer_correct": None,
        "refusal_correct": None,
        "false_refusal": False,
    }

    if not q["answerable"]:
        row["refusal_correct"] = not answered
        return row

    row["false_refusal"] = not answered

    if q.get("expected_pages") is not None:
        row["retrieval_correct"] = bool(
            answered and set(row["cited_pages"]) & set(q["expected_pages"])
        )
        if answered and q.get("expected_document"):
            row["retrieval_correct"] = bool(
                row["retrieval_correct"]
                and row["cited_document"] == q["expected_document"]
            )

    if q.get("expected_clause") is not None:
        row["citation_correct"] = bool(
            answered and _clause_matches(q["expected_clause"], row["cited_clause"])
        )

    wanted = q.get("expected_answer_contains")
    if wanted:
        haystack = " ".join(
            p["text"] for p in (result.get("answer_passages") or [])
        ).lower()
        row["answer_correct"] = bool(answered) and all(
            str(w).lower() in haystack for w in wanted
        )
        row["missing_from_answer"] = [
            w for w in wanted if str(w).lower() not in haystack
        ]

    return row


def _rate(rows: list[dict], field: str) -> tuple[int, int] | None:
    scored = [r for r in rows if r[field] is not None]
    if not scored:
        return None
    return sum(1 for r in scored if r[field]), len(scored)


def summarise(rows: list[dict]) -> dict:
    answerable = [r for r in rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]
    latencies = [r["seconds"] * 1000 for r in rows]
    ordered = sorted(latencies)

    def pct(fraction: float) -> float | None:
        if not ordered:
            return None
        i = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
        return round(ordered[i], 1)

    return {
        "questions": len(rows),
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "retrieval": _rate(answerable, "retrieval_correct"),
        "citation": _rate(answerable, "citation_correct"),
        "answer_correctness": _rate(answerable, "answer_correct"),
        "refusal": _rate(unanswerable, "refusal_correct"),
        "false_refusals": (
            sum(1 for r in answerable if r["false_refusal"]),
            len(answerable),
        ),
        "median_ms": round(statistics.median(latencies), 1) if latencies else None,
        "p95_ms": pct(0.95),
        "worst_ms": round(max(latencies), 1) if latencies else None,
        "two_passage_answers": sum(1 for r in rows if r["passage_count"] > 1),
    }


def _fmt(value) -> str:
    if value is None:
        return "not specified by the question set"
    if isinstance(value, tuple):
        got, total = value
        return f"{got}/{total}" + (f"  ({100 * got / total:.0f}%)" if total else "")
    return str(value)


def report(summary: dict, rows: list[dict], before: dict | None) -> None:
    print("\n" + "=" * 72)
    print("EVALUATION")
    print("=" * 72)
    print(f"  questions            {summary['questions']} "
          f"({summary['answerable']} answerable, {summary['unanswerable']} not)")
    labels = [
        ("retrieval (correct page)", "retrieval"),
        ("citation (correct clause)", "citation"),
        ("answer correctness", "answer_correctness"),
        ("refusal accuracy", "refusal"),
        ("false refusals", "false_refusals"),
    ]
    for label, key in labels:
        line = f"  {label:26} {_fmt(summary[key])}"
        if before and before.get(key) is not None and summary[key] is not None:
            line += f"   was {_fmt(tuple(before[key]))}"
        print(line)
    print(f"  {'median latency':26} {summary['median_ms']} ms"
          + (f"   was {before['median_ms']} ms" if before else ""))
    print(f"  {'p95 / worst latency':26} {summary['p95_ms']} / {summary['worst_ms']} ms")
    print(f"  {'two-passage answers':26} {summary['two_passage_answers']}")

    failures = [
        r for r in rows
        if r["false_refusal"]
        or r["retrieval_correct"] is False
        or r["citation_correct"] is False
        or r["answer_correct"] is False
        or r["refusal_correct"] is False
    ]
    if not failures:
        print("\n  no failures")
        return
    print(f"\n  {len(failures)} question(s) failed at least one metric:")
    for r in failures:
        marks = []
        if r["false_refusal"]:
            marks.append("FALSE REFUSAL")
        if r["retrieval_correct"] is False:
            marks.append("wrong page")
        if r["citation_correct"] is False:
            marks.append("wrong clause")
        if r["answer_correct"] is False:
            marks.append(f"missing {r.get('missing_from_answer')}")
        if r["refusal_correct"] is False:
            marks.append("ANSWERED THE UNANSWERABLE")
        print(f"    {r['id']:5} {', '.join(marks)}")
        print(f"          {r['question'][:66]}")
        print(f"          got: {r['answer_type']} · {r['cited_clause']} · "
              f"pages {r['cited_pages']}")
        if r["reason"]:
            print(f"          reason: {r['reason']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    ap.add_argument("--tier", choices=("extract", "generated"), default="extract")
    ap.add_argument("--compare", type=Path, help="an earlier results file")
    ap.add_argument("--limit", type=int, default=3)
    args = ap.parse_args()

    data = load_questions(args.questions)
    init_db()
    keyword.ensure_schema()

    before = None
    if args.compare:
        before = json.loads(args.compare.read_text(encoding="utf-8"))["summary"]

    rows = []
    for q in data["questions"]:
        result = answer_mod.answer(q["question"], tier=args.tier, limit=args.limit)
        row = score_one(q, result)
        rows.append(row)
        print(f"  {row['id']:5} {row['answer_type']:22} "
              f"{str(row['cited_clause'])[:30]:30} {row['seconds'] * 1000:>7.0f} ms")

    summary = summarise(rows)
    report(summary, rows, before)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS_DIR / f"{stamp}-{args.tier}.json"
    out.write_text(
        json.dumps(
            {
                "at": stamp,
                "tier": args.tier,
                "questions_file": str(args.questions),
                "corpus": data.get("corpus"),
                "summary": summary,
                "rows": rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n  written to {out}")
    print(f"  compare a later run with:  python eval/run_eval.py --compare {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
