import { hasArrayField, request, type Result } from "./core";

export interface TechnicalQuery {
  id: string;
  subject: string;
  contractor_name: string | null;
  department: string | null;
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
  evidence_coverage?: { searched: number; of: number; hits_in: number; failed: number; line: string } | null;
  confirmed_question?: string | null;
  confirmed_question_by?: string | null;
  confirmed_question_at?: string | null;
  status: string;
  priority: string;
  received_at: string;
  due_at: string | null;
  messages?: Array<{ id: string; from_address: string; to_addresses: string[]; cc_addresses: string[]; sent_at: string | null; received_at: string; subject: string; body: string; raw_message_hash: string | null; attachments: Array<{ id: string; filename: string; size_bytes: number; document_id: string | null; filed_at?: string | null; scan_status: string; scan_detail?: string | null; parse_status: string }> }>;
  evidence?: Array<{ id: string; document_id: string; page_start: number | null; exact_quote: string; evidence_state: string; supersession_state: string }>;
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
}

export interface TechnicalQueryMailbox {
  id: string;
  email: string;
  connection_state: string;
  label_id: string | null;
}

export interface RoutingRule { id: string; match_type: "address" | "domain"; match_value: string; contractor_name: string | null; department: string | null }
export interface GmailLabel { id: string; name: string; type: string }
export interface TechnicalQueryAssignee { id: string; display_name: string }

function queryPath(filters: TechnicalQueryFilters): string {
  const values = Object.entries(filters).filter(([, value]) => Boolean(value));
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
  activateGmailLabel: (mailboxId: string, labelId: string): Promise<Result<{ imported: number; connection_state: string }>> =>
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
