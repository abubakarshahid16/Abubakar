# UI redesign / Phase 4 status

## Verified in this pass

- Documents and Reports request bounded server pages (`limit=100`) with query,
  sort and direction controls. The list uses `content-visibility: auto` and a
  load-next control; it does not render the entire result set at once.
- A 100,000-document backend pagination regression test passes and asserts the
  `X-Total-Count` header. The browser list remains bounded to the requested
  page size.
- Guided review flow is available at `/review`, with three visible,
  revisitable steps linking to the existing Documents, Analysis and Reports
  screens. Component test passes.
- Ctrl+K command palette searches both `/api/search` and
  `/api/search/structured`, offers navigation, and hides Administration from
  non-admin identities. Component test passes.
- Dashboard displays at most seven actionable warning rows; each links to the
  relevant document or deliverables route. Technical diagnostics remain behind
  the existing disclosure.
- Backend-provided automatic baseline, inferred deliverable, and automatic-risk
  records are visibly labelled as AI suggestions where their response fields
  prove that provenance.
- Initial production assets are 141,054 bytes gzip (130.43 KB JS plus CSS),
  below the 300 KB budget. The check is now enforced in CI.
- The deferred Dashboard module is now a real responsibility split: 
  `DashboardViewContent.tsx` is 288 lines, `DashboardPrimitives.tsx` is 290,
  and `DashboardTechnicalDetails.tsx` is 368. No wrapper is being counted as
  the implementation.
- The deferred Market module is now a real responsibility split:
  `MarketPanelContent.tsx` is 184 lines, `MarketPanelPrimitives.tsx` is 341,
  and `MarketPanelDialogs.tsx` is 374. The existing public export remains
  unchanged.

## Explicitly still open

- The API has no suggestion-decision contract for Accept/Edit/Reject (actor,
  timestamp, edited value, audit event). The UI does not invent those actions;
  the limitation is recorded in `docs/ui-backend-gaps.md`.
- Backend full suite: 1,557 passed, 27 skipped, 17 expected failures, with
  `D:\project\Rag_chatbot\.venv\Scripts\python.exe -m pytest -q` (503.12s).
  This is above the 1,553 baseline; the skips and expected failures are the
  suite's recorded cases, not silently converted passes.
- Live authenticated journey measurements (2026-09-18, disposable local admin
  account) are now recorded as actual UI actions. Typing and waiting are not
  counted; route changes through the palette are counted when their command is
  activated:
  - J1 guided submittal review: **8 clicks**, from review step 1 through the
    reports screen (Phase 0 baseline about 18).
  - J2 document question: **2 clicks** (open Chat from the palette, submit the
    question).
  - J3 dashboard follow-up: **2 clicks** (open Dashboard from the palette,
    follow an actionable item).
  - J4 administration user lifecycle: **7 clicks** (open Administration,
    choose discipline, create the temporary user, dismiss its token, and
    deactivate/confirm deactivation). The temporary account was removed after
    the check.
- The authenticated axe audit completed the full matrix: 8 views × 2 themes =
  16 runs. Every run reported 0 serious and 0 critical violations. The live
  output and node counts are in `docs/ui-redesign/contrast-phase4-live.json`.
- Keyboard-only verification passed live: Ctrl+K opened the palette, Tab and
  Enter activated Chat and Guided review commands, and Enter activated the
  Guided review's Open documents control.

## Checks

- Frontend full suite: 51 files, 572 tests passing with
  `npx vitest run --pool=forks --maxWorkers=1 --reporter=verbose`.
- Dashboard split tests: 26 passing. Market split tests: 31 passing.
- `npm run typecheck`: passed.
- `npm run build`: passed.
- `npm run check:budget`: passed.
