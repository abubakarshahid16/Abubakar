// @ts-nocheck
import { analysis as analysisApi, isSignedIn, market as marketApi, reviews as reviewsApi } from "../../api/client";
import type { AppliedScope, ClassificationScope } from "../../api/client";
import type { AnalysisGapsResult, AnalysisRecommendationResult, AnalysisSummaryResult, ApiError, EvidenceItem, EgressState, MarketFinding } from "../../types/api";
import type { AnalysisResult, BaselineSelection, ClaimCluster, GapAnalysis, Recommendation } from "../../types/analysis";
import type { AnalysisMode, AnalysisToggles } from "../../components/analysis/ModeSelector";
import { citedFindings, citedSummary, enginesFor, locate, onlySamples, slotFrom, toAnalysisResult, toClaimClusters, toGapAnalysis, toGapItems, toRecommendation, str } from "./analysisModel";
// ------------------------------------------------------------- what renders

interface SummarySlotData {
  result: AnalysisResult;
  refusal: string | null;
  dropped: { sentence: string; reason: string }[];
  ledger: EvidenceItem[];
}

interface GapsSlotData {
  clusters: ClaimCluster[];
  gaps: GapAnalysis;
  ledger: EvidenceItem[];
}

interface RecommendationSlotData {
  recommendation: Recommendation | null;
  refusal: string | null;
  findings: MarketFinding[];
  ledger: EvidenceItem[];
}

interface MarketSlotData {
  notice: string;
  egress: EgressState;
  findings: MarketFinding[];
}

// ------------------------------------------------------------- screen state
//
// A module-level store, subscribed to with useSyncExternalStore. It outlives
// the component, which is the point: App.tsx unmounts this screen on every
// view switch.
//
// THE OPTIONS, and why this one. Lifting to App: App owns the view switch, not
// one screen's results, and it is out of scope here anyway. sessionStorage:
// survives a page reload - but the bearer token deliberately does not (see
// api/client.ts), so a reload signs the reader out BY DESIGN while the results
// of the signed-out session would still be sitting on disk under a signed-in
// key for the next person to open the tab. That is a leak, so no. A module
// store lives exactly as long as the page: a view switch keeps it, the reload
// that signs the reader out destroys it with everything else, and it can be
// cleared here the moment the client's token is gone.
//
// SIGN-OUT. `onSignedOut` in api/client.ts is a single slot, and App.tsx holds
// it - that is how a 401 becomes the login screen. Registering here would
// REPLACE App's handler, not add to it. And App's own Log out button never
// goes through that hook at all: it calls setToken(null) directly. Both paths
// end the same way, `isSignedIn()` flips to false, so that is what the store
// watches: at every mount, before every write, and once a second while it
// holds anything written under a signed-in client. Under auth_mode=disabled
// nothing is ever signed in and nothing is ever cleared, which is right -
// there is no session to leak across.
//
// The run itself belongs to the store too, not to the component. A response
// arriving while the reader is on Documents lands here and is on screen when
// they come back.

interface ScreenState {
  question: string;
  comparisonType: ComparisonType | "";
  mode: AnalysisMode;
  toggles: AnalysisToggles;
  baselineDocumentId: string | null;
  baselineRefusal: string | null;
  selected: string | null;
  /** The "Search in" ticks. Empty means no filter - the same thing the
   *  backend means by an empty `scope`, and the reason `runAnalysis` sends no
   *  `scope` key at all when this is empty (see there). */
  selectedTypes: string[];
  /** The server's echo from the last run, or null before the first run under
   *  the CURRENT ticks. Cleared the moment the ticks change (see
   *  `setSelectedTypes`), so a reader who reticks after a run sees the pending
   *  notice, never the previous run's stale count. */
  appliedScope: AppliedScope | null;
  summarySlot: Slot<SummarySlotData>;
  gapsSlot: Slot<GapsSlotData>;
  recSlot: Slot<RecommendationSlotData>;
  marketSlot: Slot<MarketSlotData>;
  /** `Date.now()` when the run in flight began; null when nothing is running.
   *  The elapsed counter is derived from this, so it is real time - it is
   *  right even after an unmount and remount mid-run. */
  runStartedAt: number | null;
  /** Whether this was written under a signed-in client. Every write first
   *  checks that a held store is still signed in (see `patch`), so a slot
   *  written by the very response that carried the 401 never lands. */
  heldForSession: boolean;
}

function freshState(): ScreenState {
  return {
    question: "",
    comparisonType: "",
    mode: "focused",
    toggles: { gaps: false, market: false, recommendation: false },
    baselineDocumentId: null,
    baselineRefusal: null,
    selected: null,
    selectedTypes: [],
    appliedScope: null,
    summarySlot: { s: "idle" },
    gapsSlot: { s: "idle" },
    recSlot: { s: "idle" },
    marketSlot: { s: "idle" },
    runStartedAt: null,
    heldForSession: false,
  };
}

let state: ScreenState = freshState();
const listeners = new Set<() => void>();
// Request ownership. Taken synchronously before the awaits, re-read after
// them. Bumped on every run, every mode or toggle change, and every reset, so
// a summary still in flight when the reader switches to Quote - or signs out -
// cannot land under the claim table.
let ticket = 0;
let signOutWatch: ReturnType<typeof setInterval> | null = null;

export function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function getSnapshot() {
  return state;
}

function emit() {
  for (const fn of listeners) fn();
}

/** Forget everything: question, mode, sections, results and any run in flight.
 *  Called when the client's session has ended; exported so a test can start
 *  from nothing. */
export function resetAnalysisScreen() {
  ticket += 1;
  state = freshState();
  if (signOutWatch !== null) {
    clearInterval(signOutWatch);
    signOutWatch = null;
  }
  emit();
}

/** The one sign-out rule: results written under a signed-in client do not
 *  survive that client being signed out. Returns true when it fired. */
export function clearIfSignedOut(): boolean {
  if (state.heldForSession && !isSignedIn()) {
    resetAnalysisScreen();
    return true;
  }
  return false;
}

function watchSignOut() {
  if (signOutWatch !== null) return;
  signOutWatch = setInterval(clearIfSignedOut, 1000);
}

/** Every write goes through here. A write attempted after sign-out is dropped
 *  on the floor - there is nobody it belongs to any more. */
export function patch(p: Partial<ScreenState>) {
  if (clearIfSignedOut()) return;
  state = { ...state, ...p, heldForSession: isSignedIn() };
  if (state.heldForSession) watchSignOut();
  emit();
}

function supersede() {
  ticket += 1;
  patch({
    runStartedAt: null,
    summarySlot: { s: "idle" },
    gapsSlot: { s: "idle" },
    recSlot: { s: "idle" },
    marketSlot: { s: "idle" },
    selected: null,
    baselineRefusal: null,
    // A mode or toggle change discards the results the count described, so
    // the count goes with them rather than surviving under a run that has not
    // happened yet.
    appliedScope: null,
  });
}

export function setQuestion(question: string) {
  patch({ question });
}

export function changeMode(mode: AnalysisMode) {
  patch({ mode });
  supersede();
}

export function changeToggle(k: keyof AnalysisToggles, v: boolean) {
  patch({ toggles: { ...state.toggles, [k]: v } });
  supersede();
}

export function setSelected(selected: string | null) {
  patch({ selected });
}

/** Changing the ticks invalidates the last run's count immediately - not on
 *  the next run. `appliedScope` describes what a PAST response searched, and
 *  the moment the ticks move it no longer describes what a fresh run would
 *  do. Clearing it here is what makes `pendingFilterNotice` show instead of a
 *  now-stale "N documents in scope" line. */
export function setSelectedTypes(types: string[]) {
  patch({ selectedTypes: types, appliedScope: null });
}

export function toggleType(type: string) {
  const next = state.selectedTypes.includes(type)
    ? state.selectedTypes.filter((t) => t !== type)
    : [...state.selectedTypes, type];
  setSelectedTypes(next);
}

export function clearTypes() {
  setSelectedTypes([]);
}

/**
 * `applied_scope` on the three analysis responses. `contracts/types.ts` does
 * not (yet) declare this field on `AnalysisSummaryResult`,
 * `AnalysisGapsResult` or `AnalysisRecommendationResult` even though the
 * backend routes echo it - see the note left in this screen's report. Read
 * defensively rather than widening those interfaces here: they are not this
 * screen's file to edit.
 */
/** Every response that carries a scope echo updates the SAME field, because
 *  every request was sent the SAME scope (see `runAnalysis`). A response with
 *  no `applied_scope` at all - the field missing from the contract, or a
 *  build that predates it - leaves the count exactly where RULE 3 wants an
 *  unknown count: absent. Read via `unknown` rather than widening the
 *  response interfaces (`contracts/types.ts` is not this screen's file). */
function applyServerScope(d: unknown): void {
  if (d === null || typeof d !== "object" || !("applied_scope" in d)) return;
  const scope = (d as { applied_scope?: AppliedScope | null }).applied_scope;
  if (scope) patch({ appliedScope: scope });
}

/** Run the selected engines for the current question. Exported so the
 *  one-run-at-a-time guard can be tested without a button in front of it. */
export async function runAnalysis(overrideBaseline?: string | null): Promise<void> {
  if (clearIfSignedOut()) return;
  const asked = state.question.trim();
  if (asked === "") return;
  // One run at a time. The button is disabled while this is non-null, and this
  // guard is for every other way in: retry, baseline nomination, a keyboard
  // activation that beat the re-render.
  if (state.runStartedAt !== null) return;

  const mine = ticket + 1;
  ticket = mine;
  const mineStill = () => ticket === mine;

  const { mode, toggles } = state;
  const baseline = overrideBaseline === undefined ? state.baselineDocumentId : overrideBaseline;
  const engines = enginesFor(mode, toggles);
  // The wider set is the only thing "comprehensive" can honestly mean in
  // this build; the batch-by-batch run it describes is not implemented and
  // the screen says so rather than pretending.
  const limit = mode === "comprehensive" ? 24 : 8;
  // NO `scope` KEY WHEN NOTHING IS TICKED. Not `scope: null` - an absent key,
  // so a caller who ticks nothing sends a body byte-for-byte identical to the
  // one this screen sent before the type filter existed. The SAME scope goes
  // to every engine that runs below: two panels on one screen answering about
  // different slices of the corpus is the defect the backend's shared
  // narrowing function exists to prevent, and building three different bodies
  // here would undo that from the frontend.
  const scope: ClassificationScope | null =
    state.selectedTypes.length > 0 ? { types: state.selectedTypes } : null;
  const body = scope
    ? { question: asked, limit, baseline_document_id: baseline, comparison_type: state.comparisonType || null, scope }
    : { question: asked, limit, baseline_document_id: baseline, comparison_type: state.comparisonType || null };

  patch({
    selected: null,
    runStartedAt: Date.now(),
    summarySlot: engines.summary ? { s: "loading" } : { s: "off" },
    gapsSlot: engines.gaps ? { s: "loading" } : { s: "off" },
    recSlot: engines.recommendation ? { s: "loading" } : { s: "off" },
    marketSlot: engines.market ? { s: "loading" } : { s: "off" },
  });

  const jobs: Promise<void>[] = [];

  // THE RECOMMENDATION WAITS FOR THE SUMMARY. `/api/analysis/recommendations`
  // synthesises its own summary before advising, so firing it alongside
  // `/api/analysis/summary` asked the one CPU-bound model for two syntheses at
  // once. The second regularly came back with no cited sentence, and the card
  // then said "the document layer produced no cited sentence" directly under
  // a Summary panel full of citations - one screen, two contradictory
  // answers to the same question. Sequencing removes the contention; the
  // proper fix (reuse the summary's findings server-side) is tracked.
  let summaryJob: Promise<void> = Promise.resolve();

  if (engines.summary) {
    summaryJob = analysisApi.summary(body).then((r) => {
        if (!mineStill()) return;
        if (r.ok) applyServerScope(r.data);
        patch({
          summarySlot: slotFrom(r, (d) => {
            const located = locate(d.evidence_ledger);
            const findings = citedFindings(d.documented_findings, located);
            const prose = citedSummary(d);
            const refusal = str(d.refusal);
            // Both halves are normalised to strings HERE so the renderer never
            // has to guess. An entry whose `sentence` is missing or empty is
            // still a removal the API reported: it stays in the count and is
            // named as text-not-returned below, never rendered as a bullet
            // with nothing in it.
            const dropped = (Array.isArray(d.dropped_sentences) ? d.dropped_sentences : [])
              .filter((s) => s !== null && typeof s === "object")
              .map((s) => ({
                sentence: typeof s.sentence === "string" ? s.sentence : "",
                reason: typeof s.reason === "string" ? s.reason : "",
              }));
            if (prose === null && findings.length === 0 && refusal === null) return null;
            return {
              result: toAnalysisResult(d, prose, findings),
              refusal,
              dropped,
              ledger: Array.isArray(d.evidence_ledger) ? d.evidence_ledger : [],
            };
          }),
        });
      });
    jobs.push(summaryJob);
  }

  if (engines.gaps) {
    jobs.push(
      analysisApi.gaps(body).then((r) => {
        if (!mineStill()) return;
        if (r.ok) applyServerScope(r.data);
        patch({
          gapsSlot: slotFrom(r, (d: AnalysisGapsResult) => {
            const located = locate(d.evidence_ledger);
            const clusters = toClaimClusters(d.claim_clusters, located);
            const items = toGapItems(d.gaps?.items, located);
            if (clusters.length === 0 && items.length === 0) return null;
            return {
              clusters,
              gaps: toGapAnalysis(d.gaps, items),
              ledger: Array.isArray(d.evidence_ledger) ? d.evidence_ledger : [],
            };
          }),
        });
      }),
    );
  }

  if (engines.recommendation) {
    jobs.push(
      summaryJob.then(() => analysisApi.recommendations(body)).then((r) => {
        if (!mineStill()) return;
        if (r.ok) applyServerScope(r.data);
        patch({
          recSlot: slotFrom(r, (d) => {
            const located = locate(d.evidence_ledger);
            const rec = toRecommendation(d.recommendation, located);
            const findings = rec === null ? [] : onlySamples(d.public_market_findings);
            const refusal = typeof d.recommendation_refusal === "string" && d.recommendation_refusal.trim() !== ""
              ? d.recommendation_refusal : null;
            if (rec === null && findings.length === 0 && refusal === null) return null;
            return {
              recommendation: rec,
              refusal,
              findings,
              ledger: Array.isArray(d.evidence_ledger) ? d.evidence_ledger : [],
            };
          }),
        });
      }),
    );
  }

  if (engines.market) {
    jobs.push(
      marketApi.findings().then((r) => {
        if (!mineStill()) return;
        patch({
          marketSlot: slotFrom(r, (d) => {
            const findings = onlySamples(d.findings);
            if (findings.length === 0) return null;
            return {
              notice: typeof d.notice === "string" ? d.notice : "",
              egress: d.egress,
              findings,
            };
          }),
        });
      }),
    );
  }

  await Promise.all(jobs);
  if (mineStill()) patch({ runStartedAt: null });
}

export function nominateBaseline(b: BaselineSelection) {
  if (b.kind === "stated_requirement" || b.document_id === null) {
    // The gaps route accepts `baseline_document_id` and nothing else. A
    // typed requirement would have to be dropped on the floor, and a form
    // that silently discards what was typed into it is worse than one that
    // says it cannot take it.
    patch({
      baselineRefusal:
        "This build's gap route takes a baseline DOCUMENT only. A stated requirement " +
        "cannot be sent, so nothing was run - the requirement you typed has not been used.",
    });
    return;
  }
  patch({ baselineRefusal: null, baselineDocumentId: b.document_id });
  void runAnalysis(b.document_id);
}

/** Which engines have not answered yet. Not a stage - the analysis routes
 *  report none - but a fact the client holds: it sent these requests and has
 *  not had the responses. */
export function stillWaitingOn(s: ScreenState): string[] {
  const out: string[] = [];
  if (s.summarySlot.s === "loading") out.push("Summary");
  if (s.recSlot.s === "loading") out.push("AI recommendation");
  if (s.gapsSlot.s === "loading") out.push("Gap analysis");
  if (s.marketSlot.s === "loading") out.push("Public market sample");
  return out;
}

