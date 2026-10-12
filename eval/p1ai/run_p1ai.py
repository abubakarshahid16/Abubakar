"""P1-AI: the scored model tier of P1 (#674). Usage, from the repo root, models staged:

    python eval/p1ai/run_p1ai.py                       # compare with baseline.json
    python eval/p1ai/run_p1ai.py --model qwen3.5:4b    # another model (a setting, #683)
    python eval/p1ai/run_p1ai.py --write-baseline      # record what passes right now
    python eval/p1ai/run_p1ai.py --show                # print every question's row

CANNOT RUN IN THE CLOUD: it needs the local Ollama model. It uses a throwaway
database in a temp folder, the invented corpus of P1, and no Claude spend.

* ONE HEAVY JOB AT A TIME: it takes the shared lock (`app.heavy_lock`, #684)
  and waits for it up to 30 minutes.
* IT LEAVES THE MACHINE AS IT FOUND IT: every model it used is unloaded when it
  ends, on success, on an error and on Ctrl+C (#666).
* THE MODEL IS A SETTING: `P1_AI_MODEL` (default qwen3.5:2b) or `--model`. The
  baseline is kept per model, so the same questions run unchanged on another
  machine. A model that is not reachable ends the run with code 3 and NO score:
  a score made of "model unavailable" rows would measure the host, not the model.
* TIME PER QUESTION is printed with the median, p95 and worst, so the PC cost
  is known.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "p1"))
sys.path.insert(0, str(HERE))
import harness  # noqa: E402  (eval/p1/harness.py: also puts backend/ and eval/ on sys.path)
import scoring  # noqa: E402

QUESTIONS = HERE / "questions.json"
BASELINE = HERE / "baseline.json"
EXIT_NO_MODEL = 3


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["questions"]


def load_baseline(path: Path = BASELINE) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"baselines": {}}


def check_labels(questions: list[dict]) -> list[str]:
    """Every label must be true of the invented text, so a wrong label can never
    blame the model for the author's mistake."""
    import corpus as p1_corpus

    problems = []
    for q in questions:
        if not q["answerable"]:
            continue
        doc = q["expected_document"]
        if doc not in p1_corpus.DOCS:
            problems.append(f"{q['id']}: unknown document {doc}")
            continue
        pages = q["expected_pages"]
        if not all(1 <= p <= len(p1_corpus.DOCS[doc]) for p in pages):
            problems.append(f"{q['id']}: page out of range")
            continue
        text = " ".join(p1_corpus.page_text(doc, p) for p in pages)
        if not scoring.facts_present(text, q["expected_answer_contains"]):
            problems.append(f"{q['id']}: an expected phrase is not on the expected page")
        clause = q.get("expected_clause")
        if clause and not any(line.startswith(clause + " ")
                              for p in pages for line in p1_corpus.DOCS[doc][p - 1]):
            problems.append(f"{q['id']}: clause {clause} is not on the expected page")
        for bad in q.get("forbidden_in_answer") or []:
            if any(scoring.facts_present(want, [bad]) for want in q["expected_answer_contains"]):
                # a forbidden phrase that sits inside a required one would fail every right answer
                problems.append(f"{q['id']}: forbidden phrase {bad!r} is part of a required phrase")
    for q in questions:
        if not q["answerable"] and (q.get("expected_document") or q.get("expected_answer_contains")):
            problems.append(f"{q['id']}: an unanswerable question names an expected answer")
    return problems


def model_status(model: str) -> dict:
    """Is the local model reachable and installed? (One probe; no document text.)"""
    from app import metrics
    from app.config import settings

    settings.answer_model = model
    metrics.reset_ollama_cache()
    return metrics._probe_ollama()


def run_questions(questions: list[dict], ask, scope, say=print) -> list[dict]:
    """Ask each question in its OWN conversation through `ask(question) -> result`
    and time it. `ask` is injected so the runner can be tested without a model."""
    from run_eval import score_one

    rows = []
    for q in questions:
        started = time.perf_counter()
        result = ask(q["question"], q["id"])
        elapsed = time.perf_counter() - started
        result = {**result, "seconds": result.get("seconds") or elapsed}
        row = score_one({**q}, result, asked=q["question"])
        row["category"] = q["category"]
        row["seconds"] = round(elapsed, 2)          # wall clock, not the model's own timer
        scoring.score_row(q, row, result)
        rows.append(row)
        say(f"  {q['id']} {'PASS' if row['passed'] else 'fail'}  {row['seconds']:>6.1f}s  [{q['category']}]")
    return rows


def report(rows: list[dict], model: str, say=print) -> dict:
    s = scoring.summarise(rows)
    say(f"P1-AI score: {s['passed']} of {s['questions']}   model: {model}")
    say(f"  figures not in the cited passage (answers): {len(s['figures_ungrounded_answers'])}"
        + (f"  {s['figures_ungrounded_answers']}" if s["figures_ungrounded_answers"] else ""))
    say(f"  guessed (answered, wrong):                 {len(s['guessed'])}"
        + (f"  {s['guessed']}" if s["guessed"] else ""))
    say(f"  unanswerable but answered:                 {len(s['unanswerable_answered'])}")
    say(f"  answerable, 'could not read':              {len(s['could_not_read_answerable'])}")
    say(f"  clause right:                              {s['clause_right'][0]} of {s['clause_right'][1]}")
    say(f"  figures the model wrote and the filter removed: {s['model_figures_removed']}")
    say(f"  time per question: median {s['seconds_median']}s, p95 {s['seconds_p95']}s, "
        f"worst {s['seconds_worst']}s, total {s['seconds_total']}s")
    return s


def unload_models(say=print) -> None:
    try:
        from app import model_memory

        r = model_memory.unload_used()
        if r["unloaded"] or r["failed"]:
            say(f"models unloaded: {r['unloaded']}" + (f"  NOT unloaded: {r['failed']}" if r["failed"] else ""))
    except Exception as exc:  # noqa: BLE001 - freeing memory must never turn a result into a crash
        say(f"models could not be unloaded ({type(exc).__name__})")


def main(argv: list[str] | None = None) -> int:
    from app import heavy_lock

    # One heavy job at a time on this machine (#684).
    return heavy_lock.run_locked("p1", lambda: _guarded(argv), owner="P1-AI")


def _guarded(argv: list[str] | None) -> int:
    """Run, and leave the machine as it was found (#666): models unloaded on
    success, on an error and on Ctrl+C."""
    try:
        return _run(argv)
    finally:
        unload_models()


def _run(argv: list[str] | None, *, ask_factory=None, ingest=None) -> int:
    from app.config import settings

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default=None, help="answer model (default: the P1_AI_MODEL setting)")
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--questions", type=Path, default=QUESTIONS)
    ap.add_argument("--baseline", type=Path, default=BASELINE)
    args = ap.parse_args(argv)

    model = args.model or settings.p1_ai_model
    questions = load_questions(args.questions)
    problems = check_labels(questions) if args.questions == QUESTIONS else []
    if problems:
        print("LABEL PROBLEMS (the set is wrong, not the model):")
        for p in problems:
            print("  ", p)
        return 2

    original_model = settings.answer_model
    status = model_status(model)
    settings.answer_model = original_model
    if not status.get("answer_model_reachable") or not status.get("answer_model_installed"):
        why = (status.get("ollama_error") or "Ollama is not reachable") \
            if not status.get("answer_model_reachable") else f"model {model} is not installed"
        print(f"CANNOT RUN: {why}. No score was made (a score of unavailable rows would measure the host).")
        return EXIT_NO_MODEL

    from app import access, db, keyword, vector_store

    tmp = Path(tempfile.mkdtemp(prefix="p1ai-"))
    saved = (settings.data_dir, settings.upload_dir, settings.db_path, settings.auth_mode, settings.answer_model)
    try:
        settings.data_dir = tmp
        settings.upload_dir = tmp / "uploads"
        settings.db_path = tmp / "p1ai.sqlite"
        settings.auth_mode = access.AUTH_DISABLED
        settings.answer_model = model
        db.reset_connection()
        db.init_db()
        keyword.ensure_schema()
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        (ingest or harness.ingest_corpus)(tmp / "corpus")
        if ask_factory is None:
            from app import chat as chat_mod
            from app.search import every_document_id

            scope = every_document_id()

            def ask(question: str, qid: str) -> dict:
                conv = chat_mod.create_conversation(title=f"p1ai {qid}")["id"]
                return chat_mod.ask(conv, question, tier="generated", allowed_document_ids=scope)
        else:
            ask = ask_factory()
        print(f"P1-AI: {len(questions)} questions, model {model}")
        rows = run_questions(questions, ask, None)
    finally:
        vector_store.reset()
        db.reset_connection()
        (settings.data_dir, settings.upload_dir, settings.db_path,
         settings.auth_mode, settings.answer_model) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    if any(r["model_unavailable"] for r in rows):
        print("CANNOT SCORE: the model did not answer some questions "
              f"({[r['id'] for r in rows if r['model_unavailable']]}). No score was made.")
        return EXIT_NO_MODEL
    summary = report(rows, model)
    if args.show:
        for r in rows:
            print(f"  {r['id']} [{r['category']}] {r['answer_type']} cited {r['cited_document']} "
                  f"p{r['cited_pages']} clause {r['cited_clause']} fig_ok={r['figures_ok']} "
                  f"{r['seconds']}s | {r['question']}")
    baselines = load_baseline(args.baseline)
    if args.write_baseline:
        entry = {"passing": sorted(r["id"] for r in rows if r["passed"]),
                 "total": [summary["passed"], summary["questions"]],
                 "seconds_median": summary["seconds_median"], "seconds_total": summary["seconds_total"]}
        old = (baselines.get("baselines") or {}).get(model, {})
        if "gate" in old:
            entry["gate"] = old["gate"]       # the gate is an owner decision: a rewrite keeps it
        baselines.setdefault("baselines", {})[model] = entry
        args.baseline.write_text(json.dumps(baselines, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"baseline written for {model}: {entry['total']}")
        return 0
    reasons = scoring.compare_with_baseline(rows, (baselines.get("baselines") or {}).get(model))
    if reasons:
        print("BLOCKED:")
        for r in reasons:
            print("  -", r)
        return 1
    stored = (baselines.get("baselines") or {}).get(model)
    print("OK: no ungrounded figure, nothing unanswerable answered"
          + (", nothing that passed in the baseline fails now" if stored and stored.get("passing")
             else ". NO BASELINE stored for this model yet: run once with --write-baseline"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
