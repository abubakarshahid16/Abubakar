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
  documents: {
    paper: boolean; rule_books: string[]; rule_books_note: string | null;
    /** Every document a Claude review of this paper may send, before the start (absent: the list is not known). */
    leaving?: { id: string; title: string; kind: string; why: string; contract?: boolean }[];
    not_sent?: { id?: string; title?: string; name?: string; kind: string; why: string; reason: string }[];
    not_readable?: number;
    /** True when the list could not be worked out: no Claude start is offered. */
    unreadable?: boolean;
    /** Only with the online search for rule books not held on and the AI review on Claude: what that search may send. */
    web_search?: string;
  };
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

/** The four tiles. A line the AI thinks does not apply (no proof) is in none of them: it is its own section ("na_to_confirm"). */
export type TileName = "not_met" | "questions" | "met" | "does_not_apply";

export interface ReviewPoint {
  id: string;
  source: "rule_check" | "ai_review" | "added";
  source_words: string;
  engine: string | null;
  rank: number;
  tile: TileName | "na_to_confirm";
  firm: string | null;
  other_kind: string | null;
  name: string;
  page: number | null;
  /** The first readable rule book of the point (its own name). */
  rule_book: string | null;
  /** Every rule book the point cites that the viewer may read, by identity (a document id) and the book's own name. */
  books?: { id: string; name: string }[];
  /** The equipment tags the point's name carried; shown in the opened point, never in the collapsed row. */
  tags?: string[];
  /** What the stored finding holds (U5d): shown as stored, never as verified. */
  paper_value?: string | null;
  rule_text?: string | null;
  /** Our own checklist's wording (order 14 lane B): shown as ours, never as the rule book's words. */
  check_text?: string | null;
  reason_words?: string | null;
  checked_by?: string | null;
  action_source?: string | null;
  /** True when the point cites no rule book at all (it sits under "No rule book"). */
  no_book?: boolean;
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
  /** LP0 (owner, 17 Nov 2026): the AI's own answer on a line code did not prove, labelled ("Fail (AI, rule not approved, engineer to
   *  confirm)"), and its line with the standard, clause, page and quote ("quote not found by code" when code did not find it). Words
   *  only: such a point is never a decision. Absent (null) on a code-proven point, a two-reader verdict and a point with no AI answer. */
  ai_label?: string | null;
  ai_answer?: string | null;
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
    tiles: Record<TileName, TileCounts>;
    /** Owner on PR #1872: the lines the AI thinks do not apply, to confirm, counted apart from the tiles. */
    not_applicable_to_confirm?: { label: string; total: number; confirmed: number; open: number; sentence: string | null };
    total: number;
    rule_books: { id?: string; name: string; points: number }[];
    no_rule_book_points?: number;
    /** Points that cite more than one readable rule book: each is counted under every one of its books. */
    several_books_points?: number;
    other_rule_books_points: number;
    other_rule_books_note: string | null;
    not_held: {
      names: string[];
      more: number;
      total: number;
      note: string | null;
      /** Only with the online search on: what it found for each rule book not held, in the backend's own words, "not verified"; never a rule, a clause or a point. */
      found_online?: { name: string; outcome: string | null; words: string; url: string | null }[];
    };
    decided?: number;
    decided_of?: number;
  };
  proposed_code: ProposedCode;
  final_code: string | null;
  /** The recorded code as the page and each file print it (an approving code recorded with points open says so); null: none. */
  final_code_words?: { team: string | null; contractor: string | null };
  code_run_id: string | null;
  decided: number;
  of: number;
  removed: ReviewPoint[];
  /** What the AI review's contractor copy holds for this paper's kind, in the backend's own words. */
  contractor_copy?: { kind: string | null; words: string };
  /** Rule books the review found only while it ran and did not send (not on the list shown before the start). */
  found_during_review?: number;
  /** P2: the comments (one per field) the CRS file shows, from the same grouping function; every point is in exactly one comment or removed. */
  comments?: { number: number; name: string | null; n_points: number; pill: string; pages: number[]; member_ids: string[]; disagree: boolean }[];
  comment_count?: number;
  /** The three counts of the last review (page, database, file rows). null when none is stored; ok false means the page must say what is missing. */
  completeness?: { ok: boolean; page: number; database: number; team_rows: number; contractor_rows: number; missing: string[]; sentence: string | null; checked_at: string } | null;
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

/** Owner order, 16 Nov 2026: whether the older per-review CRS files (they do not state "N points reviewed, N in this file") are
 *  offered. False only when the server says so; anything unreadable keeps them, as before (the server refuses them with a sentence
 *  when they are off, so a button shown by mistake gives no file). */
export async function oldCrsDownloadOffered(): Promise<boolean> {
  try {
    const r = await request<{ enabled: boolean; old_crs_download?: boolean }>("/reviews/page-v2", undefined, (b) => isObject(b) && typeof b.enabled === "boolean");
    return !(r.ok && r.data.old_crs_download === false);
  } catch {
    return true;
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
  /** Tick "does not apply" on one line, or on every open line of the section ("Confirm all"): one decision per line. */
  confirmNotApplicable: (documentId: string, pointIds: string[]) =>
    request<PointsListing>(`${paper(documentId)}/not-applicable/confirm`, {
      method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ point_ids: pointIds }),
    }),
  /** Undo one tick: the line is open again (the tick stays in the record). */
  undoNotApplicable: (documentId: string, pointId: string) =>
    request<PointsListing>(`${paper(documentId)}/not-applicable/undo`, {
      method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ point_id: pointId }),
    }),
  add: (documentId: string, body: { text: string; page?: number; rule_book?: string; clause?: string }) =>
    request<PointsListing>(`${paper(documentId)}/add`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) }),
  /** The ONE start. `shown` = the ids of the documents the screen listed as leaving this computer; the server stores that list and the run
   *  sends only those. Omitted: no list was shown (the older behaviour). */
  start: (documentId: string, engine: EngineChoice, shown?: string[]) =>
    request<{ review_run_id: string }>("/reviews/start", {
      method: "POST", headers: JSON_HEADERS,
      body: JSON.stringify({ submittal_document_id: documentId, engine, ...(shown ? { shown_document_ids: shown } : {}) }),
    }),
};

export type { Result };
