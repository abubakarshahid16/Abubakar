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
import re
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


#: Field names the set may use for the same thing. The question set is the
#: authority, not this harness: it was written independently and adapting to
#: it is the harness's job. Editing the set to fit the reader would defeat the
#: purpose of having someone else write it.
ALIASES = {
    "question": ("question", "q", "text"),
    "expected_document": ("expected_document", "document", "doc"),
    "expected_pages": ("expected_pages", "pages"),
    "expected_clause": ("expected_clause", "clause"),
    "expected_answer": ("expected_answer", "answer", "expected"),
    "expected_answer_contains": ("expected_answer_contains", "contains"),
}

#: A figure with its unit, or an engineering identifier. Used to derive
#: mechanically checkable tokens from a prose expected answer - see
#: required_tokens.
_GRADING_STOPWORDS = {
    "with", "and", "the", "from", "that", "this", "each", "least", "than",
    "above", "below", "before", "after", "into", "over", "under", "total",
    "roughly", "about", "approximately", "minimum", "maximum",
}

_NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_IDENTIFIER_TOKEN = re.compile(r"\b(?:[A-Z]{2,}[\s\-]?\d[\w\-.]*|[A-Z][a-z]?[A-Z][A-Za-z0-9]*)\b")


def _get(q: dict, canonical: str):
    for name in ALIASES.get(canonical, (canonical,)):
        if name in q and q[name] not in (None, "", []):
            return q[name]
    return None


def required_tokens(expected_answer: str) -> list[str]:
    """Mechanically checkable tokens from a prose expected answer.

    The set states its expected answers as prose - "85 % relative humidity;
    steel at least 3 C above dew point" - which cannot be graded by string
    equality. Rather than have this harness judge prose, and so grade its own
    author's work, it checks only what is unambiguous: the figures and the
    identifiers. Everything else is printed for a human to judge.

    Reported as "answer tokens present", NOT as answer correctness. Those are
    different claims and conflating them would overstate the result.
    """
    tokens: list[str] = []
    for m in _NUMBER.finditer(expected_answer):
        tokens.append(m.group(0))
    for m in _IDENTIFIER_TOKEN.finditer(expected_answer):
        tokens.append(m.group(0))
    if not tokens:
        # Some expected answers carry no figure at all - "nominal dry film
        # thickness", "by brush to welds, corners and edges". Falling back to
        # their content words keeps those questions scored rather than
        # silently unscored, which would quietly shrink the denominator.
        tokens = [
            w for w in re.findall(r"[A-Za-z]{4,}", expected_answer)
            if w.lower() not in _GRADING_STOPWORDS
        ]

    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def normalise(raw: dict | list) -> dict:
    """Accept either a bare array or an object with a 'questions' array, and
    either field-naming convention, without touching the file."""
    if isinstance(raw, list):
        data: dict = {"questions": raw}
    else:
        data = dict(raw)
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise SystemExit("the question set has no questions")

    normalised = []
    for i, q in enumerate(questions):
        text = _get(q, "question")
        if text is None:
            raise SystemExit(f"question {i} has no question text")
        if "answerable" not in q:
            raise SystemExit(f"question {q.get('id', i)} does not say if it is answerable")
        expected_answer = _get(q, "expected_answer")
        contains = _get(q, "expected_answer_contains")
        clause = _get(q, "expected_clause")
        normalised.append({
            **q,
            "id": str(q.get("id", i + 1)),
            "question": text,
            "answerable": bool(q["answerable"]),
            "expected_document": _get(q, "expected_document"),
            "expected_pages": _get(q, "expected_pages"),
            # A compound expectation - "4.4 + 11" - means BOTH clauses must be
            # cited, which is exactly what two-passage answers exist for.
            "expected_clauses": (
                [c.strip() for c in str(clause).split("+") if c.strip()]
                if clause else None
            ),
            "expected_answer": expected_answer,
            "expected_answer_contains": (
                list(contains) if contains
                else required_tokens(expected_answer) if expected_answer
                else None
            ),
        })
    data["questions"] = normalised
    return data


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
    return normalise(json.loads(path.read_text(encoding="utf-8")))


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


def check_ground_truth(questions: list[dict]) -> list[str]:
    """An "unanswerable" question is only unanswerable relative to a corpus.

    Question 12 asked which coating system applies to Inconel 625 and was
    marked absent, correctly, against a three-document corpus. A 1,400-page
    manual was then added which contains the word "inconel", and the harness
    reported the question as ANSWERED THE UNANSWERABLE - a refusal regression
    - when the truth was that its ground truth had gone stale.

    That cost a diagnosis. The corpus was checked by hand to find it, and the
    harness should have found it first. So: before scoring anything, every
    question marked absent has its distinctive terms checked against the
    index, and a term that is now PRESENT is reported as a stale-ground-truth
    error rather than as a system failure.
    """
    from app import lexical  # noqa: PLC0415 - keeps the import local to the check

    problems: list[str] = []
    for q in questions:
        if q["answerable"]:
            continue
        for term in lexical.distinctive_terms(q["question"]):
            if not lexical.looks_like_a_named_subject(term, q["question"]):
                continue
            occurrences = keyword.term_occurrences(term)
            if occurrences > 0:
                problems.append(
                    f"question {q['id']} is marked UNANSWERABLE but its named "
                    f"subject {term!r} now appears in {occurrences} indexed "
                    f"chunk(s). The corpus has changed since this question was "
                    f"written; the ground truth is stale, not the system."
                )
    return problems


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

    if q.get("expected_clauses"):
        # Every expected clause must be cited somewhere in the answer. A
        # compound expectation is only satisfied by covering both.
        cited_clauses = [
            p["section"] for p in (result.get("answer_passages") or []) if p["section"]
        ]
        row["citation_correct"] = bool(answered) and all(
            any(_clause_matches(expected, cited) for cited in cited_clauses)
            for expected in q["expected_clauses"]
        )
        row["expected_clauses"] = q["expected_clauses"]
        row["all_cited_clauses"] = cited_clauses

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
        row["required_tokens"] = list(wanted)
        row["expected_answer"] = q.get("expected_answer")
        row["returned_text"] = " ".join(
            p["text"] for p in (result.get("answer_passages") or [])
        )[:600]

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
        ("answer tokens present", "answer_correctness"),
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

    # Stale ground truth is a different failure from a system regression, and
    # conflating them wastes the time of whoever reads the report.
    stale = check_ground_truth(data["questions"])
    if stale:
        print()
        print("=" * 72)
        print("STALE GROUND TRUTH - the corpus changed since these were written")
        print("=" * 72)
        for problem in stale:
            print(f"  {problem}")
        print()
        print("These questions are EXCLUDED from scoring, not counted as failures.")
        print("Fix the set for the current corpus, or write new absent-topic questions.")
        print("This is NOT a refusal regression.")
        print("=" * 72)

    before = None
    if args.compare:
        before = json.loads(args.compare.read_text(encoding="utf-8"))["summary"]

    # Excluded from scoring, never counted as a system failure. Conflating a
    # stale question with a regression is what cost a diagnosis when a new
    # document made question 12's absent term present.
    stale_ids = {p.split()[1] for p in stale}

    rows = []
    for q in data["questions"]:
        if q["id"] in stale_ids:
            print(f"  {q['id']:>5} SKIPPED - ground truth stale for this corpus")
            continue
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
