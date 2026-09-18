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

## Explicitly still open

- The API has no suggestion-decision contract for Accept/Edit/Reject (actor,
  timestamp, edited value, audit event). The UI does not invent those actions;
  the limitation is recorded in `docs/ui-backend-gaps.md`.
- `DashboardViewContent.tsx` and `MarketPanelContent.tsx` remain the deferred
  large modules (923 and 889 lines respectively). They were not falsely
  “split” with wrappers; a pure responsibility split is still required.
- A full backend suite run was started with the project interpreter but was
  stopped after 18% because this environment's suite is long-running. The
  previously verified baseline is 1,553 passing tests; this pass does not
  claim a fresh full-suite result.
- Live 100,000-row scroll timing and J1–J4 click re-measurement still require a
  restarted backend and authenticated browser session.

## Checks

- Frontend targeted tests: 571 passing after the Phase 4 changes; the initial
  full run exposed one glossary regression from the new navigation label, which
  was corrected and the affected tests pass.
- `npm run typecheck`: passed.
- `npm run build`: passed.
- `npm run check:budget`: passed.
