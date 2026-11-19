import { hasArrayField, request, type Result } from "./core";

export interface TechnicalQuery {
  id: string;
  subject: string;
  contractor_name: string | null;
  department: string | null;
  extracted_question: string | null;
  status: string;
  priority: string;
  received_at: string;
  messages?: Array<{ from_address: string; to_addresses: string[]; cc_addresses: string[]; sent_at: string | null; received_at: string; subject: string; body: string; attachments: Array<{ filename: string; size_bytes: number; document_id: string | null }> }>;
  evidence?: Array<{ id: string; document_id: string; page_start: number | null; exact_quote: string; evidence_state: string; supersession_state: string }>;
  drafts?: Array<{ id: string; version: number; answer: string; assumptions_json: string; unresolved_json: string }>;
  decisions?: Array<{ decision: string; comment: string | null; created_at: string }>;
  source_access_revoked?: boolean;
}

export const technicalQueriesApi = {
  list: (): Promise<Result<{ items: TechnicalQuery[] }>> =>
    request("/technical-queries", undefined, hasArrayField("items")),
  get: (id: string): Promise<Result<TechnicalQuery>> => request(`/technical-queries/${encodeURIComponent(id)}`),
  prepareEvidence: (id: string): Promise<Result<TechnicalQuery>> => request(`/technical-queries/${encodeURIComponent(id)}/prepare-evidence`, { method: "POST" }),
  generateDraft: (id: string): Promise<Result<TechnicalQuery>> => request(`/technical-queries/${encodeURIComponent(id)}/generate-draft`, { method: "POST" }),
  createDraft: (id: string, answer: string): Promise<Result<TechnicalQuery>> => request(`/technical-queries/${encodeURIComponent(id)}/drafts`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answer }) }),
  decide: (id: string, decision: string, draftId?: string): Promise<Result<TechnicalQuery>> => request(`/technical-queries/${encodeURIComponent(id)}/decisions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision, draft_id: draftId }) }),
  confirmResolution: (id: string): Promise<Result<TechnicalQuery>> => request(`/technical-queries/${encodeURIComponent(id)}/confirm-resolution`, { method: "POST" }),
};
