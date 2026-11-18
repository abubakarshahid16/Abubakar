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
}

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
  unlisted_books: { count: number; sentence: string | null };
  checklist: { key: string | null; items: number | null; always_items?: number; reused: boolean | null; built_from: string | null };
  /** Piece G: the measured score of this paper's kind (found of 10 on planted test copies, target 7); null when no kind is named. */
  measured?: GeneralMeasured | null;
  cost: { usd: number | null; note?: string };
  /** Every call of the run, in order: the "How this review was made" view groups them by step. */
  calls?: GeneralCall[];
  seconds?: number | null;
  created_at?: string | null;
  finished_at?: string | null;
  completeness: GeneralCompleteness;
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

export const generalReview = {
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
  sheet: async (documentId: string, runId?: string): Promise<Result<{ blob: Blob; filename: string }>> => {
    let response: Response;
    try {
      const headers = new Headers();
      markSession(headers);
      response = await fetch(`${BASE}${paper(documentId)}/general/sheet${runId ? `?run_id=${encodeURIComponent(runId)}` : ""}`, { headers });
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
export async function downloadGeneralSheet(documentId: string, runId?: string): Promise<string | null> {
  const result = await generalReview.sheet(documentId, runId);
  if (!result.ok) return result.error.message;
  const url = URL.createObjectURL(result.data.blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = result.data.filename;
  link.click();
  URL.revokeObjectURL(url);
  return null;
}
