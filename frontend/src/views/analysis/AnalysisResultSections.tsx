import type { ReactNode } from "react";
import { ClaimTable } from "../../components/analysis/ClaimTable";
import { DroppedSentences as DroppedSentencesView } from "../../components/analysis/DroppedSentences";
import { GapAnalysisCard } from "../../components/analysis/GapAnalysisCard";
import { MarketPanel } from "../../components/analysis/MarketPanel";
import { RecommendationCard } from "../../components/analysis/RecommendationCard";
import { ReviewWorkflowPanel } from "../../components/analysis/ReviewWorkflowPanel";
import { SummaryCard } from "../../components/analysis/SummaryCard";
import { DisconnectedState, EmptyState, ErrorState, Spinner } from "../../components/states";
import { enginesFor, type Slot } from "./analysisModel";
import type { GapsSlotData, MarketSlotData, RecommendationSlotData, ScreenState, SummarySlotData } from "./analysisStore";
import type { ReviewFinding, ReviewFindingCreate, ReviewFindingUpdate, ReviewTemplate } from "../../types/api";
import type { PublicMarketQuery } from "../../types/analysis";

interface RenderContext {
  engines: ReturnType<typeof enginesFor>;
  summarySlot: Slot<SummarySlotData>;
  gapsSlot: Slot<GapsSlotData>;
  recSlot: Slot<RecommendationSlotData>;
  marketSlot: Slot<MarketSlotData>;
  mode: ScreenState["mode"];
  documents: Array<{ id: string; filename: string }>;
  selected: string | null;
  onCite: (evidenceId: string) => void;
  retry: () => void;
  filteredEmptyHint: (base: string) => string;
  hasBody: <T>(slot: Slot<T>) => boolean;
  store: typeof import("./analysisStore");
  createReviewFinding: (draft: ReviewFindingCreate) => Promise<void>;
  reviewTemplates: ReviewTemplate[];
  reviewFindings: ReviewFinding[];
  updateReviewFinding: (id: string, update: ReviewFindingUpdate) => Promise<void>;
  queryOutcome: string | null;
  previewQuery: (query: PublicMarketQuery) => void;
  pendingQuery: PublicMarketQuery | null;
  confirmQuery: () => Promise<void>;
  cancelQuery: () => void;
  notImplemented: string[];
}

export function Section({ title, eyebrow, children }: { title: string; eyebrow?: string; children: ReactNode }) {
  return <section aria-label={title} className="space-y-2">
    <div className="flex flex-wrap items-end justify-between gap-2">
      <h2 className="text-sm font-semibold text-slateish-100">{title}</h2>
      {eyebrow && <span className="text-xs uppercase tracking-wide text-slateish-500">{eyebrow}</span>}
    </div>
    {children}
  </section>;
}

export function SlotBody<T>({ slot, loadingLabel, emptyTitle, emptyHint, onRetry, children }: { slot: Slot<T>; loadingLabel: string; emptyTitle: string; emptyHint: string; onRetry: () => void; children: (data: T) => ReactNode }) {
  if (slot.s === "off" || slot.s === "idle") return null;
  if (slot.s === "loading") return <Spinner label={loadingLabel} />;
  if (slot.s === "offline") return <DisconnectedState onRetry={onRetry} />;
  if (slot.s === "failed") return <ErrorState error={slot.error} onRetry={onRetry} />;
  if (slot.s === "empty") return <EmptyState title={emptyTitle} hint={emptyHint} />;
  return <>{children(slot.data)}</>;
}

export function AnalysisResultSections({ ctx }: { ctx: RenderContext }) {
  const { engines, summarySlot, gapsSlot, recSlot, marketSlot, mode, documents, selected,
    onCite, retry, filteredEmptyHint, hasBody, store, createReviewFinding, reviewTemplates,
    reviewFindings, updateReviewFinding, queryOutcome, previewQuery, pendingQuery,
    confirmQuery, cancelQuery, notImplemented } = ctx;
  return <>
    {summarySlot.s === "idle" && gapsSlot.s === "idle" && <EmptyState title="Nothing has been run yet." hint="Choose the sections you need, then run the selected analysis. The frontend will not silently change the selected mode." />}
    {engines.summary && hasBody(summarySlot) && <Section title="Summary" eyebrow="document-backed synthesis"><SlotBody<SummarySlotData> slot={summarySlot} loadingLabel="Generating the summary" emptyTitle="No summary was produced for this question." emptyHint={filteredEmptyHint("Nothing the retrieval found could be summarised with a citation behind every sentence.")} onRetry={retry}>{(d: SummarySlotData) => <div className="space-y-3">
      {d.refusal !== null && <p role="status" className="rounded-[var(--radius-xs)] border border-warn-500/50 bg-warn-500/10 px-3 py-2 text-sm text-warn-500">{d.refusal}</p>}
      <SummaryCard result={d.result} onCite={onCite} /><DroppedSentencesView dropped={d.dropped} />
    </div>}</SlotBody></Section>}
    {engines.recommendation && hasBody(recSlot) && <Section title="AI recommendation" eyebrow="advisory only"><SlotBody<RecommendationSlotData> slot={recSlot} loadingLabel="Computing the recommendation" emptyTitle="No recommendation was generated." emptyHint={filteredEmptyHint("Nothing was produced that carried a citation, so there is nothing to advise on.")} onRetry={retry}>{(d: RecommendationSlotData) => <div className="space-y-3">
      {d.refusal && <p role="status" className="rounded-[var(--radius-xs)] border border-warn-500/50 bg-warn-500/10 px-3 py-2 text-sm text-warn-500">{d.refusal}</p>}
      {d.recommendation && <RecommendationCard recommendation={d.recommendation} onCite={onCite} />}
    </div>}</SlotBody></Section>}
    {engines.gaps && hasBody(gapsSlot) && <Section title="Gap analysis" eyebrow={mode === "quote" ? "quote mode — cited document evidence, no model" : "baseline-controlled"}><SlotBody<GapsSlotData> slot={gapsSlot} loadingLabel="Comparing claims across documents" emptyTitle="No comparable claims were found." emptyHint={filteredEmptyHint("Retrieval found nothing carrying a measurable claim with a page behind it. That is not proof the documents say nothing.")} onRetry={retry}>{(d: GapsSlotData) => <div className="space-y-3">
      {mode === "quote" && <p className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-850 px-3 py-2 text-xs text-slateish-300">Quote mode ran the mechanical comparison and nothing else. Everything below is document evidence with a page behind it — no model wrote any of it, and no summary or recommendation was requested.</p>}
      <GapAnalysisCard gaps={d.gaps} documents={documents} onCite={onCite} onNominateBaseline={store.nominateBaseline} ledger={d.ledger} onCreateFinding={createReviewFinding} templates={reviewTemplates} />
      <ReviewWorkflowPanel findings={reviewFindings} documents={documents} onUpdate={updateReviewFinding} />
      {(mode === "quote" || (d.gaps.applicability === "applicable" && d.gaps.baseline !== null)) && <ClaimTable clusters={d.clusters} onCite={onCite} selectedEvidenceId={selected} />}
    </div>}</SlotBody></Section>}
    {engines.market && hasBody(marketSlot) && <Section title="Public market intelligence" eyebrow="isolated egress"><SlotBody<MarketSlotData> slot={marketSlot} loadingLabel="Loading the market sample" emptyTitle="No market sample is loaded." emptyHint="No market sample is loaded and no search has returned rows, so there is nothing to show, sample or otherwise." onRetry={retry}>{(d: MarketSlotData) => <div className="space-y-3">
      {queryOutcome && <p role="status" className="rounded-[var(--radius-xs)] border border-ink-600 bg-ink-850 px-3 py-2 text-xs text-slateish-300">{queryOutcome}</p>}
      <MarketPanel findings={d.findings} egress={d.egress} onPreviewQuery={previewQuery} pendingQuery={pendingQuery} onConfirmQuery={confirmQuery} onCancelQuery={cancelQuery} />
    </div>}</SlotBody></Section>}
    {(notImplemented.length > 0 || summarySlot.s === "ready" || gapsSlot.s === "ready") && <section aria-label="Not produced by this build" className="rounded-[var(--radius-md)] border border-dashed border-ink-600 p-4"><h2 className="text-xs uppercase tracking-wide text-slateish-500">Not produced by this build</h2><ul className="mt-2 space-y-1 text-xs text-slateish-400">{notImplemented.map((s: string) => <li key={s}>{s}</li>)}<li>coverage ledger (none of these routes reports a coverage object, and the ledger cannot be drawn without inventing the document count it opens with)</li></ul></section>}
  </>;
}
