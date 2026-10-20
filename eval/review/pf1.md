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

## The report (`scripts/pf1_report.py`)

```powershell
python scripts\pf1_report.py --set D:\project\pf1-set\set --runs D:\project\pf1-set\runs\main-1 --json report.json --check
```

Reads the set's `index.json` and keys, and per sheet `<id>.findings.json`
(`review_score.py export`) and `<id>.run.json` (`pf1-run/1`: `mode` main or
checklists_off, `status`, `minutes`, `pages_read`, `pages_total`). Prints the
per-type table and totals, counts only: defects caught (and as a plain
Does-not-meet), **false Meets on planted defects (the hard rule, 0)**, correct
items confirmed Meets / wrongly flagged, keyed items decided, citations valid,
pages read, minutes. A sheet with no run is listed, never scored as zeros; an
unfinished run says INCOMPLETE beside its numbers; two modes in one report are
refused (the MAIN score and the diagnostic are never added). Held-out sheets are
in the totals and never named. `--check` exits 1 on any false Meets.

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
