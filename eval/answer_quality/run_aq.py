"""Answer quality: run prompt variants over the invented questions and score them (order 189, part B).

    python eval/answer_quality/run_aq.py --variants default,quote_first --out aq.json

WHERE IT RUNS: GitHub Actions only (`.github/workflows/answer-quality-cpu.yml`,
dispatch by hand), on the INVENTED P1 corpus and its invented questions
(`eval/p1ai/questions.json`). Never on the Mac, never on the live server, never
on a real document: it builds a throwaway database in a temp folder, exactly as
`eval/p1ai/run_p1ai.py` does, and asks through `chat.ask`. No Claude spend.

WHAT IT MEASURES per variant (`quality_scoring.py`, code only): faithfulness,
response relevancy, citation recall and precision, and noise sensitivity (the
same question asked again with two irrelevant passages from other documents
added in front; that second call goes straight to the model, so it is the
model's own wording, not the filtered answer). A variant is kept only if
`quality_scoring.keep_variant` finds it same or better than "default" on EVERY
measure with no new forbidden answer and no new figure the cited page lacks.
A measure with no value cannot justify keeping a variant.

Exit codes: 0 report made, 2 a label is false, 3 the model is not reachable
(no score is made: unavailable rows would measure the host).
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
for sub in (HERE, HERE.parent / "p1ai", HERE.parent / "p1"):
    sys.path.insert(0, str(sub))
import harness  # noqa: E402  (eval/p1/harness.py: also puts backend/ and eval/ on sys.path)
import quality_scoring as qs  # noqa: E402

NOISE_PASSAGES = 2
EXIT_NO_MODEL = 3


def noise_for(q_index: int, own: list[dict], pool: list[dict]) -> list[dict]:
    """Two passages that are not this question's own, taken in a fixed order
    (the same noise for every variant, so variants are compared fairly)."""
    own_texts = {p.get("text") for p in own}
    others = [p for p in pool if p.get("text") not in own_texts]
    rng = random.Random(q_index)
    rng.shuffle(others)
    return others[:NOISE_PASSAGES]


def corpus_pool() -> list[dict]:
    """Every page of the invented corpus as a passage: the noise is drawn from
    here, so it does not depend on what any variant retrieved."""
    import corpus as p1_corpus

    return [
        {
            "text": p1_corpus.page_text(doc, page),
            "filename": doc,
            "page_start": page,
            "page_end": page,
        }
        for doc, pages in sorted(p1_corpus.DOCS.items())
        for page in range(1, len(pages) + 1)
    ]


def run_variant(
    questions: list[dict], ask, noisy_ask, pool: list[dict], say=print
) -> list[dict]:
    """`ask(question, id) -> result` is the real chat answer; `noisy_ask(question,
    passages) -> text` sends one prompt to the model. Both are injected so the
    runner is tested without a model."""
    rows = []
    for i, q in enumerate(questions):
        started = time.perf_counter()
        result = ask(q["question"], q["id"])
        seconds = round(time.perf_counter() - started, 1)
        noisy = None
        passages = result.get("passages") or []
        answered = result.get("answer_type") in ("extract", "generated") and bool(
            result.get("answer")
        )
        if q["answerable"] and answered and passages:
            noisy_passages = [*noise_for(i, passages, pool), *passages]
            noisy = {
                "answer": noisy_ask(q["question"], noisy_passages),
                "passages": noisy_passages,
            }
        row = qs.score_row(q, result, noisy)
        row["seconds"] = seconds
        row["model_unavailable"] = result.get("answer_type") == "model_unavailable"
        rows.append(row)
        say(f"  {q['id']} {result.get('answer_type')}  {seconds:>6.1f}s")
    return rows


def compare(summaries: dict[str, dict]) -> dict[str, list[str]]:
    """variant -> reasons it is not kept (empty = kept). The base is "default"."""
    base = summaries["default"]
    return {
        name: ([] if name == "default" else qs.keep_variant(base, s))
        for name, s in summaries.items()
    }


def markdown(
    summaries: dict[str, dict], verdicts: dict[str, list[str]], model: str, n: int
) -> str:
    names = list(qs.MEASURES)
    lines = [
        f"Answer quality on the invented questions ({n} asked), model {model}.",
        "Means over the questions where the measure exists (n in brackets). Noise sensitivity: lower is better.",
        "",
        "| variant | " + " | ".join(names) + " | kept? |",
        "|---|" + "---|" * (len(names) + 1),
    ]
    for v, s in summaries.items():
        cells = [
            f"{s[m]['mean']} ({s[m]['n']})"
            if s[m]["mean"] is not None
            else f"- ({s[m]['n']})"
            for m in names
        ]
        why = "base" if v == "default" else ("YES" if not verdicts[v] else "no")
        lines.append(f"| {v} | " + " | ".join(cells) + f" | {why} |")
    for v, reasons in verdicts.items():
        for r in reasons:
            lines.append(f"- {v}: {r}")
    lines += [
        "",
        "Scores are code checks (words and figures in the cited text), not a judge model: compare variants "
        "with each other, never with published scores.",
    ]
    return "\n".join(lines)


def _run(argv: list[str] | None) -> int:
    import run_p1ai

    from app.config import settings

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--variants", default="default", help="comma separated; always includes default"
    )
    ap.add_argument(
        "--limit", type=int, default=0, help="only the first N questions (0 = all)"
    )
    ap.add_argument("--model", default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    from app import answer_prompts

    names = ["default", *[v for v in args.variants.split(",") if v and v != "default"]]
    unknown = [v for v in names if v not in answer_prompts.VARIANTS]
    if unknown:
        print(f"unknown variant(s): {unknown}; known: {list(answer_prompts.VARIANTS)}")
        return 2
    questions = run_p1ai.load_questions()
    problems = run_p1ai.check_labels(questions)
    if problems:
        print(
            "LABEL PROBLEMS (the set is wrong, not the model):", *problems, sep="\n  "
        )
        return 2
    if args.limit:
        questions = questions[: args.limit]
    model = args.model or settings.answer_model

    saved_model = settings.answer_model
    status = run_p1ai.model_status(model)
    settings.answer_model = saved_model
    if not status.get("answer_model_reachable") or not status.get(
        "answer_model_installed"
    ):
        print(
            f"CANNOT RUN: the model {model} is not reachable or not installed. No score was made."
        )
        return EXIT_NO_MODEL

    from app import access, answer, db, fts_index, vector_store
    from app import chat as chat_mod
    from app.search import every_document_id

    tmp = Path(tempfile.mkdtemp(prefix="aq-"))
    saved = (
        settings.data_dir,
        settings.upload_dir,
        settings.db_path,
        settings.auth_mode,
        settings.answer_model,
        settings.answer_prompt_variant,
    )
    try:
        settings.data_dir, settings.upload_dir = tmp, tmp / "uploads"
        settings.db_path = tmp / "aq.sqlite"
        settings.auth_mode = access.AUTH_DISABLED
        settings.answer_model = model
        db.reset_connection()
        db.init_db()
        fts_index.ensure_schema()
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        harness.ingest_corpus(tmp / "corpus")
        scope = every_document_id()

        def ask(question: str, qid: str) -> dict:
            conv = chat_mod.create_conversation(title=f"aq {qid}")["id"]
            return chat_mod.ask(
                conv, question, tier="generated", allowed_document_ids=scope
            )

        def noisy_ask(question: str, passages: list[dict]) -> str:
            shaped = [
                {"locator": None, "page_start": 1, "page_end": 1, **p} for p in passages
            ]
            raw = answer._call_model(answer._build_prompt(question, shaped))
            return raw.get("response") or ""

        pool = corpus_pool()
        all_rows: dict[str, list[dict]] = {}
        for name in names:
            settings.answer_prompt_variant = name
            print(f"variant {name}: {len(questions)} questions, model {model}")
            all_rows[name] = run_variant(questions, ask, noisy_ask, pool)
    finally:
        vector_store.reset()
        db.reset_connection()
        (
            settings.data_dir,
            settings.upload_dir,
            settings.db_path,
            settings.auth_mode,
            settings.answer_model,
            settings.answer_prompt_variant,
        ) = saved
        shutil.rmtree(tmp, ignore_errors=True)
        run_p1ai.unload_models()

    if any(r["model_unavailable"] for rows in all_rows.values() for r in rows):
        print(
            "CANNOT SCORE: the model did not answer some questions. No score was made."
        )
        return EXIT_NO_MODEL
    summaries = {v: qs.aggregate(rows) for v, rows in all_rows.items()}
    verdicts = compare(summaries)
    report = markdown(summaries, verdicts, model, len(questions))
    print(report)
    if args.out:
        args.out.write_text(
            json.dumps(
                {
                    "model": model,
                    "questions": len(questions),
                    "summaries": summaries,
                    "not_kept": verdicts,
                    "report": report,
                },
                indent=1,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    from app import heavy_lock

    return heavy_lock.run_locked("p1", lambda: _run(argv), owner="answer-quality")


if __name__ == "__main__":
    raise SystemExit(main())
