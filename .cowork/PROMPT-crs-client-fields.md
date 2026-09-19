# CRS export: four client-requested fields

Queue this after the current investigation (docs/ZERO_REQUIREMENTS_CAUSE.md
is the priority). This is self-contained and does not touch retrieval.

The client (Mohammed MDh) asked for four things on the CRS. Decisions below
were made with the user (Muhammad Usman); two were his explicit call, one
was mine because he said he didn't know - flagged as such.

## 1. Submittal number

`documents.transmittal_number` already exists in the schema and is already
captured at upload, but `crs_export.build_crs` never reads it. Add it to the
header block, same pattern as `company_transmittal` / `contractor_transmittal`
in `crs_export.py` around line 62:

    (X, "Submittal No.:", "submittal_number"),

Source it in `crs_mapping.build_crs_rows` (or wherever `meta` is assembled
for export, check `main.py`'s CRS export route) from the submittal
document's own `transmittal_number` - NOT the company/contractor transmittal
fields already there, which are a different thing. If the submittal document
has no `transmittal_number` set, render nothing, per the existing "missing
key renders as nothing, never None" rule stated in `build_crs`'s docstring.

## 2. Page number / section

Already exists - "Page No./Section" column, `crs_mapping._citation`. No
work needed. State this back explicitly so nobody re-builds it.

## 3. System generated number, one per row

USER DECISION: a unique ID per row, distinct from Item No (which is just
1..N and resets on every export).

Add a new field, not a new visible column - the client's template has 7
columns and adding an eighth without their approval is exactly what P0-5 in
the audits warned against. Options, pick the one that fits how `findings`
rows already carry identity:

- If review findings already have a stable id (`review_findings.id`, check
  `review.py`), reuse it, formatted consistently, e.g. `RF-{id[:8]}`.
- Otherwise mint one deterministically from
  `(review_run_id, finding stable key)` so re-exporting the same run
  produces the SAME numbers, not new ones each time - a re-export must not
  renumber a finding the contractor already responded to under its old
  number.

Where it renders: your call given the client didn't specify a column. The
lowest-risk placement is prefixed into the existing comment text (same
pattern `_comment_text` already uses for Requirement/Submitted/Equipment
lines) UNLESS the client confirms they want a dedicated column, which needs
the same client sign-off P0-5 already requires for the clause column. Do not
add a visible column without asking first - flag it as an open question in
your report rather than deciding it silently.

## 4. FEED scope note

USER DECISION (mine, since Usman said he wasn't sure): a single line in the
header block, not a per-row column. A per-row FEED-document trace would
require linking every requirement back to a specific FEED document, which
nothing in the system does today, and is a much bigger and riskier build for
a request that is still vague.

Add one more header row (or fold into an existing one - check whether row 5
"Document Title:" has room, or add a new row 8, renumbering the column
headers down by one and updating every hardcoded row-8/row-9 reference in
`crs_export.py` accordingly, INCLUDING `code = meta.get("recommended_code")`
block's `row = 8 + len(findings) + 2`, and the `WIDTHS`/`HEADERS` code path -
grep for the literal `8` before touching this):

    "Contractor submittals are per the project scope FEED documents."

Static text is fine unless `meta` already carries something more specific
(project name, scope reference) - if it does, use that instead of a fixed
sentence.

## Required before merging any of this

- A test that reopens the generated XLSX and reads the actual rendered
  cell text for all four additions - not file existence, not row count.
  Section 12 of the ChatGPT audit named this exact gap: "verified by opening
  the file" previously checked presence and spelling, never truth, and let
  6 false rows ship (b782f96). Do not repeat that.
- If findings have no stable id yet and one must be added, write the
  migration test for re-export producing identical numbers, not new ones.
- Confirm with a screenshot or exported file that the workbook still opens
  cleanly in Excel and the 7-column client template is visually unchanged
  except for the new header lines.

## Explicitly flag back to the user, do not decide silently

Whether the client wants the per-row system number as its own column
instead of folded into the comment text. That is a template change and
needs their sign-off, same as the clause-column question already open from
P0-5.
