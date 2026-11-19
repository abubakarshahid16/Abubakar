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
  messages?: Array<{ from_address: string; subject: string; body: string; attachments: Array<{ filename: string; document_id: string | null }> }>;
  evidence?: Array<{ document_id: string; page_start: number | null; exact_quote: string }>;
  drafts?: Array<{ id: string; version: number; answer: string; assumptions_json: string; unresolved_json: string }>;
  decisions?: Array<{ decision: string; comment: string | null; created_at: string }>;
}

export const technicalQueriesApi = {
  list: (): Promise<Result<{ items: TechnicalQuery[] }>> =>
    request("/technical-queries", undefined, hasArrayField("items")),
  get: (id: string): Promise<Result<TechnicalQuery>> => request(`/technical-queries/${encodeURIComponent(id)}`),
};
