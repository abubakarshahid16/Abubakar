# ADR-0006 — Provenance for recognised text

- **Status:** Proposed — awaiting approval. No code written.
- **Date:** 2026-09-05
- **Decision:** Recognised text is stored in a table extraction cannot touch, is
  carried to `chunks`, and is **never** labelled as a verbatim quotation.

## Why this is the hard half

Every Tier 1 answer today carries *"Quoted verbatim from the document"* and
*"quoted directly, no AI rewriting"*. Those are literally true, because the
characters came out of the PDF's own text layer.

Recognised text is a guess about pixels. The measurement in ADR-0005 produced
`Pyblish` for "Publish", `Example_1_Excel_File,xls` for `.xls`, and CJK
characters in an English document. A misread digit in `120 °C` or in a clause
number is precisely the failure this system exists to prevent. Putting that
sentence under a "verbatim" label would break the product's central claim, and
it is far harder to undo once recognised text is in the index.

`limitations.md:79` already names the answer for degraded content: the page
image, *"the reader still sees the truth. This is the durable answer."* OCR
inherits it. For a recognised page the page image is **not optional** — it is
the verification path.

---

## 1A. Where provenance lives — **not a column on `pages`**

> **The instruction this ADR was written against was wrong here, and it is
> recorded rather than quietly fixed.** The brief specified "a schema migration
> on `pages` recording HOW the text was obtained". Following it literally would
> have shipped a defect: `INSERT OR REPLACE` destroys the column on every
> re-extraction, so the provenance flag — and any recognised text beside it —
> would vanish exactly when a document was re-processed, which is the case OCR
> exists to serve. The author identified the same hazard independently in the
> speed addendum, from the opposite direction, and accepted this correction. A
> corrected instruction is worth more written down than fixed silently: the
> next person to reach for "just add a column to `pages`" should find this
> paragraph.

The brief asked for a column on `pages`. **That is unsafe, and the addendum
says why.** `extract.py` writes pages with `INSERT OR REPLACE` on
`(document_id, page_no)`. `INSERT OR REPLACE` deletes the row and inserts a new
one, so *every* column on `pages` — a provenance flag and the recognised text
alike — is destroyed by a re-extraction. `states.py` explicitly permits
re-extraction from both `NO_SEARCHABLE_CONTENT` and `FAILED`. Twenty minutes of
recognition would be silently overwritten by the empty extraction that
triggered it.

So recognised text and its provenance go in a **separate table that extraction
never writes**:

```sql
CREATE TABLE IF NOT EXISTS page_ocr (
    document_id   TEXT    NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_no       INTEGER NOT NULL,
    text          TEXT    NOT NULL,   -- already through normalise_text
    char_count    INTEGER NOT NULL,
    -- Provenance. Same house rule as the vector cache: a result states what
    -- it ran against, so a number is never orphaned from its conditions.
    engine        TEXT    NOT NULL,   -- 'rapidocr-3.9.2'
    model         TEXT    NOT NULL,   -- 'PP-OCRv6_tiny'
    dpi           INTEGER NOT NULL,   -- 150
    -- Confidence is data, not a knob (1D).
    mean_conf     REAL,               -- NULL when zero boxes were found
    min_conf      REAL,
    box_count     INTEGER NOT NULL,
    seconds       REAL    NOT NULL,
    recognised_at TEXT    NOT NULL,
    batch_no      INTEGER NOT NULL,   -- resume high-water mark, as extraction
    PRIMARY KEY (document_id, page_no)
);
```

The primary key gives the same INSERT-OR-REPLACE-safe re-run semantics
extraction already relies on, and the same `batch_no` high-water pattern for
resume.

**Effective text for a page** becomes an explicit resolution rather than a
column read:

```sql
SELECT p.page_no,
       COALESCE(o.text, p.text)                        AS text,
       CASE WHEN o.page_no IS NULL THEN 'extracted'
            ELSE 'recognised' END                      AS text_source
FROM pages p
LEFT JOIN page_ocr o ON o.document_id = p.document_id AND o.page_no = p.page_no
```

One source of truth, no denormalised flag that a re-extraction can falsify.

**Migration for existing rows — stated, not defaulted.** `page_ocr` is a new
table, so it starts empty, and every existing page therefore resolves to
`extracted`. That is not a convenient default; it is a fact about build
history. OCR has never run in any build of this system — the three assertion
strings in `chunker.py`, `ingest.py` and `limitations.md` are the proof — so no
recognised text can exist in any database that this migration will ever meet.

**This must be tested, not asserted:** recognise a page, re-run extraction on
that document, assert the recognised text is still there. The addendum is right
that this is the most expensive defect available in the feature.

## 1B. Carrying it to `chunks`

```sql
ALTER TABLE chunks ADD COLUMN text_source     TEXT NOT NULL DEFAULT 'extracted';
ALTER TABLE chunks ADD COLUMN ocr_min_conf    REAL;    -- NULL unless recognised
```

**A chunk spanning one recognised and one extracted page is `recognised`.**
Agreeing with the instinct in the brief, and for exactly that reason: a reader
cannot tell which sentence came from where, so the label must make the weaker
claim. Under-claiming costs a little confidence; over-claiming is the failure
mode this system exists to prevent.

**`'mixed'` was considered and rejected.** A third state pushes an unresolvable
hedge onto the reader — "part of this may be recognised" tells them nothing
they can act on. Two states, and the *stronger* label requires every page in
the chunk to be extracted.

`ocr_min_conf` is the minimum over the chunk's recognised pages, so the weakest
evidence governs.

Existing chunk rows migrate to `'extracted'`, on the same build-history
argument, and additively, matching the `_migrate` pattern already in `db.py`.

## 1C. THE LABEL

This is the decision that matters most, so here is the exact replacement.

**Today, for `answer_type == "extract"`:**

```text
[ Quoted verbatim from the document ]        1.2 s · quoted directly, no AI rewriting
```

**Proposed, when `chunk.text_source == 'recognised'`:**

```text
[ Read by OCR from a scanned page ]     1.2 s · not the document's own text — check it against the page below
```

with the page image **expanded by default** rather than behind a click, and the
label rendered in the warning tone, not the quote tone.

Why this wording:

- **"Read by OCR from a scanned page"** states the mechanism in the first three
  words. It cannot be misread as a quotation, because "read by OCR" is not what
  anyone says about copied text. The audience is engineers; "OCR" is the
  precise word, not jargon to them.
- **"not the document's own text"** is the direct negation of the claim the
  other label makes. A reader who has seen both labels knows exactly what
  changed.
- **"check it against the page below"** is an instruction with a referent, and
  the referent is on screen. This is the half that makes the label honest
  rather than merely cautious.

**The UI change is part of the label, not a separate feature.** For extracted
text the page image is a verification the reader *may* want. For recognised
text it is the only evidence that the answer is real, so it is shown, not
offered. A label that says "check it against the page" while the page is
collapsed is a label that expects to be ignored.

Considered and rejected:

| Wording | Why not |
|---|---|
| "Quoted from a scanned page" | Keeps "quoted". That is the word doing the damage |
| "Transcribed from a scanned page" | "Transcribed" implies a careful human; OCR is not that |
| "Machine-read text — may contain errors" | True but unfalsifiable-sounding boilerplate; gives the reader no action |
| A tooltip or an asterisk on the existing label | The brief rules it out, correctly. The claim itself is what changed |

## 1D. Confidence is data, not a knob

`page_ocr` stores `mean_conf` and `min_conf` per page; `chunks` carries
`ocr_min_conf`. A page below threshold is a **quality-gate decision recorded in
the exclusion ledger** under its own rule, with the measured confidence and the
threshold both in the reason text:

```text
rule   = 'ocr_confidence_below_threshold'
reason = 'recognised at mean confidence 0.62, below the 0.__ threshold'
```

**The threshold is deliberately not set in this ADR, because it has not been
measured.** Observed mean confidence on pages that produced sane text ran
0.92–0.99, but the corpus contains no scanned specification prose and no
labelled ground truth, so any number chosen now would be a guess wearing a
decimal point. It is set from the planted-defect work in a later phase.

**Until it is measured the gate is open**: everything recognised is indexed and
labelled. That follows the standing rule — recognised text that might be wrong
is *labelled*, not hidden and not excluded by default. The column and the rule
name ship now so that closing the gate later is a config change, not a
migration.

## 1D-bis. The alphabet guard

Cheap, model-independent, and it earns its place under either engine choice.

**A recognised page containing characters outside the document's expected
script is a recognition failure, not a curiosity.** The guard counts them,
flags the page, and surfaces the count.

```text
rule   = 'ocr_alphabet_violation'
reason = 'recognised text contains 3 characters outside the expected script: 凤 日 ≦'
```

Stored on `page_ocr` as `alphabet_violations INTEGER NOT NULL DEFAULT 0`
alongside the offending characters, so it is a measurement rather than a log
line.

Why it holds under both candidates:

- **Under v6 multilingual** it catches the CJK substitutions measured in
  ADR-0005 — including the dangerous invisible ones, `≦` for `≤`, which no
  reader would question.
- **Under the v5-English hybrid it should never fire.** That makes it a guard
  on the guard: a non-zero count on a Latin-only recogniser means something
  upstream changed — the wrong model was loaded, or the config drifted — and
  the number says so before anyone reads a wrong answer.

The expected script is a property of the document, not a global constant, so
it is configurable per corpus. It defaults to Latin + the symbol set the
existing quality gate already tolerates. **It flags and counts; it does not
delete.** Same standing rule as everything else here: recognised text that
might be wrong is labelled, not hidden.

## 1E. Replacing `needs_ocr_not_implemented`

The rule fires only when a `needs_ocr` page produced no chunk, so it stops
firing naturally once OCR writes text. Four rules replace it, each describing
the page rather than the system:

| New rule | When |
|---|---|
| `ocr_not_run` | Page is flagged `needs_ocr`, recognition has not run on it yet |
| `ocr_found_no_text` | Recognition ran and returned zero boxes |
| `ocr_confidence_below_threshold` | 1D, once a threshold exists |
| `ocr_failed` | The engine raised on that page |

`ocr_found_no_text` is not hypothetical. **5 of the 12 pages measured returned
zero boxes at both 150 and 300 dpi** — they are genuinely blank, not scanned.
"Blank page" and "scanned page we cannot read" are different facts and the
ledger must not conflate them.

**Existing rows.** Chunking already does `DELETE FROM exclusions WHERE
document_id = ?` before re-inserting, so the stale name disappears for any
document that is re-chunked. That is not every document, so a one-time
migration renames it in place:

```sql
UPDATE exclusions SET rule = 'ocr_not_run',
       reason = 'scanned page with no extractable text; recognition has not run'
 WHERE rule = 'needs_ocr_not_implemented';
```

The rename is honest rather than a cover-up: the old name asserted a property
of the *system* ("OCR is not implemented") which becomes false the day this
ships. The new name asserts a property of the *page* ("recognition has not run
on it"), which was true when the row was written and stays true forever. This
is the same defect class as the corpus field that certified state it never
read, and it is fixed the same way — by making the stored string describe what
actually happened.

The two prose assertions are edited, not deleted:

- `ingest.py::_no_content_reason` — "all N pages are scanned images with no
  extractable text; OCR is not implemented" → the reason must now distinguish
  *recognition has not run yet* from *recognition ran and found nothing*.
- `limitations.md:71` — "OCR is not implemented." → replaced with what OCR
  does and does not do, including the CJK finding from ADR-0005.

## 1F. Mixed documents are the normal case

A 500-page document with 12 scanned pages must never read as "OCR'd".

- **Provenance is per page.** `page_ocr` is keyed `(document_id, page_no)`.
  There is no document-level provenance flag to be wrong.
- **The document record gets a count, not a boolean**, matching the existing
  `needs_ocr_pages` / `equation_pages` pattern exactly:
  `ALTER TABLE documents ADD COLUMN recognised_pages INTEGER NOT NULL DEFAULT 0`.
- **The UI states the fraction**: "12 of 546 pages read by OCR", never a badge
  on the document.
- **The answer label is driven by the chunk, never by the document.** An answer
  quoted from page 300 of a document whose page 12 was recognised is a verbatim
  quotation and is labelled as one. This is the whole reason provenance is
  carried to `chunks` in 1B rather than joined back at render time.

The real corpus is 3 documents, 2,559 pages, **74** flagged pages — 2.9 %.
Mixed is not an edge case here, it is every case.

## Consequences

- One new table, two new `chunks` columns, one new `documents` column, all
  additive, matching `_migrate`.
- Retrieval and the answer path must select `text_source` alongside the text,
  and the contract in `contracts/types.ts` gains it.
- Anything that reads `pages.text` directly must move to the `COALESCE`
  resolution or it will silently ignore recognised text.
