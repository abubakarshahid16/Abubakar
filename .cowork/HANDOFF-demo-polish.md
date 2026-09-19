# Merge and verify: cowork/demo-polish (head 2b20ad5)

Three commits ahead of what you have. The last one (2b20ad5) contains
frontend edits I could NOT run a test or a typecheck against, because npm
on this machine would replace the Windows node_modules with Linux
binaries. Treat every line of it as unverified.

## What to do

1. Merge `cowork/demo-polish` into main.
2. Run `npx tsc --noEmit` in `frontend/`. `ReviewRunsView.tsx` gained a
   `useRef<HTMLElement | null>` attached to a `<section>` ref; if that
   assignment does not typecheck, fix the type, do not remove the ref.
3. Run the full frontend test suite. Two files assert on the string
   NOMINAL ESTIMATE (`ReviewCodePanel.test.tsx` lines 27 and 46). I did
   NOT touch `ReviewCodePanel` or `completenessLine`, so those should
   still pass. If they fail, my change reached further than I believed -
   report that rather than editing the tests.
4. `ReviewRunsView.tsx` has no test file at all. Write one covering the
   thing I could not verify: selecting a run renders the findings section
   BEFORE the runs list in the DOM, and a run whose `recommended_reason`
   already contains "NOMINAL ESTIMATE" renders that sentence once on the
   card, not twice.
5. Load the app and click a run. The findings must be on screen without
   scrolling.

## What is in the merge

- 5056c21 browser tab title: "frontend" -> "RAG Intelligence System"
- ebb4a97 vitest maxWorkers: 4 (the frontend flake was memory)
- 2b20ad5 the three UI fixes described in its own message

## Not in the merge, and not defects - do not "fix" these

- Nav and run-card buttons reported as having no accessible name: false.
  Both have text content and compute a name. The a11y snapshot tool was
  wrong, not the markup.
- Every document showing "Civil Engineering": that chip is the access
  GRANT, not a document property, and its own tooltip says so.
- All 274 documents "Awaiting a type": designed behaviour. The system
  never guesses a type.
- "illustrative sample only" and "Prototype": honesty labels. Keep them.
