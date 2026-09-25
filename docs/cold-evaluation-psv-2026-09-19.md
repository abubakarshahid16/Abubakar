# Cold evaluation: client PSV datasheet (DS-0000-DAS-I-01), 2026-09-19

Measurement only. No code was changed, no fixture written, no defect repaired.
Working tree was clean at `3b8d95d` before and after.

## 0. The holdout premise does not hold, and that is the first finding

The task was set as "nothing in the codebase has ever seen it". **That is not
true of this document.** `docs/AI_SUBMITTAL_REVIEW_PROGRESS.md` §55 records it
by name as "client PSV (I-01)" with the same 8 missing references measured below,
and §54 records **37 facts** recovered from it during Phase 4. Its strings are
quoted in the source: `datasheets.py:236` cites `0.01cP By Contractor` as a
label the extractor once invented, and that string is on page 1 of this file.

So this is a PARTIAL holdout:

| Phase | Saw this sheet? |
|---|---|
| 4 (fact extraction, `is_field_label`, blank markers) | **yes** - rules written against it |
| 5A (applicability) | **yes** - §55 tabulates it |
| 5B, containment matcher, units, `table_row`, model tier, trigger/relative, field-name fixes | no - all built against the drum sheet only |

Everything after Phase 5A is a genuine cold read. Phase 4's extractor is not,
which matters because Phase 4's extractor is what failed hardest.

## 1. Ingestion

Dropped into `watch-inbox/submittals/`, picked up by the watcher on its second
scan (it requires size and mtime unchanged across two passes).

| | |
|---|---|
| id | `doc_d30f4c63d481` |
| filename | DS-0000-DAS-I-01.pdf |
| role | CONTRACTOR_SUBMITTAL, from the `submittals/` folder |
| status | ready |
| pages | 5 |
| chunks | 23, of which 17 retrievable |

Exactly two CONTRACTOR_SUBMITTAL rows now exist. ✅

## 2. References

8 distinct standards cited, **0 in the library, reference coverage 0.0 of 8.**

`API RP 520 Pt-1`, `KOC-MP-027`, `ASTM A216`, `ASTM A193`, `API RP 578`,
`NACE MR-0175`, `ISO 15156`, `ASTM B633`.

The library is 272 Saudi Aramco (SAES) standards. This is a client
sheet citing API/ASTM/NACE/ISO and its own company standards. Identical to the figure §55 recorded for
this sheet in Phase 5A. **Not a defect** - the system reports it correctly.

## 3. Applicability

5 standards selected, **every one by `semantic`**, each carrying:

> "retrieved as textually similar to the submittal; NOT a citation and not
> evidence of applicability on its own"

and `satisfies_reference = false`. Selected: SAES-H-004, SAES-L-108,
SAES-J-605, SAES-G-005, SAES-L-150. Reference coverage stayed 0.0 with all
five on the list.

**Cited-and-present standards not selected: 0 of 0.** No defect under the
step's definition - there are no cited-and-present standards to miss.

Tuned sheet for contrast: 15 cited, coverage 0.4, 10 selected (6 `referenced`,
4 `semantic`).

## 4. Facts - **0 extracted. The headline failure.**

| | tuned sheet | this sheet |
|---|---|---|
| facts | 48 | **0** |
| pages unparsed | 9 of 11 | **5 of 5** |
| numeric facts with a unit | 20 of 48 | **0 of 0** |

Hand count of numbered rows carrying a stated value:

| page | hand count | extracted |
|---|---|---|
| 1 | 41 | 0 |
| 2 | 41 | 0 |
| 3 | 41 | 0 |
| 4 | 38 | 0 |
| 5 | 1 (+12 prose notes) | 0 |
| **total** | **162** | **0** |

Baseline for the tuned sheet was 12 of 15 on page 4. Here it is **0 of 162**.

### Root cause: the page-furniture rule

The pairing layer works. It recovers 187-191 pairs on each of pages 1-4.
Every one is then discarded. Replaying the filters:

| filter | pairs discarded |
|---|---|
| value gate (not a quantity, blank marker or categorical) | 494 |
| duplicate on the same page | 222 |
| **furniture: label appears on 3+ pages** | **53** |
| would have been written | **0** |

The 53 killed by the furniture rule are the ones carrying real values:
`Set pressure` = `340 psig`, `Relieving temperature` = `220ºC`,
`Density at relieving temper.` = `23.55 Kg/m3`, `Max. allow. working pressure`
= `23.5 barg`, `Compressibility factor` = `0.892`, and so on.

`furniture_labels` treats any label appearing on 3 or more pages as a title
block or footer. Its docstring states the assumption: "a real field appears
where the form asks for it". **This sheet is five instances of one form** -
page 1 is PSV-4301, page 2 is PSV-4303, page 3 is PSV-4360, page 4 is
PSV-4306 - so every real field appears on every page and the rule classifies
the entire form as furniture.

The rule postdates the 37-fact measurement: Phase 4 is commit `02e0acb`
(#444 in history), the furniture rule arrived in `b4cd904`
(#459, "strip page furniture"). **37 → 0 is a regression introduced by a
later fix**, on a document the project had already measured.

### Second defect, in the reporting

Every page is reported as `"no label-value pairs recovered from this page"`.
That message is emitted whenever zero facts are written, whatever the cause.
190 pairs were recovered from page 1 and then filtered away. The operator is
told the page could not be read; the truth is that it was read and discarded.

### Garbage labels that got through

None - nothing got through at all.

## 5. Requirements

870 rows across the 5 selected standards (all five had to be extracted; none
had requirements).

| type | count | share |
|---|---|---|
| statement | 793 | 91.1% |
| numeric_limit | 69 | 7.9% |
| table_row | 7 | 0.8% |
| applicability_trigger | 1 | 0.1% |
| relative_limit | 0 | 0.0% |

| field | non-NULL |
|---|---|
| raw_value | 77 of 870 (8.9%) |
| raw_unit | 62 of 870 (7.1%) |
| normalised value | 40 of 870 (4.6%) |

The classifiers built last task fired on standards they had never seen: one
applicability trigger and seven table rows found without a false positive
visible in the sample reviewed.

## 6. The review

870 findings, **100.0% MISSING_INFORMATION** (870 of 870).

COMPLIANT 0, NON_COMPLIANT 0, CONDITIONAL 0, NOT_APPLICABLE 0,
NEEDS_ENGINEER_REVIEW 0.

76 matches attempted, 0 pairings - there were 0 facts to pair against.
Model tier off; `model_disabled` recorded on 76 requirements.
Recommendation: **Manual Review Required**, completeness 0.0
(0 fields read of a nominal 175 over 5 pages).

Findings that are not MISSING_INFORMATION: **none**, so there is nothing to
print.

## 7. Verification

**0 of 0 checks possible.** There is no COMPLIANT, NON_COMPLIANT or
NEEDS_ENGINEER_REVIEW finding to verify.

Supplementary, since the standard side is the only citation the run emitted:
8 findings sampled at random, each opened at its cited page in its cited PDF.
**8 of 8 resolve.** Examples, verbatim from the PDFs:

- SAES-L-108.pdf p10 - "All resilient (soft) seated isolation valves shall
  have zero leakage."
- SAES-J-605.pdf p11 - "Valve bodies for service temperature ranging from
  -28°C to +115°C shall..."
- SAES-G-005.pdf p9 - "All horizontal sealless pumps shall be self-venting
  and shall be designed..."

## 8. Verdict

### Worked unseen

- **Ingestion and the watcher.** Correct role from the folder, correct page
  count, chunked and retrievable, no manual step.
- **Reference extraction.** 8 of 8 citations found, including the awkward
  spellings `API RP 520 Pt-1` and `NACE MR-0175`. Identical to the Phase 5A
  record.
- **Applicability honesty.** Five semantic matches, every one labelled as not
  evidence, `satisfies_reference` false on all, reference coverage held at 0.0.
  This is the guard working exactly as designed on a sheet whose entire
  reference set is absent.
- **Requirement extraction on unseen standards.** 870 rows from 5 standards
  never extracted before, 91% honestly typed `statement` rather than forced
  into `numeric_limit`.
- **Citation resolution.** 8 of 8 on the standard side.
- **The refusals.** 100% MISSING_INFORMATION, completeness 0.0, Manual Review
  Required. With zero facts the system claimed nothing about the contractor.
  It did not invent a single finding.

### Degraded, with the measured gap

- **Fact extraction: 48 → 0.** Recall 0 of 162 hand-counted rows, against
  12 of 15 on the tuned sheet's page 4.
- **Against this sheet's own history: 37 → 0.** Phase 4 measured 37 facts on
  this file; the furniture rule introduced later takes it to 0.
- **Extraction coverage: 0.80 → 0.0** on the same document, by the project's
  own Phase 5A record.
- **Pages unparsed: 5 of 5.**

### New failure modes this sheet exposed

1. **The repeated-form datasheet.** One document, five instances of the same
   form, one piece of equipment per page. Every heuristic that uses
   cross-page repetition to identify furniture inverts on this shape. The
   tuned sheet is a single vessel with different fields per page and could
   never have exposed it.
2. **"Unparsed" conflates "could not read" with "read and discarded".** A
   diagnostic that points an operator at the wrong half of the pipeline.
3. **A library with zero overlap with the submittal.** 272 SAES standards, a
   client sheet, no intersection. The system behaves correctly but the output is
   870 findings that are all "no value submitted" against standards nobody
   cited - a review whose every row is noise, produced honestly.
4. **Multi-tag documents have no representation.** Four PSV tags on four
   pages become one submittal with one fact set. Nothing in the schema
   distinguishes "this valve" from "that valve", so even with extraction
   working, four different set pressures would land in one undifferentiated
   pile.
5. **Ranges remain unparsed and are common here.** `-3 to 121OC`,
   `23.5 / 9 barg`, `4-28 cP`, `10.15psig/97.18psig`. Known limitation 3 from
   Phase 4, unchanged, and this sheet is dense with them.

## Suite

**2,126 passed / 0 failed**, unchanged - as last measured at `3b8d95d`. No
source file was touched in this task; the working tree was clean throughout.
Not re-run here, because nothing could have moved it.

---

# Follow-up, same day: the regression fixed

The furniture rule now requires BOTH conditions before calling a repeating
label a field: two or more distinct non-empty answers, AND non-empty on more
than half the pages it appears on. Otherwise furniture.

Distinctness alone was not enough. This document's own title block on the drum
sheet - `ONSHORE FACILITY A` - is empty on six of the eight pages it
appears on and catches a stray neighbouring fragment on two (`D` on page 5,
`2003` on page 7). Two distinct non-empty answers, so condition 1 alone
promotes it to a field and `2003` becomes a numeric fact. Condition 2 kills
it at 2 of 8.

| | before the fix | after |
|---|---|---|
| PSV facts (DS-0000-DAS-I-01) | 0 | **35** |
| PSV pages unparsed | 5 of 5 | **1 of 5** (page 5 is the notes page) |
| PSV blank-marked facts | 0 | **25 of 35**, all surviving |
| drum facts | 48 | **48**, unchanged, junk row dead |

Recall against the 162 hand-counted rows: **21.6%**, from 0%. Phase 4 recovered
37 from this sheet before the furniture rule existed; 35 of those are back,
and the two that are not are accounted for below.

**The two PSV fields the rule costs, each measured, neither a surprise:**

- `separable flange material` - reads `NA` on all four valves. One distinct
  answer, so condition 1 strips it. 4 facts. Same class as `Lifting lever:
  Required`, the residual documented in `furniture_labels`.
- `mole wt of relieved fluid` - the extractor pairs it with a value on only
  two of the four pages, so it fails condition 2 (and condition 1, both its
  answers being `30.13`). 2 facts. The underlying pairing miss on pages 3-4
  is a separate defect, not this rule.

**The blank-marker question, checked before the fixtures were written.** A
field reading exactly `By Contractor` on every page would have one distinct
answer and would die under condition 1, which would be a real loss: 25 of the
35 facts are `By Contractor` blanks and they are how the review reports
MISSING_INFORMATION instead of inventing a breach. On this sheet none does -
every one carries a purchaser value beside the marker (`340 psig (By
Contractor, as per Code)` against `145 psig By Contractor, as per Code`), so
their answers differ per valve. **No blank-marker exemption is needed today**,
and `test_an_identical_by_contractor_answer_everywhere_is_the_known_residual`
is where it will show up if a future sheet needs one.

**The diagnostic** no longer says `no label-value pairs recovered from this
page` unless the pairing layer genuinely produced none. Otherwise it states
the counts: `9 label-value pairs were recovered and none became a fact (8 by
value gate, 1 by duplicate)` - which is what page 5, the notes page, now says.

Ranges and the equipment-tag column remain unfixed and are the next two tasks,
in that order.
