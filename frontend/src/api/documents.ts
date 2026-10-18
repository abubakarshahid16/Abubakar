/**
 * Documents, standards and classification calls.
 *
 * Split out of api/client.ts (order 79b). Moved verbatim; screens keep
 * importing from "api/client", which re-exports this module.
 */
import type {
  DeletedDocument,
  ClauseCheckDecisionResult,
  ClauseCheckDraft,
  MissingStandard,
  ChunkPage,
  DocumentRecord,
  DocumentPage,
  ExclusionsResponse,
  PagesResponse,
  ClassificationVocabulary,
  ClassificationCoverage,
  ClassificationUpdate,
  DocumentClassification,
  DocumentKindVocabulary,
  BulkRoleUpdate,
  BulkRoleResult,
  StructuredSearchResult,
  WorkbookPreview,
  StandardSummary,
  StandardClause,
  StandardRequirement,
  StandardExtraction,
  UploadDisciplines,
} from "../types/api";

import { BASE, request, hasArrayField, isArrayBody, downloadReport } from "./core";
import type { DownloadResult } from "./core";
export interface SearchResult {
  query: string;
  mode: string;
  total: number;
  hits: Array<{ filename: string }>;
}

/** The unauthenticated route, and the only one. It answers "is the service up"
 *  and "are the models present" and nothing else.
 *
 *  It used to return document counts, the exact answer-model name and version,
 *  free-text last_error and stalled_reasons, and current_document - a real
 *  document id that the UI joined against the document list to display a
 *  filename. An unauthenticated caller could learn that a specific document
 *  existed and was being processed.
 *
 *  The full worker status lives on /api/metrics, which is scoped. `alive` and
 *  `stalled` remain here because a client has to distinguish "backend down"
 *  from "backend up but stuck", and neither fact is about anybody's
 *  documents. */
export interface HealthWorker {
  alive: boolean;
  stalled: boolean;
  /** work is under way. WHETHER, never WHICH - see the note above. */
  busy: boolean;
}

export interface Health {
  ok: boolean;
  embed_model_present: boolean;
  /** whether an answer model is configured, NOT which one */
  answer_model_configured: boolean;
  ingestion: HealthWorker;
}

/** The watched folder: a host directory the backend scans on an interval and
 *  ingests from, so a team can drop PDFs in rather than upload through the app.
 *
 *  `folder_name` is the folder's own name, never a path, and is null for a
 *  non-admin caller. A screen must render nothing in its place rather than a
 *  placeholder that implies a value was withheld or, worse, that there is none.
 *
 *  The feature being OFF is a normal state, not an error: `enabled` false with
 *  every other field empty. */
export type WatchOutcome = "ingested" | "duplicate" | "failed";

export interface WatchEvent {
  filename: string;
  outcome: WatchOutcome;
  /** ISO-8601 UTC */
  at: string;
  /** why it failed, when it did. null otherwise. */
  detail: string | null;
}

export interface WatchStatus {
  enabled: boolean;
  /** The watched folder's OWN NAME - its last path segment, never a path.
   *
   *  `D:\\project\\data\\watch-inbox` and `\\\\fileserver\\engineering\\inbox` arrive
   *  here as "watch-inbox" and "inbox". The route used to publish the full
   *  host path; under AUTH_MODE=disabled every caller reads as unrestricted,
   *  so the admin gate alone did not hold and the value itself was narrowed.
   *
   *  Still null for a non-admin caller, and null when the configured value has
   *  no final segment. A screen renders nothing in its place - and must not
   *  word it as though a location were being shown. */
  folder_name: string | null;
  /** ISO-8601 UTC, or null when no scan has run. */
  last_scan_at: string | null;
  interval_seconds: number | null;
  /** Did the MOST RECENT scan find the folder readable?
   *
   *  null means no scan has completed yet - never false, which would assert a
   *  failure nobody has observed. Back to null when the feature is turned off.
   *  A screen must render NOTHING for null: "unknown" is a claim of its own. */
  reachable: boolean | null;
  /** A short sentence about the most recent SCAN-LEVEL failure - the folder is
   *  missing, or unreadable. null when the last scan was fine.
   *
   *  A single corrupt PDF is a per-file `failed` event in `recent` and does not
   *  set this. Built from the exception class, never from OS error text, so it
   *  carries no host path and is safe to show a non-admin caller. */
  last_error: string | null;
  /** the newest ten, newest first */
  recent: WatchEvent[];
}

export const structuredSearch = (query: string, kind?: "deliverable" | "finding" | "risk" | "stakeholder") =>
  request<{ results: StructuredSearchResult[] }>(
    `/search/structured?q=${encodeURIComponent(query)}${kind ? `&kind=${kind}` : ""}`,
    undefined,
    hasArrayField("results"),
  );

// The market preview/search contract now lives in contracts/types.ts, which
// this file's own header calls the single source of truth. It was declared
// HERE, and that is exactly how the drift happened: the backend renamed
// `payload` to `payloads`, `tsc` passed, all 23 panel tests passed, and the
// confirmation dialog rendered `undefined` in the one place the whole panel
// exists to fill. Re-exported so existing imports keep working.
export type {
  ClassificationVocabulary,
  ClassificationCoverage,
  ClassificationScope,
  ClassificationSource,
  ClassificationUpdate,
  DocumentClassification,
  BulkRoleUpdate,
  BulkRoleResult,
  AppliedScope,
  CoverageByType,
  SubjectRow,
} from "../types/api";

/* ------------------------------------------------------------ classification
 *
 * Four calls. Two reads that every screen shares, one read per document, and
 * the one write - which the backend gates on the ADMIN capability and answers
 * 404, not 403, to anyone else. A wrong type misroutes searches for everyone,
 * not just for the person who set it, so it needs a role that answers for
 * everyone. `backend/app/main.py::put_document_classification`.
 */
export const classification = {
  /** The filter vocabulary. `types` comes from the register, so a component
   *  MUST render this list rather than a hardcoded three. */
  /** GUARDED ON `types`, like every other list-bearing read in this file. A
   *  body without it used to reach the screen intact: `useTypeVocabulary`
   *  handed back `types: undefined`, and `vocabulary.types.length` took the
   *  Documents view - the app's first screen - down with it. 101 of 108
   *  frontend failures were that one crash. A malformed body is now an
   *  ordinary ApiError, so the filter is simply not offered. */
  vocabulary: () =>
    request<ClassificationVocabulary>(
      "/classification/vocabulary",
      undefined,
      hasArrayField("types"),
    ),
  /** Counts per axis, scoped. This is how a screen gets per-type counts
   *  WITHOUT asking each document its type: one request, no N+1. */
  coverage: () => request<ClassificationCoverage>("/classification/coverage"),
  /** One document's classification. In scope but never classified is a 200
   *  with every field null - not a 404. Null means "awaiting a type". */
  ofDocument: (id: string) =>
    request<DocumentClassification>(
      `/documents/${encodeURIComponent(id)}/classification`,
    ),
  /** CONFIRM or CHANGE. Admin only; a non-admin gets a 404 that says nothing
   *  about whether the document exists. Callers must therefore treat 404
   *  here as "you may not do this", not as "gone". */
  confirm: (id: string, body: ClassificationUpdate) =>
    request<DocumentClassification>(
      `/documents/${encodeURIComponent(id)}/classification`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),
  /** The document types the router knows (never a hardcoded list). */
  kinds: () => request<DocumentKindVocabulary>("/document-kinds"),
  /** A person confirms or corrects the router's suggested document type.
   *  Admin only; a non-admin gets the same silent 404 as `confirm`. */
  confirmKind: (id: string, kind: string) =>
    request<DocumentClassification>(`/documents/${encodeURIComponent(id)}/kind`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind }),
    }),
  /** Set ONE role on MANY documents. Admin only, same as `confirm`.
   *
   *  Answers 207 when some documents were not written, and the result names
   *  each one in `failed`. `request` treats 207 as success - it is a 2xx and
   *  the body is the real answer - so callers MUST read `failed` rather than
   *  assuming `ok` means every document was updated. */
  setRoleBulk: (body: BulkRoleUpdate) =>
    request<BulkRoleResult>("/documents/bulk/role", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

export const documentsApi = {
  /** Who a new upload may be made visible to, and the default (#609). */
  uploadDisciplines: () =>
    request<UploadDisciplines>("/documents/upload-disciplines", undefined, hasArrayField("choices")),
  search: (query: string) => request<SearchResult>(`/search?q=${encodeURIComponent(query)}&limit=8`),
  /** The document list, optionally narrowed.
   *
   *  THE FILTERS ARE APPLIED SERVER-SIDE AND NOWHERE ELSE. They are passed
   *  through to `classification.restrict`, which intersects the matched ids
   *  with the caller's grants and returns a NARROWER AccessScope - so a filter
   *  can only ever shrink what comes back. Filtering the returned array here
   *  instead would be the same defect in a new place: the server would have
   *  already sent rows the caller was not meant to see.
   *
   *  The array-valued filters repeat the key (`?document_role=A&document_role=B`),
   *  which is what FastAPI reads as a list. */
  /** One document by id. Used where a screen holds an id and needs the
   *  record - a finding's citation names a document, not a row. */
  document: (id: string) =>
    request<DocumentRecord>(`/documents/${encodeURIComponent(id)}`),
  documents: (opts: {
    limit?: number; offset?: number; sort?: string; direction?: string;
    q?: string; status?: string;
    document_role?: string[]; discipline?: string[];
    equipment_type?: string[]; project?: string[];
  } = {}) => {
    const q = new URLSearchParams();
    for (const [key, value] of Object.entries(opts)) {
      if (Array.isArray(value)) {
        for (const item of value) if (item !== "") q.append(key, String(item));
        continue;
      }
      if (value != null && value !== "") q.set(key, String(value));
    }
    return request<DocumentPage | DocumentRecord[]>(`/documents${q.toString() ? `?${q}` : ""}`, undefined,
      (body) => Array.isArray(body) || (!!body && typeof body === "object" && Array.isArray((body as { items?: unknown }).items)))
      .then((result) => result.ok
        ? { ...result, data: Array.isArray(result.data) ? result.data : result.data.items }
        : result);
  },
  chunks: (id: string, opts: { limit?: number; offset?: number; retrievable?: string } = {}) => {
    const q = new URLSearchParams();
    if (opts.limit != null) q.set("limit", String(opts.limit));
    if (opts.offset != null) q.set("offset", String(opts.offset));
    if (opts.retrievable) q.set("retrievable", opts.retrievable);
    return request<ChunkPage>(`/documents/${encodeURIComponent(id)}/chunks?${q}`);
  },
  pages: (id: string, opts: { limit?: number; offset?: number } = {}) => {
    const q = new URLSearchParams();
    if (opts.limit != null) q.set("limit", String(opts.limit));
    if (opts.offset != null) q.set("offset", String(opts.offset));
    return request<PagesResponse>(`/documents/${encodeURIComponent(id)}/pages?${q}`);
  },
  excluded: (id: string, opts: { limit?: number; offset?: number } = {}) => {
    const q = new URLSearchParams();
    if (opts.limit != null) q.set("limit", String(opts.limit));
    if (opts.offset != null) q.set("offset", String(opts.offset));
    return request<ExclusionsResponse>(`/documents/${encodeURIComponent(id)}/excluded?${q}`);
  },
  /** The plain rendered page. */
  pageImageUrl: (id: string, page: number) =>
    `${BASE}/documents/${encodeURIComponent(id)}/pages/${page}/image`,
  /** The ORIGINAL uploaded bytes, fetched with the bearer header.
   *
   *  Used for the PDF viewer, the workbook preview and "download original" -
   *  one route, so the previewed bytes and the downloaded bytes cannot differ.
   *
   *  A URL STRING IS DELIBERATELY NOT RETURNED. Handing one to an `<iframe
   *  src>`, an `<a href>` or `window.open` sends a request with no
   *  Authorization header, which under auth_mode=demo_required is a 404 that
   *  reads to the user as "this document does not exist" - the exact defect
   *  already fixed for page images (`useAuthedImage`), for report downloads
   *  (`downloadReport`) and for uploads (`authorize`). The token stays in the
   *  header and never goes on a URL, where it would reach browser history,
   *  proxy logs and Referer headers.
   *
   *  The caller owns the returned bytes and the object URL it makes from them,
   *  and must revoke it. */
  originalFile: (id: string, filename: string): Promise<DownloadResult> =>
    downloadReport(`/documents/${encodeURIComponent(id)}/original`, filename),
  /** ------------------------------------------- the Standards Library
   *
   *  One database, one set of grants, one retrieval path. These read the same
   *  documents and chunks as everything else, scoped the same way; "library"
   *  describes what the reader sees. */
  standards: (opts: { include_superseded?: boolean } = {}) => {
    const q = new URLSearchParams();
    if (opts.include_superseded != null) {
      q.set("include_superseded", String(opts.include_superseded));
    }
    return request<StandardSummary[]>(
      `/standards${q.toString() ? `?${q}` : ""}`, undefined, isArrayBody);
  },
  standardClauses: (id: string) =>
    request<StandardClause[]>(
      `/standards/${encodeURIComponent(id)}/clauses`, undefined, isArrayBody),
  standardRequirements: (id: string) =>
    request<StandardRequirement[]>(
      `/standards/${encodeURIComponent(id)}/requirements`, undefined, isArrayBody),
  standardRevisions: (id: string) =>
    request<StandardSummary[]>(
      `/standards/${encodeURIComponent(id)}/revisions`, undefined, isArrayBody),
  /** Re-read a standard and record every obligation it states. ADMIN. */
  extractStandardRequirements: (id: string) =>
    request<StandardExtraction>(
      `/standards/${encodeURIComponent(id)}/requirements/extract`,
      { method: "POST" }),
  /** #645: checks the AI proposed for clause sentences, verified by code,
   *  waiting for the engineer. */
  clauseCheckDrafts: () =>
    request<ClauseCheckDraft[]>("/standards/clause-checks", undefined, isArrayBody),
  /** #645: accept (a confirmed, versioned limit) or reject a draft. ADMIN, audited. */
  decideClauseCheck: (id: string, decision: "accept" | "reject") =>
    request<ClauseCheckDecisionResult>(
      `/standards/clause-checks/${encodeURIComponent(id)}/decision`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision }),
      }),
  /** Mark a standard as replaced, or clear the mark with null. ADMIN, audited. */
  /** Standards cited but not in the library, with the publisher's catalogue
   *  page and whether each has been requested. Nothing is fetched. */
  missingStandards: () =>
    request<MissingStandard[]>("/standards/missing", undefined, isArrayBody),
  /** Record, under the signed-in engineer's name, that a missing standard
   *  has been asked for. */
  requestMissingStandard: (identifier: string, note: string | null) =>
    request<{ identifier: string; status: string; requested_by: string; requested_at: string }>(
      "/standards/missing/request",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identifier, note }),
      }),
  supersedeStandard: (id: string, superseded_by: string | null) =>
    request<{ superseded_by: string | null }>(
      `/standards/${encodeURIComponent(id)}/supersede`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ superseded_by }),
      }),
  /** A read-only view of a stored workbook: sheets and populated cells.
   *
   *  Read on the SERVER with the Python standard library rather than by a
   *  spreadsheet parser in the browser - see `backend/app/workbook.py` for
   *  why. The original bytes are untouched by this call; `originalFile` still
   *  serves the file itself. */
  workbook: (id: string) =>
    request<WorkbookPreview>(
      `/documents/${encodeURIComponent(id)}/workbook`,
      undefined,
      hasArrayField("sheets"),
    ),
  /** The rendered page with the answering sentence BOXED on the image.
   *
   *  The box is drawn server-side, in PDF coordinate space where the
   *  rectangles were measured. Overlaying in CSS would mean reproducing the
   *  page-to-image transform here as well, and any drift between the two
   *  draws the box slightly off - on a dense specification table, slightly
   *  off is the wrong row.
   *
   *  When the sentence cannot be located the page comes back with no box and
   *  `X-Answer-Located: 0`. */
  pageImageWithAnswerUrl: (
    id: string,
    page: number,
    chunkId: string,
    question: string,
  ) => {
    const q = new URLSearchParams({ chunk_id: chunkId, q: question });
    return `${BASE}/documents/${encodeURIComponent(id)}/pages/${page}/image?${q}`;
  },
  extract: (id: string) =>
    request<unknown>(`/documents/${encodeURIComponent(id)}/extract`, { method: "POST" }),
  chunk: (id: string) =>
    request<unknown>(`/documents/${encodeURIComponent(id)}/chunk`, { method: "POST" }),
  embed: (id: string) =>
    request<unknown>(`/documents/${encodeURIComponent(id)}/embed`, { method: "POST" }),
  remove: (id: string) =>
    request<DeletedDocument>(`/documents/${encodeURIComponent(id)}?confirm=true`, {
      method: "DELETE",
    }),

};
