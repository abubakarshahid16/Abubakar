"""Evaluation harness.

Consumes a question set written by someone else. It does NOT contain questions
and must never grow any: a system evaluated against questions its own author
chose is measuring the author, not the system. If eval/questions.json is
absent this script refuses to run rather than substituting anything.

TWO MODES, MEASURING TWO DIFFERENT THINGS.

  conversational (DEFAULT)  Drives chat.ask inside ONE conversation, asking the
                            questions in order, which is what a person does.
                            This exercises resolve_followup, so terms carried
                            from an earlier turn can change or rewrite a later
                            question before retrieval ever sees it. THIS IS THE
                            PRODUCT, and it is the headline number.

  isolated (--isolated)     Calls answer.answer directly with no conversation,
                            so every question is asked in a vacuum. This is a
                            DIAGNOSTIC: it measures retrieval and answering
                            with the conversation layer removed.

The isolated mode was the only mode for the first eleven runs, and it reported
a clean sheet while the product did not have one. It structurally cannot fail
on a conversational defect, because it never creates a conversation. A harness
that scores better than the product is the harness being wrong.

Re-runnable by design. Every run writes a timestamped JSON result beside the
question set so any two runs can be diffed, which is the only way to know
whether a change helped or merely moved the failures around.

Usage, from the project root with the venv active:

    python eval/run_eval.py                       # conversational (the product)
    python eval/run_eval.py --isolated            # diagnostic: no conversation
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
import hashlib
import json
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import answer as answer_mod  # noqa: E402
from app import chat as chat_mod  # noqa: E402
from app.search import every_document_id  # noqa: E402
from app import keyword  # noqa: E402
from app.db import connect
from app.config import settings
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


def evidence_of(result: dict) -> list[dict]:
    """The passages the answer was actually built from, whichever tier ran.

    THIS FUNCTION EXISTS BECAUSE THE SCORER COULD NOT READ A TIER 2 ANSWER.
    Every field below - pages, clauses, passage count, returned text - read
    `answer_passages`, which ONLY the extract branch sets. A generated answer
    sets `passages` and `cited` instead, so every Tier 2 row scored zero
    passages, no pages and empty text: retrieval and citation came out false
    however good the answer was.

    Nobody saw it because the harness has only ever been run at
    `--tier extract`, even though `--tier generated` is documented at the top
    of this file. The same shape as the two defects before it: the harness
    could not see the failure because it never asked under the condition.

    For a generated answer the evidence is the passages the model CITED, not
    every passage it was shown - citing is what makes a passage part of the
    answer.
    """
    if result.get("answer_passages"):
        return list(result["answer_passages"])
    if result.get("passage"):
        return [result["passage"]]
    supplied = result.get("passages") or []
    cited = [i for i in (result.get("cited") or []) if 1 <= i <= len(supplied)]
    return [supplied[i - 1] for i in cited]


def _lead(result: dict) -> dict | None:
    """The passage the answer leads on, whichever tier ran."""
    evidence = evidence_of(result)
    return evidence[0] if evidence else None


def _pages_of(result: dict) -> list[int]:
    pages: list[int] = []
    for p in evidence_of(result):
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
    allowed_document_ids = frozenset(every_document_id())
    for q in questions:
        if q["answerable"]:
            continue
        for term in lexical.distinctive_terms(
            q["question"], allowed_document_ids=allowed_document_ids
        ):
            if not lexical.looks_like_a_named_subject(term, q["question"]):
                continue
            occurrences = keyword.term_occurrences(
                term, allowed_document_ids=allowed_document_ids
            )
            if occurrences > 0:
                problems.append(
                    f"question {q['id']} is marked UNANSWERABLE but its named "
                    f"subject {term!r} now appears in {occurrences} indexed "
                    f"chunk(s). The corpus has changed since this question was "
                    f"written; the ground truth is stale, not the system."
                )
    return problems


def score_one(q: dict, result: dict, asked: str | None = None) -> dict:
    """Score one question. Every metric is None when the set does not specify
    the ground truth for it, so an unscored dimension is never counted as a
    pass."""
    answered = result["answer_type"] in ("extract", "generated")
    # What retrieval ACTUALLY ran, and what was borrowed from earlier turns.
    # A row that scores wrong because the question was rewritten has to say so
    # on its face rather than needing someone to go digging.
    resolved = result.get("resolved_question") or asked or q["question"]
    carried = result.get("carried_terms") or []
    row: dict = {
        "id": q["id"],
        "question": q["question"],
        "resolved_question": resolved,
        "carried_terms": carried,
        "question_was_rewritten": resolved.strip() != q["question"].strip(),
        "answerable": bool(q["answerable"]),
        "answer_type": result["answer_type"],
        "answered": answered,
        "seconds": round(result["seconds"], 3),
        "reason": result.get("reason"),
        # Also read through evidence_of: `passage` is an extract-only field, so
        # a Tier 2 answer reported no document and no clause, and
        # retrieval_correct was then false however well it had answered.
        "cited_clause": (_lead(result) or {}).get("section"),
        "cited_document": (_lead(result) or {}).get("filename"),
        "cited_pages": _pages_of(result),
        "passage_count": len(evidence_of(result)),
        "retrieval_correct": None,
        "citation_correct": None,
        "answer_correct": None,
        "refusal_correct": None,
        "false_refusal": False,
        "length_limited": False,
    }

    # A REFUSAL CAUSED BY THE TOKEN BUDGET IS NOT A REFUSAL ABOUT THE CORPUS.
    #
    # When generation runs out of room inside its only citation, the marker is
    # stripped, the answer is left unsupported, and it is refused - correctly,
    # by the same rule that rejects invented citations. But the CAUSE is a
    # length limit, not an absence of evidence, and counting the two together
    # corrupts the metric in both directions:
    #
    #   * on an UNANSWERABLE question it scores a correct refusal for the wrong
    #     reason, so refusal accuracy would IMPROVE the more often generation
    #     ran out of room - a truncation bug making the system look better.
    #   * on an ANSWERABLE question it is recorded as a false refusal, blaming
    #     retrieval for a failure that happened after retrieval succeeded.
    #
    # Neither number is about the documents, so it is reported as its own
    # category and excluded from both. Left unscored rather than counted as a
    # pass or a fail: an unscored dimension is never a pass here.
    row["length_limited"] = bool(result.get("truncated") and not answered)
    if row["length_limited"]:
        return row

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
        cited_clauses = [p["section"] for p in evidence_of(result) if p["section"]]
        row["citation_correct"] = bool(answered) and all(
            any(_clause_matches(expected, cited) for cited in cited_clauses)
            for expected in q["expected_clauses"]
        )
        row["expected_clauses"] = q["expected_clauses"]
        row["all_cited_clauses"] = cited_clauses

    wanted = q.get("expected_answer_contains")
    if wanted:
        # For a quotation the evidence IS the answer. For generated prose the
        # answer is the model's own text, and that is where an expected figure
        # has to appear - a token present only in a source the model was shown
        # is not the model having answered.
        haystack = " ".join(
            [result.get("answer") or ""]
            + [p["text"] for p in evidence_of(result)]
        ).lower()
        row["answer_correct"] = bool(answered) and all(
            str(w).lower() in haystack for w in wanted
        )
        row["missing_from_answer"] = [
            w for w in wanted if str(w).lower() not in haystack
        ]
        row["required_tokens"] = list(wanted)
        row["expected_answer"] = q.get("expected_answer")
        row["returned_text"] = (
            result.get("answer")
            or " ".join(p["text"] for p in evidence_of(result))
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
        # Reported separately and never folded into the two above. Should be
        # zero; a non-zero value means some questions were not scored at all,
        # and the other rates are over a smaller population than they look.
        "length_limited": sum(1 for r in rows if r.get("length_limited")),
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
    # Printed unconditionally, including when it is zero. A category that only
    # appears when non-zero is a category nobody remembers exists, and its
    # absence would be indistinguishable from it never having been checked.
    n_len = summary.get("length_limited", 0)
    print(f"  {'length-limited refusals':26} {n_len}"
          + ("   <- NOT counted in refusal accuracy or false refusals; these "
             "questions were not scored" if n_len else "   (none - the two "
             "refusal figures above are over the whole set)"))
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



def observed_corpus() -> dict:
    """The corpus this run ACTUALLY ran against, read from the database.

    The stored field used to be `data.get("corpus")` - a static string copied
    out of the questions file. It described what the questions were written
    against and was stamped on the result regardless of what was ingested, so
    a result file claimed "3 documents" whether or not a fourth was present.
    Every stored result was therefore unattributable, which is why a phantom
    "superlinear latency growth" could not be checked against the record and
    had to be re-measured from scratch.

    A result that cannot say what it ran against is not a measurement.
    """
    conn = connect()
    docs = conn.execute(
        "SELECT id, filename, chunk_count FROM documents WHERE status = 'ready'"
        " ORDER BY id"
    ).fetchall()
    chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    retrievable = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE retrievable = 1"
    ).fetchone()[0]
    vectors = conn.execute("SELECT COUNT(*) FROM chunk_vectors").fetchone()[0]
    ids = "".join(r["id"] for r in docs)
    return {
        "documents": len(docs),
        "document_ids_sha256": hashlib.sha256(ids.encode()).hexdigest()[:16],
        "filenames": [r["filename"] for r in docs],
        "chunks": chunks,
        "retrievable": retrievable,
        "excluded": chunks - retrievable,
        "vectors": vectors,
    }


def machine_state() -> dict:
    """Free RAM and whether the answer model is resident.

    Recorded because it moves the headline number more than anything about the
    corpus does: across nine runs of the same question set, the first
    question's latency and the warm median correlated at r = 0.977, and the
    median ranged 1,434-4,291 ms with the corpus unchanged. A latency figure
    without this is not reproducible.
    """
    state: dict = {}
    try:
        import psutil

        mem = psutil.virtual_memory()
        state["ram_percent_used"] = mem.percent
        state["ram_available_gib"] = round(mem.available / 2**30, 2)
        state["process_rss_mib"] = round(
            psutil.Process().memory_info().rss / 2**20
        )
    except Exception as exc:  # noqa: BLE001 - provenance must never fail a run
        state["memory_error"] = f"{type(exc).__name__}: {exc}"

    # Whether the generation model is loaded. Asked of the local daemon only;
    # no document text, question or answer leaves the machine.
    try:
        import httpx

        r = httpx.get(f"{settings.ollama_url}/api/ps", timeout=2.0)
        loaded = [m.get("name") for m in r.json().get("models", [])]
        state["answer_model_resident"] = bool(loaded)
        state["models_resident"] = loaded
    except Exception as exc:  # noqa: BLE001
        state["answer_model_resident"] = None
        state["ollama_error"] = f"{type(exc).__name__}: {exc}"
    return state


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    ap.add_argument("--tier", choices=("extract", "generated"), default="extract")
    ap.add_argument("--compare", type=Path, help="an earlier results file")
    ap.add_argument("--limit", type=int, default=3)
    ap.add_argument(
        "--isolated", action="store_true",
        help="ask every question in a vacuum (diagnostic). The default drives "
             "chat.ask in one conversation, which is what a person does.")
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
    # The eval tools have no user, so they state corpus-wide OUT LOUD.
    # When auth arrives this is a line somebody changes on purpose.
    corpus_scope = every_document_id()

    mode = "isolated" if args.isolated else "conversational"
    print(f"  MODE: {mode}"
          + ("  (diagnostic - no conversation, resolve_followup never runs)"
             if args.isolated else
             "  (the product - one conversation, questions in order)"))
    conversation_id = None
    if not args.isolated:
        conversation_id = chat_mod.create_conversation(
            title=f"eval {datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")["id"]

    for q in data["questions"]:
        if q["id"] in stale_ids:
            print(f"  {q['id']:>5} SKIPPED - ground truth stale for this corpus")
            continue
        # A question may pin its own tier. Question 17 exists to exercise the
        # Tier 2 context window against numeric-table evidence, and asked at
        # Tier 1 it proves nothing at all - Tier 1 never builds a prompt.
        tier = q.get("tier", args.tier)
        if args.isolated:
            result = answer_mod.answer(
                q["question"], tier=tier, limit=args.limit,
                allowed_document_ids=corpus_scope)
        else:
            result = chat_mod.ask(conversation_id, q["question"],
                                  tier=tier, limit=args.limit,
                                  allowed_document_ids=corpus_scope)
        row = score_one(q, result, asked=q["question"])
        # Evidence dropped to fit the context window. Recorded per row because
        # it is invisible otherwise: the runtime used to discard it inside
        # llama.cpp and report FEWER tokens evaluated than the window holds.
        row["evidence_removed"] = result.get("evidence_removed") or []
        row["tier"] = tier
        rows.append(row)
        flag = ""
        if row["question_was_rewritten"]:
            # The single most useful thing this harness can print. A wrong row
            # whose question was rewritten is a DIFFERENT defect from a wrong
            # row whose question was asked as written.
            flag = f"  <- REWRITTEN, carried {row['carried_terms']}"
        print(f"  {row['id']:5} {row['answer_type']:22} "
              f"{str(row['cited_clause'])[:30]:30} {row['seconds'] * 1000:>7.0f} ms{flag}")
        if flag:
            print(f"        asked   : {row['question']}")
            print(f"        ran     : {row['resolved_question']}")

    summary = summarise(rows)
    report(summary, rows, before)

    observed = observed_corpus()
    machine = machine_state()
    print()
    print("  RAN AGAINST (read from the database, not from the question set)")
    print(f"    {observed['documents']} ready documents, "
          f"{observed['chunks']} chunks, {observed['retrievable']} retrievable, "
          f"{observed['excluded']} excluded, {observed['vectors']} vectors")
    print(f"    document-set hash {observed['document_ids_sha256']}")
    declared = data.get("corpus")
    if declared:
        print(f"    questions were written against: {declared}")
    print(f"    machine: RAM {machine.get('ram_percent_used')}% used, "
          f"{machine.get('ram_available_gib')} GiB free, "
          f"answer model resident: {machine.get('answer_model_resident')}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS_DIR / f"{stamp}-{args.tier}.json"
    out.write_text(
        json.dumps(
            {
                "at": stamp,
                "tier": args.tier,
                "questions_file": str(args.questions),
                # what the QUESTIONS were written against (static, from the
                # question set) versus what this run ACTUALLY saw (read from
                # the database). Keeping both makes a mismatch visible instead
                # of letting the first masquerade as the second.
                "corpus_declared": data.get("corpus"),
                "corpus_observed": observed,
                "machine": machine,
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
