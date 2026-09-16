"""Real Precision@K / Recall@K for the hybrid retriever, against the gold set.

WHAT THIS MEASURES, PRECISELY. eval/run_eval.py checks one thing per question:
did the single BEST passage the system settled on match the expected page. It
never looks at what else sat in the ranked candidate list. Precision@K and
Recall@K are a different, harder question: of the top K candidates the
retriever RANKED (before any answer is written), how many are actually
relevant, and how much of the known-relevant material got surfaced at all.

GROUND TRUTH, AND ITS HONEST LIMIT. "Relevant" here means: the chunk's page
range overlaps one of the `expected_pages` already hand-verified in
eval/questions.json for that question. This is real, hand-checked ground
truth, not invented. But it is PAGE-LEVEL ground truth for ONE known-correct
location per question, not an exhaustive labeling of every chunk in the
corpus that could plausibly relate to the question. That means recall@K here
answers "did the retriever surface the specific page we already know holds
the answer", not "did it find every conceivably relevant passage in the
whole corpus" - the second question would require hand-labeling relevance
for all ~8,000 chunks against every question, which is not a reasonable ask
of a hand-built gold set this size. State the number for what it is.

Only questions with both `document` and `expected_pages` set are scored.
Unanswerable questions and questions without a recorded expected page
(question 10, 17) are skipped and reported as skipped, never silently
dropped.

Usage, from the project root with the venv active:

    .venv\\Scripts\\python.exe eval\\retrieval_metrics.py
    .venv\\Scripts\\python.exe eval\\retrieval_metrics.py --questions eval/questions.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.search import search, every_document_id  # noqa: E402
from app.db import init_db  # noqa: E402

DEFAULT_QUESTIONS = Path(__file__).resolve().parent / "questions.json"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

K_VALUES = (3, 5, 10)


def pages_covered(hit: dict) -> set[int]:
    start, end = hit["page_start"], hit["page_end"]
    if start is None or end is None:
        return set()
    return set(range(start, end + 1))


def score_question(q: dict, max_k: int) -> dict | None:
    expected_pages = set(q.get("expected_pages") or [])
    expected_document = q.get("document")
    if not expected_pages or not expected_document:
        return None

    question = q.get("question") or q.get("q") or q.get("text")
    if not isinstance(question, str) or not question.strip():
        return None
    result = search(
        question, limit=max_k, rerank=True,
        allowed_document_ids=every_document_id(),
    )
    hits = result["hits"]

    per_k = {}
    for k in K_VALUES:
        topk = hits[:k]
        relevant_flags = [
            h["filename"] == expected_document and pages_covered(h) & expected_pages
            for h in topk
        ]
        relevant_count = sum(1 for flag in relevant_flags if flag)
        covered_pages: set[int] = set()
        for h in topk:
            if h["filename"] == expected_document:
                covered_pages |= pages_covered(h) & expected_pages

        precision = relevant_count / k if k else 0.0
        recall = len(covered_pages) / len(expected_pages) if expected_pages else 0.0
        per_k[k] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "relevant_in_topk": relevant_count,
            "pages_covered": sorted(covered_pages),
        }

    return {
        "id": q["id"],
        "question": question,
        "expected_document": expected_document,
        "expected_pages": sorted(expected_pages),
        "per_k": per_k,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    args = parser.parse_args()

    questions_path = Path(args.questions)
    if not questions_path.exists():
        print(f"refusing to run: {questions_path} does not exist")
        sys.exit(1)

    data = json.loads(questions_path.read_text(encoding="utf-8"))
    questions = data["questions"]

    init_db()

    max_k = max(K_VALUES)
    rows = []
    skipped = []
    for q in questions:
        row = score_question(q, max_k)
        if row is None:
            skipped.append(q["id"])
            continue
        rows.append(row)

    summary = {}
    for k in K_VALUES:
        precisions = [r["per_k"][k]["precision"] for r in rows]
        recalls = [r["per_k"][k]["recall"] for r in rows]
        summary[k] = {
            "mean_precision": round(sum(precisions) / len(precisions), 4) if precisions else None,
            "mean_recall": round(sum(recalls) / len(recalls), 4) if recalls else None,
        }

    print(f"\nScored {len(rows)} question(s); skipped {len(skipped)} "
          f"(no expected_pages/document): {skipped}\n")
    print(f"{'K':>4}  {'mean precision@K':>18}  {'mean recall@K':>15}")
    for k in K_VALUES:
        s = summary[k]
        print(f"{k:>4}  {s['mean_precision']!s:>18}  {s['mean_recall']!s:>15}")

    print("\nPer-question (K=5):")
    for r in rows:
        p5 = r["per_k"][5]
        print(f"  [{r['id']}] precision@5={p5['precision']:.2f} "
              f"recall@5={p5['recall']:.2f}  {r['question']!r}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"{stamp}-precision-recall.json"
    out_path.write_text(
        json.dumps({"at": stamp, "summary": summary, "skipped": skipped, "rows": rows}, indent=2),
        encoding="utf-8",
    )
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
