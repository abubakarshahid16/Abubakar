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
 */
import { useCallback, useId, useMemo, useRef, useState } from "react";

import { analysis as analysisApi, market as marketApi, type Result } from "../api/client";
import { ClaimTable } from "../components/analysis/ClaimTable";
import { GapAnalysisCard } from "../components/analysis/GapAnalysisCard";
import { MarketPanel } from "../components/analysis/MarketPanel";
import {
  ModeSelector,
  type AnalysisMode,
  type AnalysisToggles,
} from "../components/analysis/ModeSelector";
import { RecommendationCard } from "../components/analysis/RecommendationCard";
import { SummaryCard } from "../components/analysis/SummaryCard";
import { DisconnectedState, EmptyState, ErrorState, Spinner } from "../components/states";
import type {
  AnalysisGapsResult,
  AnalysisRecommendationResult,
  AnalysisSummaryResult,
  ApiError,
  EgressState,
  EvidenceItem,
  MarketFinding,
} from "../types/api";
import type {
  AnalysisResult,
  BaselineSelection,
  ClaimCluster,
  ClaimRow,
  DocumentedFinding,
  GapAnalysis,
  GapItem,
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
    const rows = rawRows
      .map((r: Record<string, unknown>) => toClaimRow(r, located))
      .filter((r): r is ClaimRow => r !== null);
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
  findings: MarketFinding[];
  ledger: EvidenceItem[];
}

interface MarketSlotData {
  notice: string;
  egress: EgressState;
  findings: MarketFinding[];
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="space-y-2">
      <h2 className="text-xs uppercase tracking-wide text-slateish-500">{title}</h2>
      {children}
    </section>
  );
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

/** The passage behind a citation: a document, a page, and the words. Nothing
 *  on this screen cites anything that cannot be shown here. */
function SelectedPassage({ item }: { item: EvidenceItem }) {
  return (
    <section
      aria-label="Selected passage"
      className="rounded-lg border border-signal-500/40 bg-ink-850 p-4"
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

  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<AnalysisMode>("focused");
  const [toggles, setToggles] = useState<AnalysisToggles>({
    gaps: false,
    market: false,
    recommendation: false,
  });
  const [baselineDocumentId, setBaselineDocumentId] = useState<string | null>(null);
  const [baselineRefusal, setBaselineRefusal] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const [summarySlot, setSummarySlot] = useState<Slot<SummarySlotData>>({ s: "idle" });
  const [gapsSlot, setGapsSlot] = useState<Slot<GapsSlotData>>({ s: "idle" });
  const [recSlot, setRecSlot] = useState<Slot<RecommendationSlotData>>({ s: "idle" });
  const [marketSlot, setMarketSlot] = useState<Slot<MarketSlotData>>({ s: "idle" });

  // ------------------------------------------------------ request ownership
  //
  // Taken synchronously before the awaits, re-read after them. Bumped on every
  // run AND on every mode or toggle change, so a summary still in flight when
  // the reader switches to Quote cannot land under the claim table.
  const ticket = useRef(0);
  const running = useRef(false);

  const supersede = useCallback(() => {
    ticket.current += 1;
    running.current = false;
    setSummarySlot({ s: "idle" });
    setGapsSlot({ s: "idle" });
    setRecSlot({ s: "idle" });
    setMarketSlot({ s: "idle" });
    setSelected(null);
    setBaselineRefusal(null);
  }, []);

  const changeMode = useCallback(
    (m: AnalysisMode) => {
      setMode(m);
      supersede();
    },
    [supersede],
  );

  const changeToggle = useCallback(
    (k: keyof AnalysisToggles, v: boolean) => {
      setToggles((t) => ({ ...t, [k]: v }));
      supersede();
    },
    [supersede],
  );

  const run = useCallback(
    async (overrideBaseline?: string | null) => {
      const asked = question.trim();
      if (asked === "") return;

      const mine = ticket.current + 1;
      ticket.current = mine;
      running.current = true;
      const mineStill = () => ticket.current === mine;

      const baseline =
        overrideBaseline === undefined ? baselineDocumentId : overrideBaseline;
      const engines = enginesFor(mode, toggles);
      // The wider set is the only thing "comprehensive" can honestly mean in
      // this build; the batch-by-batch run it describes is not implemented and
      // the screen says so rather than pretending.
      const limit = mode === "comprehensive" ? 24 : 8;
      const body = { question: asked, limit, baseline_document_id: baseline };

      setSelected(null);
      setSummarySlot(engines.summary ? { s: "loading" } : { s: "off" });
      setGapsSlot(engines.gaps ? { s: "loading" } : { s: "off" });
      setRecSlot(engines.recommendation ? { s: "loading" } : { s: "off" });
      setMarketSlot(engines.market ? { s: "loading" } : { s: "off" });

      const jobs: Promise<void>[] = [];

      if (engines.summary) {
        jobs.push(
          analysisApi.summary(body).then((r) => {
            if (!mineStill()) return;
            setSummarySlot(
              slotFrom(r, (d) => {
                const located = locate(d.evidence_ledger);
                const findings = citedFindings(d.documented_findings, located);
                const prose = citedSummary(d);
                const refusal = str(d.refusal);
                const dropped = (Array.isArray(d.dropped_sentences) ? d.dropped_sentences : [])
                  .filter((s) => s !== null && typeof s === "object" && typeof s.sentence === "string");
                if (prose === null && findings.length === 0 && refusal === null) return null;
                return {
                  result: toAnalysisResult(d, prose, findings),
                  refusal,
                  dropped,
                  ledger: Array.isArray(d.evidence_ledger) ? d.evidence_ledger : [],
                };
              }),
            );
          }),
        );
      }

      if (engines.gaps) {
        jobs.push(
          analysisApi.gaps(body).then((r) => {
            if (!mineStill()) return;
            setGapsSlot(
              slotFrom(r, (d: AnalysisGapsResult) => {
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
            );
          }),
        );
      }

      if (engines.recommendation) {
        jobs.push(
          analysisApi.recommendations(body).then((r) => {
            if (!mineStill()) return;
            setRecSlot(
              slotFrom(r, (d) => {
                const located = locate(d.evidence_ledger);
                const rec = toRecommendation(d.recommendation, located);
                const findings = onlySamples(d.public_market_findings);
                if (rec === null && findings.length === 0) return null;
                return {
                  recommendation: rec,
                  findings,
                  ledger: Array.isArray(d.evidence_ledger) ? d.evidence_ledger : [],
                };
              }),
            );
          }),
        );
      }

      if (engines.market) {
        jobs.push(
          marketApi.findings().then((r) => {
            if (!mineStill()) return;
            setMarketSlot(
              slotFrom(r, (d) => {
                const findings = onlySamples(d.findings);
                if (findings.length === 0) return null;
                return {
                  notice: typeof d.notice === "string" ? d.notice : "",
                  egress: d.egress,
                  findings,
                };
              }),
            );
          }),
        );
      }

      await Promise.all(jobs);
      if (mineStill()) running.current = false;
    },
    [baselineDocumentId, mode, question, toggles],
  );

  const retry = useCallback(() => {
    void run();
  }, [run]);

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

  const nominateBaseline = useCallback(
    (b: BaselineSelection) => {
      if (b.kind === "stated_requirement" || b.document_id === null) {
        // The gaps route accepts `baseline_document_id` and nothing else. A
        // typed requirement would have to be dropped on the floor, and a form
        // that silently discards what was typed into it is worse than one that
        // says it cannot take it.
        setBaselineRefusal(
          "This build's gap route takes a baseline DOCUMENT only. A stated requirement " +
            "cannot be sent, so nothing was run - the requirement you typed has not been used.",
        );
        return;
      }
      setBaselineRefusal(null);
      setBaselineDocumentId(b.document_id);
      void run(b.document_id);
    },
    [run],
  );

  const engines = enginesFor(mode, toggles);
  const canRun = question.trim() !== "";

  const notImplemented =
    summarySlot.s === "ready"
      ? summarySlot.data.result.not_implemented_sections
      : [];

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-lg font-semibold text-slateish-200">Analysis</h1>
        <p className="mt-1 text-sm text-slateish-400">
          Every claim below carries the document and page it came from. A claim that cites
          nothing is not shown at all.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[20rem_minmax(0,1fr)]">
        <div className="space-y-3">
          <div>
            <label htmlFor={questionId} className="block text-xs text-slateish-400">
              Question
            </label>
            <textarea
              id={questionId}
              rows={3}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              className="mt-1 w-full rounded border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-slateish-200"
            />
          </div>

          <ModeSelector mode={mode} onChange={changeMode} toggles={toggles} onToggle={changeToggle} />

          {mode === "comprehensive" && (
            <p className="rounded border border-warn-500/40 bg-warn-500/[0.08] px-2.5 py-1.5 text-xs text-warn-500">
              Batch-by-batch analysis and cancellation are not built. This runs the same engine
              as Focused over a wider set of passages.
            </p>
          )}

          <button
            type="button"
            disabled={!canRun}
            onClick={() => void run()}
            className="w-full rounded border border-signal-500/60 px-3 py-2 text-sm text-signal-300 hover:bg-signal-500/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Run analysis
          </button>

          {baselineRefusal !== null && (
            <p role="alert" className="rounded border border-warn-500/50 bg-warn-500/10 px-2.5 py-1.5 text-xs text-warn-500">
              {baselineRefusal}
            </p>
          )}
        </div>

        <div className="min-w-0 space-y-6">
          {summarySlot.s === "idle" && gapsSlot.s === "idle" && (
            <EmptyState
              title="Nothing has been run yet."
              hint="Ask a question and choose a mode. Quote runs the mechanical comparison and needs no model."
            />
          )}

          {engines.summary && (
            <Section title="Summary">
              <SlotBody
                slot={summarySlot}
                loadingLabel="Generating the summary"
                emptyTitle="No summary was produced for this question."
                emptyHint="Nothing the retrieval found could be summarised with a citation behind every sentence."
                onRetry={retry}
              >
                {(d) => (
                  <div className="space-y-3">
                    {d.refusal !== null && (
                      <p
                        role="status"
                        className="rounded border border-warn-500/50 bg-warn-500/10 px-3 py-2 text-sm text-warn-500"
                      >
                        {d.refusal}
                      </p>
                    )}
                    <SummaryCard result={d.result} onCite={onCite} />
                    {d.dropped.length > 0 && (
                      <details className="rounded border border-ink-700 bg-ink-850 px-3 py-2">
                        <summary className="cursor-pointer text-xs text-slateish-400">
                          {d.dropped.length} sentence{d.dropped.length === 1 ? " was" : "s were"} removed
                          from this summary
                        </summary>
                        <ul className="mt-2 space-y-1.5">
                          {d.dropped.map((s, i) => (
                            <li key={`${i}-${s.sentence.slice(0, 24)}`} className="text-xs text-slateish-400">
                              <span className="text-slateish-300">{s.sentence}</span>
                              <span className="ml-1 text-slateish-500">&mdash; {s.reason}</span>
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </div>
                )}
              </SlotBody>
            </Section>
          )}

          {engines.recommendation && (
            <Section title="Recommendation">
              <SlotBody
                slot={recSlot}
                loadingLabel="Computing the recommendation"
                emptyTitle="No recommendation was generated."
                emptyHint="Nothing was produced that carried a citation, so there is nothing to advise on."
                onRetry={retry}
              >
                {(d) => (
                  <div className="space-y-3">
                    <RecommendationCard recommendation={d.recommendation} onCite={onCite} />
                    {d.findings.length > 0 && (
                      <MarketPanel
                        findings={d.findings}
                        egress={{ web_search_enabled: false, allow_public_egress: false }}
                      />
                    )}
                  </div>
                )}
              </SlotBody>
            </Section>
          )}

          {engines.gaps && (
            <Section title="Gap analysis and claim comparison">
              <SlotBody
                slot={gapsSlot}
                loadingLabel="Comparing claims across documents"
                emptyTitle="No comparable claims were found."
                emptyHint="Retrieval found nothing carrying a measurable claim with a page behind it. That is not proof the documents say nothing."
                onRetry={retry}
              >
                {(d) => (
                  <div className="space-y-3">
                    <GapAnalysisCard
                      gaps={d.gaps}
                      documents={documents}
                      onCite={onCite}
                      onNominateBaseline={nominateBaseline}
                    />
                    <ClaimTable clusters={d.clusters} onCite={onCite} />
                  </div>
                )}
              </SlotBody>
            </Section>
          )}

          {engines.market && (
            <Section title="Public market sample">
              <SlotBody
                slot={marketSlot}
                loadingLabel="Loading the market sample"
                emptyTitle="No market sample is loaded."
                emptyHint="This machine is offline and there is no provider; there is nothing to show, sample or otherwise."
                onRetry={retry}
              >
                {(d) => <MarketPanel findings={d.findings} egress={d.egress} />}
              </SlotBody>
            </Section>
          )}

          {selectedItem !== null && <SelectedPassage item={selectedItem} />}

          {(notImplemented.length > 0 || summarySlot.s === "ready" || gapsSlot.s === "ready") && (
            <section aria-label="Not produced by this build" className="rounded-lg border border-dashed border-ink-600 p-4">
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
      </div>
    </div>
  );
}
