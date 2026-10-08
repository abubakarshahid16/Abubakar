"""P1: the labelled question set, run through the real chat on an invented corpus.

WHAT IT DOES. Builds the invented corpus (corpus.py) into whatever database
`app.config.settings` currently points at, asks every labelled question through
`chat.ask` (extract tier: no model call, no Claude spend), scores each answer
with the same scorer as `eval/run_eval.py`, and compares the result with
`baseline.json`.

THE RULE IT ENFORCES. The score may go up but never down. A drop in any
category, or any unanswerable question that gets an answer, fails the run.
`baseline.json` lists each question that currently passes. A question moves
into the baseline only when it passes; it never moves out.

WHAT IT IS NOT. It is not proof on real documents. It uses invented text, and
this project learned (27 September) that fake-data results can be poor on real
documents. The same questions format runs on the real library with
`--questions <private file>` kept under `.cowork/` (git-ignored); see
`eval/p1/README.md`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(HERE))

import corpus as p1_corpus  # noqa: E402

QUESTIONS = HERE / "questions.json"
BASELINE = HERE / "baseline.json"


def check_labels(questions: list[dict]) -> list[str]:
    """Every label must be true of the invented text. A wrong label would
    blame the system for the author's mistake."""
    problems = []
    for q in questions:
        if not q["answerable"]:
            continue
        doc = q["expected_document"]
        if doc not in p1_corpus.DOCS:
            problems.append(f"{q['id']}: unknown document {doc}")
            continue
        pages = q["expected_pages"]
        if not any(1 <= p <= len(p1_corpus.DOCS[doc]) for p in pages):
            problems.append(f"{q['id']}: page out of range")
            continue
        text = " ".join(p1_corpus.page_text(doc, p) for p in pages).lower()
        for needle in q["expected_answer_contains"]:
            if needle.lower() not in text:
                problems.append(f"{q['id']}: {needle!r} is not on the expected page")
    return problems


def ingest_corpus(folder: Path) -> dict[str, str]:
    """Upload and ingest every invented PDF; returns filename -> document id."""
    from fastapi.testclient import TestClient

    from app import db
    from app.ingest import IngestionWorker
    from app.main import app

    client = TestClient(app, base_url="http://localhost")
    ids = {}
    for path in p1_corpus.build(folder):
        with path.open("rb") as fh:
            resp = client.post(
                "/api/documents", files={"file": (path.name, fh, "application/pdf")})
        assert resp.status_code == 200, (resp.status_code, resp.text[:300])
        doc_id = resp.json()["document"]["id"]
        IngestionWorker().process(doc_id)
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO document_classification (document_id,document_role,"
                "suggested_by) VALUES (?,'COMPANY_STANDARD','p1')"
                " ON CONFLICT(document_id) DO UPDATE SET document_role="
                "'COMPANY_STANDARD'", (doc_id,))
        ids[path.name] = doc_id
    return ids


def run_questions(questions: list[dict]) -> list[dict]:
    """Ask each question in its OWN conversation, so no question borrows terms
    from the one before it (the set measures questions, not chat memory)."""
    from run_eval import score_one

    from app import chat as chat_mod
    from app.search import every_document_id

    scope = every_document_id()
    rows = []
    for q in questions:
        conv = chat_mod.create_conversation(title=f"p1 {q['id']}")["id"]
        result = chat_mod.ask(conv, q["question"], tier="extract",
                              allowed_document_ids=scope)
        row = score_one(
            {**q, "question": q["question"]}, result, asked=q["question"])
        row["category"] = q["category"]
        row["passed"] = _passed(q, row)
        row["clause_ok"] = clause_ok(q, row)
        rows.append(row)
    return rows


def _passed(q: dict, row: dict) -> bool:
    """One question passes when the answer a reader sees is right: the right
    document and page, and the expected words in the returned text. An
    unanswerable question passes only when it is refused. The clause label is
    tracked on its own (`clause_ok`), because a chunk that holds several short
    clauses carries the first clause's label, which is a citation defect but
    not a wrong answer, and the two should not hide each other."""
    if not q["answerable"]:
        return bool(row["refusal_correct"])
    return row["retrieval_correct"] is True and row["answer_correct"] is True


def clause_ok(q: dict, row: dict) -> bool | None:
    from run_eval import _clause_matches

    if not q["answerable"] or not q.get("expected_clause"):
        return None
    return bool(_clause_matches(q["expected_clause"], row.get("cited_clause")))


def summarise_by_category(rows: list[dict]) -> dict:
    cats: dict[str, list[int]] = {}
    for r in rows:
        c = cats.setdefault(r["category"], [0, 0])
        c[1] += 1
        c[0] += 1 if r["passed"] else 0
    total = [sum(v[0] for v in cats.values()), sum(v[1] for v in cats.values())]
    clause = [r["clause_ok"] for r in rows if r["clause_ok"] is not None]
    return {"total": total, "categories": cats,
            "clause_label_right": [sum(clause), len(clause)],
            "unanswerable_answered": [r["id"] for r in rows
                                      if not r["answerable"] and r["answered"]]}


def compare_with_baseline(rows: list[dict], baseline: dict) -> list[str]:
    """Reasons this run must block the change. Empty list = no regression."""
    reasons = []
    passed_now = {r["id"] for r in rows if r["passed"]}
    for qid in baseline["passing"]:
        if qid not in passed_now:
            row = next((r for r in rows if r["id"] == qid), None)
            what = "missing from the run" if row is None else (
                f"now {row['answer_type']}, cited {row['cited_document']} "
                f"pages {row['cited_pages']}")
            reasons.append(f"{qid} passed in the baseline and does not now ({what})")
    clause_now = {r["id"] for r in rows if r.get("clause_ok")}
    for qid in baseline.get("clause_passing", []):
        if qid not in clause_now:
            reasons.append(f"{qid} cited the right clause in the baseline and does not now")
    known = set(baseline.get("failing_known", []))
    for r in rows:
        if not r["answerable"] and r["answered"] and r["id"] not in known:
            reasons.append(f"{r['id']} is unanswerable and was answered")
    return reasons


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["questions"]


def load_baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))
