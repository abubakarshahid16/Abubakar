/**
 * The Analysis screen: pick a mode, run the engine that mode means, render the
 * result with the cards that already exist.
 *
 * WHAT A "MODE" MAPS TO. `ModeSelector` speaks in quote / focused /
 * comprehensive plus three optional sections; the API speaks in three routes.
 * The mapping is not arbitrary - it is the one the selector's own copy already
 * promises:
 *
 *   quote          -> POST /api/analysis/gaps   ("No model involved.")
 *   focused        -> POST /api/analysis/summary
 *   comprehensive  -> POST /api/analysis/summary, wider passage set
 *   + Gap analysis toggle           -> POST /api/analysis/gaps
 *   + Generate recommendation       -> POST /api/analysis/recommendations
 *   + Public market sample          -> GET  /api/market/findings
 *
 * `gaps` is the only engine that needs no model, which is exactly what Quote
 * mode says it is. Running the three engines as separate requests is
 * deliberate: an unreachable Ollama takes out the summary and the
 * recommendation and leaves the mechanical comparison working, and each
 * failure is reported where it happened rather than collapsed into one.
 *
 * FOUR STATES, NEVER THREE. loading, backend-offline, request-failed and
 * empty-result are four different facts and get four different renderings -
 * `Spinner`, `DisconnectedState` (amber, "the backend is not running"),
 * `ErrorState` (red, the error's own words) and `EmptyState`. Collapsing
 * offline into failed is the defect this screen was written after: an operator
 * who reads "that request failed" goes looking at the request.
 *
 * REQUEST OWNERSHIP. Same approach as ChatView (0e77809): a ticket taken
 * synchronously before the awaits and re-read after them. A response whose
 * ticket has been superseded is DROPPED, not merged - a summary rendered under
 * a mode the reader has since left is worse than no summary at all.
 *
 * WHAT THIS SCREEN WILL NOT RENDER, and why the guards are here rather than in
 * the cards:
 *  1. `complete: true`. Completeness is `false` or `null`. A true would be a
 *     claim that the corpus was exhausted, which nothing can know.
 *  2. A confidence word other than "low" or "medium". "high" is structurally
 *     unreachable; a backend that sent one would otherwise be printed verbatim
 *     by RecommendationCard, which renders the word it is given.
 *  3. A null as a zero, a dash or an "N/A". An absent value is absent.
 *  4. An uncited sentence. Every claim that reaches a card carries an
 *     evidence id that resolves to a document id AND a page number in the
 *     ledger that came back with it. A finding citing nothing, a claim row
 *     with no page, generated prose whose markers point at no supplied source:
 *     none of them are renderable, and they are dropped here rather than shown
 *     with a warning beside them - the sentence would still be on screen.
 *  5. A market row that does not say `is_sample: true`. This build has no
 *     provider, so a row claiming to be a real finding is a row this screen
 *     has no honest way to draw. MarketPanel tags every row it is given; this
 *     screen makes sure it is only ever given taggable ones.
 *
 * WHAT IS NOT HERE. `CoverageLedger` is not rendered. None of the three routes
 * returns a coverage object, and the ledger's header line begins with
 * "N authorized" - a number this screen would have to invent. The omission is
 * named on screen instead, alongside the `not_implemented_sections` the API
 * itself reports.
 *
 * WHERE THE STATE LIVES, and why it is not useState. App.tsx renders
 * `{view === "analysis" && <AnalysisModeScreen />}`, so opening Documents
 * UNMOUNTS this screen and React state dies with it - a run in flight was
 * lost the moment a reader went to check a document. The question, mode,
 * sections, the run in flight and its result therefore live in a module-level
 * store (below, "screen state") that the component subscribes to. See that
 * section for the alternatives that were weighed and for what happens on
 * sign-out.
 *
 * ONE RUN AT A TIME. How long a run takes is not known in advance and is not
 * claimed anywhere on this screen - only the elapsed seconds are shown, which
 * are measured, not estimated. The button used to stay live throughout: a
 * second click meant two concurrent model generations on a machine with memory
 * for one. While a run is in flight the button is
 * disabled and `aria-busy`, and the screen shows the seconds elapsed since the
 * run's REAL start timestamp - the same pattern ChatView/LocalWork use for
 * chat. Unlike chat, the analysis routes accept no `progress_id` and report no
 * stage, so none is shown: what IS shown is which engines have not yet
 * answered, which the client knows for a fact because it sent the requests.
 */
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import {
  analysis as analysisApi,
  isSignedIn,
  market as marketApi,
  reviews as reviewsApi,
  type AppliedScope,
  type ClassificationScope,
  type Result,
} from "../api/client";
import { ClaimTable } from "../components/analysis/ClaimTable";
import { GapAnalysisCard } from "../components/analysis/GapAnalysisCard";
import { MarketPanel } from "../components/analysis/MarketPanel";
import {
  ModeSelector,
  type AnalysisMode,
  type AnalysisToggles,
} from "../components/analysis/ModeSelector";
import { RecommendationCard } from "../components/analysis/RecommendationCard";
import { ReviewWorkflowPanel } from "../components/analysis/ReviewWorkflowPanel";
import { SummaryCard } from "../components/analysis/SummaryCard";
import { DisconnectedState, EmptyState, ErrorState, Spinner } from "../components/states";
import {
  TypeFilter,
  pendingFilterNotice,
  useTypeVocabulary,
} from "../components/classification/TypeFilter";
import type {
  AnalysisGapsResult,
  AnalysisRecommendationResult,
  AnalysisSummaryResult,
  ApiError,
  EgressState,
  EvidenceItem,
  MarketFinding,
  ReviewFindingCreate,
  ReviewFinding,
  ReviewTemplate,
  ComparisonType,
} from "../types/api";
import type {
  AnalysisResult,
  BaselineSelection,
  ClaimCluster,
  ClaimRow,
  DocumentedFinding,
  GapAnalysis,
  GapItem,
  PublicMarketQuery,
  Recommendation,
} from "../types/analysis";

// --------------------------------------------------------------- slot state
//
// One per engine, because the engines fail independently and a reader must be
// able to see WHICH one failed and HOW.

export type Slot<T> =
  | { s: "off" }
  | { s: "idle" }
  | { s: "loading" }
  | { s: "offline" }
  | { s: "failed"; error: ApiError }
  | { s: "empty" }
  | { s: "ready"; data: T };

/**
 * A typed result becomes a slot. The two `!r.ok` branches are the whole point
 * of the exercise: `disconnected` is a dead backend and gets the amber banner,
 * anything else is a request that was served and refused and gets the red card.
 *
 * `adapt` returning null means "served, and there is nothing renderable in it" -
 * an empty result, which is a fact about the corpus and not a failure.
 */
export function slotFrom<A, B>(r: Result<A>, adapt: (a: A) => B | null): Slot<B> {
  if (!r.ok) {
    return r.disconnected ? { s: "offline" } : { s: "failed", error: r.error };
  }
  const data = adapt(r.data);
  return data === null ? { s: "empty" } : { s: "ready", data };
}

// --------------------------------------------------------------- the guards

/** RULE 2. Anything that is not "low" or "medium" is not a confidence word.
 *  A "high" arriving over the wire becomes null - not assessed - because there
 *  is no calibration behind any word this system could issue, and "high" would
 *  be the one a reader acts on. */
export function confidenceWord(raw: unknown): "low" | "medium" | null {
  return raw === "low" || raw === "medium" ? raw : null;
}

/** RULE 1. `complete` is false or null. A true is discarded rather than
 *  rendered: there is no way to know a corpus was exhausted, so the value
 *  cannot mean what it says. */
export function completeness(raw: unknown): false | null {
  return raw === false ? false : null;
}

/** RULE 5. A row that does not declare itself a sample cannot be drawn: this
 *  build has no provider and no verified-source rendering, so there is no
 *  honest shape for it on screen. */
export function onlySamples(findings: readonly MarketFinding[] | undefined): MarketFinding[] {
  if (!Array.isArray(findings)) return [];
  return findings.filter(
    (f) => f !== null && typeof f === "object" && (f as MarketFinding).is_sample === true,
  );
}

/** Where a citation lands: a document and a page, or nothing. RULE 4 is
 *  enforced against this map - an evidence id that is not in it cites nothing
 *  the reader can open. */
export function locate(ledger: readonly EvidenceItem[] | undefined): Map<string, EvidenceItem> {
  const m = new Map<string, EvidenceItem>();
  if (!Array.isArray(ledger)) return m;
  for (const e of ledger) {
    if (
      e !== null &&
      typeof e === "object" &&
      typeof e.evidence_id === "string" &&
      typeof e.document_id === "string" &&
      e.document_id !== "" &&
      Number.isFinite(e.page_start)
    ) {
      m.set(e.evidence_id, e);
    }
  }
  return m;
}

/** RULE 4, for the documented findings. A finding citing nothing, or citing an
 *  id that resolves to no document and page, is DROPPED. It is not rendered
 *  with a caveat: the claim would still be on screen and the reader takes the
 *  claim. */
export function citedFindings(
  findings: readonly { claim: string; citation_ids: string[]; text_source: string }[] | undefined,
  located: Map<string, EvidenceItem>,
): DocumentedFinding[] {
  if (!Array.isArray(findings)) return [];
  const out: DocumentedFinding[] = [];
  for (const f of findings) {
    if (f === null || typeof f !== "object") continue;
    const ids: string[] = Array.isArray(f.citation_ids) ? f.citation_ids : [];
    if (ids.length === 0) continue;
    if (!ids.every((id: string) => located.has(id))) continue;
    // `claim`, not `text`: the API emits DocumentedFinding.claim, and this
    // helper used to rename a key the API never sent.
    if (typeof f.claim !== "string" || f.claim.trim() === "") continue;
    const source = f.text_source;
    out.push({
      claim: f.claim,
      citation_ids: ids,
      // There is no user-stated finding path in this build; every finding here
      // came out of a document. Saying otherwise would relabel evidence.
      source_kind: "document",
      text_source:
        source === "recognised" || source === "mixed" || source === "extracted"
          ? source
          : "extracted",
    });
  }
  return out;
}

function str(v: unknown): string | null {
  return typeof v === "string" && v !== "" ? v : null;
}

/** RULE 3 and RULE 4, for one claim row. `normalized_value` survives only as a
 *  number; an unparseable one becomes null, never 0 - 0 is a real measurement
 *  and would read as one. A row with no evidence id, no filename or no page is
 *  not a citation and does not come back. */
export function toClaimRow(raw: Record<string, unknown>, located: Map<string, EvidenceItem>): ClaimRow | null {
  if (raw === null || typeof raw !== "object") return null;
  const evidenceId = str(raw.evidence_id);
  const filename = str(raw.filename);
  const span = str(raw.exact_span);
  const page = raw.page_start;
  if (evidenceId === null || filename === null || span === null) return null;
  if (typeof page !== "number" || !Number.isFinite(page)) return null;
  if (!located.has(evidenceId)) return null;
  return {
    evidence_id: evidenceId,
    filename,
    page_start: page,
    section: str(raw.section),
    exact_span: span,
    raw_value: str(raw.raw_value),
    raw_unit: str(raw.raw_unit),
    normalized_value: typeof raw.normalized_value === "number" ? raw.normalized_value : null,
    normalized_unit: str(raw.normalized_unit),
  };
}

const CLAIM_LABELS = new Set(["agreement", "addition", "possible_conflict", "unresolved"]);

/**
 * `facet` is `list[str]` in the contract and a joined string in what claims.py
 * actually builds (`_facet_string` returns a str). Both are read here rather
 * than one being guessed, so this screen renders whichever the backend settles
 * on instead of printing "f, l, o, w" the day it changes.
 */
export function toClaimClusters(
  clusters: readonly { facet: unknown; label: unknown; rows: Record<string, unknown>[] }[] | undefined,
  located: Map<string, EvidenceItem>,
): ClaimCluster[] {
  if (!Array.isArray(clusters)) return [];
  const out: ClaimCluster[] = [];
  for (const c of clusters) {
    if (c === null || typeof c !== "object") continue;
    if (!CLAIM_LABELS.has(c.label as string)) continue;
    const facet = Array.isArray(c.facet)
      ? (c.facet as unknown[]).filter((f): f is string => typeof f === "string").join(" · ")
      : (str(c.facet) ?? "");
    const rawRows: Record<string, unknown>[] = Array.isArray(c.rows) ? c.rows : [];
    // Retrieval can hand back the same passage twice - overlapping chunks, or
    // one chunk per page where a sentence or a running heading crosses the page
    // break - and the table then shows one piece of evidence as two rows a
    // reader cannot tell apart. The key WAS (document, page, words), which let
    // byte-identical text on p.267 and p.268 of the same file through as two
    // rows; the page is now out of the key, so identical words from the same
    // document are one row. The FIRST occurrence survives, with its own page.
    //
    // What is deliberately NOT collapsed:
    //  - identical words in DIFFERENT documents stay two rows. Two documents
    //    saying the same thing is the finding a comparison exists to report,
    //    and merging it would delete it.
    //  - near-identical is not identical. The words are compared as sent -
    //    byte for byte, no trimming, no case folding, no whitespace or
    //    punctuation normalisation - so one differing character is two rows.
    //  - the key is per cluster, as before: the same passage cited under two
    //    facets is two comparisons, not one duplicated row.
    const rows: ClaimRow[] = [];
    const seenRows = new Set<string>();
    for (const r of rawRows) {
      const row = toClaimRow(r, located);
      if (row === null) continue;
      const key = JSON.stringify([row.filename, row.exact_span]);
      if (seenRows.has(key)) continue;
      seenRows.add(key);
      rows.push(row);
    }
    // A cluster whose every row was uncitable is not a comparison; it is an
    // empty box with a heading, and rule 3 says an absent thing is absent.
    if (rows.length === 0) continue;
    out.push({ facet: facet === "" ? "(unnamed)" : facet, label: c.label as ClaimCluster["label"], rows });
  }
  return out;
}

const GAP_STATUSES = new Set([
  "met",
  "possible_gap",
  "conflict",
  "insufficient_evidence",
  "not_applicable",
]);

/** RULE 4, for the gap items. A quoted baseline span with no citation behind it
 *  is an uncited claim in a serif quote block, which is the most convincing
 *  shape an uncited claim can take. Dropped. */
export function toGapItems(
  items: readonly unknown[] | undefined,
  located: Map<string, EvidenceItem>,
): GapItem[] {
  if (!Array.isArray(items)) return [];
  const out: GapItem[] = [];
  for (const raw of items) {
    if (raw === null || typeof raw !== "object") continue;
    const it = raw as Record<string, unknown>;
    if (!GAP_STATUSES.has(it.status as string)) continue;
    const facet = str(it.facet);
    if (facet === null) continue;
    const span = typeof it.baseline_span === "string" ? it.baseline_span : "";
    const citation = str(it.baseline_citation_id);
    if (span !== "" && (citation === null || !located.has(citation))) continue;
    const projectIds = (Array.isArray(it.project_citation_ids) ? it.project_citation_ids : [])
      .filter((id): id is string => typeof id === "string" && located.has(id));
    // Nothing to show and nothing to compare against.
    if (span === "" && projectIds.length === 0) continue;
    out.push({
      facet,
      status: it.status as GapItem["status"],
      baseline_citation_id: citation,
      baseline_span: span,
      project_citation_ids: projectIds,
      note: str(it.note),
    });
  }
  return out;
}

/**
 * The API's applicability vocabulary is not the card's.
 *
 * `analysis.py` returns `not_applicable` for exactly one reason: the caller
 * named no baseline. The card's `not_applicable` means something else - "the
 * question contains no comparison" - and offers no way out of it. The card's
 * `insufficient_baseline` is the state the backend is actually describing, and
 * it carries the nomination form. Mapping to it is what makes the screen
 * usable; leaving it alone would show a dead end.
 */
export function toGapAnalysis(
  gaps: { applicability?: unknown; baseline?: unknown } | undefined,
  items: GapItem[],
): GapAnalysis {
  const applicability = gaps?.applicability === "applicable" ? "applicable" : "insufficient_baseline";
  const b = gaps?.baseline as Record<string, unknown> | null | undefined;
  let baseline: BaselineSelection | null = null;
  if (b !== null && b !== undefined && typeof b === "object") {
    const kind = b.kind;
    if (kind === "document" || kind === "document_section" || kind === "stated_requirement") {
      baseline = {
        kind,
        document_id: str(b.document_id),
        section: str(b.section),
        text: str(b.text),
      };
    }
  }
  return { applicability, baseline, items };
}

/** RULE 4, for generated prose. `[S1]` resolves positionally against
 *  `summary_cited_evidence_ids`; with that list empty every marker is dead and
 *  the whole passage cites nothing. It is not rendered. */
export function citedSummary(r: AnalysisSummaryResult): string | null {
  const ids = Array.isArray(r.summary_cited_evidence_ids) ? r.summary_cited_evidence_ids : [];
  if (typeof r.summary !== "string" || r.summary.trim() === "") return null;
  if (ids.length === 0) return null;
  return r.summary;
}

/** RULE 2 and RULE 4 together. A recommendation citing nothing is advisory
 *  prose with no evidence under it, and there is no shape for that on a screen
 *  whose whole claim is that everything is cited. */
export function toRecommendation(
  raw: AnalysisRecommendationResult["recommendation"],
  located: Map<string, EvidenceItem>,
): Recommendation | null {
  if (raw === null || raw === undefined || typeof raw !== "object") return null;
  if (typeof raw.text !== "string" || raw.text.trim() === "") return null;
  const ids = (Array.isArray(raw.citation_ids) ? raw.citation_ids : []).filter(
    (id): id is string => typeof id === "string" && located.has(id),
  );
  if (ids.length === 0) return null;
  const checks = (Array.isArray(raw.checks) ? raw.checks : [])
    .filter((c) => c !== null && typeof c === "object" && typeof c.label === "string")
    .map((c) => ({ label: c.label, fired: c.fired === true }));
  return {
    text: raw.text,
    citation_ids: ids,
    basis: raw.basis === "documents_and_public_market" ? "documents_and_public_market" : "documents_only",
    confidence: confidenceWord(raw.confidence),
    checks,
    requires_engineer_approval: true,
  };
}

/**
 * SummaryCard takes the whole `AnalysisResult`. The three routes return a
 * fraction of it, so the rest is filled with what is true: nothing measured.
 * Every count is null rather than 0, and `complete` goes through
 * `completeness()` so a true can never reach a card.
 */
export function toAnalysisResult(
  r: AnalysisSummaryResult,
  summary: string | null,
  findings: DocumentedFinding[],
): AnalysisResult {
  return {
    analysis_id: "",
    question: typeof r.question === "string" ? r.question : "",
    run_status: "complete",
    status: summary === null && findings.length === 0 ? "insufficient_evidence" : "answered",
    coverage: {
      authorized_documents_selected: 0,
      documents_attempted: null,
      documents_search_completed: null,
      relevant_documents: null,
      no_sufficient_evidence_documents: null,
      failed_documents: null,
      not_searchable_documents: null,
      complete: completeness(undefined),
    },
    documents: [],
    evidence_ledger: [],
    documented_findings: findings,
    summary,
    summary_truncated: r.summary_truncated === true,
    summary_cited_evidence_ids: Array.isArray(r.summary_cited_evidence_ids)
      ? r.summary_cited_evidence_ids
      : [],
    claim_clusters: [],
    gaps: { applicability: "not_applicable", baseline: null, items: [] },
    public_market_findings: [],
    recommendation: null,
    assumptions: [],
    limitations: [],
    not_implemented_sections: Array.isArray(r.not_implemented_sections)
      ? r.not_implemented_sections
      : [],
    batches_done: null,
    batches_total: null,
    seconds: null,
  };
}

/** Which routes a mode means. Quote runs the one engine that needs no model,
 *  which is what its own description promises. */
export function enginesFor(mode: AnalysisMode, toggles: AnalysisToggles) {
  const quote = mode === "quote";
  return {
    summary: !quote,
    gaps: quote || toggles.gaps,
    recommendation: !quote && toggles.recommendation,
    market: !quote && toggles.market,
  };
}

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

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

function getSnapshot() {
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
function clearIfSignedOut(): boolean {
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
function patch(p: Partial<ScreenState>) {
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

function setQuestion(question: string) {
  patch({ question });
}

function changeMode(mode: AnalysisMode) {
  patch({ mode });
  supersede();
}

function changeToggle(k: keyof AnalysisToggles, v: boolean) {
  patch({ toggles: { ...state.toggles, [k]: v } });
  supersede();
}

function setSelected(selected: string | null) {
  patch({ selected });
}

/** Changing the ticks invalidates the last run's count immediately - not on
 *  the next run. `appliedScope` describes what a PAST response searched, and
 *  the moment the ticks move it no longer describes what a fresh run would
 *  do. Clearing it here is what makes `pendingFilterNotice` show instead of a
 *  now-stale "N documents in scope" line. */
function setSelectedTypes(types: string[]) {
  patch({ selectedTypes: types, appliedScope: null });
}

function toggleType(type: string) {
  const next = state.selectedTypes.includes(type)
    ? state.selectedTypes.filter((t) => t !== type)
    : [...state.selectedTypes, type];
  setSelectedTypes(next);
}

function clearTypes() {
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

function nominateBaseline(b: BaselineSelection) {
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
function stillWaitingOn(s: ScreenState): string[] {
  const out: string[] = [];
  if (s.summarySlot.s === "loading") out.push("Summary");
  if (s.recSlot.s === "loading") out.push("AI recommendation");
  if (s.gapsSlot.s === "loading") out.push("Gap analysis");
  if (s.marketSlot.s === "loading") out.push("Public market sample");
  return out;
}

function Section({
  title,
  eyebrow,
  children,
}: {
  title: string;
  eyebrow?: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-label={title} className="space-y-2">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h2 className="text-sm font-semibold text-slateish-100">{title}</h2>
        {eyebrow && (
          <span className="text-[11px] uppercase tracking-wide text-slateish-500">
            {eyebrow}
          </span>
        )}
      </div>
      {children}
    </section>
  );
}

function RunChip({ active, children }: { active: boolean; children: React.ReactNode }) {
  return (
    <span
      className={[
        "inline-flex items-center gap-1.5 rounded-[var(--radius-xs)] border px-2 py-1 text-xs",
        active
          ? "border-signal-500/50 bg-signal-500/10 text-signal-300"
          : "border-ink-600 bg-ink-850 text-slateish-500",
      ].join(" ")}
    >
      {children}
      <span className="font-mono text-[10px] uppercase tracking-wide">
        {active ? "On" : "Off"}
      </span>
    </span>
  );
}

function RunPlan({
  mode,
  engines,
}: {
  mode: AnalysisMode;
  engines: ReturnType<typeof enginesFor>;
}) {
  const modeText =
    mode === "quote"
      ? "Quote: mechanical evidence comparison"
      : mode === "focused"
        ? "Focused: generated synthesis over top passages"
        : "Comprehensive: wider synthesis request";
  return (
    <section
      aria-label="Selected analysis work"
      className="card-3d surface-card rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-slateish-400">
          Selected work
        </p>
        <span className="text-xs text-slateish-500">{modeText}</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {engines.summary && <RunChip active>Summary</RunChip>}
        {engines.recommendation && <RunChip active>AI recommendation</RunChip>}
        {engines.gaps && <RunChip active>Gap analysis</RunChip>}
        {engines.market && <RunChip active>Public market sample</RunChip>}
        {!engines.summary && !engines.recommendation && !engines.market && (
          <RunChip active={false}>Summary, recommendation and market</RunChip>
        )}
      </div>
      <p className="mt-2 text-xs text-slateish-400">
        Recommendation, gaps and public evidence stay separate. Review and approval by a
        qualified engineer is required.
      </p>
    </section>
  );
}

/**
 * Whether a slot has anything to put under a heading.
 *
 * `Section` draws an `<h2>` unconditionally; `SlotBody` returns null for `off`
 * and `idle`. Together they drew a heading over nothing, and the place it hurt
 * was Quote mode: Quote turns the summary, recommendation and market engines
 * OFF, so the only section it keeps is Gap analysis - and before a run that
 * section was a bare "Gap analysis / baseline-controlled" header with empty
 * space beneath it, sitting under "Nothing has been run yet". A reader who
 * selected Quote saw a heading, no content, and concluded Quote does nothing.
 *
 * A heading is a promise that something is under it. This is the guard that
 * keeps the promise: no slot state, no section. It is the same rule the rest of
 * this screen already follows - an absent thing is absent, not an empty box.
 */
export function hasBody<T>(slot: Slot<T>): boolean {
  return slot.s !== "off" && slot.s !== "idle";
}

/**
 * The four states, rendered four ways. `off` is nothing at all - a section the
 * reader did not ask for is absent, not disabled and not empty.
 */
function SlotBody<T>({
  slot,
  loadingLabel,
  emptyTitle,
  emptyHint,
  onRetry,
  children,
}: {
  slot: Slot<T>;
  loadingLabel: string;
  emptyTitle: string;
  emptyHint: string;
  onRetry: () => void;
  children: (data: T) => React.ReactNode;
}) {
  if (slot.s === "off" || slot.s === "idle") return null;
  if (slot.s === "loading") return <Spinner label={loadingLabel} />;
  if (slot.s === "offline") return <DisconnectedState onRetry={onRetry} />;
  if (slot.s === "failed") return <ErrorState error={slot.error} onRetry={onRetry} />;
  if (slot.s === "empty") return <EmptyState title={emptyTitle} hint={emptyHint} />;
  return <>{children(slot.data)}</>;
}

/**
 * What was removed from the generated summary, and why.
 *
 * THE DISCLOSURE IS THE POINT, so it may never be empty. A live run showed
 * "2 sentences were removed from this summary" over two bullets with no text
 * in them: the reader was told something had been hidden and then shown
 * nothing, which is worse than saying nothing at all. An empty bullet is a
 * null rendering as something, which rule 3 forbids.
 *
 * So: a bullet is rendered only for an entry that HAS the removed text. The
 * count in the summary line still counts every removal the API reported - the
 * honest number is the number removed, not the number this screen can show -
 * and any entry whose text did not come back is named in one line as exactly
 * that. No reason is ever invented, and a missing reason renders as nothing
 * rather than as a bare dash.
 */
function DroppedSentences({ dropped }: { dropped: { sentence: string; reason: string }[] }) {
  if (dropped.length === 0) return null;
  const shown = dropped.filter((s) => s.sentence.trim() !== "");
  const withheld = dropped.length - shown.length;
  return (
    <details className="surface-card rounded-[var(--radius-sm)] border border-ink-700 bg-ink-850 px-3 py-2">
      <summary className="cursor-pointer text-xs text-slateish-400">
        {dropped.length} sentence{dropped.length === 1 ? " was" : "s were"} removed from this
        summary
      </summary>
      {shown.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {shown.map((s, i) => (
            <li key={`${i}-${s.sentence.slice(0, 24)}`} className="text-xs text-slateish-400">
              <span className="text-slateish-300">{s.sentence}</span>
              {s.reason.trim() !== "" && (
                <span className="ml-1 text-slateish-500">&mdash; {s.reason}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      {withheld > 0 && (
        <p className="mt-2 text-xs text-slateish-500">
          {withheld === 1
            ? "One of them was reported without the removed text, so it is not shown here."
            : `${withheld} of them were reported without the removed text, so they are not shown here.`}
        </p>
      )}
    </details>
  );
}

/** The passage behind a citation: a document, a page, and the words. Nothing
 *  on this screen cites anything that cannot be shown here. */
function SelectedPassage({ item }: { item: EvidenceItem }) {
  return (
    <section
      aria-label="Selected passage"
      className="card-3d accent-edge relative surface-floating rounded-[var(--radius-md)] border border-signal-500/40 bg-ink-850 p-4"
    >
      <div className="flex flex-wrap items-baseline gap-x-2 text-xs text-slateish-400">
        <span className="font-medium text-slateish-200">{item.filename}</span>
        <span>p.{item.page_start}</span>
        {item.section !== null && <span>&sect; {item.section}</span>}
      </div>
      <blockquote className="document-quote mt-2 whitespace-pre-wrap border-l-2 border-signal-500/60 bg-ink-900 py-2 pl-4 pr-3 text-[14px] text-slateish-100">
        {item.exact_span}
      </blockquote>
    </section>
  );
}

const NOT_RENDERED_HERE =
  "coverage ledger (none of these routes reports a coverage object, and the " +
  "ledger cannot be drawn without inventing the document count it opens with)";

export function AnalysisModeScreen() {
  const questionId = useId();
  const s = useSyncExternalStore(subscribe, getSnapshot);
  const { question, mode, toggles, baselineRefusal, selected, selectedTypes, appliedScope, comparisonType } = s;
  const { summarySlot, gapsSlot, recSlot, marketSlot } = s;
  // RULE 1 (TypeFilter's own doc comment): the vocabulary comes from the
  // register. Null while loading or on failure, in which case the filter
  // renders nothing at all rather than a guess - see useTypeVocabulary.
  const typeVocabulary = useTypeVocabulary();
  const filtering = selectedTypes.length > 0;

  // The mount-time half of the sign-out rule. Before paint, so a remount after
  // a sign-out never shows the previous session's results for even one frame.
  useLayoutEffect(() => {
    clearIfSignedOut();
  }, []);

  // Egress preview state is transient UI and stays with the component.
  const [pendingQuery, setPendingQuery] = useState<PublicMarketQuery | null>(null);
  const [queryOutcome, setQueryOutcome] = useState<string | null>(null);
  const [reviewFindings, setReviewFindings] = useState<ReviewFinding[]>([]);
  const [reviewTemplates, setReviewTemplates] = useState<ReviewTemplate[]>([]);

  // A ticking counter rather than a bare spinner, exactly as ChatView does it:
  // the seconds since the run's real start, re-derived from the timestamp each
  // tick so a missed tick or a remount cannot make it drift. Nothing here
  // estimates how long is left - the length of a generation is unknown until
  // it ends, and a bar would be an invention.
  const running = s.runStartedAt !== null;
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (s.runStartedAt === null) return;
    const started = s.runStartedAt;
    const tick = () => setElapsed(Math.floor((Date.now() - started) / 1000));
    tick();
    const t = window.setInterval(tick, 1000);
    return () => window.clearInterval(t);
  }, [s.runStartedAt]);

  const retry = useCallback(() => {
    void runAnalysis();
  }, []);

  // The documents the run actually retrieved from. Not "the corpus" - this
  // screen has no list of authorised documents and will not pretend to one.
  const ledger = useMemo(() => {
    const all: EvidenceItem[] = [];
    if (summarySlot.s === "ready") all.push(...summarySlot.data.ledger);
    if (gapsSlot.s === "ready") all.push(...gapsSlot.data.ledger);
    if (recSlot.s === "ready") all.push(...recSlot.data.ledger);
    const seen = new Map<string, EvidenceItem>();
    for (const e of all) if (!seen.has(e.evidence_id)) seen.set(e.evidence_id, e);
    return [...seen.values()];
  }, [summarySlot, gapsSlot, recSlot]);

  const documents = useMemo(() => {
    const seen = new Map<string, string>();
    for (const e of ledger) if (!seen.has(e.document_id)) seen.set(e.document_id, e.filename);
    return [...seen.entries()].map(([id, filename]) => ({ id, filename }));
  }, [ledger]);

  const selectedItem = useMemo(
    () => (selected === null ? null : (ledger.find((e) => e.evidence_id === selected) ?? null)),
    [ledger, selected],
  );

  const onCite = useCallback((evidenceId: string) => setSelected(evidenceId), []);

  const createReviewFinding = useCallback(async (draft: ReviewFindingCreate) => {
    const result = await reviewsApi.create(draft);
    if (!result.ok) {
      throw new Error(result.error.message);
    }
    setReviewFindings((current) => [result.data, ...current.filter((item) => item.id !== result.data.id)]);
  }, []);

  const updateReviewFinding = useCallback(async (id: string, update: import("../types/api").ReviewFindingUpdate) => {
    const result = await reviewsApi.update(id, update);
    if (!result.ok) throw new Error(result.error.message);
    setReviewFindings((current) => current.map((item) => item.id === id ? result.data : item));
  }, []);

  useEffect(() => {
    if (gapsSlot.s !== "ready") return;
    let cancelled = false;
    void reviewsApi.list().then((result) => {
      if (!cancelled && result.ok) setReviewFindings(result.data.findings);
    });
    void reviewsApi.templates().then((result) => {
      if (!cancelled && result.ok) setReviewTemplates(result.data.templates);
    });
    return () => { cancelled = true; };
  }, [gapsSlot]);

  /**
   * BRING THE SOURCES PANEL INTO VIEW ON SELECT.
   *
   * The panel sits at the top of the right rail. On a long result page a
   * citation click populated it a screen or two ABOVE the viewport, so the
   * click looked like it did nothing and the reader concluded the audit trail
   * was broken.
   *
   * Both remedies are in place, and they cover different widths. The rail is
   * `xl:sticky` (below), which keeps the panel on screen only once the layout
   * is two columns; below xl the rail stacks under the results and sticky does
   * nothing at all. So the scroll is the one that matters on a narrow window,
   * and it is `block: "nearest"` deliberately: "nearest" is a NO-OP when the
   * panel is already visible, where "center" would yank the page out from
   * under a reader who could see it perfectly well.
   *
   * `prefers-reduced-motion` turns the animation off, not the scroll - the
   * reader still needs to be taken to the panel, they just do not need to be
   * flown there.
   */
  const sourcesRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (selected === null) return;
    const el = sourcesRef.current;
    // jsdom and older engines have no scrollIntoView; the selection still works.
    if (el === null || typeof el.scrollIntoView !== "function") return;
    const reduced =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView(reduced ? { block: "nearest" } : { block: "nearest", behavior: "smooth" });
  }, [selected]);

  // The egress preview. This lived in a MarketScreen that was in neither
  // App.tsx nor Shell.tsx, so `/api/market/preview-query` had no caller at
  // all - and that route is the privacy demonstration: it builds the object
  // that WOULD be sent to a public search and returns `sent: false`.
  //
  // Confirming does not send either. It calls the same route, which is the
  // point: there is one code path, it is inert, and the response says so.
  const previewQuery = useCallback((q: PublicMarketQuery) => setPendingQuery(q), []);
  const cancelQuery = useCallback(() => setPendingQuery(null), []);
  const confirmQuery = useCallback(async () => {
    if (!pendingQuery) return;
    const r = await marketApi.previewQuery({
      query: pendingQuery.query,
      country: pendingQuery.country,
      freshness_days: pendingQuery.freshness_days,
    });
    // `sent` is false whatever happens; showing what came back is how a
    // reader sees that for themselves rather than being told it.
    setQueryOutcome(
      r.ok
        ? `Nothing was sent. ${r.data.reason}`
        : `Nothing was sent: the request failed (${r.error.message}).`,
    );
    setPendingQuery(null);
  }, [pendingQuery]);

  const engines = enginesFor(mode, toggles);
  const canRun = question.trim() !== "" && !running;
  const waitingOn = stillWaitingOn(s);

  // An empty slot under an active filter is a different fact from an empty
  // slot with no filter on: the filter narrowed WHAT WAS SEARCHED, and an
  // empty result says nothing about whether the full corpus would have
  // answered. Conflating the two is how a reader ends up believing the
  // documents are silent on something the filter simply excluded.
  const filteredEmptyHint = (base: string): string =>
    filtering
      ? "The type filter narrowed the search, and nothing in scope matched this question. " +
        "That is not the same as the documents having nothing to say - clear or change the " +
        "filter to search the rest of the corpus."
      : base;

  const notImplemented =
    summarySlot.s === "ready"
      ? summarySlot.data.result.not_implemented_sections
      : [];

  return (
    <div className="aurora-field mx-auto max-w-7xl space-y-6">
      <div aria-hidden className="aurora-a" />
      <div aria-hidden className="aurora-b" />
      <header className="border-b border-ink-700 pb-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-signal-400">
          Enterprise FEED intelligence
        </p>
        <h1 className="mt-1 text-xl font-semibold text-slateish-100">Analysis</h1>
        <p className="mt-2 max-w-3xl text-sm text-slateish-300">
          Ask one engineering question, choose the work to run, and inspect only
          cited document evidence. Public evidence is isolated from private document context.
        </p>
        <div className="mt-4 grid gap-2 md:grid-cols-3">
          <div className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-850 px-3 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slateish-400">
              Evidence rule
            </p>
            <p className="mt-1 text-xs text-slateish-300">
              Document claims render only when citations resolve to page evidence.
            </p>
          </div>
          <div className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-850 px-3 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slateish-400">
              Recommendation rule
            </p>
            <p className="mt-1 text-xs text-slateish-300">
              Advisory output is separate from document facts and carries engineer review.
            </p>
          </div>
          <div className="rounded-[var(--radius-xs)] border border-warn-500/40 bg-warn-500/10 px-3 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-warn-500">
              Market rule
            </p>
            <p className="mt-1 text-xs text-slateish-300">
              Public market rows are sample data unless a governed provider is enabled.
            </p>
          </div>
        </div>
      </header>

      <section
        aria-label="Analysis controls"
        className="card-3d surface-floating rounded-[var(--radius-lg)] border border-ink-600 bg-ink-800 p-4"
      >
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="space-y-4">
            <div>
              <label htmlFor={questionId} className="block text-xs font-semibold uppercase tracking-wide text-slateish-400">
                Question
              </label>
              <textarea
                id={questionId}
                rows={4}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Example: What does PID mean in this control section?"
                className="mt-2 w-full resize-y rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-3 py-2 text-base text-slateish-100 placeholder:text-slateish-500"
              />
            </div>

            <label htmlFor="comparison-type" className="block text-xs font-semibold uppercase tracking-wide text-slateish-400">
              Comparison workflow
              <select id="comparison-type" value={comparisonType} onChange={(e) => patch({ comparisonType: e.target.value as ComparisonType | "" })} className="mt-2 block w-full rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-3 py-2 text-sm font-normal normal-case text-slateish-200">
                <option value="">No named comparison</option>
                <option value="baseline_vs_submittal">Baseline vs submittal</option>
                <option value="requirements_vs_submittal">Requirements vs submittal</option>
                <option value="revision_delta">Revision delta</option>
                <option value="discipline_coordination">Discipline coordination</option>
              </select>
              {comparisonType && <span className="mt-1 block text-xs font-normal normal-case text-slateish-500">Pick the documents for this workflow; the system will not invent an authoritative baseline.</span>}
            </label>

            {/* Narrows what the run searches, never what may be read - see the
                doc comment on TypeFilter. Rendered here (nothing, if the
                vocabulary has not loaded) rather than hard-coding a type list:
                a register with different types must not show a filter for
                types it does not have. */}
            <div aria-label="Search in">
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slateish-400">
                Search scope
              </p>
              <p className="mb-2 text-xs text-slateish-400">
                Leave all filters clear to search across every indexed document.
                Select a category only when you want to narrow the run.
              </p>
              <TypeFilter
                vocabulary={typeVocabulary}
                selected={selectedTypes}
                onToggle={toggleType}
                onClear={clearTypes}
                applied={appliedScope}
                label="Document categories"
                layout="column"
              />
              {/* RULE 3, the other half: no server echo yet under the CURRENT
                  ticks (before the first run, or after a retick) means no
                  count - the pending sentence stands in for it instead of a
                  stale or invented number. */}
              {appliedScope === null && pendingFilterNotice(selectedTypes) !== null && (
                <p className="mt-1 text-xs text-slateish-400">
                  {pendingFilterNotice(selectedTypes)}
                </p>
              )}
            </div>

            <ModeSelector mode={mode} onChange={changeMode} toggles={toggles} onToggle={changeToggle} />
          </div>

          <div className="space-y-3">
            <RunPlan mode={mode} engines={engines} />

            {mode === "comprehensive" && (
              <p className="rounded-[var(--radius-xs)] border border-warn-500/40 bg-warn-500/[0.08] px-3 py-2 text-xs text-warn-500">
                Persistent analysis jobs, streaming progress and cancellation are not exposed by
                this backend yet. This frontend sends the available wider synchronous request and
                labels that limitation.
              </p>
            )}

            <button
              type="button"
              disabled={!canRun}
              aria-busy={running}
              onClick={() => void runAnalysis()}
              className="w-full rounded-[var(--radius-sm)] border border-signal-500/70 bg-signal-500 px-4 py-2.5 text-sm font-semibold text-ink-950 shadow-[var(--shadow-raised)] transition-all hover:shadow-[var(--shadow-glow)] active:scale-[0.98] disabled:cursor-not-allowed disabled:border-ink-500 disabled:bg-ink-700 disabled:text-slateish-500 disabled:shadow-none"
            >
              {running ? "Running…" : "Run analysis"}
            </button>

            {/* Real elapsed time from the run's own start timestamp, and the
                engines that have not answered - both facts the client holds.
                No stage: the analysis routes take no progress_id and report
                none, and a stage guessed from the clock would be wrong on
                exactly the run where it mattered. */}
            {running && (
              <div
                role="status"
                aria-live="polite"
                data-testid="analysis-run-status"
                className="rounded-[var(--radius-xs)] border border-ink-700 bg-ink-850 p-3"
              >
                <div className="flex items-baseline justify-between gap-3">
                  <p className="text-sm font-medium text-slateish-200">Working on this machine</p>
                  <span
                    data-testid="analysis-elapsed"
                    className="shrink-0 font-mono text-sm tabular-nums text-slateish-300"
                  >
                    {elapsed}s
                  </span>
                </div>
                {waitingOn.length > 0 && (
                  <p className="mt-1.5 text-xs text-slateish-400">
                    Still waiting on: {waitingOn.join(", ")}.
                  </p>
                )}
                <p className="mt-1.5 text-xs text-slateish-500">
                  Generation runs on this CPU and is not streamed; the backend reports no stage for
                  analysis, so only the elapsed time is shown. Leaving this screen does not cancel
                  the run - the result will be here when you come back.
                </p>
              </div>
            )}

            {baselineRefusal !== null && (
              <p role="alert" className="rounded-[var(--radius-xs)] border border-warn-500/50 bg-warn-500/10 px-3 py-2 text-xs text-warn-500">
                {baselineRefusal}
              </p>
            )}
          </div>
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-6">
          {summarySlot.s === "idle" && gapsSlot.s === "idle" && (
            <EmptyState
              title="Nothing has been run yet."
              hint="Choose the sections you need, then run the selected analysis. The frontend will not silently change the selected mode."
            />
          )}

          {engines.summary && hasBody(summarySlot) && (
            <Section title="Summary" eyebrow="document-backed synthesis">
              <SlotBody
                slot={summarySlot}
                loadingLabel="Generating the summary"
                emptyTitle="No summary was produced for this question."
                emptyHint={filteredEmptyHint(
                  "Nothing the retrieval found could be summarised with a citation behind every sentence.",
                )}
                onRetry={retry}
              >
                {(d) => (
                  <div className="space-y-3">
                    {d.refusal !== null && (
                      <p
                        role="status"
                        className="rounded-[var(--radius-xs)] border border-warn-500/50 bg-warn-500/10 px-3 py-2 text-sm text-warn-500"
                      >
                        {d.refusal}
                      </p>
                    )}
                    <SummaryCard result={d.result} onCite={onCite} />
                    <DroppedSentences dropped={d.dropped} />
                  </div>
                )}
              </SlotBody>
            </Section>
          )}

          {engines.recommendation && hasBody(recSlot) && (
            <Section title="AI recommendation" eyebrow="advisory only">
              <SlotBody
                slot={recSlot}
                loadingLabel="Computing the recommendation"
                emptyTitle="No recommendation was generated."
                emptyHint={filteredEmptyHint(
                  "Nothing was produced that carried a citation, so there is nothing to advise on.",
                )}
                onRetry={retry}
              >
                {(d) => (
                  <div className="space-y-3">
                    {d.refusal && <p role="status" className="rounded-[var(--radius-xs)] border border-warn-500/50 bg-warn-500/10 px-3 py-2 text-sm text-warn-500">{d.refusal}</p>}
                    {d.recommendation && <RecommendationCard recommendation={d.recommendation} onCite={onCite} />}
                  </div>
                )}
              </SlotBody>
            </Section>
          )}

          {/* In Quote mode this is the ONLY section on the screen: quote turns
              the summary, the recommendation and the market off, and gaps is
              the one engine that needs no model - which is exactly what the
              mode's own description promises. The eyebrow therefore names the
              mode when quote is selected, so the reader can tell that Quote ran
              and that what follows is its product, rather than reading a
              generic "Gap analysis" heading and wondering where their output
              went. The claim is honest either way: it describes the request
              this screen actually issued. */}
          {engines.gaps && hasBody(gapsSlot) && (
            <Section
              title="Gap analysis"
              eyebrow={
                mode === "quote"
                  ? "quote mode — cited document evidence, no model"
                  : "baseline-controlled"
              }
            >
              <SlotBody
                slot={gapsSlot}
                loadingLabel="Comparing claims across documents"
                emptyTitle="No comparable claims were found."
                emptyHint={filteredEmptyHint(
                  "Retrieval found nothing carrying a measurable claim with a page behind it. That is not proof the documents say nothing.",
                )}
                onRetry={retry}
              >
                {(d) => (
                  <div className="space-y-3">
                    {mode === "quote" && (
                      <p className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-850 px-3 py-2 text-xs text-slateish-300">
                        Quote mode ran the mechanical comparison and nothing else. Everything
                        below is document evidence with a page behind it — no model wrote any
                        of it, and no summary or recommendation was requested.
                      </p>
                    )}
                    <GapAnalysisCard
                      gaps={d.gaps}
                      documents={documents}
                      onCite={onCite}
                      onNominateBaseline={nominateBaseline}
                      ledger={d.ledger}
                      onCreateFinding={createReviewFinding}
                      templates={reviewTemplates}
                    />
                    <ReviewWorkflowPanel findings={reviewFindings} onUpdate={updateReviewFinding} />
                    {(mode === "quote" || (d.gaps.applicability === "applicable" && d.gaps.baseline !== null)) && (
                      <ClaimTable
                        clusters={d.clusters}
                        onCite={onCite}
                        selectedEvidenceId={selected}
                      />
                    )}
                  </div>
                )}
              </SlotBody>
            </Section>
          )}

          {engines.market && hasBody(marketSlot) && (
            <Section title="Public market intelligence" eyebrow="isolated egress">
              <SlotBody
                slot={marketSlot}
                loadingLabel="Loading the market sample"
                emptyTitle="No market sample is loaded."
                emptyHint="No market sample is loaded and no search has returned rows, so there is nothing to show, sample or otherwise."
                onRetry={retry}
              >
                {(d) => (
                  <div className="space-y-3">
                    {/* What came back from the preview. Rendered so a reader
                        SEES that nothing was sent rather than being told it
                        in a tooltip. */}
                    {queryOutcome && (
                      <p
                        role="status"
                        className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-850 px-3 py-2 text-xs text-slateish-300"
                      >
                        {queryOutcome}
                      </p>
                    )}
                    {/* `d.egress` is the state the API MEASURED. The copy of
                        this panel that used to render inside the AI
                        recommendation section passed a hard-coded
                        web_search_enabled/allow_public_egress pair of
                        `false` instead - an egress claim the screen invented
                        rather than read. */}
                    <MarketPanel
                      findings={d.findings}
                      egress={d.egress}
                      onPreviewQuery={previewQuery}
                      pendingQuery={pendingQuery}
                      onConfirmQuery={confirmQuery}
                      onCancelQuery={cancelQuery}
                    />
                  </div>
                )}
              </SlotBody>
            </Section>
          )}

          {(notImplemented.length > 0 || summarySlot.s === "ready" || gapsSlot.s === "ready") && (
            <section aria-label="Not produced by this build" className="rounded-[var(--radius-md)] border border-dashed border-ink-600 p-4">
              <h2 className="text-xs uppercase tracking-wide text-slateish-500">
                Not produced by this build
              </h2>
              <ul className="mt-2 space-y-1 text-xs text-slateish-400">
                {notImplemented.map((s) => (
                  <li key={s}>{s}</li>
                ))}
                <li>{NOT_RENDERED_HERE}</li>
              </ul>
            </section>
          )}
        </div>

        <aside className="space-y-4 xl:sticky xl:top-6 xl:self-start">
          <section className="surface-card rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slateish-400">
              Execution-plan boundary
            </h2>
            <ul className="mt-3 space-y-2 text-xs text-slateish-300">
              <li>Backend algorithms and routes are unchanged in this frontend pass.</li>
              <li>Live market research requires an approved provider and privacy gate.</li>
              <li>Current market output is the labelled local sample dataset.</li>
              <li>Durable 202 analysis jobs are not exposed by this backend.</li>
            </ul>
          </section>

          <div ref={sourcesRef} data-testid="analysis-sources-panel">
            {selectedItem !== null ? (
              <SelectedPassage item={selectedItem} />
            ) : (
              <section className="surface-card rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-4">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-slateish-400">
                  Sources
                </h2>
                <p className="mt-2 text-sm text-slateish-500">
                  Select a citation or evidence row to inspect the exact passage here.
                </p>
              </section>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
