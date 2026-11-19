import { hasArrayField, request, type Result } from "./core";

export interface TechnicalQuery {
  id: string;
  subject: string;
  contractor_name: string | null;
  department: string | null;
  assignee_user_id: string | null;
  extracted_question: string | null;
  status: string;
  priority: string;
  received_at: string;
  messages?: Array<{ from_address: string; to_addresses: string[]; cc_addresses: string[]; sent_at: string | null; received_at: string; subject: string; body: string; attachments: Array<{ filename: string; size_bytes: number; document_id: string | null; scan_status: string; parse_status: string }> }>;
  evidence?: Array<{ id: string; document_id: string; page_start: number | null; exact_quote: string; evidence_state: string; supersession_state: string }>;
  drafts?: Array<{ id: string; version: number; answer: string; assumptions_json: string; unresolved_json: string }>;
  decisions?: Array<{ decision: string; comment: string | null; created_at: string }>;
  source_access_revoked?: boolean;
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
  get: (id: string): Promise<Result<TechnicalQuery>> => request(`/technical-queries/${encodeURIComponent(id)}`),
  prepareEvidence: (id: string): Promise<Result<TechnicalQuery>> => request(`/technical-queries/${encodeURIComponent(id)}/prepare-evidence`, { method: "POST" }),
  generateDraft: (id: string): Promise<Result<TechnicalQuery>> => request(`/technical-queries/${encodeURIComponent(id)}/generate-draft`, { method: "POST" }),
  createDraft: (id: string, answer: string): Promise<Result<TechnicalQuery>> => request(`/technical-queries/${encodeURIComponent(id)}/drafts`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answer }) }),
  decide: (id: string, decision: string, draftId?: string): Promise<Result<TechnicalQuery>> => request(`/technical-queries/${encodeURIComponent(id)}/decisions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision, draft_id: draftId }) }),
  confirmResolution: (id: string): Promise<Result<TechnicalQuery>> => request(`/technical-queries/${encodeURIComponent(id)}/confirm-resolution`, { method: "POST" }),
};
