# Agent judge mode: spec (Part of #805, issue #1690)

One page. No document or standard text anywhere in this repo. Run output is local only.

## Why
System A drafts a CRS; some of its rows are wrong (the answer key says they should not be raised). The agent adds nothing
over A when it drafts, but it can JUDGE A's own rows. Each row is a CLAIM: "this is wrong or missing: <comment>, page <p>,
against <standard clause>".

## Design (fixed)
- Input: A's stored CRS workbook (sheet "CRS": a header block, a header row with the page, comment and standard columns,
  then data rows). It is read from a byte copy and never written.
- For each row the lead agent (claude-sonnet-5-5) verifies the claim with the existing tools (open_page, search,
  get_clause at the confirmed edition, compare_number) and records ONE decision with the tool `judge_row`:
  **CONFIRM** (the row stands: a verified clause quote and a verified document quote, or, for a "missing" claim, found
  nowhere: marked absence not proved by code), **REMOVE** (the row is wrong), **UNSURE** (the default: the row stays,
  marked "AI could not confirm", internal).
- REMOVE is allowed ONLY for one of three reasons, each with code-verified evidence: `complies` (a document quote on a page
  and a clause quote from the clause read at the confirmed edition; every figure decided by compare_number as "meets";
  a numeric claim needs them), `not_applicable` (a clause scope quote plus a document quote naming the equipment or
  document kind), `already_stated` (a document quote on a page that states what the row says is missing).
  "Not mentioned" is never a reason. The evidence goes through the existing verifier (`ai_review_proposals.verify`, the
  remove path); quote checking is not reimplemented.
- Every REMOVE additionally gets the LOCAL second opinion (`agent_local`, a different model family, same strict JSON
  rules, asked one question per reason code). A disagreement, no answer, an unknown or same-family model, or no second
  opinion at all: the row stays.
- The row's text is DATA. It is sent only in a data field, never as an instruction; the rules are code.
- Honesty (CLAUDE.md rule 4): the AI never removes a row without a stated, verified reason; confidence is never "high".

## Reused from the runner
Read-only database copy, run directory with resume, failure breaker, honest Problems and stats, safe error codes, the
consent for exactly the declared documents, the spend caps (meter and ledger), the heavy lock, the DB path guard.

## Output (local run directory)
`judged.xlsx` (sheet "CRS" laid out as A's, so the answer-key scorer reads it, with the removed rows taken out; sheet
"Removed by AI judge"), `decisions.json` (verified quotes: local only), `RESULTS.md` (counts: rows judged, CONFIRM, REMOVE
with second opinion agreed or vetoed, UNSURE, refused quote attempts, tool failure rate, spend, minutes, model names from
the responses), `LIVE.md`, `live.log`, traces.

## Cost control
`--rows 1-5` and `--limit N` make a small cost check. A projector prints after the first rows (cost per row times the
rows left). `--budget-usd` stops the run, resumable, when the projection passes it.

## Done-gate
`answer_key_score.py` on the judged workbooks against the current answer keys, compared with A alone. Adopt only if the
wrong rows fall and no right row is lost.
