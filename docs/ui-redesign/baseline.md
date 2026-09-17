# Phase 0 UI baseline

Recorded 2026-09-17 on branch `feat/phase-1-ui-reaches-backend` at source commit
`cea382e`. Phase 0 observes and measures the current product; it does not begin
the redesign.

## Source-state proof

The measurements below were taken while `frontend/src` matched the committed
tree. Phase 0 added test tooling and generated evidence outside that directory.

```text
> git status --short
 M frontend/package-lock.json
 M frontend/package.json
?? docs/ui-backend-gaps.md
?? docs/ui-redesign/
?? frontend/playwright.phase0.config.ts
?? frontend/tests/e2e/phase0-baseline.spec.ts
?? frontend/tests/e2e/phase0-evidence-display.spec.ts
?? frontend/tests/e2e/phase0-ingestion-timing.spec.ts
?? frontend/tests/e2e/reports-download-live.spec.ts

> git diff --stat -- frontend/src
(no output)
```

Therefore, none of the counts is affected by an uncommitted production-source
edit. The dependency and tests shown above are Phase 0 measurement tooling.

## Reproducible source counts

These are **regex match counts**, not matching-line counts. Files included are
`*.ts`, `*.tsx`, and `*.css` recursively under `frontend/src`. Files whose
filename contains `.test.` are excluded. The same commands must be used for the
final before/after report.

```powershell
$prod = Get-ChildItem frontend/src -Recurse -File -Include *.ts,*.tsx,*.css |
  Where-Object { $_.Name -notmatch '\.test\.' }

function Count-Matches([string]$pattern) {
  $total = 0
  foreach ($file in $prod) {
    $total += ([regex]::Matches(
      (Get-Content -LiteralPath $file.FullName -Raw),
      $pattern
    )).Count
  }
  $total
}

Count-Matches 'text-\[(?:9|10|11)px\]'
Count-Matches 'text-xs'
Count-Matches 'focus-visible:'
Count-Matches '(?<![a-z])(ml|mr|pl|pr)-[A-Za-z0-9\[\]./-]+'
Count-Matches 'dir='
Count-Matches 'motion-(?:safe|reduce):|prefers-reduced-motion'
Count-Matches 'document\.title'
```

| Measure | Exact pattern | Baseline matches |
| --- | --- | ---: |
| 9–11 px text utilities | `text-\[(?:9|10|11)px\]` | 119 |
| `text-xs` utilities | `text-xs` | 309 |
| visible-focus utilities | `focus-visible:` | 32 |
| physical LTR spacing utilities | `(?<![a-z])(ml\|mr\|pl\|pr)-...` | 64 |
| direction attributes | `dir=` | 0 |
| reduced-motion handling | `motion-(?:safe\|reduce):\|prefers-reduced-motion` | 4 |
| title setters | `document\.title` | 0 |

The measured counts replace the older estimates of 117, 284, 12, and 53.

Current largest production files, counted with PowerShell `Measure-Object -Line`:

| File | Lines |
| --- | ---: |
| `frontend/src/views/AnalysisModeScreen.tsx` | 1,597 |
| `frontend/src/views/DashboardView.tsx` | 904 |
| `frontend/src/components/analysis/MarketPanel.tsx` | 826 |
| `frontend/src/components/chat/AnswerCard.tsx` | 802 |

## R6 live-check gate

`npm run build` passed before the browser checks. `dist/index.html` was written
at 2026-09-17 20:38:23, later than the newest file then present under
`frontend/src` (2026-09-17 18:30:57). The generated bundle was 465.53 kB JS
(124.81 kB gzip) and 60.52 kB CSS (11.05 kB gzip).

## 0.1 Reports download — closed

The live Reports screen was exercised in installed Google Chrome by
`frontend/tests/e2e/reports-download-live.spec.ts`.

Command:

```powershell
cd D:\project\Rag_chatbot\frontend
npx playwright test tests/e2e/reports-download-live.spec.ts --workers=1 --config playwright.phase0.config.ts
```

Observed evidence:

| Property | Result |
| --- | --- |
| HTTP status | 200 |
| Content type | `application/pdf` |
| Content disposition | `attachment; filename="rag-intelligence-report-rpt_4ca405a0d40d.pdf"` |
| Browser filename | `rag-intelligence-report-rpt_4ca405a0d40d.pdf` |
| Downloaded size | 129,384 bytes |
| Test result | 1 passed |

Machine-readable evidence is in `report-download-evidence.json`. The earlier
failure to observe a download occurred in the Codex in-app browser, while the
same live endpoint and UI succeeded in installed Chrome. No report code change
was justified. The Playwright regression test is retained.

## 0.2 Screenshot inventory

`frontend/tests/e2e/phase0-baseline.spec.ts` captures all eight views in light
and dark themes at 1366×768, 1600×900, and 1920×1080 after a five-second settle
period. The complete 48-file set is in `docs/ui-redesign/before/`.

## 0.3 Accessibility baseline

`@axe-core/playwright` was added as a development-only audit dependency. Axe ran
at 1600×900 for every view in both themes. Full results are in
`axe-baseline.json`.

| View | Theme | Serious rules / nodes | Critical rules / nodes |
| --- | --- | ---: | ---: |
| Dashboard | Light | 2 / 17 | 0 / 0 |
| Documents | Light | 1 / 20 | 0 / 0 |
| Chat | Light | 1 / 19 | 0 / 0 |
| Analysis | Light | 1 / 22 | 0 / 0 |
| Reports | Light | 1 / 13 | 0 / 0 |
| Deliverables | Light | 1 / 41 | 0 / 0 |
| Ingestion | Light | 1 / 59 | 0 / 0 |
| Administration | Light | 1 / 59 | 0 / 0 |
| Dashboard | Dark | 2 / 15 | 0 / 0 |
| Documents | Dark | 1 / 13 | 0 / 0 |
| Chat | Dark | 1 / 16 | 0 / 0 |
| Analysis | Dark | 1 / 14 | 0 / 0 |
| Reports | Dark | 1 / 12 | 0 / 0 |
| Deliverables | Dark | 1 / 21 | 0 / 0 |
| Ingestion | Dark | 1 / 33 | 0 / 0 |
| Administration | Dark | 1 / 76 | 0 / 0 |

The common serious rule is insufficient colour contrast. Dashboard also has
one invalid list-content node in each theme. Zero critical violations does not
make this a pass: serious violations remain across every view.

## Ingestion-load finding

The H1 was timed five times by
`frontend/tests/e2e/phase0-ingestion-timing.spec.ts`.

| Run | H1 visible | Slow `/api/metrics` calls |
| ---: | ---: | --- |
| 1 | 3,563 ms | 1,345 / 2,260 / 3,143 ms |
| 2 | 3,523 ms | 1,202 / 2,101 / 2,968 ms |
| 3 | 4,553 ms | 1,155 / 2,757 / 4,153 ms |
| 4 | 3,545 ms | 1,523 / 2,437 / 3,274 ms |
| 5 | 3,523 ms | 1,231 / 2,181 / 3,082 ms |

`IngestionView.load()` waits for metrics and documents together. A spinner
labelled “Reading the queue” exists, but the page H1 and explanatory context are
inside the post-load branch, so the screen has no identity while those calls
run. The same metrics resource is requested three times during the observed
mount. Severity: **3 (major usability)**. Preserve the H1 and context during
loading, and remove redundant metrics work in a later phase. Raw timings and
requests are in `ingestion-timing.json`.

## 0.4 Current journeys

These are the current paths, not proposed redesigns. A “click” counts an
intentional pointer/keyboard activation; typing and waiting are listed but not
counted as clicks.

### J1 — contractor submittal, upload to report

1. Documents (1 click).
2. Choose or drop a PDF (1), then wait for ingestion.
3. Inspect document status/type; an administrator may need to confirm its type
   (1–2).
4. Analysis (1), enter the review question.
5. Choose a named comparison workflow (1), then separately pick the two
   document sides (2). The app deliberately does not invent the authoritative
   baseline.
6. Choose analysis mode and optional gap/recommendation work (1–3), then Run
   analysis (1).
7. Inspect findings and activate citations (at least 1 per finding).
8. Create a tracked finding, choose severity/owner/due date/action, then save
   (at least 5).
9. To produce a frozen PDF, leave Analysis for Chat, obtain/open an answer, use
   Save as report, then go to Reports and Download (at least 4 more clicks).

Minimum practical path: about **18 clicks**, excluding repeated evidence checks.
Unclear/dead ends: upload, review, finding disposition, and reporting are split
across four views; there is no visible review progress; state has no URL and
cannot be shared or restored; the Analysis result itself has no direct complete
review-report action; long analysis has progress but no backend cancel endpoint.

### J2 — chat question to boxed source page

1. Chat (1), New if required (1), choose response style (optional 1).
2. Enter the question and Ask (1), then wait for retrieval/generation.
3. Activate an inline/source citation (1).
4. Evidence opens with filename, page, passage and page image. When a highlight
   exists, the client requests the server-drawn answer box.

Typical path: **3–5 clicks**. Main risk: the client labels a requested box as
“answer outlined” but discards the server’s `X-Answer-Located` response header;
the “could not be located” wording is only chosen when no highlight existed
before the request. See `ui-backend-gaps.md`.

### J3 — overdue deliverables and risks for one WBS node

1. Dashboard and Open deliverables, or Deliverables directly (1).
2. Select the relevant WBS row/node (1).
3. Inspect linked deliverables, review findings, stakeholder assignments and
   escalation state.
4. Change the risk-type filter (1 per type) and open/create the relevant risk.

Typical path: **3–5 clicks**. Unclear/dead ends: dashboard cards are counts more
than task links; there are no stable filtered URLs; risk, escalation, and WBS
content share one long screen; returning to the same node cannot be bookmarked.

### J4 — admin creates user, grants discipline, deactivates user

1. Administration (1).
2. Enter email, choose discipline, optionally choose admin, Create user (2–3).
3. Preserve and deliver the one-time setup token shown after creation.
4. Find the required document in the long permission list and grant the
   discipline (1 per grant).
5. Later find the user and Deactivate (1, followed by the existing named
   confirmation where applicable).

Typical path: **5–7 clicks**, but finding records dominates time. Unclear/dead
ends: document grants are an unfiltered, unpaged wall of cards; user creation
and document access are separate mental models; there is no deep link to the
new user or document permission record.

## 0.5 Heuristic review

Nielsen codes: H1 visibility, H2 real-world match, H3 control, H4 consistency,
H5 error prevention, H6 recognition, H7 efficiency, H8 minimalism, H9 recovery,
H10 help. Severity 1 cosmetic, 2 minor, 3 major, 4 blocking.

| View | H | Sev. | Finding and evidence | Suggested later fix |
| --- | --- | ---: | --- | --- |
| All | H4/H6 | 3 | Every view has serious axe contrast failures; secondary text and compact uppercase labels are especially faint. See all 1600×900 captures and `axe-baseline.json`. | Raise token contrast in both themes, then make serious/critical axe violations fail CI. |
| Dashboard | H8 | 2 | Capability cards, EPC counters, readiness metrics and notices compete before the first clear task. [`dashboard-light-1600x900.png`](before/dashboard-light-1600x900.png) | Lead with at most seven actionable items; move diagnostics behind Technical detail. |
| Dashboard | H4 | 2 | Navigation list markup has a serious axe list-content violation in both themes. | Correct the list DOM without changing its appearance. |
| Documents | H7/H8 | 3 | Nineteen documents produce a multi-screen wall of large cards with repeated five-button action groups; scanning by exception is difficult. [`documents-light-1600x900.png`](before/documents-light-1600x900.png) | Introduce compact rows, search/filter/sort and server paging before corpus scale increases. |
| Documents | H7/H8 | 3 | Full document inventory has no paging/virtualisation/filter API; actions grow linearly with the corpus. | Add server paging/filter/sort, then virtualise lists over 100 rows. |
| Chat | H1/H3 | 2 | A long local model run shows real stages and time, but occupies an otherwise blank answer area and cannot be cancelled because no cancel endpoint exists. [`chat-light-1600x900.png`](before/chat-light-1600x900.png) | Keep durable cross-navigation progress; do not add a fake cancel control. |
| Chat | H6/H8 | 2 | History competes with the answer on narrower screens; titles truncate repeatedly and have no search. | Make history collapsible by default at constrained widths and searchable. |
| Analysis | H2/H8 | 3 | Comparison, scope, mode, optional engines, execution limitations and sources appear together before any result; first-time contractors must decode internal system boundaries. [`analysis-light-1600x900.png`](before/analysis-light-1600x900.png) | Turn the measured J1 path into a guided review flow; keep advanced controls available. |
| Analysis | H1 | 3 | Selected evidence shows the quote but hides source provenance/confidence already returned by the API. | Reuse the existing provenance components beside each selected passage. |
| Reports | H7/H8 | 3 | Every report is fully rendered in one page; the 1600px capture is over 7,000px tall and has no search, paging, grouping or sort. [`reports-light-1600x900.png`](before/reports-light-1600x900.png) | Add paged/filterable report list and concise rows with expandable detail. |
| Reports | H2/H4 | 2 | Raw ISO timestamps and repeated “Outside this report” blocks read as implementation output, not a management register. | Use locale-aware dates and one clear report-scope affordance. |
| Deliverables | H4/H8 | 3 | Add form, WBS register, expectations, risk register and escalation policy share one continuous page with weak task separation. [`deliverables-light-1600x900.png`](before/deliverables-light-1600x900.png) | Use task-oriented tabs/URLs while preserving cross-record context. |
| Deliverables | H5 | 2 | “Add risk” and deliverable creation expose minimal fields before submission; downstream ownership/action expectations are not visible at the decision point. | Show required operational fields and calm inline validation before submission. |
| Ingestion | H1 | 3 | H1/context disappear for 3.52–4.55 s while repeated metrics calls complete. [`ingestion-light-1600x900.png`](before/ingestion-light-1600x900.png) | Render page identity immediately; load panels independently; deduplicate metrics. |
| Ingestion | H8 | 2 | Duplicate watch events and all indexed documents form very long, dense lists. | Summarise repeated events and add filtering/paging. |
| Administration | H7/H8 | 3 | The permission inventory is nearly 3,000px tall for only 19 documents, with repeated discipline buttons and no filter. [`administration-light-1600x900.png`](before/administration-light-1600x900.png) | Search/filter documents and use a compact access matrix or selected-record editor. |
| Administration | H5/H6 | 2 | Baseline rules, summaries, users, disciplines and document grants share one page; the relationship between a newly created user and later access grants is not guided. | Split stable task routes and link the post-create state to the relevant grants. |
| All | H7 | 3 | App state uses component state rather than routes; refresh/back/share cannot restore a record or filtered task. | Phase 1 URL routing before visual redesign. |

No severity-4 blocker was observed in the static baseline. The widespread
contrast failures and lack of stable navigation are release-significant
severity-3 issues.

## 0.6 Evidence visibility

The full field-by-field inventory is in [`../ui-backend-gaps.md`](../ui-backend-gaps.md).
Two existing disclosures were captured without rebuilding them:

- [`evidence-removed-chat.png`](../ui-redesign/evidence-removed-chat.png) shows
  the current `AnswerCard` disclosure from a real stored answer. The test only
  moves that older real conversation onto the first history page; it does not
  alter its message payload.
- [`dropped-sentences-analysis-controlled.png`](../ui-redesign/dropped-sentences-analysis-controlled.png)
  shows the current collapsed `AnalysisModeScreen` renderer opened with a
  controlled response fixture. It demonstrates presentation, not a claim that
  this particular sentence came from the live corpus.

`GapAnalysisCard` does not receive either response field. It separately reports
how many structurally empty gap rows were withheld; duplicating the summary or
chat disclosure there would be incorrect.

## 0.7 Questions requiring product/client answers

1. Does the real KJO corpus contain Arabic documents that engineers must read
   or search? Arabic/RTL work remains unapproved until this is confirmed.
2. What browser and typical screen resolution do the reviewing engineers use?
3. Does any intended user rely on a screen reader? If yes, which screen reader
   and browser combination must be used for the acceptance pass?

These are open product inputs, not Phase 0 test failures.

## Phase 0 disposition

- 0.1 report download: **closed with live Chrome evidence**.
- 0.2 screenshots: **48/48 captured**.
- 0.3 axe: **16/16 view/theme combinations measured; serious findings open**.
- 0.4 journeys: **documented**.
- 0.5 heuristics: **documented; no redesign applied**.
- 0.6 evidence display: **documented with screenshots and field inventory**.
- 0.7 open questions: **recorded for owner response**.

Verification at close-out:

- `npx vitest run --maxWorkers=1`: **44 files, 562 tests passed**. A single
  worker was used because this laptop timed out tests when two complete suites
  were accidentally launched concurrently; the isolated rerun is the valid
  result.
- `npm run build`: **passed** (465.53 kB JS / 124.81 kB gzip).
- Settled 48-screen + axe Playwright run: **1 passed** in 5.5 minutes.
- Evidence, ingestion-timing and report-download Playwright checks: **4 passed**
  in 32.2 seconds.

Phase 1 has not started.
