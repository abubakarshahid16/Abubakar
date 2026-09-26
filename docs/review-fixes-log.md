# AI Submittal Review fixes - log (owner order 2026-09-26)

The owner's order "AI Submittal Review - make it produce real comments" lives in
the owner's local `.cowork/` folder (not in git). This log is the repository's
record of what each PR delivered, for the owner to paste into CURRENT_STATE
section 16. No client text, document numbers or standard text here.

Owner priority for the PRs: step 0 (page ledger), 2d, then 1 (wording 2g, pill
contrast, picker/panel), then 2 (CRS Review notes 2f + grouping 2e), then 4
(datasheet self-checks 2c), then the extraction filter audit, 2a+2b, the screen
redesign (section 3), and 2d-2 (web standards).

## Step 0 - page ledger (honesty audit entry 68)

- A page with recorded current facts reads as **read** in the ledger and on the
  screen, whichever reader wrote them.
- A requirement not found on a page read **only** by the geometry/vision reader
  stays **Needs engineer review** ("value not found by the page reader -
  engineer to check the page"). It never becomes the contractor's missing
  information, and it is one summary row on the CRS, not a comment each.
- DB migration: **none** (no new column; the ledger is recomputed).

## 2d - AI engineering check (kind C), behind `REVIEW_AI_CHECK_ENABLED`

- **Off by default.** Even when on, it needs the Claude lane
  (`REASONING_PROVIDER=claude`, both `STANDARDS_READER_*` egress flags and a
  key). Spend is booked to the step `review_ai_check` and checked against the
  USD caps before the call leaves.
- **When it runs:** at the end of a review job, after the comparison has decided
  the suggested code. It can also be re-run on demand with
  `POST /api/reviews/runs/{id}/ai-check`, which answers counts only, never text.
- **What Claude sees:** the datasheet's extracted fields, its page text, the
  names of the cited standards, and for the held standards the clause numbers
  that were read.
- **The gate** (`ai_engineering_check.accept`) refuses an item, with a named
  reason, when:
  - its datasheet value is not on the page it cites;
  - it uses a number that is not on that page;
  - it cites a clause that cannot be verified from a held standard;
  - it quotes a sentence that is not on the page;
  - it uses a pass/fail word;
  - its confidence is above medium.
- **Kept items** are stored as pending, unconfirmed findings with no compliance
  status (`origin = 'ai_engineering_check'`). They never move the review code.
- **On the screen:** "AI engineering check - not from the standard text -
  engineer to confirm".
- **On the CRS** (owner decision 2026-09-27):
  - a new last column, "AI Review Comments", holds each unconfirmed item, with
    COMPANY Comments left empty;
  - confirming the item moves its text to COMPANY Comments, with Comment By
    "AI engineering check, confirmed by <name>";
  - a rejected item is not on the sheet.
- **Export CRS** offers two copies:
  - "internal review copy" (the default): includes the "AI Review Comments"
    column;
  - "issue to contractor": that column and every unconfirmed row are removed.
  - The file name says which copy it is.
- **Not in this PR:**
  - the optional public-web lane for 2d; it comes with 2d-2;
  - CRS re-import (no importer exists yet); confirmation is done on the
    screen.
- DB migration: **none**. The existing `origin` column is reused, and no new
  table or column is added.
