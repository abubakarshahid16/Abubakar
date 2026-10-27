# Review workspace v2 - spec and contract

Planner team, branch `planner/workspace-v2`. Frontend only. Read this whole
file before you write code. The shared types live in `contract.ts`; do not
redefine them. If the contract is wrong, say so in your report; do not edit
`contract.ts` yourself (the integrator does).

## 1. Goal

One screen per review that a manager can finish with few clicks:

1. See the verdict in one line.
2. Press the blocker buttons in order until "Sign and export" lights up.
3. Everything else ("How this was reviewed", findings, standards, steps,
   numbers) is a tab on the same screen, not a separate page.

## 2. Hard rules (all builders)

- Frontend only. No changes to `backend/`, `contracts/`, generated files,
  migrations. No new endpoints: use `src/api/*` as it is. Where data has no
  endpoint, write ONE clearly named `TODO ADAPTER` function (already stubbed
  for you where known) so a future endpoint swaps in at one place.
- Behind a switch that is OFF: `routing.WORKSPACE_IS_DEFAULT = false` (added
  by the planner). With the switch off and no "Try new design" opt-in, every
  existing screen, address and test behaves exactly as today:
  `/review/<run>` = CrsSheetView (CRS_SHEET_IS_DEFAULT), `/cards`,
  `/crs-sheet`, `/how`, the behind-the-scenes panels, the landing list.
- Never write the client or company name anywhere. Tests use made-up data
  ("Pump datasheet rev B.pdf", "API 610", run ids like "run-1").
- Copy is plain everyday English for a manager. No engine codes, no rule
  ids, no "tier", no "P1". Any raw code goes through builder C's table and
  sits folded under "Details".
- Honesty rules (CLAUDE.md rule 4): an unknown number renders as nothing,
  never 0; a count says what it counts; a guess is labelled.
- localStorage / sessionStorage always inside try/catch.
- Reuse, do not fork: `buildCrsRows`, `useCrsDecisions`, `saveCrsDecisions`,
  `downloadCrs`, `CrsTable`, `CrsEvidenceDrawer`, `HowReviewedView`,
  panels under `components/review/panels`, `groupRunsByDocument`.
  Do not change the behaviour of these; small additive exports are fine.
- Checks before you hand in: `npx tsc -b`, `npx oxlint`,
  `npx vitest run src/components/review/workspace <your other test files>`,
  then the full `npx vitest run` once.

## 3. The screen

```
/review/<run>/workspace?tab=sheet&row=<rowKey>&panel=evidence
+-----------------------------------------------------------------------------+
| <- Reviews   Pump datasheet rev B.pdf                [Review again] (D)     |
+-----------------------------------------------------------------------------+
| WHAT YOU NEED TO DO  (B: ActionBar)                                         |
| "12 comments, 3 need your judgement. Not signed yet."     <- verdictLine    |
| [Upload missing standards (2)] [Check unread pages (3)] [Decide comments (5)]
|                                                     [Sign and export] (off) |
|   "Check unread pages" opens: Pages 4, 9 and 12  [Read these pages again]   |
+-----------------------------------------------------------------------------+
| [Comment sheet] [How this was reviewed] [Findings] [Standards] [Steps]      |
| [Numbers]                                    (A: WorkspaceTabs)             |
+--------------------------------------------------+--------------------------+
| tab=sheet:                                       | panel=evidence:          |
| 12 comments, 3 need you, 40 met, 7 not           | (C: WorkspaceEvidence    |
| applicable, 3 pages not read  (B: SheetCountsLine)  wrapping                |
| +----------------------------------------------+ |  CrsEvidenceDrawer)      |
| | No | Page | Item | Clause | Observation | ...| | page image, quote,       |
| |  1 | p.4  | ...  |        | (plain words)    | | plain reason,            |
| +----------------------------------------------+ | > Details (raw code)     |
|   (C: WorkspaceSheet = CrsTable over plainRow)   |                          |
| SIGN-OFF (B: SignOffPanel, inside the sheet)     |                          |
| 5 left to decide · 0 not saved  [Save] [Sign]    |                          |
+--------------------------------------------------+--------------------------+
Any page: (D: FinishedReviewNotice) "Your review of X is ready. [Open it]"
Landing /review: (D: NewReviewDropZone) + each row (E: Past reviews (N))
```

Bar order is fixed: standards, pages, decide, sign. Sign is enabled only
when the other three are done AND every "Needs you" row was opened AND
nothing is unsaved AND the comment sheet's issue gate has nothing left
(`signLeft`: final code recorded, unread pages ticked, items decided) AND
the run is not already signed. The sign-off shows the comment sheet's own
"Before you sign" box (crs/BeforeYouSign.tsx); "Check unread pages" leads
to its tick boxes. Signing goes through crs/issueContractorCopy.ts, the one
shared issuing path the comment sheet uses too.

## 4. One source of numbers (builder B)

`computeReviewNumbers(input: ReviewNumbersInput): ReviewNumbers` in
`numbers.ts` is pure. Every count on the workspace comes from it: the bar,
the verdict, the sheet header line, the sign-off panel, tab badges. No other
workspace file may count rows, findings or pages.

Rules (keep them identical to what CrsSheetView shows today so the two
screens never disagree):

| Field | Rule |
|---|---|
| comments | rows with tier B or C (`rowCounts(rows).comment + .needsYou`) |
| needsYou | rows with tier C |
| findingsInComments | sum of `row.findings.length` over comment rows |
| met, anotherDocument | `rowCounts(rows)` |
| notApplicableRows | `rowCounts(rows).notApplicable` (rows; what the table folds, as CrsSheetView) |
| notApplicableClauses | `headlineFieldsOf(run, summary?.how_reviewed).doesNotApply` when a number, else null (clauses of the standards, not rows) |
| removed | `summary?.counts.removed ?? splitRejected(findings).rejected` (exactly what CrsSheetView shows) |
| unreadPages | when the issue gate is known: its `unread_pages` (pages still to tick); else union of `headlineFieldsOf(...).unreadPages` and `readiness?.unread_pages ?? []`; unique, ascending |
| signLeft | `signLeft({ gate }, run, rows)` from crs/issueGate.ts; never empty while the gate is unknown |
| missingStandards | unique of `readiness?.standards_missing ?? []` only: the live list (`export_status.missing_standards`), the one the strip shows. The run's stored list (`input.missingStandards`) is as of the run and is not unioned in (order 243.1) |
| standardsKnown / pagesKnown | standardsKnown: false while the standards read failed (`missingStandards` null) or readiness is null. pagesKnown: true only when readiness answered from a current page ledger (`ledger_state === "current"`) or the issue gate answered from a page record (no "no page coverage" blocker); false otherwise (loading, failed, stale ledger, no page record). An unknown count is never 0: its step is not done, shows "could not read this yet" with no number, and Sign stays off ("Waiting to read the standards and page checks.") |
| undecided / undecidedKeys | comment rows where `decisions.decisions[key]` is absent and `priorState !== "agreed"`, in row order |
| unopenedNeedsYou | tier C rows not in `decisions.opened` |
| pageRecordMissing | the issue gate answered with its "no page coverage" blocker (the run has no page record). Its empty `unread_pages` then means "nobody could count", so pagesKnown is false even if readiness is current: the pages step shows "cannot read yet" (no tick, no number) and says the record of which pages were read is missing |
| unsaved | `input.unsaved.length` |
| signed / signedAt | `run.crs_issued_at` present |

`actionSteps(numbers)` returns the four `ActionStep`s; labels are
"Upload missing standards (N)", "Check unread pages (N)", "Decide comments
(N)", "Sign and export" (or "Signed" when signed). A step with count 0 is
`done: true` and shown as a quiet tick, not hidden. `detail` for pages is
"Pages 4, 9 and 12" (use `pageList` from reviewFormat).

`verdictLine(numbers, run)` is one sentence, e.g. "12 comments, 3 need your
judgement. Not signed yet." / "No comments. Ready to sign." / "Signed on
19 Oct 2026."

## 5. Plain words (builder C)

There is no `glossary.ts` on main and #1149 is not merged
(`src/glossary.test.ts` is the banned-words test). The mappings that exist
are scattered; builder C gathers them into `plainWords.ts` WITHOUT changing a
single existing word:

| Kind | Source today |
|---|---|
| reason | `CrsEvidenceDrawer.tsx` REASON_WORDS (Tier C reasons) |
| tier | tier labels "Met", "Not applicable", "Another document", "Comment", "Needs you" |
| removal | `evidenceNav.ts` REMOVAL_REASON_WORDS |
| trust | `reviewFormat.ts` TRUST_WORDS |
| code | `sheet/DecisionCard.tsx` CODE_WORDS (review codes) |
| status | `reviewFormat.ts` STATUS_LABEL (compliance statuses) |
| runStatus | `reviewFormat.ts` RUN_STATUS_LABEL |
| engine | reason-code prefixes in finding text: `no_field_matched`, `ambiguous_match`, any `snake_case:` prefix (crsRows `plainObservation`) |
| rule | short rule labels such as "p4" and any other rule id shown today |

`plainWords(code, kind)` returns `{ words, detail }`: known code ->
plain words with the code as `detail`; unknown code -> a humanised version
("value_conflict" -> "Value conflict") with the code as `detail`; already
plain -> `detail: null`. `plainText(text)` rewrites known codes inside free
text. `plainRow(row)` returns a COPY with plain observation / required
action / status; key, tier and findings are untouched. `<PlainTerm>` renders
the words with a native `<details><summary>Details</summary>` fold.

Old screens: C may make the old maps import from the new table only if every
string stays byte-identical and all old tests pass. If in doubt, leave the
old maps alone.

## 6. Routing and the switch (builder A)

- `routing.ts`: `WORKSPACE_IS_DEFAULT = false` exists. A adds `"workspace"`
  to `PANELS.review`. Nothing else in routing changes meaning.
- `isWorkspaceScreen(panel, switchOn)` decides: panel `"workspace"` always;
  no panel only when the switch is on; every other panel never.
- Switch = `WORKSPACE_IS_DEFAULT || readWorkspaceOptIn()`; the opt-in key is
  `WORKSPACE_OPT_IN_KEY`. `<TryNewDesignToggle>` is shown on the Submittals
  landing header and on the workspace itself (to switch back). Turning it on
  while on `/review/<run>` opens the workspace; off goes back to the old screen.
- URL keeps the place: path `/review/<run>/workspace`, query
  `tab` (omitted when "sheet"), `row`, `panel` ("evidence"), `doc`.
  `parseWorkspaceQuery(search)` ignores unknown values (falls back to
  defaults, never throws). `workspaceSearch(location)` is the inverse and
  `parse(workspaceSearch(x)) == x`. Tab/row/panel changes use
  `history.replaceState` (no history spam); opening a run uses pushState via
  the existing `onNavigate`. App must keep `window.location.search` when it
  parses on load, so refresh and post-sign-in land in the same place (the
  login screen sits above Shell; route state survives it).
- In App.tsx: render `<ReviewWorkspace>` when `isWorkspaceScreen(...)`; mount
  `<FinishedReviewNotice onOpenRun>` once inside Shell (all views); pass
  `workspace` flag + `onOpenRun` to the landing (see section 9).

## 7. Data flow inside ReviewWorkspace (builder A wires it)

```
data      = useWorkspaceRun(runId)                 // A
decisions = useCrsDecisions()                      // existing
numbers   = computeReviewNumbers({ run, findings, rows, summary,
              missingStandards: missingStandardIds (null = not known),
              readiness, decisions: decisions.state,
              unsaved: decisions.unsaved })        // B
steps     = actionSteps(numbers)                   // B
signOff   = useSignOff({ runId, rows, decisions, refresh })  // B
<ActionBar run numbers steps signOff onAction>     // B
  onAction("standards") -> tab=standards
  onAction("pages")     -> handled inside ActionBar (list + reread button);
                           A passes nothing extra
  onAction("decide")    -> tab=sheet, row=numbers.undecidedKeys[0], panel=evidence
  onAction("sign")      -> signOff.sign()  (ActionBar calls it itself; A no-op)
<WorkspaceTabs tab onTab>                          // A
  sheet:     <SheetCountsLine numbers/> + <WorkspaceSheet ... footer={<SignOffPanel/>}/>
  how:       <HowReviewedView runId .../> (existing)
  findings / standards / steps / numbers: the existing panels
             (BehindTheScenes panel ids "findings", "standards", "steps", "numbers")
<ReviewAgainButton documentId=run.submittal_document_id onStarted=onOpenRun>  // D
```

Loading, failed and still-running runs show the same states CrsSheetView
shows today (reuse its wording; `ReviewJobControl` for running).

## 8. File ownership and acceptance

Only the owner edits a file. Shared existing files are listed with the
single builder allowed to touch them.

### A - shell, switch, routing, tabs, URL
Owns: `workspaceRoute.ts`, `useWorkspaceSwitch.ts`, `useWorkspaceRun.ts`,
`ReviewWorkspace.tsx`, `WorkspaceTabs.tsx`, `TryNewDesignToggle.tsx`, their
tests; edits `src/routing.ts`, `src/App.tsx`.
Accept:
- switch off: App renders CrsSheetView at `/review/<run>`; all existing App and
  routing tests green unchanged.
- `/review/<run>/workspace` renders ReviewWorkspace with the switch off.
- opt-in in storage -> `/review/<run>` renders ReviewWorkspace; blocked storage
  -> old screen, no crash.
- `parseWorkspaceQuery` / `workspaceSearch` round-trip; junk query -> defaults.
- changing tab updates the query string; reload with that query reopens the tab
  and the open row.
- tabs are a proper `role=tablist` with arrow-key movement.

### B - numbers, action bar, sign-off, agree test
Owns: `numbers.ts`, `useSignOff.ts`, `ActionBar.tsx`, `SheetCountsLine.tsx`,
`SignOffPanel.tsx`, `numbers.test.ts`, `numbers.agree.test.tsx`.
Accept:
- `numbers.test.ts`: each rule in section 4 with a made-up fixture
  (unknown readiness, summary null, duplicates in unread pages, agreed rows).
- `numbers.agree.test.tsx`: renders ActionBar, SheetCountsLine and SignOffPanel
  from ONE `computeReviewNumbers` result and asserts every shared count
  (`data-count="comments|needsYou|undecided|unreadPages|missingStandards"`)
  is identical across the three and equal to the helper; fails if any
  component counts on its own (mutate a component to prove it once).
- Sign disabled until standards, pages and decide are done and unsaved = 0;
  enabled -> calls `downloadCrs(runId, "issue")` (mock it). #1150 is not on
  main: note this in the code where `sign` is defined.
- "Check unread pages" lists the pages and offers `reviewsApi.rereadPages`.

### C - plain words in the workspace
Owns: `plainWords.ts`, `PlainTerm.tsx`, `WorkspaceSheet.tsx`,
`WorkspaceEvidence.tsx`, `plainWords.test.ts`, `WorkspaceSheet.test.tsx`.
Accept:
- every entry of the existing maps (section 5) appears with identical words.
- `plainWords("no_field_matched", "engine")` -> plain words + detail
  "no_field_matched"; unknown code humanised; never returns an empty string
  for a non-empty code.
- a test renders WorkspaceSheet with rows whose text carries
  "no_field_matched:" and a rule label "p4": neither code is visible until
  "Details" is opened.
- WorkspaceSheet opens WorkspaceEvidence for `openRowKey`, calls `onOpenRow`
  on row click / close, keeps CrsTable keyboard behaviour.

### D - new review, review again, finished notice
Owns: `newReview.ts`, `reviewWatch.ts`, `NewReviewDropZone.tsx`,
`ReviewAgainButton.tsx`, `FinishedReviewNotice.tsx`, their tests; edits
`src/views/SubmittalsLandingView.tsx` and `src/components/Uploader.tsx`
(only to `export` `uploadOne`, no behaviour change).
Accept:
- drop a file -> upload -> `markAsContractorSubmittal` -> wait for the
  document to be read in -> `startReviewRun` -> `onStarted(runId)`, in that
  order (mock each call, assert order); 3 clicks or fewer from the landing.
- a non-admin role refusal (404 from setRoleBulk) shows a plain message and
  does not start a review.
- "Review again" calls `startReviewRun(documentId)` and opens the new run;
  a refusal (review already running) is shown as the API said it.
- a watched run turning completed shows the notice on another view, with
  "Open it"; dismiss works; watch list survives a re-mount (sessionStorage in
  try/catch).
- switch off: the landing page renders exactly as today (no drop zone).

### E - past reviews per document
Owns: `pastReviews.ts`, `PastReviewsButton.tsx`, `PastReviewsList.tsx`, their
tests; edits `src/components/review/DocumentsFromContractors.tsx` (optional
new prop only).
Accept:
- `pastReviewsOf` filters by document, newest first (same order as
  `groupRunsByDocument`), result in plain words, `signed` from
  `crs_issued_at`.
- "Past reviews (N)" counts from the runs already loaded (no request);
  hidden when N is 0.
- opening the list fetches comment counts lazily via `loadCommentCount`;
  a failed count shows nothing, never 0.
- clicking a row calls `onOpenRun(runId)`.
- DocumentsFromContractors without the new prop renders exactly as today.

## 9. Integration points (names are fixed)

- `SubmittalsLandingView` gets optional props `workspace?: boolean` (switch
  on) and keeps `onOpenRun`. When `workspace` is true, D mounts
  `<NewReviewDropZone onStarted={onOpenRun}/>` above the list and passes
  `onOpenPastRun={onOpenRun}` to DocumentsFromContractors. A passes
  `workspace={switchOn}` from App and renders `<TryNewDesignToggle>` in the
  landing header area from App (above the view, so A does not edit the
  landing file).
- `DocumentsFromContractors` gets optional `onOpenPastRun?: (runId) => void`;
  when present, each row shows `<PastReviewsButton documentId runs
  onOpenRun={onOpenPastRun}/>` (E).
- Opening a run from anywhere while the switch is on goes to
  `/review/<run>` (the switch decides the screen); with the switch off,
  links from new pieces go to `/review/<run>/workspace`.
- `watchRun(runId, filename)` is called by D after any start (new review,
  review again). `FinishedReviewNotice` is mounted by A in App.

## 10. Merge order

A first (routing + shell with placeholders wired), then B, C, E in any
order, D last (touches the landing). Each builder rebases on the previous
merge; conflicts outside your owned files mean you touched someone else's
file - undo that instead of resolving.
