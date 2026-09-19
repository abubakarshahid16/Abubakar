# Prohibitive modal verbs: the corpus scan and the stored result

Evidence for the change in `734a2a8` ("fix(standards): extract prohibitive
numeric limits"), which added `may not exceed` and `must not exceed` to the
requirement gate and the comparator table.

Read-only, on a disposable copy made with SQLite's backup API. The scan is
plain text over `pages.text`, so it is unaffected by the extractor change and
gives the same numbers before or after it.

## The corpus scan, with denominators

```
python step4_scan.py <disposable copy>
```

| | count |
|---|---:|
| standards scanned | **272 / 272** |
| of those, with at least one extracted page | 272 / 272 |
| pages scanned | **7,914** (the 272 standards' pages; 7,930 pages exist across all 274 documents) |
| sentences containing "may not" | **150** |
| sentences containing "must not" | **31** |
| of those 181, NUMERIC prohibitions (`may/must not exceed <number>`) | **4** |

By SAES sub-series, over the 181 sentences:

```
SAES-A 32  SAES-W 24  SAES-M 16  SAES-O 12  SAES-T 12  SAES-L 11  SAES-P 11
SAES-B  7  SAES-K  7  SAES-S  7  SAES-Z  7  SAES-J  6  SAES-Q  6  SAES-G  5
SAES-H  5  SAES-F  3  SAES-X  3  SAES-C  2  SAES-D  2  SAES-I  2  SAES-E  1
```

Ten sample locations. No sentence text is reproduced; each is a document id,
page, the clause of the chunk covering that page, and a sha256 prefix.

```
  document             page  clause   sha256[:12]   form      kind
  doc_3d43150e87ef       18  5.11.6.7 0917a0d41790  may not   descriptive
  doc_40601865a94d       30  12.2     4c43973594ed  may not   descriptive
  doc_f475b4be5688       27  8.1.1    bc3ff1ebee77  may not   descriptive
  doc_eb904b37f3d8       10  6.1.1    808e408938a4  may not   descriptive
  doc_eb904b37f3d8       14  7.1.6    79c414ec8aed  may not   descriptive
  doc_eb904b37f3d8       14  7.1.6    16d21a82122f  may not   descriptive
  doc_eb904b37f3d8       19  7.2.2    9e78b33b2cf4  may not   descriptive
  doc_eb904b37f3d8       22  7.2.2    9e78b33b2cf4  may not   descriptive
  doc_eb904b37f3d8       25  7.4.1    5bdd6b9fddd2  may not   descriptive
  doc_1cff22d0b9d1       11  7.3      dfef29da891f  must not  descriptive
```

**177 of the 181 are descriptive**, which is precisely why the implemented
rule requires a NUMBER after the modal (`may\s+not\s+exceed\s+[-+]?\d`).
Admitting "may not" as a bare modal would have turned 177 descriptive
sentences into false requirements across the corpus.

The four numeric prohibitions are in **four different standards**, one each:

```
SAES-A-105.pdf  doc_a835c3a15e04  p9   c0147ce491ef
SAES-O-202.pdf  doc_05067f25161e  p16  8dc7f371bc1e
SAES-T-629.pdf  doc_b3e4657becef  p29  1ab67daff854
SAES-T-911.pdf  doc_bbd4e26ac42f  p35  2c47460d59b7
```

## The stored result for SAES-A-105

Extraction was re-run for SAES-A-105 on the disposable copy. It produced **28
requirements** from 0, of which 4 carry a parsed comparator and value:

```
  clause    page  type           category     op   value  unit
  5.3.3        9  numeric_limit  prohibition  <=     105  dB(A)
  5.3.3        9  numeric_limit  prohibition  <=      97  dB(A)
  5.3.3        9  numeric_limit  prohibition  <=     105  dB(A)
  5.3.3        9  numeric_limit  prohibition  <=     115  dB(A)
```

The pressure-relief requirement, as stored:

| field | value |
|---|---|
| clause | `5.3.3` |
| page | `9` |
| operator | `<=` |
| raw_value | `115` |
| raw_unit | `dB(A)` |
| category | `prohibition` |
| requirement_type | `numeric_limit` |
| source evidence | retained, 71 chars, sha256 `b96c27cce79207a6` |

Only ONE of those four rows comes from a `may not exceed` sentence - the
corpus scan above finds exactly one such sentence in this document. The other
three are `shall not exceed`, which was already supported; they are labelled
`prohibition` by the classifier, not by the new modal.

Two honest qualifications:

1. **The normalised `value` and `unit` columns are NULL.** dB(A) is not a
   convertible dimension, so `claims.normalise` does not produce a canonical
   value. The limit is fully specified by `operator` + `raw_value` +
   `raw_unit`; nothing was silently rounded or converted. A reader of the
   `value` column alone would find nothing there.
2. **The scan's hash and the stored `source_text` hash differ** for the same
   requirement (`c0147ce491ef` vs `b96c27cce792`). The scan hashes the whole
   split sentence; the extractor stores the sub-part that `_requirement_parts`
   isolates. Neither is wrong, and they are not comparable.

## Not blocked by the Step 5 cause

`docs/ZERO_REQUIREMENTS_CAUSE.md` found that the 252 standards were never
submitted for extraction. That does not block this step: extraction runs
correctly for SAES-A-105 on demand and yields the rows above. What remains
undone is the corpus-wide backfill, which is deferred.

## SUPERSEDED, 2026-09-20 — and this page understated the clause

The backfill was done: all 272 standards extracted, 1,746 rules now carry a
comparator a datasheet value can be compared against.

More importantly, **the four rows listed above were the exceptions to a rule
this page did not notice was missing.** SAES-A-105 5.3.3 states its primary
limit as "new equipment shall not generate noise in excess of 90 dB(A)" and
its exceptions as "may not exceed 105/97/105/115 dB(A)". Only the exceptions
parsed, so the table above reads as the complete content of 5.3.3 when it is
the four exceptions to a 90 dB(A) ceiling the database did not hold. `bf4f5ab`
added the negated "in excess of" and "should not exceed" to the vocabulary in
both homes, with negative controls in `test_standards_3b.py` for the trigger
sentences that must NOT become rules. Clause 5.3.3 now stores five rows:

```
  clause   page  op   value  unit
  5.3.3       9  <=      90  dB(A)   <- the primary limit
  5.3.3       9  <=      97  dB(A)
  5.3.3       9  <=     105  dB(A)
  5.3.3       9  <=     105  dB(A)
  5.3.3       9  <=     115  dB(A)
```

The "may not exceed" analysis above is unaffected and still stands; what it
missed was a different phrasing in the same clause.
