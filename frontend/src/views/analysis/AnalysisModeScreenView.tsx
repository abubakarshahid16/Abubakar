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

import { market as marketApi, reviews as reviewsApi } from "../../api/client";
import { useTypeVocabulary } from "../../components/classification/TypeFilter";
import type { EvidenceItem, ReviewFindingCreate, ReviewFinding, ReviewTemplate } from "../../types/api";
import type { PublicMarketQuery } from "../../types/analysis";


import * as model from "./analysisModel";
import * as store from "./analysisStore";
import { AnalysisResultSections } from "./AnalysisResultSections";
import { AnalysisControls } from "./AnalysisControls";
import { AnalysisHeader } from "./AnalysisHeader";
import { AnalysisSources } from "./AnalysisSources";
export function hasBody<T>(slot: model.Slot<T>): boolean {
  return slot.s !== "off" && slot.s !== "idle";
}

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

  const updateReviewFinding = useCallback(async (id: string, update: import("../../types/api").ReviewFindingUpdate) => {
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
    <div className="aurora-field w-full space-y-6">
      <div aria-hidden className="aurora-a" />
      <div aria-hidden className="aurora-b" />
      <AnalysisHeader />
      <AnalysisControls ctx={{ questionId, question, comparisonType, selectedTypes, appliedScope, typeVocabulary, mode, toggles, running, canRun, elapsed, waitingOn, baselineRefusal, store, engines }} />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-6">
          <AnalysisResultSections ctx={{
            engines,
            summarySlot,
            gapsSlot,
            recSlot,
            marketSlot,
            mode,
            documents,
            selected,
            onCite,
            retry,
            filteredEmptyHint,
            hasBody,
            store,
            createReviewFinding,
            reviewTemplates,
            reviewFindings,
            updateReviewFinding,
            queryOutcome,
            previewQuery,
            pendingQuery,
            confirmQuery,
            cancelQuery,
            notImplemented,
          }} />
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

          <AnalysisSources selectedItem={selectedItem} sourcesRef={sourcesRef} />
        </aside>
      </div>
    </div>
  );
}
