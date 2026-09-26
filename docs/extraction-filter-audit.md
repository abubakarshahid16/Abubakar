# Extraction filter audit (owner order 2026-09-26)

**Trigger.** On a real 11-page vessel datasheet (aggregate only), the geometry and
vision readers recovered 10-44 label/value pairs per page on 9 pages, and the
filters kept none of them. Part (1), the page ledger, was fixed in PR #273. This
is part (2): an audit of every filter rule that rejected pairs on the layouts
that sheet uses.

**Method.** The layouts were rebuilt with made-up values in
`backend/tests/synthetic_vessel_sheet.py`: a cover with a title block and a
revision table, a contents page, a drawing with a ruled design-data box, a ruled
nozzle schedule, and a data page with a row-number ruler in the margin. The
sheet was extracted with the default readers and again with the geometry reader
on. Every dropped pair was then traced to the rule that dropped it. No client
text is involved.

## Before and after (synthetic sheet, default readers)

| Page (layout) | Real pairs read before | Real pairs read after |
|---|---|---|
| 1 cover | 0 (21 recovered, all dropped) | design code |
| 2 contents | 0 (correct: nothing to read) | 0 ✅ |
| 3 drawing, design-data box | 7 of 9 | 9 of 9 |
| 4 nozzle schedule | 20 (table reader) | 20 |
| 5 data page with ruler | 1 of 6 | 4 of 6 |

Total facts went from 28 to 34. Page 1 moved from "no facts" to read.

## Per rule: what it rejected, why, and what changed

| Rule | What it rejected on these layouts | Why | Changed? |
|---|---|---|---|
| **Pairing: label, unit, value in that order** (`split_label_value`) | Data page: `OPERATING TEMPERATURE / C / 90` was paired as "C", so the 90 was never paired (the same for density and liquid level). | Cells are paired left to right. Only the value-then-unit order was handled. | **Loosened.** A bare recognised unit followed by a number is read as "90 C". Every other row is unchanged. |
| **Value gate** (`states_a_value`) | Drawing: `SHELL MATERIAL / SA-516 GR.70`, `RADIOGRAPHY / FULL`. Cover: `DESIGN CODE / ASME VIII DIV. 1`. It also rejected revision names, title-block values and contents entries, which is correct. | Only a quantity, an explicit blank or a closed word counted as an answer. A designation is none of these. | **Loosened, narrowly.** Material, code and rating designations are now answers (a family prefix plus a number: SA-516, A105, ASME VIII, API 610, EN 13445, CL300, 300#). The closed words now also include FULL, SPOT, PARTIAL, RF, RTJ and FF. Names, places and document numbers are still refused (tested). |
| **Revision table, per row** (`row_noise` REVISION) | Cover: revision rows and the "REV → B" title-block rows. | They are the revision history and the title block. | **Kept** (owner). |
| **Revision table, whole table** (`revision_table_ids`) | Cover: the geometry reader's reading of the revision table (people's names under Prepared, Checked and Approved). | The table as a whole carries the revision headings. | **Kept** (owner). Guard mutation M1066. |
| **Title block** (`row_noise` DOCUMENT_ID) | Every page: DOCUMENT NO. and SHEET rows. | Document identity, not the equipment's. | **Kept.** |
| **Column heading read as a value** | Cover: "PREPARED → CHECKED". | A header row. | **Kept.** |
| **Page furniture** (repeats with the same answer on 3+ pages) | Title block rows on pages 1-5. | Same text on every page. | **Kept.** |
| **Geometry: furniture, tag or date** | Title block rows read by the geometry reader. | Same as above. | **Kept.** |
| **Tag row, date, checkbox on quantity, duplicate, empty label** | Nothing real on these layouts. | Not applicable. | Unchanged. |

## Still not read, and why

- **Free text** such as `SERVICE / PRODUCED WATER`, `EQUIPMENT / HORIZONTAL
  SEPARATOR` and `FLUID / PRODUCED WATER`. These have exactly the shape of a
  caption ("Facility: Example Bay"), and without knowing what the label means
  the two cannot be told apart. Admitting free text is what once produced
  fields named after people.
- **Viscosity in cP.** `cP` and `mPa·s` are not in the unit table, so the
  unit-before-value rule does not apply to that row. Adding a viscosity unit
  dimension is a change to the unit table, not a filter, and is left as a
  follow-up.

## Tests and mutations

- `backend/tests/test_extraction_filter_audit.py` (23 tests):
  - every real pair on each layout survives;
  - the revision block, title block, contents entries and people's names stay
    out;
  - pages with real pairs read as read;
  - the new pairing shape, and designations against captions.
- Guard mutations (detected):
  - M1066: the revision table is dropped whole;
  - M1068: the value gate;
  - M1069: the designation rule stays narrow.
- Loosening mutations (detected): M1070, M1071, M1072. M105 was re-anchored.
- All 139 mutations on `datasheets.py` and `row_noise.py` are still detected.

**Next step (owner, on the laptop):** re-run the real datasheet and compare the
per-page facts. The owner-run measurement script from B4 reports them as counts
only.
