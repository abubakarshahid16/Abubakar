# P1-AI: the scored model tier (#674)

P1 asks the extract tier (no model). P1-AI asks the same invented corpus
through the **generated** tier, with the local model, and scores what the
**model wrote**. It is the everyday gate before any W4b merge; the hidden exam
(#650) stays the final unseen-document check.

**It cannot run in the cloud.** It needs the local Ollama model on the PC. In
the cloud only its scoring code and the runner's logic are tested (with invented
answers). No baseline exists yet; the first one is made on the PC.

## What is scored, per question

| score | rule |
|---|---|
| figures | no figure, sign or unit in the shown answer that the passage its sentence cites does not state. Checked by `scoring.py`, which does **not** call the application's own figure filter (#653): an exam that used the filter it tests could not notice the filter getting weaker |
| clause | the cited clause is the expected clause or a subclause |
| could not read, not a guess | a question the corpus cannot answer must be refused; an answerable one the model cannot support may be refused (costs a point), but a wrong answer is a **guess** |
| time | wall-clock seconds per question, with median, p95 and worst, so the PC cost is known |

A question **passes** when it is answered, with no ungrounded figure, the expected
facts and none of the forbidden ones (the old revision's number, the near-miss
standard's number, `psi` for a percent limit), the right document, page and clause.

Also reported, not part of the pass rule: how many figures the model wrote that
the application's filter removed (`model_figures_removed`), which is the model's
own quality.

## The questions

`questions.json`: 26 invented questions over the P1 corpus (STD-A-001 to
STD-P-014): plain figures, an old revision, near-miss standards, a negative sign,
a decimal comma, a unit trap, a table cell, and five the corpus cannot answer.
`run_p1ai.check_labels` proves every label against the corpus text first.

## Run it (on the PC, models staged)

```powershell
cd D:\project\Rag_chatbot
$env:PYTHONPATH = "backend"
.venv\Scripts\python.exe eval\p1ai\run_p1ai.py                    # default model: P1_AI_MODEL (qwen3.5:2b)
.venv\Scripts\python.exe eval\p1ai\run_p1ai.py --model qwen3.5:4b
.venv\Scripts\python.exe eval\p1ai\run_p1ai.py --write-baseline   # record what passes, for that model
```

* **The model is a setting** (`P1_AI_MODEL`, or `--model`; #683). The baseline is
  stored **per model** in `baseline.json`, so the same questions run unchanged on
  the Mac Studio.
* **One heavy job at a time:** it takes the shared lock (#684) and waits up to 30
  minutes.
* **It unloads the model when it ends**, on success, on an error and on Ctrl+C
  (#666).
* **Exit codes:** 0 ok, 1 blocked, 2 a label is false, 3 the model is not
  reachable or not installed or did not answer (no score is made: a score of
  unavailable rows would measure the host), 75 the lock was not free.

## The gate

Two rules need no baseline: a figure shown that the cited page does not hold, and
an unanswerable question that was answered. With a stored baseline for the model,
every question that passed must still pass. The owner may add a `gate`
(`min_passing`, `protected`) to a model's entry, as for P1; a baseline rewrite
keeps it.
