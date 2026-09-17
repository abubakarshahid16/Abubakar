import type { Result } from "../../api/client";
import type {
  AnalysisRecommendationResult, AnalysisSummaryResult, ApiError,
  EvidenceItem, MarketFinding,
} from "../../types/api";
import type {
  AnalysisResult, BaselineSelection, ClaimCluster, ClaimRow, DocumentedFinding,
  GapAnalysis, GapItem, Recommendation,
} from "../../types/analysis";
import type { AnalysisMode, AnalysisToggles } from "../../components/analysis/ModeSelector";

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

export function str(v: unknown): string | null {
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
    evidence_removed: Array.isArray(r.evidence_removed) ? r.evidence_removed : [],
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

