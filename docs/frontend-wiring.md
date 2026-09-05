# Frontend wiring — the enterprise components

Eleven new files were written in parallel against the plan's section 9 and
section 7.2, and against the design docs. **None is typechecked or run.** They
accept data and callbacks as props and call no API function, so the backend can
land in any order and each component lights up when its data arrives.

## What exists

| File | Exports | Renders |
|---|---|---|
| `types/analysis.ts` | all contracts | — |
| `views/LoginView.tsx` | `LoginView`, `RoleBadge`, `LoginOutcome` | Login form; role badge for the shell |
| `views/ReportsView.tsx` | `ReportsView` | Report list, download, verify, suppressed count |
| `views/AnalysisView.tsx` | `AnalysisView` | Composes everything below in the plan's mandated order |
| `components/analysis/ModeSelector.tsx` | `ModeSelector`, `AnalysisMode`, `AnalysisToggles` | Quote / Focused / Comprehensive + three toggles |
| `components/analysis/SummaryCard.tsx` | `SummaryCard`, `CitedText` | Generated summary, amber, "Summary of N passages" |
| `components/analysis/RecommendationCard.tsx` | `RecommendationCard` | AI advisory, confidence as a word, checklist |
| `components/analysis/CoverageLedger.tsx` | `CoverageLedger` | 20→15 header, per-document table, paginated |
| `components/analysis/ClaimTable.tsx` | `ClaimTable` | Mechanical cross-document claim comparison |
| `components/analysis/GapAnalysisCard.tsx` | `GapAnalysisCard` | Baseline nomination + gap items |
| `components/analysis/MarketPanel.tsx` | `MarketPanel` | Sample data banner, egress pills, outbound-query dialog |

## Rules every component was written to hold

- **A null renders as nothing.** No tick, no green, no "complete". `coverage.complete` is `false | null`; `confidence` is `"low" | "medium" | null`; `normalized_value` is a number or null. Nothing defaults to 0.
- **Quoted text is serif on a quote rule; generated text is sans on amber.** `exact_span` and `baseline_span` are quotes. `summary` and `recommendation.text` are generated.
- **Status is text + icon, never colour alone.**
- **"possible_conflict" and "possible_gap" say "possible"**, with captions saying why certainty is unavailable.
- **The literal sentence "Review and approval by a qualified engineer is required."** appears on every recommendation and every gap analysis.
- **Market rows are labelled SAMPLE on every row and in a banner.** URLs are text, not links — the machine is offline.
- **The outbound-query dialog shows the exact string** and its Confirm is disabled while `allow_public_egress === false`.
- **One error message for all credential failures.** Rate-limit gets its own.

## Wiring steps

### 1. Types — merge, do not duplicate
When each Pydantic model lands, move its interface from `types/analysis.ts` into
`contracts/types.ts` and delete it from the former. Two copies drift.

### 2. Shell — nav and badge
`Shell.tsx` `NAV` gains `reports` and, admin-only, `access`. `RoleBadge` goes in
the bottom block beside `ConnectionBadge`, fed by `GET /api/me` (or `null` under
`AUTH_MODE=disabled`).

### 3. Login — above the shell, not inside it
Render `LoginView` in place of the whole shell when `AUTH_MODE=demo_required`
and there is no token. Health stays unauthenticated so the connection line still
works on the login screen — "backend offline" and "wrong password" must be
distinguishable.

`client.ts`: a module-level `bearer`, attached in `request()`, cleared on 401
with a callback that flips the app to the login screen. **Split `humanMessage`'s
401 from its 403** — today both say "check the backend settings", which is wrong
for a logged-out user.

Map: 401 → `{ok:false, kind:"credentials"}` · 429 → `{ok:false, kind:"rate_limited"}`
· network error → `{ok:false, kind:"offline"}`.

### 4. Chat — the mode selector
`ModeSelector` sits above the input. `mode === "quote"` is today's Tier 1 path,
unchanged. `focused` is today's Tier 2. `comprehensive` posts to
`POST /api/conversations/{id}/analyses` and receives a 202 + `analysis_id`; the
view then polls `GET /api/analyses/{id}` every 2 s (no SSE — see
`design-analysis-and-synthesis.md` section A) and renders `AnalysisView` with the
result. `onCancel` posts to `/cancel`.

### 5. AnalysisView — the drawer is the parent's
`onCite(evidenceId)` resolves the evidence item from `result.evidence_ledger`
and opens the existing evidence drawer on its document/page. The view owns no
drawer of its own.

### 6. Reports
`ReportsView` is a nav entry. `onDownload` → `GET /api/reports/{id}/file`
(blob, `Content-Disposition` names the id). `onVerify` → `GET /api/reports/{id}/verify`.
`suppressedCount` comes from the list endpoint's `suppressed_count`.
`onGenerate` posts `POST /api/reports` from a `message_id` or `analysis_id`.

### 7. Market — hard-wired off
`egress` comes from config: `{web_search_enabled: false, allow_public_egress: false}`
in this build. `findings` is the labelled local sample. Do not pass
`onPreviewQuery` unless the provider is real — the dialog's Confirm is disabled
anyway, but a form that can never submit is noise.

### 8. Tests, each proven to fail first
- `complete: null` renders no tick and no word "complete" anywhere.
- `confidence` renders a word and never a digit or `%`.
- Two credential failures render byte-identical messages.
- `possible_conflict` renders the word "possible".
- Every market row carries "SAMPLE".
- Confirm is disabled while egress is blocked.
- `RoleBadge` with `me === null` renders no invented name.
- `CoverageLedger` renders `—` for a null count and `0` for zero.

## What is NOT wired
Everything. These are components with props. Nothing imports them yet, nothing
routes to them, and no API function exists for most of them. That is deliberate:
the backend is landing feature by feature under a hard clock, and each component
can be connected the moment its endpoint exists without waiting for the rest.
