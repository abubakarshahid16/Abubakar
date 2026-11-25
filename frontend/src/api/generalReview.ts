/**
 * The general review's calls (order 14, piece C): the stored review of a paper as the results page draws it, its Excel file, and the
 * paper's history of reviews (piece D's route). Reads only; every file is the TEAM copy: there is no contractor copy and no sign-off.
 */
import type { GeneralMeasured } from "../components/review/general/MeasuredBadge";
import { BASE, failureOf, markSession, request, type Result } from "./core";

export interface GeneralLine {
  n: number;
  field: string;
  page: number | null;
  label: string;
  shown_label: string;
  comment: string;
  quote: string;
  item_id: string;
  standard: string;
  clause: string;
  source: string;
  topic?: string;
  code_note?: string;
  quote_unverified?: boolean;
  /** What code compared, in words ("380 psig <= 23.5 barg: false"); empty when code compared nothing. */
  compared?: string;
  compare_kind?: string;
  /** The comment card (code-decided, from the server; absent on an older answer): how serious, a short title, and the parts of the card. */
  severity?: Severity;
  title?: string;
  paper_says?: string;
  rule_says?: string;
  we_ask?: string;
  applies_to?: { page: number | null; field: string; quote: string; /** Every page the field stands on (one chip per field). */ pages?: number[]; /** The valve tag or sheet in the field's last bracket. */ tag?: string; /** What the paper says there, "<field>: blank" for a blank value. */ value?: string }[];
  /** "compared by code", or the mark when it is an AI reading. */
  proven?: string;
  /** Set when the two readers of this comment differ: shown as a small tag, never part of the comment's text. */
  readers?: { first: string; second: string; reason: string } | null;
  /** The AI chose which two values of the paper to compare and code compared them: said as a small tag, never in the comment text. */
  paired?: boolean;
  /** Parts the paper answers that were cut out of the comment (team only): the page and the full text before the cut. */
  cut?: { page: number; before: string }[];
  /** The engineer's latest decision on this comment (append-only on the server); null when undecided. */
  decision?: CommentDecision | null;
}

export type DecisionState = "accept" | "edit" | "reject";

/** The engineer's sign-off of the review (server's answer): not signed / signed / changed since the sign-off. */
export interface SignoffStatus {
  state: "not_signed" | "signed" | "changed";
  undecided: { part: "comment" | "confirmation"; n: number; title: string }[];
  undecided_count: number;
  /** The four configured review codes: the engineer chooses one, nothing is proposed by the machine. */
  codes: string[];
  can_sign: boolean;
  /** The admin capability ("super user"): only that reader signs, and fetches the contractor copy, until engineer accounts are named. */
  may_sign: boolean;
  may_sign_words: string | null;
  signed: { by: string; at: string; code: string; statement: string | null; copy_statement: string } | null;
}

export interface SignoffRefusal { message: string; blockers: { part: string; n: number; title?: string; why?: string }[] }

export interface CommentDecision {
  state: DecisionState;
  words: string;
  text: string | null;
  reason: string | null;
  by: string;
  at: string;
  revisions: number;
  sentence?: string;
}

export type Severity = "Must fix" | "Check a value" | "Missing information" | "Please confirm";

/** One model or code call of the run, as the server recorded it. `usd` null: the cost of this call was not read. */
export interface GeneralCall {
  step: string;
  model: string;
  usd: number | null;
  seconds?: number | null;
  ok?: boolean;
  code?: string;
}

export interface GeneralCompleteness {
  ok: boolean;
  page: number;
  database: number;
  file_rows: number;
  sentence: string | null;
}

/** One part (a Schedule) of the contract package: what the review did with it. A page counts as read only if text came back for it. */
export interface GeneralReference {
  part: string;
  title: string | null;
  status: string;
  reason: string;
  questions: number | null;
  settled: number | null;
  pages_read: number | null;
  pages_held: number | null;
  compared: number | null;
  differs: number | null;
}

export interface GeneralReview {
  paper_document_id: string;
  run_id: string;
  method: string;
  mark: string;
  status: "completed" | "stopped";
  stop_reason?: string | null;
  identity: { kind: string | null; equipment_type: string | null; subject: string | null };
  counts: {
    points: number; comments: number; by_label: Record<string, number>; by_shown_label?: Record<string, number>; boundary: string;
    /** Comments whose points all only ask the vendor to confirm a stated value: counted apart, not sent (18 Nov 2026). */
    confirmations?: number;
    /** The points inside the comments sent, and inside the confirmations: comment_lines + confirmation_lines = the points that qualified to be sent. */
    comment_lines?: number;
    confirmation_lines?: number;
    /** The summary tiles: how many comments (and confirmations) of each severity. */
    by_severity?: Partial<Record<Severity, number>>;
    /** How many points code decided (Pass or Fail, compared by code), out of all points; null for a review with no points. */
    decided_by_code?: { count: number; of: number; sentence: string } | null;
  };
  comments: GeneralLine[];
  /** The confirmations not sent (absent on an older answer). */
  confirmations?: GeneralLine[];
  points: GeneralLine[];
  books: { id: string; title: string; why: string }[];
  books_not_readable?: number;
  /** The documents listed before the start (besides the paper) and how many the run used; null for a run with no stored list. */
  documents_listed?: { listed: number; used: number; sentence: string } | null;
  not_held: { name: string; why: string }[];
  /** The parts of the contract package a contract review read (a Schedule), and what was done with each; absent for other papers. */
  references?: GeneralReference[];
  unlisted_books: { count: number; sentence: string | null };
  checklist: { key: string | null; items: number | null; always_items?: number; reused: boolean | null; built_from: string | null };
  /** Piece G: the measured score of this paper's kind (found of 10 on planted test copies, target 7); null when no kind is named. */
  measured?: GeneralMeasured | null;
  cost: { usd: number | null; note?: string };
  /** A checking step whose answer was not applied to this sheet, in plain words (a failed AI step is shown in the run). */
  steps_not_applied?: { step: string; why: string; sentence: string }[];
  /** Every call of the run, in order: the "How this review was made" view groups them by step. */
  calls?: GeneralCall[];
  seconds?: number | null;
  created_at?: string | null;
  finished_at?: string | null;
  completeness: GeneralCompleteness;
  /** The engineer's sign-off state of this run (absent on an older answer). */
  signoff?: SignoffStatus;
  /** False when an earlier-engine review of the paper is newer: the page then draws the older sections. */
  is_latest?: boolean;
}

export interface HistoryRun {
  run_id: string;
  version: "general" | "earlier version";
  part: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  points: number | null;
  files: { label: string; url: string }[];
}
export interface PaperHistory { paper_document_id: string; boundary: string; runs: HistoryRun[] }

const isObject = (b: unknown): b is Record<string, unknown> => typeof b === "object" && b !== null;
const paper = (documentId: string) => `/reviews/papers/${encodeURIComponent(documentId)}`;

const JSON_HEADERS = { "Content-Type": "application/json" };

export const generalReview = {
  /** Accept every comment and confirmation that has no decision yet (each its own, append-only, decision). */
  acceptRest: (documentId: string, runId: string) =>
    request<{ run_id: string; accepted: number }>(`${paper(documentId)}/general/accept-rest`,
      { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ run_id: runId }) }, (b) => isObject(b) && typeof b.accepted === "number"),
  /** Sign the review off with the engineer's own choice of the review code. A 409 carries the reason and the comments in the way. */
  signOff: (documentId: string, body: { run_id: string; review_code: string; statement?: string }) =>
    request<{ run_id: string; signoff: SignoffStatus }>(`${paper(documentId)}/general/signoff`,
      { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) }, (b) => isObject(b) && isObject(b.signoff)),
  /** Accept, edit or reject ONE comment (or confirmation). Only a signed-in user who may read the paper; the answer is the comment's
   *  latest decision. Edit needs the engineer's text, reject a one-line reason (the server refuses otherwise, in its own words). */
  decide: (documentId: string, body: { run_id: string; comment: number; part: "comment" | "confirmation"; state: DecisionState; text?: string; reason?: string }) =>
    request<{ run_id: string; comment: number; part: string; decision: CommentDecision }>(
      `${paper(documentId)}/general/decision`,
      { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) },
      (b) => isObject(b) && isObject(b.decision),
    ),
  /** Which method the Review button runs now (piece E's route): "general" or "earlier". */
  method: () => request<{ method: "general" | "earlier" }>("/reviews/method", undefined, (b) => isObject(b) && typeof b.method === "string"),
  /** The paper's latest finished general review (or the one asked for). A 404 means: this paper has none. */
  get: (documentId: string, runId?: string) =>
    request<GeneralReview>(
      `${paper(documentId)}/general${runId ? `?run_id=${encodeURIComponent(runId)}` : ""}`,
      undefined,
      (b) => isObject(b) && Array.isArray(b.points) && Array.isArray(b.comments) && isObject(b.counts) && isObject(b.completeness),
    ),
  /** The paper's reviews, newest first, each marked "general" or "earlier version" (piece D's route). */
  history: (documentId: string) =>
    request<PaperHistory>(`${paper(documentId)}/history`, undefined, (b) => isObject(b) && Array.isArray(b.runs)),
  /** The team file of one general review. The server refuses it (409, with the sentence) unless page, database and rows agree. */
  sheet: async (documentId: string, runId?: string, copy: "team" | "contractor" = "team"): Promise<Result<{ blob: Blob; filename: string }>> => {
    let response: Response;
    try {
      const headers = new Headers();
      markSession(headers);
      response = await fetch(`${BASE}${paper(documentId)}/general/sheet?${runId ? `run_id=${encodeURIComponent(runId)}&` : ""}copy=${copy}`, { headers });
    } catch (e) {
      return { ok: false, disconnected: true, error: { code: "internal", message: e instanceof Error ? e.message : "Network request failed." } };
    }
    if (!response.ok) return failureOf(response);
    const match = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") ?? "");
    try {
      return { ok: true, data: { blob: await response.blob(), filename: match?.[1] ?? "general-review.xlsx" } };
    } catch (e) {
      return { ok: false, disconnected: true, error: { code: "internal", message: e instanceof Error ? e.message : "The download was interrupted." } };
    }
  },
};

/** Fetch the file and hand it to the browser. Returns the server's own sentence on a refusal, or null when handed over. */
export async function downloadGeneralSheet(documentId: string, runId?: string, copy: "team" | "contractor" = "team"): Promise<string | null> {
  const result = await generalReview.sheet(documentId, runId, copy);
  if (!result.ok) return result.error.message;
  const url = URL.createObjectURL(result.data.blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = result.data.filename;
  link.click();
  URL.revokeObjectURL(url);
  // A browser may hold a download while its tab is in the background, and then nothing seems to happen (first-time user, 19 Nov): say it.
  if (typeof document !== "undefined" && document.visibilityState === "hidden") {
    return "This tab is in the background, so the browser may not have saved the file. Bring this tab to the front and press Download again.";
  }
  return null;
}
