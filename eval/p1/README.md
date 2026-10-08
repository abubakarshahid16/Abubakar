# P1: the labelled question set

A fixed list of questions with known right answers, run through the real chat
on every change. If a question that used to pass stops passing, the change is
blocked.

## What is in this folder

| file | what it is |
|---|---|
| `corpus.py` | eleven invented standards (STD-A-001 to STD-K-010, one of them an old revision) and the code that writes them as PDFs |
| `questions.json` | 60 invented-name questions, version 2. P1-01 to P1-30: direct, reworded, abbreviation, document named in the question, table, condition, old revision, and six that the corpus cannot answer. P1-31 to P1-60: ten hard paraphrases, five distractors, five more unanswerable, five multi-document, five number/unit/sign |
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
* A multi-document question (`expected_sources` instead of
  `expected_document`) passes only when the answer cites EVERY listed
  document on a listed page and holds every listed phrase. Citing one side
  of a comparison is half an answer.
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
2. An engineer should extend the set from 60 to 100 or more, and write the
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

## Version 2 (2026-10-08): 60 questions

Thirty questions and four invented standards (STD-G-007 to STD-K-010) were
added for issue #466. Every label is checked against the corpus text by
`check_labels`, and each new single-document answer phrase was also checked
to appear in no other document, so a label cannot be satisfied by the wrong
standard.

| category | what it tests | passed on 2026-10-08 |
|---|---|---|
| paraphrase | a version 1 topic asked without the clause's words ("stress relieving" for PWHT, "ear defenders" for hearing protection) | 2 of 10 |
| distractor | a near-miss passage in another document holds a different number (a tank's 24 hour fill hold beside a vessel's 30 minute test hold) | 5 of 5 |
| unanswerable | text that looks like an answer sits next to the question (MAWP is defined but never given a value) | 1 of 5 |
| multidoc | the answer needs two or three documents, all cited | 1 of 5 |
| number | a negative value, a signed range, a decimal comma, a power of ten | 5 of 5 |

Whole set: **37 of 60** (62 percent), clause label right 25 of 41. Version 1
was 23 of 30 (77 percent); the lower percentage is the harder questions, not
a regression: all 23 version 1 passes and all 15 version 1 clause passes
still hold with the four new documents in the corpus.

Run with the real e5-small embedder and reranker, extract tier, no model
call, no Claude spend. The new failures, by kind:

* Six of ten paraphrases are refused as insufficient evidence; one cites
  the weekly-test page for the annual-test question, one cites the new
  STD-G-007 design temperature for the enclosure ambient question. This is
  the "matches words, not meaning" gap (#467).
* Four of five new unanswerable questions get an answer: the MAWP
  abbreviation line, a pump reading-frequency clause for gearboxes, the
  heat tracing range for an inspection question, and the primer DFT for a
  finish coat DFT question.
* Four of five multi-document questions miss at least one of their
  documents (one leads on the wrong page of the fan standard).

What the 5 of 5 on numbers does NOT show: the extract tier quotes the PDF
text verbatim, so a sign, comma or exponent cannot be lost on the way out.
Those questions test that the right clause is found. They would test number
handling only when run on a tier that rewrites the value (generated answers).
