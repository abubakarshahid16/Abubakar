# P1: the labelled question set

A fixed list of questions with known right answers, run through the real chat
on every change. If a question that used to pass stops passing, the change is
blocked.

## What is in this folder

| file | what it is |
|---|---|
| `corpus.py` | seven invented standards (STD-A-001 and so on) and the code that writes them as PDFs |
| `questions.json` | 30 invented-name questions: direct, reworded, abbreviation, document named in the question, table, condition, old revision, and six that the corpus cannot answer |
| `baseline.json` | which questions pass today. The bar. It only goes up |
| `harness.py`, `run_p1.py` | build the corpus in a throwaway database, ask every question, score, compare |
| `../../backend/tests/test_p1_question_set.py` | the gate. GitHub CI runs it with the rest of the suite |

## Run it

```powershell
cd D:\project\Rag_chatbot
$env:REASONING_PROVIDER = "ollama"
$env:PYTHONPATH = "backend"
.venv\Scripts\python.exe eval\p1\run_p1.py
```

It uses a temp database. It never opens your live one, calls no model and
spends nothing on Claude.

After a real improvement, raise the bar and commit the new `baseline.json`:

```powershell
.venv\Scripts\python.exe eval\p1\run_p1.py --write-baseline
```

## What counts as a pass

* An answerable question passes when the answer cites the right document and
  page and the returned text holds the expected words.
* An unanswerable question passes only when it is refused.
* The clause label is scored separately ("clause label right"), because a
  chunk with several short clauses carries the first clause's label. That is a
  citation defect, not a wrong answer, and it should not hide the other score.

A change is blocked when a baseline question fails, a baseline clause label is
lost, or a new unanswerable question gets an answer.

## What this does not prove

The text is invented. This project learned on 27 September that results on
invented text can be poor on real documents. So:

1. Run the same format on the real library. Put the questions in
   `.cowork/p1-real-questions.json` (git ignores `.cowork/`, so no client
   text, filenames or page numbers reach git) and run
   `python eval\p1\run_p1.py --questions .cowork\p1-real-questions.json`
   against a copy of the library, never the live database. A real-library
   run needs its own baseline kept in `.cowork/` too.
2. An engineer should extend the set from 30 to 100 or more, and write the
   expected answers before seeing the system's output. Until then the set
   was written by the same side that builds the system, and says so in
   `questions.json`.

## Known failures on the day it was written

Nine of 30 questions fail. They are recorded, not hidden, and fixing one
raises the bar: reworded questions that the word gate refuses (3), a named
standard's question that returns its Scope page or is refused (2), the old
revision question (1), a condition question (1), one direct question where
the right page is cited but the wrong chunk (1), and one unanswerable
question that gets an answer (1). These match the "wrong page and old
revisions" and "matches words, not meaning" items in the plan.
