# ADR-0021 — Structured requirement representation: CODE-ACCORD vs regex extraction

- **Status:** Accepted (research stage 1)
- **Date:** 2026-09-24
- **Decision:** **ADOPT-FOR-EVALUATION-ONLY** — adopt CODE-ACCORD's
  *annotation schema* as the template for a small hand-labelled gold set on our
  standards. Do **not** adopt a learned extractor or replace
  `requirements_3b.py`.

## Source read

CODE-ACCORD (arXiv 2403.02231). 862 sentences from building regulations of
England and Finland (English), annotated by 12 annotators: 4,297 entities in
4 types (object, property, quality, value) and 4,329 relations in 10 types
(selection, necessity, part-of, not-part-of, greater, greater-equal, equal,
less-equal, less, none). CC BY 4.0. The paper reports **no baseline model
scores**; it is a dataset, not a method.

## The existing weakness

- `backend/app/requirements_3b.py` extracts requirements deterministically
  (regex and sentence rules, no model — by design, so a limit is
  reproducible). 34,938 rows: 87% carry a clause, **15.3% a condition, 1.1%
  exceptions**.
- Those percentages are coverage, not accuracy. Nobody knows whether 1.1% is
  the true exception rate in these standards or a recall failure of
  `parse_exceptions` / `parse_condition`. The module's own notes record a case
  where only the exceptions parsed and the general limit was lost — the error
  class exists.

## Evaluation data needed

- ~200–300 requirement sentences sampled across several standards (not only
  the ones the regexes were written against), hand-labelled with the
  CODE-ACCORD entity/relation types plus our `condition` and `exception`
  fields. Labelled by an engineer; until then, labelled as a sample.
- Score precision and recall for: comparator (maps onto
  greater/less/equal relations), value + unit, subject (object/property),
  condition, exception. Both denominators, as `scripts/eval_extraction.py`
  already does for datasheets.

## Measured benefit on our data

**Not measured.** CODE-ACCORD has no published extractor numbers to borrow,
and its domain (building codes) differs from process-plant engineering
standards.

## Cost on the stated hardware (estimate)

Labelling time only: roughly a person-day for ~250 sentences (estimate). No
compute, no new dependency. Training a relation-extraction model would add a
model runtime and a non-reproducible limit — rejected on the section 14
principle quoted in `requirements_3b.py`.

## Integration risk

Low: a gold CSV and a scoring script alongside the existing ones. The schema
is richer than ours (e.g. `part-of`, `selection`); do not widen
`standard_requirements` until the gold set shows a field is both missing and
needed.

## Reason for the decision

The weakness is an *unknown*, not a measured defect. The cheapest decisive
step is a gold set; CODE-ACCORD gives a published, citable schema for it.
