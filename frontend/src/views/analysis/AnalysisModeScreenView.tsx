// @ts-nocheck
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
} from "../../api/client";
import { ClaimTable } from "../../components/analysis/ClaimTable";
import { DroppedSentences as DroppedSentencesView } from "../../components/analysis/DroppedSentences";
import { GapAnalysisCard } from "../../components/analysis/GapAnalysisCard";
import { MarketPanel } from "../../components/analysis/MarketPanel";
import {
  ModeSelector,
  type AnalysisMode,
  type AnalysisToggles,
} from "../../components/analysis/ModeSelector";
import { RecommendationCard } from "../../components/analysis/RecommendationCard";
import { ReviewWorkflowPanel } from "../../components/analysis/ReviewWorkflowPanel";
import { SummaryCard } from "../../components/analysis/SummaryCard";
import { DisconnectedState, EmptyState, ErrorState, Spinner } from "../../components/states";
import {
  TypeFilter,
  pendingFilterNotice,
  useTypeVocabulary,
} from "../../components/classification/TypeFilter";
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
} from "../../types/api";
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
} from "../../types/analysis";


import * as model from "./analysisModel";
import * as store from "./analysisStore";
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
          <span className="text-xs uppercase tracking-wide text-slateish-500">
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
      <span className="font-mono text-xs uppercase tracking-wide">
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
      <blockquote className="document-quote mt-2 whitespace-pre-wrap border-l-2 border-signal-500/60 bg-ink-900 py-2 ps-4 pe-3 text-[14px] text-slateish-100">
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
  const s = useSyncExternalStore(store.subscribe, store.getSnapshot);
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
    store.clearIfSignedOut();
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
    void store.runAnalysis();
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

  const onCite = useCallback((evidenceId: string) => store.setSelected(evidenceId), []);

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

  const engines = model.enginesFor(mode, toggles);
  const canRun = question.trim() !== "" && !running;
  const waitingOn = store.stillWaitingOn(s);

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
        <p className="mt-1 text-sm font-semibold text-signal-300">Document submittal review</p>
        <p className="mt-2 max-w-3xl text-sm text-slateish-300">
          Ask one engineering question, choose the work to run, and inspect only
          cited document evidence. Public evidence is isolated from private document context.
        </p>
        <div className="mt-4 grid gap-2 md:grid-cols-3">
          <div className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-850 px-3 py-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-slateish-400">
              Evidence rule
            </p>
            <p className="mt-1 text-xs text-slateish-300">
              Document claims render only when citations resolve to page evidence.
            </p>
          </div>
          <div className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-850 px-3 py-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-slateish-400">
              Recommendation rule
            </p>
            <p className="mt-1 text-xs text-slateish-300">
              Advisory output is separate from document facts and carries engineer review.
            </p>
          </div>
          <div className="rounded-[var(--radius-xs)] border border-warn-500/40 bg-warn-500/10 px-3 py-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-warn-500">
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
                onChange={(e) => store.setQuestion(e.target.value)}
                placeholder="Example: What does PID mean in this control section?"
                className="mt-2 w-full resize-y rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-3 py-2 text-base text-slateish-100 placeholder:text-slateish-500"
              />
            </div>

            <label htmlFor="comparison-type" className="block text-xs font-semibold uppercase tracking-wide text-slateish-400">
              Comparison workflow
              <select id="comparison-type" value={comparisonType} onChange={(e) => store.patch({ comparisonType: e.target.value as ComparisonType | "" })} className="mt-2 block w-full rounded-[var(--radius-xs)] border border-ink-600 bg-ink-900 px-3 py-2 text-sm font-normal normal-case text-slateish-200">
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
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slateish-400">
                Search scope
              </p>
              <p className="mb-2 text-xs text-slateish-400">
                Leave all filters clear to search across every indexed document.
                Select a category only when you want to narrow the run.
              </p>
              <TypeFilter
                vocabulary={typeVocabulary}
                selected={selectedTypes}
                onToggle={store.toggleType}
                onClear={store.clearTypes}
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

            <ModeSelector mode={mode} onChange={store.changeMode} toggles={toggles} onToggle={store.changeToggle} />
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
              onClick={() => void store.runAnalysis()}
              className="w-full rounded-[var(--radius-sm)] border border-signal-500/70 bg-signal-500 px-4 py-2.5 text-sm font-semibold text-ink-950 shadow-[var(--shadow-raised)] motion-safe:transition-all hover:shadow-[var(--shadow-glow)] active:scale-[0.98] disabled:cursor-not-allowed disabled:border-ink-500 disabled:bg-ink-700 disabled:text-slateish-500 disabled:shadow-none"
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
                    <DroppedSentencesView dropped={d.dropped} />
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
                      onNominateBaseline={store.nominateBaseline}
                      ledger={d.ledger}
                      onCreateFinding={createReviewFinding}
                      templates={reviewTemplates}
                    />
                    <ReviewWorkflowPanel findings={reviewFindings} documents={documents} onUpdate={updateReviewFinding} />
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
