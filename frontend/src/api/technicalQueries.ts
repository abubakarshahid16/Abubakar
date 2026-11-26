import { hasArrayField, request, type Result } from "./core";

export interface TechnicalQuery {
  id: string;
  subject: string;
  contractor_name: string | null;
  department: string | null;
  /** Read from the subject by code: TQ (technical query) or CFC (conflict finding clarification), the running number, the discipline code, the short title. */
  ref_type?: string | null;
  ref_number?: string | null;
  discipline_code?: string | null;
  title_short?: string | null;
  /** 1 when the subject carried no TQ/CFC number: kept, and flagged for a person. */
  needs_person?: number | null;
  routing_source?: string | null;
  assignee_user_id: string | null;
  /** The email's own question, as received. */
  extracted_question: string | null;
  attachment_context?: Array<{ filename: string; page: number; text: string }>;
  /** A clean question the system proposes; a guess until an engineer confirms it. */
  proposed_question?: string | null;
  /** The questions the local model found in the attachment, one by one with their page. Proposals only: the engineer ticks and confirms. */
  proposed_questions?: Array<{ question: string; filename: string | null; page: number | null }>;
  /** "model_unavailable" when the local model could not propose any. */
  proposal_note?: string | null;
  /** Which attachment pages were read for questions, and which were not (a visible mark: nothing is cut without saying so). */
  attachment_reading?: Array<{ filename: string; pages_read: number; page_count: number | null; line: string }>;
  /** The newest "prepare evidence" job: it runs in the background, one at a time, and waits for a running review. */
  evidence_job?: { id: string; state: "queued" | "running" | "done" | "failed"; progress_done: number; progress_total: number; label: string | null; error: string | null } | null;
  /** How many contracts the evidence search covered: "Searched N of N contracts, hits in M." */
  evidence_coverage?: { searched: number; of: number; hits_in: number; failed: number; line: string; matching_passages?: number; key_terms?: number; /** The best passage's own reranker score: a number from the search, never a verdict. */ top_rerank_score?: number | null } | null;
  confirmed_question?: string | null;
  confirmed_question_by?: string | null;
  confirmed_question_at?: string | null;
  status: string;
  priority: string;
  received_at: string;
  due_at: string | null;
  extracted_question_main?: string | null;
  extracted_question_folded?: string | null;
  messages?: Array<{ id: string; is_inbound?: number | boolean; body_main?: string; body_folded?: string; from_address: string; to_addresses: string[]; cc_addresses: string[]; sent_at: string | null; received_at: string; subject: string; body: string; raw_message_hash: string | null; attachments: Array<{ id: string; filename: string; media_type?: string | null; size_bytes: number; document_id: string | null; filed_at?: string | null; scan_status: string; scan_detail?: string | null; parse_status: string }> }>;
  evidence?: Array<{ id: string; document_id: string; page_start: number | null; /** The clause heading the passage stands under ("6.1 Painting"), read by code; null when none was found. */ locator?: string | null; /** How many of the question's key terms the passage holds, out of `match_terms`; `match_ok` 1 when at least half. */ match_count?: number | null; match_terms?: number | null; match_ok?: number | null; exact_quote: string; evidence_state: string; supersession_state: string }>;
  /** True when the signed-in person holds the technical-query reviewer role. The server enforces it. */
  can_review?: boolean;
  drafts?: Array<{ id: string; version: number; answer: string; assumptions_json: string; unresolved_json: string; citations_json: string; model: string | null }>;
  decisions?: Array<{ decision: string; comment: string | null; created_at: string }>;
  source_access_revoked?: boolean;
  /** True when the attachment text was left out because the signed-in person may not read that attachment. */
  attachment_text_hidden?: boolean;
}

export interface TechnicalQueryFilters {
  status?: string;
  contractor?: string;
  department?: string;
  assignee_user_id?: string;
  received_from?: string;
  received_to?: string;
  evidence_state?: string;
  ref_type?: string;
  discipline?: string;
  number?: string;
  needs_person?: boolean;
}

export interface MailboxImportJob {
  id: string;
  kind: "import" | "poll";
  state: "queued" | "running" | "done" | "failed";
  total: number;
  done: number;
  failed: number;
  error: string | null;
  failures: Array<{ subject: string; reason: string }>;
  /** Messages imported (or already held): `done` less the listed messages that were not ones to import. */
  imported?: number;
  /** {reason: count} of listed messages that were not imported (sent from this mailbox, not under the label). */
  skipped?: Record<string, number>;
  /** The queries this mailbox's messages are in (replies and forwards with the same number join one query). */
  queries?: number | null;
  /** The messages of this mailbox stored now (any import or poll). */
  messages?: number | null;
  /** False for an import that ran before skipped messages were counted by reason. */
  reasons_recorded?: boolean;
}

/** The finished import in one sentence, every count with its boundary: "77 messages in 33 queries: 36 imported, 40 our replies, added to
 *  their query (sent by us), 1 failed." A listed message that was not imported is never called imported. */
export function importDoneWords(job: MailboxImportJob): string {
  if (job.reasons_recorded === false) {
    // an import that ran before the reasons were counted: never "imported N of N"; what is stored is said, and that the rest is unknown
    const stored = typeof job.messages === "number" ? job.messages : null;
    const where = typeof job.queries === "number" ? ` of ${job.queries} ${job.queries === 1 ? "query" : "queries"}` : "";
    const held = stored === null ? "" : `; ${stored} stored as messages${where}`;
    const rest = stored === null ? job.total : Math.max(0, job.total - stored);
    return `Import finished: processed ${job.total} messages${held}; the reason the other ${rest} were not stored was not recorded for this import (it ran before this was counted).`;
  }
  const parts = [`${job.imported ?? job.done} imported`];
  for (const [why, n] of Object.entries(job.skipped ?? {})) if (n > 0) parts.push(`${n} ${why}`);
  if (job.failed) parts.push(`${job.failed} failed`);
  const where = typeof job.queries === "number" ? ` in ${job.queries} ${job.queries === 1 ? "query" : "queries"}` : "";
  return `Import finished: ${job.total} messages${where}: ${parts.join(", ")}.`;
}

export interface TechnicalQueryMailbox {
  id: string;
  email: string;
  connection_state: string;
  label_id: string | null;
  last_checked_at?: string | null;
  status_note?: string | null;
  import_job?: MailboxImportJob | null;
}

export interface RoutingRule { id: string; match_type: "address" | "domain"; match_value: string; contractor_name: string | null; department: string | null }
export interface GmailLabel { id: string; name: string; type: string }
export interface TechnicalQueryAssignee { id: string; display_name: string }

function queryPath(filters: TechnicalQueryFilters): string {
  const values = Object.entries(filters).filter(([, value]) => Boolean(value)).map(([key, value]) => [key, String(value)]);
  const params = new URLSearchParams(values as [string, string][]);
  return `/technical-queries${params.size ? `?${params}` : ""}`;
}

export const technicalQueriesApi = {
  list: (filters: TechnicalQueryFilters = {}): Promise<Result<{ items: TechnicalQuery[] }>> =>
    request(queryPath(filters), undefined, hasArrayField("items")),
  metrics: (filters: Omit<TechnicalQueryFilters, "status"> = {}): Promise<Result<Record<string, number>>> =>
    request(queryPath(filters).replace("/technical-queries", "/technical-queries/metrics")),
  mailboxes: (): Promise<Result<{ items: TechnicalQueryMailbox[] }>> =>
    request("/technical-queries/providers/gmail/mailboxes", undefined, hasArrayField("items")),
  startGmail: (): Promise<Result<{ authorization_url: string }>> =>
    request("/technical-queries/providers/gmail/oauth/start"),
  /** The end of the Google connection: the app's own return page posts what Google sent, as a same-site request (so the sign-in cookie goes). */
  completeGmail: (body: { code?: string | null; state?: string | null; error?: string | null }): Promise<Result<{ result: "connected" | "admin_must_allow"; mailbox_id: string | null }>> =>
    request("/technical-queries/providers/gmail/oauth/complete", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  gmailLabels: (mailboxId: string): Promise<Result<{ items: GmailLabel[] }>> =>
    request(`/technical-queries/providers/gmail/mailboxes/${encodeURIComponent(mailboxId)}/labels`, undefined, hasArrayField("items")),
  /** "Check now": queues one poll; answers at once. */
  checkNow: (mailboxId: string): Promise<Result<{ import_job: string }>> =>
    request(`/technical-queries/providers/gmail/mailboxes/${encodeURIComponent(mailboxId)}/check-now`, { method: "POST" }),
  activateGmailLabel: (mailboxId: string, labelId: string): Promise<Result<{ imported: number; connection_state: string; import_job?: string | null }>> =>
    request(`/technical-queries/providers/gmail/mailboxes/${encodeURIComponent(mailboxId)}/activate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ label_id: labelId }) }),
  get: (id: string): Promise<Result<TechnicalQuery>> => request(`/technical-queries/${encodeURIComponent(id)}`),
  assignees: (): Promise<Result<{ items: TechnicalQueryAssignee[] }>> =>
    request("/technical-queries/assignees", undefined, hasArrayField("items")),
  assign: (id: string, assigneeUserId: string): Promise<Result<TechnicalQuery>> =>
    request(`/technical-queries/${encodeURIComponent(id)}/assignment`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ assignee_user_id: assigneeUserId }) }),
  triage: (id: string, fields: { contractor_name: string | null; department: string | null; priority: string; due_at: string | null }): Promise<Result<TechnicalQuery>> =>
    request(`/technical-queries/${encodeURIComponent(id)}/triage`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(fields) }),
  /** Files a mailbox attachment into the library on purpose, with a role (until then it stays out of search, Chat and the review picker). */
  fileIntoLibrary: (id: string, attachmentId: string, role: string): Promise<Result<TechnicalQuery>> =>
    request(`/technical-queries/${encodeURIComponent(id)}/attachments/${encodeURIComponent(attachmentId)}/file-into-library`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role }) }),
  confirmQuestion: (id: string, question: string): Promise<Result<TechnicalQuery>> =>
    request(`/technical-queries/${encodeURIComponent(id)}/confirm-question`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question }) }),
  classifyEvidence: (id: string, evidenceId: string, evidenceState: string, supersessionState: string): Promise<Result<TechnicalQuery>> =>
    request(`/technical-queries/${encodeURIComponent(id)}/evidence/${encodeURIComponent(evidenceId)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ evidence_state: evidenceState, supersession_state: supersessionState }) }),
  routingRules: (): Promise<Result<{ items: RoutingRule[] }>> =>
    request("/technical-queries/routing-rules", undefined, hasArrayField("items")),
  saveRoutingRule: (rule: Omit<RoutingRule, "id">): Promise<Result<{ items: RoutingRule[] }>> =>
    request("/technical-queries/routing-rules", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(rule) }),
  deleteRoutingRule: (id: string): Promise<Result<{ items: RoutingRule[] }>> =>
    request(`/technical-queries/routing-rules/${encodeURIComponent(id)}`, { method: "DELETE" }),
  prepareEvidence: (id: string): Promise<Result<TechnicalQuery>> => request(`/technical-queries/${encodeURIComponent(id)}/prepare-evidence`, { method: "POST" }),
  /** `engine: "claude"` sends only `documentIds` (the contract documents the engineer chose for this one query) and is refused while the server's draft engine is local. */
  generateDraft: (id: string, engine: "local" | "claude" = "local", documentIds: string[] = []): Promise<Result<TechnicalQuery>> =>
    request(`/technical-queries/${encodeURIComponent(id)}/generate-draft`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ engine, document_ids: documentIds }) }),
  /** A query entered by hand with its papers, so the feature works with no mailbox. */
  createByHand: (form: FormData): Promise<Result<{ item: TechnicalQuery; uploaded: number }>> =>
    request("/technical-queries/manual", { method: "POST", body: form }),
  createDraft: (id: string, answer: string): Promise<Result<TechnicalQuery>> => request(`/technical-queries/${encodeURIComponent(id)}/drafts`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answer }) }),
  decide: (id: string, decision: string, draftId?: string): Promise<Result<TechnicalQuery>> => request(`/technical-queries/${encodeURIComponent(id)}/decisions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision, draft_id: draftId }) }),
  confirmResolution: (id: string): Promise<Result<TechnicalQuery>> => request(`/technical-queries/${encodeURIComponent(id)}/confirm-resolution`, { method: "POST" }),
};

type QueryAttachment = { filename: string; media_type?: string | null; document_id: string | null; parse_status: string; scan_status: string };

/** Why an attachment of a query was NOT read, in plain words, or null when it was read (its paper is in and ready). Nothing is silently
 *  missing: a picture, a macro file, a Word file and an unread PDF are each named (lead-4, 26 Nov 2026). */
export function notReadWhy(a: QueryAttachment): string | null {
  const name = a.filename.toLowerCase();
  const ext = name.includes(".") ? name.slice(name.lastIndexOf(".") + 1) : "";
  if (a.document_id && a.parse_status === "ready") return null;
  if (/^(xlsm|xltm|docm|dotm|pptm|potm|ppsm|xlam|ppam)$/.test(ext) || /macroenabled/i.test(a.media_type ?? "")) return "macro file, not opened";
  if ((a.media_type ?? "").startsWith("image/") || /^(png|jpe?g|gif|bmp|tiff?|webp|heic)$/.test(ext)) return "picture, not read";
  if (ext === "docx") {
    if (a.scan_status === "static_check_flagged") return "Word with active content, its text is not used";
    if (a.scan_status === "static_check_unreadable") return "Word, could not be checked";
    return a.parse_status === "failed" ? "Word, could not be read" : "Word, not read yet";
  }
  if (/^(doc|dotx|rtf|odt)$/.test(ext)) return `older Word format (.${ext}), not read: save it as .docx`;
  if (ext === "pdf") return a.parse_status === "failed" ? "PDF, could not be read" : a.scan_status === "static_check_flagged" ? "PDF with active content, its text is not used" : "PDF, not read yet";
  return `${ext ? ext.toUpperCase() + " file" : "file"}, not read`;
}

/** "3 of 7 attachments read" over every message of the query (the boundary: this query's attachments), with each one not read and why. */
export function attachmentsRead(messages: Array<{ attachments: QueryAttachment[] }> | undefined): { line: string; notRead: Array<{ filename: string; why: string }> } | null {
  const all = (messages ?? []).flatMap((m) => m.attachments);
  if (!all.length) return null;
  const notRead = all.flatMap((a) => { const why = notReadWhy(a); return why ? [{ filename: a.filename, why }] : []; });
  return { line: `${all.length - notRead.length} of ${all.length} attachment${all.length === 1 ? "" : "s"} read`, notRead };
}
