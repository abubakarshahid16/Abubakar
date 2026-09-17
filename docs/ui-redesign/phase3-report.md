# Phase 3 close-out

## Delivered

- Added an accessible citation inspector on the existing evidence citation. It
  exposes filename, page range, section when supplied, exact passage, and the
  provenance wording “Verbatim from PDF” or “Read by OCR, lowest confidence X”.
  Escape closes the inspector and returns focus to its trigger.
- Kept citation selection connected to the existing authenticated page-image
  viewer and server-drawn answer box, including the `X-Answer-Located: 0`
  sentence-not-located disclosure.
- Added a keyboard-operable resizer for the evidence split pane; its width is
  saved in browser storage.
- Moved retrieval scores into expandable “Retrieval details” disclosures and
  described them as ranking diagnostics rather than quality judgements.
- Improved the existing analysis summary disclosure for `evidence_removed`.
- Added provenance and OCR confidence to selected analysis evidence using the
  existing provenance primitives.
- Replaced the one-line traceability summary with a vertical timeline showing
  finding, document, baseline, citations, deliverable, owner, action, and
  review events.

## Known backend contract gap

`ReviewTraceability` returns citation identifiers and a baseline filename, but
not citation records/routes or a baseline document identifier. The UI therefore
does not invent links for those nodes. This is recorded in
`docs/ui-backend-gaps.md` for the Phase 4/backend follow-up.

## Verification

- Axe audit: `contrast-root-cause.spec.ts` authenticated with a disposable
  local audit account, all 8 views × both themes (16 runs), **0
  serious/critical violations**. The runner prints one line per view/theme
  with its non-zero DOM node count, and `contrast-phase3.json` contains all 16
  entries (including zero-violation runs).
- Frontend: **570 passed** with
  `npx vitest run --pool=forks --maxWorkers=1`.
- Backend: **1553 passed, 27 skipped, 17 xfailed** with
  `.venv\Scripts\python.exe -m pytest -q`.
- `npm run typecheck`: passed.
- `npm run build`: passed.
- Backend was restarted from the current branch after the audit and health
  returned HTTP 200.

## Audit authentication

The audit logged in through the real sign-in form using a disposable local
account created only for the run. That account was deleted after the audit;
the normal `AUTH_MODE=demo_required` backend was restored and no credentials or
`.env` files were committed.
