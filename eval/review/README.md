# The review score (#676)

P1 scores chat answers. This scores **reviews**: did a review run find the real
defects in a submittal, and only those? Nothing else measures that.

The scorer (`backend/tools/review_score.py`, command `scripts/review_score.py`)
compares a run's findings with an **answer key**. It prints counts and item ids,
never document text, so a report can be posted to the tracking comment.

## The numbers, each with its denominator

| number | meaning | rule |
|---|---|---|
| recall | defects found / defects in the key | a defect is found when a finding on it is NON_COMPLIANT, MISSING_INFORMATION, CONDITIONAL or NEEDS_ENGINEER_REVIEW |
| precision | correct findings / findings the key can judge | a flag on a defect, COMPLIANT on a met item or trap, NOT_APPLICABLE on a not-applicable item are correct |
| false compliant | defects a finding called COMPLIANT | **must be 0**; any one blocks a merge |
| false not-applicable | defects, met items or traps a finding called NOT_APPLICABLE | counted |
| trap false flags | traps a finding flagged / traps in the key | a trap looks wrong and is fine |
| citation validity | findings whose cited page (and clause) really contain the requirement / findings checked | **not checked** (never 100%) when the page text or the stored verdict is missing |

A finding no key item matches is **not judged by the key**: it stays out of
precision, and is counted, unless the key says `complete_for_flags` (every real
defect is listed), in which case a flagged finding with no item is a false
positive. Findings with another status (NOT_IN_DOCUMENT_SCOPE, empty...) are
counted apart and are not in precision.

## The answer key (`review-answer-key/1`)

JSON, shape in `answer_key.schema.json`, sample in `keys/invented-pump.json`
(invented, to test the scorer).

* `source`: `invented`, `engineer_confirmed` (a named engineer wrote or approved
  it; `approved_by` is required), `gold_lite` or `hidden_exam`.
* `gold_lite` (#829): read by a named session or person from real documents
  (`read_by` is required), **not confirmed by an engineer** (`approved_by` is
  refused). Every report says so beside the key's name. It shows a change
  between runs (a met item that stops being met, a new false compliant); it
  does not prove a verdict is right. A gold-lite key built from client
  documents stays on this machine: only ids and counts are committed.
* `items[]`: `id`, `kind` (`defect`, `met`, `trap`, `not_applicable`),
  `standard` (file name or document number), `clause`, optional `field`.
* A finding matches the item whose standard matches and whose clause is equal to
  or above the finding's clause (`4.2` matches `4.2.1`, not `4.20`); a `field`
  must have all its words in the finding. The most specific item wins; a finding
  answers one item.

* **Checklist items (#829).** A checklist finding has no standard document: its
  label carries the standard and the clause together ("API 520-I 5.3"). The
  export splits it (`standard`, `clause`, `checklist: true`), so a key item
  names them the usual way. A label that is not "a standard, then a clause
  number" is left as it is; no standard is guessed.
* `submittal_page` (optional, on an item): the datasheet page the item is about,
  for a sheet that covers several valves or tags. A finding answers the item
  only on that page; an item without it is answered on any page. A finding that
  names **no** page (for example "no value was found") still answers a paged
  item, when exactly one item fits; two items that differ only by their page
  are answered by neither. The score says how many defects were found that
  way (`defects_found_without_page`): found, but the engineer is not told where.

## The findings file (`review-findings/1`)

Written by `export` from a **copy** of the database, read-only. It holds
requirement text, so it stays on this machine. Each finding: `standard`,
`standard_number`, `clause`, `page`, `field`, `compliance_status`,
`requirement_text`, and `citation_valid` (a boolean, computed at export time
against the stored page text; null when the page is missing). The file also
names the `model`, and every number is reported per model so the same keys run
unchanged on the Mac Studio (#683).

## Scores by step (#832)

`review_score.py score` judges the decision step. `review_score.py steps --runs-dir DIR` scores
every step on its own and prints one table per document type (counts only):

| step | compares | the key needs | the findings file needs |
|---|---|---|---|
| reading | fields the key says the sheet holds / fields the run read | `fields_read` | `fields_read` |
| standards chosen | standards that apply / standards the run selected | `standards_chosen` | `standards_selected` |
| pairing | for each item that names a `field`: does the answering finding name that field | items with `field` | - |
| decision | defects found, findings right (the usual score) | the usual items | - |
| CRS wording | **not scored**: a person reads wording | - | - |

Optional key fields: `document_type` (the slice; "document type not stated" when absent),
`fields_complete` and `standards_complete` (true when the key's list is the whole list; only then
is precision judged, otherwise the extra things the run named are counted and not judged). The
export adds `standards_selected` and `fields_read` as names only (no value, no text); a database
without the tables gives no list and the step reads "not scored: ...". A step with nothing to
compare is never 0 and never 100 %. Counts are SUMMED per document type and then divided;
percentages are never averaged. Hidden-exam keys are never read by `steps`.

## Commands

```powershell
python scripts\review_score.py export --db COPY.sqlite --run RUN_ID --out runs\invented-pump.findings.json --model qwen3.5:4b
python scripts\review_score.py score  --key eval\review\keys\invented-pump.json --findings runs\invented-pump.findings.json
python scripts\review_score.py check  --key eval\review\keys\invented-pump.json --findings runs\invented-pump.findings.json
python scripts\review_score.py record-baseline --key ... --findings ...
python scripts\review_score.py weekly --runs-dir runs --out runs\week.md
```

* `check` exits 1 (BLOCKED) when any defect was called COMPLIANT, or when recall,
  precision or citation validity is more than `margin` (5 points) below the
  stored baseline for that key and model. With no baseline stored it checks the
  false-compliant rule only and says so.
* `weekly` scores every key in `eval/review/keys` that has a run file
  `<runs-dir>/<key name>.findings.json`, and prints a counts-only markdown report
  to post as the one tracking comment. A key with no run is listed, never
  scored; no number is invented. It always states how many keys are invented and
  how many are from a named engineer, because invented keys prove the scorer,
  not the system.
* The baseline lives in `baseline.json` (empty until the first real run is
  recorded). It also holds the **proposed** bar below.

## The proposed world-class bar (owner to confirm)

recall >= 80%, trap false flags <= 10%, false compliant = 0, citations valid =
100%. This is Claude's recommendation (issue #676), not a measurement. The
report shows each number against it as "meets", "BELOW" or "cannot tell".

## What this does not do

* **The hidden exam (#650).** No default, glob or loop in this code opens that
  folder. The weekly report skips any key whose `source` is `hidden_exam` and
  refuses a keys folder with `hidden-exam` in its path. Only the merger session
  scores it, by passing its key to `score` itself.
* **Real answer keys.** At least two real submittals with a CRS written or
  approved by a named engineer at the client are an owner action. Until they exist the
  weekly report says it scored only invented keys.
* It does not replace `scripts/blind_score.py`, which scores a run's CRS rows
  against an engineer's CSV key (the blind-test procedure, `docs/blind-test.md`).
  The two answer different questions: that one asks "are the comments right",
  this one asks "were the real defects found, and was nothing wrongly cleared".
