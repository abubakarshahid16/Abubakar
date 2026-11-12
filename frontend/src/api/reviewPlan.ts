/**
 * The pre-start plan and the planned start of the ONE Review button (`GET /api/reviews/plan`, `POST /api/reviews/start`).
 * Kept in its own file so the review page's older start route stays as it is. The plan lists every document a Claude review
 * may send (`documents.leaving`) and what will not go (`documents.not_sent`); the start stores the list the screen showed.
 */
import type { ReviewRunSummary } from "../types/api";
import { request, type Result } from "./core";

export type Engine = "automatic" | "claude" | "local";

export interface LeavingDocument {
  id: string;
  title: string;
  kind: string;
  why: string;
  /** A contract by role or by the code's own kind decision: the panel says so before the start. */
  contract?: boolean;
}

export interface NotSentDocument {
  /** Absent for a cited standard the library does not hold: then `name` is what the paper cites. */
  id?: string;
  title?: string;
  name?: string;
  kind: string;
  why: string;
  reason: string;
}

export interface PlanPart {
  name: string;
  engine: string;
  why: string;
}

export interface ReviewPlan {
  choice: Engine;
  parts: PlanPart[];
  text_leaves: boolean;
  refused: string | null;
  unscored?: boolean;
  unscored_note?: string;
  sentence?: string;
  boundary?: string;
  cost?: { at_most_usd: number | null; basis: string | null };
  documents: {
    leaving: LeavingDocument[];
    not_sent: NotSentDocument[];
    not_readable: number;
    summary?: string;
    unreadable?: boolean;
  };
}

const isObject = (b: unknown): b is Record<string, unknown> => typeof b === "object" && b !== null;
const isPlan = (b: unknown): boolean =>
  isObject(b) &&
  Array.isArray(b.parts) &&
  typeof b.text_leaves === "boolean" &&
  isObject(b.documents) &&
  Array.isArray(b.documents.leaving) &&
  Array.isArray(b.documents.not_sent);

export const reviewPlan = {
  /** What would run, and which documents would leave, for this paper and engine. No side effect. */
  plan: (submittalDocumentId: string, engine: Engine): Promise<Result<ReviewPlan>> =>
    request<ReviewPlan>(
      `/reviews/plan?submittal_document_id=${encodeURIComponent(submittalDocumentId)}&engine=${engine}`,
      undefined,
      isPlan,
    ),
  /** Start the review the plan allows, with the ids of the documents the screen listed as leaving. */
  start: (submittalDocumentId: string, engine: Engine, shownDocumentIds: string[]): Promise<Result<ReviewRunSummary>> =>
    request<ReviewRunSummary>("/reviews/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        submittal_document_id: submittalDocumentId,
        engine,
        shown_document_ids: shownDocumentIds,
      }),
    }),
};
