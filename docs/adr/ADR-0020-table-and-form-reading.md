# ADR-0020 — Table and form reading: geometry reader + verified vision + field naming

- **Status:** PROPOSED - owner review
- **Date:** 2026-09-25
- **Issue:** #193 (pilot v2 section 5, B4)
- **Numbering note:** `ADR-0020-visually-rich-page-retrieval.md` already uses
  number 0020. This file carries the number the pilot v2 order named; the
  owner decides whether it is renumbered (next free: 0026) before acceptance.
- **Decision (proposed):** read table and form pages with a **geometry reader**
  over the PDF text layer, add a **Claude vision reader whose values are kept
  only when proven** against the text layer or a geometry cell, and let a
  model **name fields by index into a code-built dictionary, never write a
  value**. Field-name pairing of requirements to facts is **held for engineer
  review**. Everything sits behind `GEOMETRY_READER_ENABLED` (default OFF;
  the live system still runs with it OFF).

All accuracy numbers below are **PROVISIONAL / UNSCORED**: the pump answer key
(`gold/M03-FIELDS.csv`) was prepared by Claude reading the PDF, not by an
engineer, and its scored field set has not been engineer-reviewed. The vessel
and PSV sheets have no answer key. This ADR quotes no document text, field
value or standard clause; it records counts only.

## Context

- The rule reader (`tables.py` + `datasheets.pairs_from_table_shape`) parses a
  minority of table pages (ADR-0019: 33 of 98) and fills 30 of 161 pump
  answer-key fields correctly.
- Few review findings cite a submittal fact, because few facts exist to cite:
  fact-citing findings on the three regression sheets were 0 (pump), 1
  (vessel), 0 (PSV) before this work.
- Each earlier fix was a heuristic for one layout (ADR-0019). The next reader
  must work from page geometry, not from one sheet's wording.

## Decision

### 1. Geometry reader (values)

1. PyMuPDF `find_tables()` run with both the `lines` and the `text` strategy;
   per page the grid with the better **documented score** (cells filled,
   column consistency) is kept.
2. **Multi-row headers** rebuilt by geometry: a header cell whose x-span covers
   several columns becomes a parent label prefixed to each child column.
3. **Form label pairing** by word bounding boxes: a label is paired with the
   value on the same baseline to its right, or directly below inside the same
   column band.
4. **Blank needs evidence:** a slot is recorded as blank only when the page
   shows a blank marker (empty cell with ruled borders, underscores, dash
   line). "Not found by the reader" is never converted into "blank in the PDF".
5. **Code-only noise filter:** title-block, revision-block and repeated
   drawing-frame text is dropped by position and repetition rules in code; no
   model decides what is noise.
6. Every value keeps page, bounding box, table id, row and column; units are
   split by code with the original text kept.

### 2. Claude vision reader (values, verified)

Claude reads the page image. A vision value is **kept only when proven**: the
same value must appear in the page's text layer or in a geometry cell for the
same page. Unproven vision values are discarded, not stored as guesses.
Transport is `reader_transport.py` only, under the `claude_spend` caps
(USD 5 per step, USD 20 in total).

### 3. Field naming (names only, never values)

Claude/Haiku maps each column header or form label to a canonical field. The
model answers an **index into a dictionary built by code** from the answer-key
fields and the requirement fields. It never returns free text used as a value
or as a new field name. Out-of-range or absent indexes leave the label
unmapped.

### 4. Pairing requirements to facts

Numeric requirements are paired with facts by canonical field name instead of
word overlap. Pairings created this way are **held for engineer review**; they
are not shown as confirmed comparisons.

### 5. Flag

All of the above is gated by `GEOMETRY_READER_ENABLED` (config default
`False`). With it OFF, extraction is the pre-B4 extraction byte for byte. When
ON, a rule-reader fact for the same page and label always wins; a disagreeing
geometry reading is stored with `validation_state='conflict'`, never used to
overwrite. Live: OFF.

**Table path alone - `GEOMETRY_TABLE_READER_ENABLED` (default `False`),
2026-09-25.** Measured on a real vessel datasheet (owner-approved cloud test,
no document content in the repo): its nozzle schedule - 20 nozzles, one row
each across Mark / Size / Unit / Rating / Type / Facing / Service - produced
0 facts on the default path (44 label/value pairs recovered, all rightly
rejected by the value gate), and 123 correct facts from the table path. The
form path on a pump sheet mis-paired fields ("IMPELLER DIA." -> "RATED *"),
so the new flag turns on the TABLE path only; the form path and the vision
reader stay behind `GEOMETRY_READER_ENABLED`. Same precedence: a rule-reader
fact wins, and a geometry reading does not make a page "read into fields" in
the ledger. The table path also read the page-1 revision block as facts
(names under a service-order row label), so a geometry table carrying two or
more distinct revision-header words (Rev, Prepared, Checked, Approved,
"Issued for", "Status Description") is dropped whole, under either flag
(`row_noise.revision_table_ids`). Tests `test_b4_schedule_tables.py`,
mutations M780-M785. **Live: ON by default** (owner decision 2026-09-25); `GEOMETRY_TABLE_READER_ENABLED=false` switches it off.

## Options considered

| option | measured result | outcome |
|---|---|---|
| Docling / TableFormer (ADR-0019) | 22-44 s per page on CPU; pump filled F1 0.157 vs rule reader 0.294 | not adopted |
| Whole-page reading by the local 9B model | 0 rows extracted; ~16 min per page; output cut off before the table ended | rejected |
| Geometry + model column labels only | values from geometry, names from the model; basis of the chosen design | taken forward |
| PyMuPDF `find_tables` vs pdfplumber | same grids found; pdfplumber drops spaces inside cell text | PyMuPDF kept (already a dependency) |
| **Chosen:** geometry + verified vision + index-only naming + held pairing | see results below | proposed |

## Measured results (PROVISIONAL - Claude-prepared pump key, not engineer-reviewed)

Pump answer key: 161 fields.

| reader / stage | correct | wrong | where |
|---|---|---|---|
| rule reader (current live) | 30 / 161 | 0 | main |
| geometry reader, first run | 75 / 161 | 4 | branch work |
| geometry reader after fixes | 79 / 161 | 0 | branch work, then merged |
| stored facts with flag ON | 82 / 161 | 0 | merged, DB copy |
| B4 quality branch (`feat/b4-quality`, unmerged) | 126 / 161 (78.3%) | 0 | unmerged |

Fact-citing findings (a finding that cites a submittal fact), on DB copies:

| sheet | before | merged #241 | `feat/b4-quality` (unmerged) |
|---|---|---|---|
| pump | 0 | 3 | 10 / 55 (1 wrong, held for engineer) |
| vessel | 1 | - | 2 / 75 |
| PSV | 0 | - | 0 / 78 |

## Evidence labels per capability

| capability | CODE EXISTS | PASSES TESTS | MEASURED ON REAL DOCUMENTS | WORKING IN THE LIVE REVIEW |
|---|---|---|---|---|
| geometry reader (grid score, multi-row header, form pairing, blank evidence, noise filter) | yes - main (`geometry_reader.py`); code-only noise filter on `feat/b4-quality` | fixtures exist (`test_geometry_reader.py`, `test_geometry_wiring.py`) | yes - pump, copies | no (flag OFF) |
| stored geometry facts behind the flag | yes - main (#241) | fixtures exist | yes - pump 82/161, DB copy | no |
| Claude vision reader with proof check | local branch `feat/b4-quality` only (unmerged, not on origin) | fixtures exist (`test_vision_reader.py`, branch) | pump 126/161 on the branch, copies | no |
| index-only field naming | yes - main (`field_naming.py`), extended on branch | fixtures exist (`test_field_naming.py`) | yes - 3 sheets, copies | no |
| field-name pairing held for engineer | partly merged (#241), rest on branch | fixtures exist | yes - counts above | no |

Test runs were not repeated for this ADR; "fixtures exist" means the test
files are present, not a fresh pass result.

## Consequences

- Fact coverage on the pump sheet rises from 30 to 82 correct (merged) and to
  126 (unmerged branch), with 0 wrong against the provisional key.
- Two readers can now disagree; conflicts are stored, not resolved silently.
- Pairing depends on the field dictionary; a field missing from it stays
  unpaired rather than guessed.

## Risks

- **Vision egress:** page images of client submittals go to the Claude API.
  This is inside the owner-approved Claude lane (CLAUDE.md rule 1) and is
  permitted for the **3 regression submittals only**. Any wider use needs a
  new owner decision.
- **Cost:** about USD 0.9 for vision on the 3 sheets, inside the
  `claude_spend` caps.
- **Accuracy claims rest on a Claude-prepared key.** A shared blind spot
  between the key and the reader would not show as "wrong".
- **Spurious rows:** 82 or more rows on the sheets do not map to a scored
  field; they are stored and must not be shown as findings.
- **Speed:** about 30 s per sheet.

## Open items

1. Engineer review of the scored field set in `gold/M03-FIELDS.review.csv`;
   until then every number here is PROVISIONAL.
2. Vessel and PSV have no answer key; their counts are fact-citing findings
   only, not accuracy.
3. Filter or label the 82+ spurious rows.
4. Owner approval sequence before any live change (see #193 proposal):
   approve, flag ON for a backfill on a DB copy, approve again, then live
   with a backup and `live_guard`.
5. Numbering collision with the existing ADR-0020 (see header).
