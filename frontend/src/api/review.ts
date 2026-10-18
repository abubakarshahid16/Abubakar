/**
 * Review, report, deliverable, risk and analysis calls.
 *
 * Split out of api/client.ts (order 79b). Moved verbatim; screens keep
 * importing from "api/client", which re-exports this module.
 */
import type {
  BackgroundJob,
  ApiError,
  CrsIssueDecision,
  CrsIssueGate,
  ClauseCoverage,
  AnalysisGapsResult,
  AnalysisRecommendationResult,
  AnalysisRequest,
  AnalysisSummaryResult,
  PairRejection,
  ReportList,
  ReportRecord,
  ReportVerification,
  ReviewDashboard,
  CrsComment,
  CrsCommentHistory,
  CrsPreview,
  ReviewTrace,
  FindingEvidence,
  CrsTransmittals,
  CrsReplyImport,
  CrsResponseCode,
  ReviewReadiness,
  VisionReaderStatus,
  ReviewRunStandard,
  ReviewRunMissingReference,
  ReviewRunSummary,
  ReviewFinding,
  ReviewFindingCreate,
  ReviewFindingUpdate,
  ReviewFindingEvent,
  ReviewTemplate,
  Deliverable,
  DeliverableCreate,
  DeliverableUpdate,
  ReviewBaselineRule,
  BaselineSelection,
  ExpectedDeliverable,
  Risk,
  RiskType,
  ReviewTraceability,
} from "../types/api";

import { BASE, request, disconnected, humanMessage, hasArrayField, hasNumberField, downloadReport, signOutOn401, token } from "./core";
import type { DownloadResult, Result, SheetMark } from "./core";
export const analysis = {
  summary: (body: AnalysisRequest) =>
    request<AnalysisSummaryResult>("/analysis/summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  recommendations: (body: AnalysisRequest) =>
    request<AnalysisRecommendationResult>("/analysis/recommendations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  gaps: (body: AnalysisRequest) =>
    request<AnalysisGapsResult>("/analysis/gaps", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

export const reviews = {
  templates: (params?: { discipline?: string; deliverable_type?: string; active_only?: boolean }) => {
    const query = new URLSearchParams();
    if (params?.discipline) query.set("discipline", params.discipline);
    if (params?.deliverable_type) query.set("deliverable_type", params.deliverable_type);
    if (params?.active_only !== undefined) query.set("active_only", String(params.active_only));
    return request<{ templates: ReviewTemplate[] }>(`/reviews/templates${query.toString() ? `?${query.toString()}` : ""}`);
  },
  list: (params?: { document_id?: string; status?: string; review_run_id?: string }) => {
    const query = new URLSearchParams();
    if (params?.document_id) query.set("document_id", params.document_id);
    if (params?.status) query.set("status", params.status);
    if (params?.review_run_id) query.set("review_run_id", params.review_run_id);
    return request<{ findings: ReviewFinding[] }>(
      `/reviews/findings${query.toString() ? `?${query.toString()}` : ""}`,
    );
  },
  create: (body: ReviewFindingCreate) =>
    request<ReviewFinding>("/reviews/findings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  /** Confirm the pairing. The caller is named by the server, never by us. */
  confirm: (id: string) =>
    request<ReviewFinding>(`/reviews/findings/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmed: true }),
    }),
  update: (id: string, body: ReviewFindingUpdate) =>
    request<ReviewFinding>(`/reviews/findings/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  history: (id: string) =>
    request<{ events: ReviewFindingEvent[] }>(`/reviews/findings/${encodeURIComponent(id)}/history`),
  traceability: (id: string) => request<ReviewTraceability>(`/reviews/findings/${encodeURIComponent(id)}/traceability`),
  /** Review runs, newest first, over submittals the caller may read. */
  reviewRuns: (documentId?: string) =>
    request<{ runs: ReviewRunSummary[] }>(
      `/reviews/runs${documentId ? `?document_id=${encodeURIComponent(documentId)}` : ""}`,
      undefined,
      hasArrayField("runs"),
    ),
  /** R21 / #508: the page one side of a finding cites, with the finding's
   *  own stored text boxed on it. The text is looked up by finding id on the
   *  server and never travels in this URL. `X-Answer-Located` says whether a
   *  box was drawn. Fetched with the bearer header (`useAuthedImage`). */
  evidenceImageUrl: (findingId: string, side: "submittal" | "standard") =>
    `${BASE}/reviews/findings/${encodeURIComponent(findingId)}/evidence-image?side=${side}`,
  /** #967: the run's datasheet page with every card's value underlined on
   *  it by the server, amber or grey by the card's state. Only finding ids
   *  and states travel in the URL - never a value or a field name.
   *  `X-Marks-Located` / `X-Marks-Total` say how many were placed. */
  sheetPageImageUrl: (runId: string, page: number, marks: SheetMark[]) =>
    `${BASE}/reviews/runs/${encodeURIComponent(runId)}/page-image?page=${page}&marks=${encodeURIComponent(
      marks.map((m) => `${m.findingId}:${m.state}`).join(","),
    )}`,
  /** #785: where each side of a finding sits (document, page) and what kind
   *  of box the evidence image draws on it, or why the side cannot be shown. */
  findingEvidence: (findingId: string) =>
    request<FindingEvidence>(`/reviews/findings/${encodeURIComponent(findingId)}/evidence`),
  /** Which standards a run compared against, and why each one is there. */
  reviewRunStandards: (runId: string) =>
    request<{ standards: ReviewRunStandard[]; missing_references?: ReviewRunMissingReference[] }>(
      `/reviews/runs/${encodeURIComponent(runId)}/standards`,
      undefined,
      hasArrayField("standards"),
    ),
  /** Which standards a run considered, INCLUDING the ones not applied - the
   *  engineer's add-a-standard list. */
  reviewRunStandardsAll: (runId: string) =>
    request<{ standards: ReviewRunStandard[]; missing_references?: ReviewRunMissingReference[] }>(
      `/reviews/runs/${encodeURIComponent(runId)}/standards?include_excluded=true`,
      undefined,
      hasArrayField("standards"),
    ),
  /** P2: an engineer adds or removes one standard, with a reason; the run's
   *  findings are recomputed. Returns every standard the run considered. */
  overrideRunStandard: (runId: string, body: { standard_document_id: string; include: boolean; reason: string }) =>
    request<{ standards: ReviewRunStandard[]; missing_references?: ReviewRunMissingReference[] }>(
      `/reviews/runs/${encodeURIComponent(runId)}/standards/override`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
      hasArrayField("standards"),
    ),
  /** P3: cancel a queued review now, or a running one at its next step. */
  cancelJob: (jobId: string) =>
    request<BackgroundJob>(`/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }),
  /** Start a review. Admin-gated, and refuses while one is already running. */
  startReviewRun: (submittalDocumentId: string) =>
    request<ReviewRunSummary>("/reviews/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ submittal_document_id: submittalDocumentId }),
    }),
  /** The four cards of master plan section 20, under the caller's grants.
   *
   *  SHAPE-CHECKED, like every other list on this screen. Without it a body
   *  of the wrong shape reached the cards as `ok`, and `.toLocaleString()` on
   *  the missing count threw - taking the WHOLE Dashboard down over one
   *  panel. That is exactly the white screen `ShapeCheck` exists to prevent. */
  dashboard: () =>
    request<ReviewDashboard>("/reviews/dashboard", undefined,
                             hasNumberField("submittals_total")),
  /** The engineer's final code. A reason is required when it differs from
   *  the recommendation; the server enforces that, not this call. */
  decideCode: (runId: string, code: string, overrideReason: string | null) =>
    request<ReviewRunSummary>(
      `/reviews/runs/${encodeURIComponent(runId)}/code`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, override_reason: overrideReason }),
      }),
  /** The same Comment Resolution Sheet, as JSON, for the on-screen preview.
   *
   *  A SIBLING OF `exportCrs`, NOT A SUBSTITUTE. The server builds both from
   *  one builder, so this cannot show a row the downloaded file does not
   *  have. Shape-checked like every other list on this screen: a body of the
   *  wrong shape reaching the table as `ok` is how one bad response takes a
   *  whole view down. */
  /** Owner order section 3: the readiness strip - pages read, standards
   *  held and missing, and whether anything changed since the last run. */
  readiness: (submittalDocumentId: string) =>
    request<ReviewReadiness>(
      `/reviews/readiness/${encodeURIComponent(submittalDocumentId)}`,
      undefined,
      hasArrayField("standards_missing"),
    ),
  /** Owner order section 3: "Read unread pages" - re-extracts this ONE
   *  submittal, then answers the readiness strip's own numbers again. */
  rereadPages: (submittalDocumentId: string) =>
    request<ReviewReadiness>(
      `/reviews/readiness/${encodeURIComponent(submittalDocumentId)}/reread-pages`,
      { method: "POST" },
      hasArrayField("standards_missing"),
    ),
  /** Can "Read unread pages" use the vision reader right now, and if not,
   *  what to change. About the service, not a document. */
  visionReaderStatus: () =>
    request<VisionReaderStatus>(
      "/reviews/vision-reader-status",
      undefined,
      (b) => typeof b === "object" && b !== null
        && typeof (b as Record<string, unknown>).state === "string",
    ),
  /** #725 F7: enter the CRS header's transmittal numbers for a run. */
  setCrsTransmittals: (runId: string, body: CrsTransmittals) =>
    request<CrsTransmittals>(`/reviews/runs/${encodeURIComponent(runId)}/crs/transmittals`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  /** #791: the run step by step (stored trace, or built under the caller's access). */
  reviewTrace: (runId: string) =>
    request<ReviewTrace>(
      `/reviews/runs/${encodeURIComponent(runId)}/trace`,
      undefined,
      hasArrayField("steps"),
    ),
  previewCrs: (runId: string) =>
    request<CrsPreview>(
      `/reviews/runs/${encodeURIComponent(runId)}/crs/preview`,
      undefined,
      hasArrayField("rows"),
    ),
  /** PF5 (#885): the run's open items before its contractor copy. Read only. */
  crsIssueGate: (runId: string) =>
    request<CrsIssueGate>(`/reviews/runs/${encodeURIComponent(runId)}/crs/issue-gate`),
  /** PF5: the engineer checked an unread page by eye; the reason is theirs,
   *  who and when are the server's. */
  decideCrsPage: (runId: string, page: number, reason: string) =>
    request<CrsIssueDecision>(
      `/reviews/runs/${encodeURIComponent(runId)}/crs/open-items/pages/${page}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      }),
  /** PF5: the engineer accepts or rejects one open finding, with a reason. */
  decideCrsFinding: (runId: string, findingId: string, decision: "accept" | "reject", reason: string) =>
    request<CrsIssueDecision>(
      `/reviews/runs/${encodeURIComponent(runId)}/crs/open-items/findings/${encodeURIComponent(findingId)}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision, reason }),
      }),
  /** PF4 (#884): the run's clause coverage ledger. Read only. */
  runCoverage: (runId: string) =>
    request<ClauseCoverage>(`/reviews/runs/${encodeURIComponent(runId)}/coverage`),
  /** Close or re-open one numbered comment (its Final Resolution). Only a
   *  signed-in reviewer can; the server records who from the session. */
  setCrsCommentStatus: (runId: string, ref: string, status: "Open" | "Closed", note?: string) =>
    request<CrsComment>(
      `/reviews/runs/${encodeURIComponent(runId)}/crs/comments/${encodeURIComponent(ref)}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, note: note?.trim() || null }),
      }),
  /** Record the contractor's reply to one comment, when it came by email or
   *  letter rather than the returned sheet. `code` null = they stated none. */
  recordCrsResponse: (runId: string, ref: string, code: CrsResponseCode | null, text: string) =>
    request<CrsComment>(
      `/reviews/runs/${encodeURIComponent(runId)}/crs/comments/${encodeURIComponent(ref)}/response`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, text }),
      }),
  crsCommentHistory: (runId: string, ref: string) =>
    request<CrsCommentHistory>(
      `/reviews/runs/${encodeURIComponent(runId)}/crs/comments/${encodeURIComponent(ref)}/history`,
      undefined,
      hasArrayField("events"),
    ),
  /** Import the contractor's returned CRS (.xlsx). Rows are matched by their
   *  permanent number only; statuses are not changed. */
  importCrsReply: (runId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<CrsReplyImport>(
      `/reviews/runs/${encodeURIComponent(runId)}/crs/reply`,
      { method: "POST", body: form },
      hasArrayField("rows"),
    );
  },
  /** The run's findings as a Comment Resolution Sheet.
   *
   *  NOT `request()`, because the body is a spreadsheet rather than JSON -
   *  but the token is attached the same way and the failure shape is the
   *  same `Result`, so a caller handles it exactly like any other call. The
   *  filename is the SERVER's: one definition of what the file is called. */
  exportCrs: async (
    runId: string,
    copy: "internal" | "issue" = "internal",
  ): Promise<Result<{ blob: Blob; filename: string }>> => {
    // Owner order 2f: "internal" keeps the AI Review Comments column;
    // "issue" is the contractor's copy, with every unconfirmed AI item removed.
    // PF5 (#885): the contractor's copy is ISSUED (POST): the server refuses
    // it while a page is unread or a finding undecided, and keeps the copy.
    const run = encodeURIComponent(runId);
    const path = copy === "issue" ? `/reviews/runs/${run}/crs/issue` : `/reviews/runs/${run}/crs?copy=${copy}`;
    let response: Response;
    try {
      const headers = new Headers();
      if (token) headers.set("Authorization", `Bearer ${token}`);
      response = await fetch(`${BASE}${path}`, { headers, method: copy === "issue" ? "POST" : "GET" });
    } catch (e) {
      return disconnected(
        e instanceof Error ? e.message : "Network request failed.");
    }
    if (!response.ok) {
      signOutOn401(response.status);
      let error: ApiError = {
        code: response.status === 404 ? "not_found" : "internal",
        message: humanMessage(response.status),
      };
      try {
        const body = await response.json();
        const raw = body?.detail ?? body;
        if (raw && typeof raw === "object" && "code" in raw) error = raw as ApiError;
      } catch {
        /* keep the fallback */
      }
      return { ok: false, disconnected: false, error };
    }
    const disposition = response.headers.get("Content-Disposition") ?? "";
    const match = /filename="([^"]+)"/.exec(disposition);
    let blob: Blob;
    try {
      blob = await response.blob();
    } catch (e) {
      // The status line arrives before the bytes: a dropped connection throws
      // here, on a response that already said 200.
      return disconnected(
        e instanceof Error ? e.message : "The download was interrupted.");
    }
    return {
      ok: true,
      data: {
        blob,
        filename: match?.[1] ?? `CRS_${runId}.xlsx`,
      },
    };
  },
  /** Refuse a pairing so no future run proposes it again. */
  rejectPairing: (findingId: string, reason: string) =>
    request<PairRejection>("/reviews/pairs/reject", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ finding_id: findingId, reason }),
    }),
  baselineRules: () => request<{ rules: ReviewBaselineRule[] }>("/reviews/baseline-rules"),
  createBaselineRule: (body: Partial<ReviewBaselineRule>) => request<ReviewBaselineRule>("/reviews/baseline-rules", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  updateBaselineRule: (id: string, body: Partial<ReviewBaselineRule>) => request<ReviewBaselineRule>(`/reviews/baseline-rules/${encodeURIComponent(id)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  baselineSelection: (documentId: string) => request<BaselineSelection | null>(`/reviews/baseline-selection/${encodeURIComponent(documentId)}`),
};

export const deliverables = {
  list: () => request<{ deliverables: Deliverable[] }>("/deliverables"),
  alerts: () => request<{ alerts: { deliverable_id: string; wbs_code: string; title: string; due_date: string; days_overdue: number; escalation_level: number; severity: string }[] }>("/deliverables/alerts"),
  create: (body: DeliverableCreate) => request<Deliverable>("/deliverables", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  update: (id: string, body: DeliverableUpdate) => request<Deliverable>(`/deliverables/${encodeURIComponent(id)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  stakeholders: (id: string) => request<{ stakeholders: import("../types/api").DeliverableStakeholder[] }>(`/deliverables/${encodeURIComponent(id)}/stakeholders`),
  replaceStakeholders: (id: string, assignments: import("../types/api").DeliverableStakeholderAssignment[]) => request<{ stakeholders: import("../types/api").DeliverableStakeholder[] }>(`/deliverables/${encodeURIComponent(id)}/stakeholders`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ assignments }) }),
  workspace: (id: string) => request<import("../types/api").WbsWorkspace>(`/deliverables/${encodeURIComponent(id)}/workspace`),
  expected: (wbsCode?: string) => request<{ deliverables: ExpectedDeliverable[] }>(`/deliverables/expected${wbsCode ? `?wbs_code=${encodeURIComponent(wbsCode)}` : ""}`),
};

export const risks = {
  list: (riskType?: RiskType) => request<{ risks: Risk[] }>(`/risks${riskType ? `?risk_type=${encodeURIComponent(riskType)}` : ""}`),
  create: (body: Partial<Risk> & { risk_type: RiskType; title: string; description: string }) => request<Risk>("/risks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
};

export const reports = {
  list: (opts: { limit?: number; offset?: number; sort?: string; direction?: string; q?: string } = {}) => {
    const q = new URLSearchParams();
    for (const [key, value] of Object.entries(opts)) if (value != null && value !== "") q.set(key, String(value));
    return request<ReportList>(`/reports${q.toString() ? `?${q}` : ""}`);
  },
  generate: (message_id: string) =>
    request<ReportRecord>("/reports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message_id }),
    }),
  verify: (id: string) =>
    request<ReportVerification>(`/reports/${encodeURIComponent(id)}/verify`),
  /** Fetch the report PDF as bytes, with the bearer token on the request.
   *
   *  This replaces a `window.open(downloadUrl(id))` navigation. A navigation
   *  carries no Authorization header, and the token is in memory only (see
   *  the note on `token`), so under auth_mode=demo_required the download
   *  resolved to an empty scope and the backend answered 404 - telling the
   *  reader that a report listed on that same screen did not exist. The old
   *  comment here conceded the path only worked while auth was disabled.
   *
   *  The token stays in the Authorization header and is NEVER placed in the
   *  URL. A URL reaches browser history, proxy and server access logs and
   *  Referer headers; RAG-INTELLIGENCE-POC-EXECUTION.md rule 6 (line 43)
 *  forbids secrets in logs.
   *
   *  Returns bytes, never a file: writing the file is the caller's job, and
   *  a failure returns no bytes at all so no empty or truncated PDF can be
   *  handed to the reader. */
  download: (id: string): Promise<DownloadResult> =>
    downloadReport(`/reports/${encodeURIComponent(id)}/download`, `rag-intelligence-report-${id}.pdf`),
};
