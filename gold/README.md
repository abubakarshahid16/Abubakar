# Gold set

Hand-checked ground truth: what a standard actually says, written down by an
engineer, so the extractor can be measured against it.

- **Filling one in:** `docs/gold-set.md`. Written for the engineer; no code.
- **Scoring:** `python scripts/gold_score.py <database> gold/*.csv`
- **Blind test of the review's findings:** `FINDINGS-TEMPLATE.csv`, filled BEFORE the
  upload, scored with `python scripts/blind_score.py <review_run_id> <key.csv>`.
  Procedure: `docs/blind-test.md`.

## Why the filled files are not committed

`.gitignore` keeps `gold/*.csv` out of the repository except the three templates
(`TEMPLATE.csv`, `PAIRS-TEMPLATE.csv`, `FINDINGS-TEMPLATE.csv`).
The format asks for a clause number and a page rather than the sentence, so a
filled sheet holds no standard text - but it is still a description of a
client's standards, and this project's rule is that such material lives in the
local database and not in git. Keep the filled sheets beside the database.

**No filled sheet is tracked.** Two were, as named exceptions in `.gitignore`,
under an accepted risk recorded while the repository was private. It is public
now, and both were untracked on 2026-10-08 (they stay on the owner's disk).
Untracking does not remove them from history. `backend/tests/test_gold_sheets_untracked.py`
fails if a filled sheet is tracked again.

Nothing in the test suite depends on a filled sheet existing.

## Question sets for the real corpus (`QUESTIONS-TEMPLATE.csv`)

The shipped `eval/questions.json` was written against a reference corpus that is
not in the owner's database: on 2026-09-29 only 4 of its 18 questions could run
there. A set for the real documents is built in two steps:

1. Candidates are pulled from the documents (a page, a clause and the verbatim
   line holding a value; plus commercial terms checked to appear in no chunk).
2. An engineer writes each question in their own words, corrects the expected
   answer, and sets `engineer_verified` to `yes`. Unverified lines are left out.

`python scripts/questions_from_csv.py gold/QUESTIONS-real.csv gold/QUESTIONS-real.json`
then `python eval/run_eval.py --questions gold/QUESTIONS-real.json --tier generated`.
Filled sheets and the JSON quote client documents and stay out of git.
