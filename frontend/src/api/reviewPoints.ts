/**
 * The redesigned review page's calls (owner, 12 Nov 2026; SPEC.md): the plan before a review starts, the ONE list of points of a
 * paper, a decision on each, the engineer's own points, and the owner's yes for a contract. Every route except `pageV2Switch` answers
 * 404 "feature_off" while `REVIEW_PAGE_V2_ENABLED` is off; the switch itself always answers.
 */
import { request, type Result } from "./core";

export type EngineChoice = "automatic" | "claude" | "local";
export const ENGINE_CHOICES: readonly EngineChoice[] = ["automatic", "claude", "local"];

export interface PlanPart { name: "rule_check" | "ai_review"; engine: "claude" | "local" | "not_run"; why: string }
export interface ReviewPlan {
  choice: EngineChoice;
  parts: PlanPart[];
  text_leaves: boolean;
  refused: string | null;
  refused_code: string | null;
  needs_yes: boolean;
  unscored: boolean;
  unscored_note?: string;
  wont_run: { part: string; why: string }[];
  kind: string | null;
  documents: { paper: boolean; rule_books: string[]; rule_books_note: string | null };
  cost: {
    at_most_usd: number | null;
    by_part_at_most_usd: { rule_check: number | null; ai_review: number | null };
    basis: string | null;
    last_review_usd: number | null;
    last_review_note: string | null;
    exact: false;
  };
  notes: string[];
  sentence: string;
  contract_yes: { document_id?: string; status?: string; approved_by?: string; approved_on?: string } | null;
}

export interface PointDecision {
  state: "keep" | "edit" | "remove" | null;
  words: string;
  by?: string | null;
  at?: string | null;
  text?: string | null;
  reason?: string | null;
}

export interface ReviewPoint {
  id: string;
  source: "rule_check" | "ai_review" | "added";
  source_words: string;
  engine: string | null;
  rank: number;
  tile: "not_met" | "questions" | "met" | "does_not_apply";
  firm: string | null;
  other_kind: string | null;
  name: string;
  page: number | null;
  rule_book: string | null;
  clause: string | null;
  action: string | null;
  paper_quote: string | null;
  clause_quote: string | null;
  paper_quote_note: string;
  clause_quote_note: string;
  route_note: string | null;
  view_page: { document_id: string; page: number; image_url: string } | null;
  group_key: string | null;
  added_by: string | null;
  n_alike: number;
  pill: string;
  decision: PointDecision;
}

export interface TileCounts {
  label: string;
  total: number;
  two_readers?: number | null;
  one_reader?: number;
  proven_by_code?: number | null;
  groups?: number;
}

export interface ProposedCode {
  code: string | null;
  reason: string;
  line: string;
  so_far: boolean;
  undecided: number;
  rule: string;
  proposed_by: string;
}

export interface PointsListing {
  paper_document_id: string;
  runs: { rule_check: string | null; ai_review: string | null };
  points: ReviewPoint[];
  counts: {
    tiles: Record<ReviewPoint["tile"], TileCounts>;
    total: number;
    rule_books: { name: string; points: number }[];
    other_rule_books_points: number;
    other_rule_books_note: string | null;
    not_held: { names: string[]; more: number; total: number; note: string | null };
    decided?: number;
    decided_of?: number;
  };
  proposed_code: ProposedCode;
  final_code: string | null;
  code_run_id: string | null;
  decided: number;
  of: number;
  removed: ReviewPoint[];
}

const JSON_HEADERS = { "Content-Type": "application/json" };
const paper = (id: string) => `/reviews/papers/${encodeURIComponent(id)}/points`;
const isObject = (b: unknown): b is Record<string, unknown> => typeof b === "object" && b !== null;

/** Whether the redesigned page is on. Anything unreadable is "off": the old page stays. */
export async function pageV2Switch(): Promise<boolean> {
  try {
    const r = await request<{ enabled: boolean }>("/reviews/page-v2", undefined, (b) => isObject(b) && typeof b.enabled === "boolean");
    return r.ok && r.data.enabled;
  } catch {
    return false;
  }
}

export const reviewPoints = {
  plan: (documentId: string, engine: EngineChoice) =>
    request<ReviewPlan>(
      `/reviews/plan?submittal_document_id=${encodeURIComponent(documentId)}&engine=${engine}`,
      undefined, (b) => isObject(b) && Array.isArray(b.parts) && typeof b.sentence === "string",
    ),
  list: (documentId: string) =>
    request<PointsListing>(paper(documentId), undefined, (b) => isObject(b) && Array.isArray(b.points) && isObject(b.counts)),
  decide: (documentId: string, body: { point_id: string; state: "keep" | "edit" | "remove"; text?: string; reason?: string }) =>
    request<PointsListing>(`${paper(documentId)}/decision`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) }),
  keepAll: (documentId: string, pointIds: string[]) =>
    request<PointsListing>(`${paper(documentId)}/decisions`, {
      method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ point_ids: pointIds }),
    }),
  add: (documentId: string, body: { text: string; page?: number; rule_book?: string; clause?: string }) =>
    request<PointsListing>(`${paper(documentId)}/add`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) }),
  start: (documentId: string, engine: EngineChoice) =>
    request<{ review_run_id: string }>("/reviews/start", {
      method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ submittal_document_id: documentId, engine }),
    }),
  recordYes: (documentId: string) =>
    request<unknown>("/reviews/contract-yes", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ document_id: documentId }) }),
};

export type { Result };
