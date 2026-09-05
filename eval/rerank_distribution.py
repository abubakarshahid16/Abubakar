"""What separates a query whose answer is present from one whose answer is not?

The credibility decision is currently a constant, MIN_RERANK_SCORE = -3.0, on a
scale that moves by 16 points with nothing but the wording of the question. The
same correct passage scores +8 for one phrasing and -8 for another. A constant
cannot sit on that.

Before designing a replacement, look at the actual shape of the candidate set
for every query we have ground truth for. Two populations:

  ANSWER PRESENT   the 30 phrasings, where a correct candidate exists
  ANSWER ABSENT    the 5 unanswerable questions, where none does

For each query this reports the top score, the second, the median, the spread,
the gap between first and second, and - for the present population - where the
CORRECT candidate actually sat. If the two populations differ in shape rather
than in level, the decision can be made on shape and will survive a document
whose score distribution sits somewhere else entirely.

    python eval/rerank_distribution.py
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import keyword, lexical, search  # noqa: E402
from app.db import init_db  # noqa: E402

QUESTIONS = ROOT / "eval" / "questions.json"
PHRASINGS = ROOT / "eval" / "phrasings.json"

#: How many candidates to look at. Deliberately more than rerank_candidates so
#: the shape of the whole field is visible, not just the shortlist.
LOOK_AT = 16


def profile(question: str, expected_pages: set[int] | None) -> dict:
    """The shape of the candidate set for one query."""
    result = search.search(question, limit=LOOK_AT,
                           allowed_document_ids=search.every_document_id())
    hits = result["hits"]
    scores = [h["rerank_score"] for h in hits if h["rerank_score"] is not None]
    if not scores:
        return {"question": question, "n": 0}

    correct_rank = None
    correct_score = None
    if expected_pages:
        for i, h in enumerate(hits, start=1):
            pages = set(range(h["page_start"], h["page_end"] + 1))
            if pages & expected_pages:
                correct_rank, correct_score = i, h["rerank_score"]
                break

    top = scores[0]
    second = scores[1] if len(scores) > 1 else None
    median = statistics.median(scores)
    # Heading precedence evidence: does the top candidate's HEADING declare the
    # question's designator, or does it only mention it in the body?
    wanted = keyword.find_designators(question)
    top_heading_declares = None
    if wanted:
        heading = (hits[0]["section"] or "").lower()
        top_heading_declares = any(w in heading for w in wanted)

    return {
        "question": question,
        "n": len(scores),
        "top": top,
        "second": second,
        "median": median,
        "min": min(scores),
        "gap": (top - second) if second is not None else None,
        # Spread of the FIELD below the winner: how much better is the winner
        # than a typical candidate for this query?
        "lift": top - median,
        "stdev": statistics.pstdev(scores) if len(scores) > 1 else 0.0,
        "correct_rank": correct_rank,
        "correct_score": correct_score,
        "top_section": hits[0]["section"],
        "top_pages": (hits[0]["page_start"], hits[0]["page_end"]),
        "top_heading_declares": top_heading_declares,
        "lexical_ok": lexical.assess(question, hits[0]["text"])["ok"],
    }


def row(label: str, p: dict) -> str:
    if p["n"] == 0:
        return f"  {label:26} no candidates"

    def f(v, w=7, d=2):
        return f"{v:>{w}.{d}f}" if isinstance(v, (int, float)) else f"{'-':>{w}}"

    correct = (
        f"#{p['correct_rank']} @{p['correct_score']:.2f}"
        if p["correct_rank"]
        else "NOT IN FIELD"
    )
    return (
        f"  {label:26} top{f(p['top'])} 2nd{f(p['second'])} med{f(p['median'])} "
        f"gap{f(p['gap'],6)} lift{f(p['lift'],6)} sd{f(p['stdev'],5,1)}  "
        f"correct {correct:14} lex={'ok' if p['lexical_ok'] else 'NO'}"
    )


def summarise(name: str, profiles: list[dict]) -> dict:
    usable = [p for p in profiles if p["n"] > 0]
    tops = [p["top"] for p in usable]
    gaps = [p["gap"] for p in usable if p["gap"] is not None]
    lifts = [p["lift"] for p in usable]
    print()
    print(f"  {name}: n={len(usable)}")
    for field, values in (("top", tops), ("gap (top-2nd)", gaps), ("lift (top-median)", lifts)):
        if values:
            print(
                f"    {field:20} min={min(values):>7.2f}  median={statistics.median(values):>7.2f}"
                f"  max={max(values):>7.2f}"
            )
    return {
        "top": tops,
        "gap": gaps,
        "lift": lifts,
    }


def main() -> int:
    init_db()
    keyword.ensure_schema()

    originals = {str(q["id"]): q for q in json.loads(QUESTIONS.read_text(encoding="utf-8"))}
    spec = json.loads(PHRASINGS.read_text(encoding="utf-8"))["phrasings"]

    print("=" * 118)
    print("ANSWER PRESENT - 30 phrasings of 10 facts")
    print("=" * 118)
    present: list[dict] = []
    for entry in spec:
        original = originals[entry["of"]]
        expected = set(entry["expected_pages"])
        print(f"  fact {entry['of']}: {entry['fact'][:70]}   expect pages {sorted(expected)}")
        for label, q in (
            ("original", original["q"]),
            ("document-worded", entry["close"]),
            ("user-worded", entry["loose"]),
        ):
            p = profile(q, expected)
            p["fact"] = entry["of"]
            p["label"] = label
            present.append(p)
            print(row(label, p))
        print()

    print("=" * 118)
    print("ANSWER ABSENT - the 5 unanswerable questions")
    print("=" * 118)
    absent: list[dict] = []
    for q in json.loads(QUESTIONS.read_text(encoding="utf-8")):
        if q.get("answerable"):
            continue
        p = profile(q["q"], None)
        p["label"] = f"id {q['id']}"
        absent.append(p)
        print(row(f"id {q['id']}", p))
        print(f"      {q['q'][:100]}")

    print()
    print("=" * 118)
    print("THE TWO POPULATIONS")
    print("=" * 118)
    a = summarise("ANSWER PRESENT", present)
    b = summarise("ANSWER ABSENT", absent)

    print()
    print("  SEPARATION:")
    for field in ("top", "gap", "lift"):
        pa, pb = a[field], b[field]
        if not pa or not pb:
            continue
        overlap = max(min(pa), min(pb)) <= min(max(pa), max(pb))
        print(
            f"    {field:18} present [{min(pa):7.2f} .. {max(pa):7.2f}]   "
            f"absent [{min(pb):7.2f} .. {max(pb):7.2f}]   "
            f"{'OVERLAP' if overlap else 'CLEAN SPLIT'}"
        )

    # Where the correct candidate sat, for the present population
    print()
    ranks = [p["correct_rank"] for p in present if p.get("correct_rank")]
    missing = [p for p in present if p["n"] and not p.get("correct_rank")]
    print(f"  correct candidate in the field: {len(ranks)}/{len([p for p in present if p['n']])}")
    if ranks:
        print(f"    at rank 1: {sum(1 for r in ranks if r == 1)}   "
              f"rank 2-3: {sum(1 for r in ranks if 2 <= r <= 3)}   "
              f"rank 4+: {sum(1 for r in ranks if r >= 4)}")
    if missing:
        print("    NOT IN THE FIELD AT ALL:")
        for p in missing:
            print(f"      fact {p['fact']} {p['label']}: {p['question'][:70]}")

    # Heading precedence: how often does the top candidate only MENTION the
    # designator while a heading-declaring candidate sits just below?
    print()
    close_calls = [
        p for p in present
        if p["n"] > 1 and p["gap"] is not None and p["gap"] < 1.0
    ]
    print(f"  queries where top and second are within 1.0 point: {len(close_calls)}")
    for p in close_calls:
        print(f"    fact {p['fact']} {p['label']:16} gap={p['gap']:.3f} "
              f"top={p['top_section']} heading_declares={p['top_heading_declares']}")

    out = ROOT / "eval" / "rerank-distribution.json"
    out.write_text(json.dumps({"present": present, "absent": absent}, indent=2, default=str), encoding="utf-8")
    print(f"\n  raw data written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
