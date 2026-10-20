# PF1: the unfamiliar-datasheet test set (#881)

PROOF FIRST gate 1 (#805). The question it answers: **does a review work on a
sheet the system was not developed on?** The three approved datasheets cannot
answer that; a result on them is never quoted as proof for other sheets.

The set is **invented** datasheets of several equipment types and layouts. Each
carries planted defects, correct items and traps, and comes with the answers a
review should give. Two or three types are **held out**: never run by the
builders, never used when fixing anything, scored only by the merger session.

## Where things are

| what | where |
|---|---|
| the builder (code, no set content) | `backend/tools/pf1_set.py`, command `scripts/pf1_set.py` |
| the spec, the set, the answers | **local only**, outside every git repository |
| scoring | `scripts/review_score.py` (`eval/review/README.md`); counts only are posted |

The builder refuses an output folder inside a git repository: held-out answers
in a repository are not held out.

## Two groups (owner, 13 Oct 2026)

* **Library group (the main one).** Invented sheets planted against
  requirements **stored in our library**. A local script picks stored numeric
  limits that have a clause, a subject, an operator, a value and a unit and
  no condition or exception recorded, and plants a value by arithmetic
  (outside the limit, inside it, exactly at it, or inside it in another
  unit). The sheet cites the real standards by number. A document says
  `"library_standards": [...]` instead of `"standard"`; no standard file is
  written, and every answer names which cited standard it is about.
  The truth rests on **the stored requirement as extracted**: no engineer
  confirmed those rows, so a limit the extractor mis-read is inherited. The
  row label is the requirement's own stored subject, which makes pairing
  easier than a real vendor's wording would. Its key never claims
  `complete_for_flags`: a real library may rightly apply requirements nobody
  judged. Sheets, spec and keys hold text from the standards: local only.
* **Invented group (diagnostic).** Each sheet cites its own invented standard,
  described below.

## What the set does and does not prove

Each sheet cites **its own invented standard** (numbered clauses, a table, a
clause that does not apply), written in the author's own words. So the set
tests the whole path on unfamiliar documents: read the sheet, find the cited
standard, read its clauses, decide each one.

It does **not** test the client's real standards. Invented standards are
shorter and cleaner than real ones, so requirement reading will look better
here than on a 200-page standard. Real-standard proof stays with the engineer
review (PF6, #886) and the real CRS validation (#747).

## The spec (`pf1-spec/1`)

A JSON file kept on this machine. Everything in it must be invented.

```
{"format": "pf1-spec/1", "documents": [{
   "id": "pf1-01-pump",                 lower case, digits, dashes; unique
   "equipment_type": "Centrifugal Pump",
   "held_out": false,                   required: true or false, never a default
   "layout": "ruled_units",             one of the ten below
   "complete_for_flags": true,          optional; false when the key does not list every defect
   "sheet": {"document_number": "...", "tag": "...", "title": "...",
             "pages": [{"rows": [
                {"field": "Design pressure", "value": "9", "unit": "barg",
                 "required": "12 min",   only drawn by required_offered
                 "group": "Design",      only drawn by merged_cells
                 "key": {"id": "D1", "kind": "defect", "clause": "4.2", "note": "..."}}],
               "notes": ["..."]}]},
   "standard": {"number": "STD-0001", "title": "...",
                "sections": [{"clause": "4.2", "title": "...", "text": "... shall ...",
                              "table": [["header", "header"], ["cell", "cell"]]}]},
   "unprinted": [{"id": "N1", "kind": "not_applicable", "clause": "9.4"}]
}]}
```

* A row's `key` is its answer: `defect`, `met`, `trap` or `not_applicable`
  (the scorer's kinds). A row with no `key` is drawn and not scored.
* `key` may be a list. The same printed value can answer a clause of the
  invented standard **and** a rule of a checklist the product already holds;
  the second item names that checklist's `standard`.
* `unprinted` holds answers no row carries: a value the sheet leaves out
  altogether, a clause that does not apply.

Layouts: `ruled_units`, `two_column_form`, `required_offered`, `label_value`,
`odd_headers`, `numbered_lines`, `merged_cells`, `sentences`, `landscape`
(page turned 90 degrees), `scanned` (image only, no text layer).

## The three rules the builder enforces

1. **The key is written from the rows that are drawn.** Each keyed value is
   read back from its page of the finished sheet; one that is not there stops
   the build. (A scan is checked on the text page it is a picture of.)
2. **Every keyed clause is in the standard, and the sheet cites the standard**
   by number.
3. **The set never lands in a git repository.**

It also refuses a label wider than its cell (it would print over the value
beside it), a document with no correct item (a set of defects only cannot show
a false flag), and a `held_out` left to a default. Nothing is written unless
every document passes. The same spec gives the same bytes.

## Commands

```powershell
python scripts\pf1_set.py check --spec D:\project\pf1-set\spec.json
python scripts\pf1_set.py build --spec D:\project\pf1-set\spec.json --out D:\project\pf1-set\set
```

Both print counts only. The output: per document `<id>.datasheet.pdf`,
`<id>.standard.pdf`, `<id>.key.json` (`review-answer-key/1`, `source:
invented`), and `index.json` (document, equipment type, held out, layout,
pages, files, items by kind).

## Scoring and reporting (#881)

* **MAIN score** = the normal client workflow as a client would run it.
  "Checklists off" is a diagnostic score only.
* Per type: defects caught / planted, false Meets on planted defects, correct
  items wrongly flagged, citations valid, pages read, minutes.
* The first run is the baseline. The hard rule from day one: **0 false Meets
  on planted defects**.
* A finding from the sheet's own consistency checks carries no standard, so no
  key item can name it. With `complete_for_flags: true` the scorer counts it
  as a false positive even when it is right; read that number with this in
  mind until the scorer sets such findings apart.
* Held-out types are scored, but their per-item results stay with the scorer.

## Running the set (runner)

`scripts/pf1_run.py` sends each sheet of the built set through a **test**
server: upload (the invented group also uploads its invented standard, sets it
as a company standard and extracts it), start the review, wait for its job,
write `<id>.run.json` (run id, job state, minutes; no document text) and
`run-index.json`. It does not score: export the findings from a copy of the
test server's database with `scripts/review_score.py export --run RUN_ID`, then
`score`.

```powershell
$env:PF1_PASSWORD = "..."   # read from the environment, never an argument
python scripts\pf1_run.py --set D:\project\pf1-set\set --out D:\project\pf1-set\runs `
    --server http://127.0.0.1:11435 --test-server --db-copy D:\project\pf1-copy.sqlite `
    --email EMAIL --discipline DISCIPLINE
```

It refuses a server not named `--test-server`, one that is not on this machine,
and ports 8000 and 8001 (the ports the live app has run on); it also needs
`--db-copy` naming the diagnostic copy the run will be exported from (it must
exist and must not have the live database's shape). The runner cannot see which
database the server holds: the port and the copy are a backstop, so start the
test server on a copy yourself. Held-out sheets are skipped unless
`--include-held-out` (only the merger session uses it); `--only ID` runs one
sheet; `--no-standards` when the library already holds the standards. Prints
counts only. The runner's tests use a fake server: the first real run on the
Mac is what proves the routes still match.

## The GitHub CPU workflow (order 171)

`.github/workflows/pf1-cpu.yml` (manual only) reviews every invented **tuning**
sheet of `tests/data/pf1/` in parallel, one job per sheet, with Ollama on the
runner's CPU, then collects them (`scripts/pf1_collect.py`) and scores them with
`scripts/pf1_report.py` and posts the counts on the tracking issue. Scores count; **timings do not** (speed is measured on
the Mac). `scripts/pf1_ci_guard.py` decides which sheets may go: exactly that
folder, never a sheet marked `held_out`, never the library group (it carries
standard text), never a file outside the folder; one such sheet refuses the
whole run. No secret, no Claude call; the default token only posts the result.
The dispatcher names the Ollama release and the model tag (the Mac's), because
the workflow must not guess them. One run at a time; 300 minutes per job at
most; each job prints the minutes it used.

Feasibility is not proven: a 4B model on a shared CPU runner may not finish a
sheet inside the limit, and the dry run on two sheets is what says so. If a
run would need more than 600 minutes in total, the held-out and the slow
sheets stay on the Mac queue.

