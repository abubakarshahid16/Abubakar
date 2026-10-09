# Evaluation

The harness contains no questions, and must never grow any. A system evaluated
against questions its own author chose is measuring the author.

## Running it

```powershell
cd D:\project\Rag_chatbot
.venv\Scripts\python.exe eval\run_eval.py
```

It reads `eval/questions.json`. Without that file it refuses to run rather
than substituting anything.

| flag | effect |
|---|---|
| `--questions <path>` | use a different set |
| `--tier generated` | Tier 2 instead of quoted answers (~50 s per question) |
| `--compare <results.json>` | print each metric against an earlier run |
| `--limit N` | candidates considered per question (default 3) |

Every run writes `eval/results/<timestamp>-<tier>.json` containing the summary
and the per-question rows, so any two runs can be diffed. The folder is git-ignored: the rows hold corpus file names and passage text, which stay on this machine (CLAUDE.md rule 3). Keep a run you want to compare against outside the repo. That is the only way
to know whether a change helped or merely moved the failures around.

## P1: the gate that blocks a score drop

`eval/p1/` holds 67 invented-name questions (version 5), an invented corpus and a baseline. CI fails a change that drops below 44 of 67 or makes one of the 26 protected questions fail. See `eval/p1/README.md`.

## The question set

Shape is defined in `questions.schema.json`. Only `id`, `question` and
`answerable` are required. Every other field is scored when present and
skipped when absent, so a partially specified set yields the metrics it can
support rather than failing or having ground truth guessed for it.

`answerable: false` means the documents genuinely do not contain the answer.
Answering one of those is the worst outcome the harness measures — worse than
a refusal, because a refusal is visible and a confident wrong answer is not.

## What is measured

| metric | definition |
|---|---|
| retrieval | the cited page range overlaps `expected_pages` (and the document matches, when given) |
| citation | the cited clause is `expected_clause` or a subclause of it |
| answer correctness | every string in `expected_answer_contains` appears in the returned passage text |
| refusal accuracy | unanswerable questions that were refused |
| false refusals | answerable questions that were refused |
| latency | median, p95 and worst, wall clock per question |

A citation to a subclause of the expected clause counts as correct: `10.2` is
satisfied by `10.2.3`, because that is right rather than nearly right.

## Refusal calibration (`refusal_calibration.py`)

Measures the rerank floor (`MIN_RERANK_SCORE`, `app/answer.py`) against
whatever corpus is currently indexed, instead of the 12-example reference set
it was originally tuned on. Self-supervised: builds its own answer-present,
answer-absent and wrong-value questions from the corpus by template, needs no
human-written key.

```powershell
cd D:\project\Rag_chatbot
$env:REASONING_PROVIDER = "ollama"
.venv\Scripts\python.exe -u eval\refusal_calibration.py --present 200 --seed 20260929
```

| flag | effect |
|---|---|
| `--present N` | target number of answer-present items (default 200) |
| `--scan-cap N` | max raw chunks scanned looking for that many matches (default 20000) |
| `--seed N` | seeds both the document sampling and the wrong-value fabrication |
| `--log-path PATH` | per-row JSONL log - scores and ids only, never question or passage text (default `gold/refusal_calibration_log.jsonl`, git-ignored) |

Read-only and local: works on a `live_guard.diagnostic_copy()`, never the
live database; `tier="extract"` never calls a model; no Claude spend. Prints
counts, score distributions and a floor-sweep table only - see the module
docstring for the exact definitions (exact-chunk vs same-value vs really-wrong
answers, and the four approximations the numbers carry). Findings and the
2026-09-29 run are recorded in `docs/limitations.md`.

## Reading the numbers honestly

- **Run it with nothing else on the machine.** This laptop is the production
  machine and it thermally throttles. A run taken while documents are being
  reprocessed measures the contention, not the system: a probe during a
  reprocess showed 7.6 s for a question that takes 1.3 s idle.
- **Latency is wall clock**, including the first question paying any lazy model
  load. The median over a full set is the number to quote.
- **A metric reading "not specified by the question set"** has not passed. It
  has not been measured, and the two must never be conflated.
