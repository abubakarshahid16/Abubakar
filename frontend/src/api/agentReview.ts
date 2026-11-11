/**
 * The AI reviewer's calls (#1690), typed by the generated contract
 * (contracts/generated/agent_review.ts). Every route answers 404
 * "feature_off" while the one switch is off; for agent-status that is an
 * answer ("switch off"), not an error, so no screen shows a red line for it.
 */
import type {
  AgentLineList, AgentRulesUsed, AgentRunSummary, AgentStatus, AgentTrace, ReviewRunSummary,
} from "../types/api";
import { humanMessage, request, type Result } from "./core";
import { fetchSpreadsheet } from "./review";

/** What the switch says. `off` also covers any unreadable answer: when in
 *  doubt the screen shows nothing of the feature. */
export type AgentSwitch =
  | { state: "off" }
  | { state: "on"; status: AgentStatus };

const isObject = (b: unknown): b is Record<string, unknown> => typeof b === "object" && b !== null;
const hasLines = (b: unknown) => isObject(b) && Array.isArray(b.lines);
const hasSummaryShape = (b: unknown) =>
  isObject(b) && typeof b.paper_kind === "string" && isObject(b.counts_by_class) && Array.isArray(b.missing_books);
const hasRulesShape = (b: unknown) =>
  isObject(b) && Array.isArray(b.asked) && Array.isArray(b.left_out) && Array.isArray(b.missing_books);
const hasTraceShape = (b: unknown) => isObject(b) && typeof b.item_id === "string" && Array.isArray(b.gate);

/** True for the answer "this feature is not switched on" (404). */
export function isFeatureOff<T>(result: Result<T>): boolean {
  if (result.ok || result.disconnected) return false;
  const code: string = result.error.code;
  // A plain-string 404 body ("feature_off") carries no code, so request()
  // answers with the 404 words; both shapes mean "not switched on".
  return code === "not_found" || code === "feature_off" || result.error.message === humanMessage(404);
}

export async function agentSwitch(): Promise<AgentSwitch> {
  try {
    const result = await request<AgentStatus>(
      "/reviews/agent-status", undefined, (b) => isObject(b) && typeof b.enabled === "boolean",
    );
    if (result.ok && result.data.enabled) return { state: "on", status: result.data };
  } catch {
    /* unreadable: off */
  }
  return { state: "off" };
}

const run = (runId: string) => `/reviews/runs/${encodeURIComponent(runId)}`;

export const agentReview = {
  status: () => request<AgentStatus>("/reviews/agent-status"),
  start: (submittalDocumentId: string) =>
    request<ReviewRunSummary>("/reviews/agent-run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ submittal_document_id: submittalDocumentId }),
    }),
  summary: (runId: string) => request<AgentRunSummary>(`${run(runId)}/agent/summary`, undefined, hasSummaryShape),
  lines: (runId: string, cursor?: string | null) =>
    request<AgentLineList>(
      `${run(runId)}/agent/lines${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`, undefined, hasLines,
    ),
  trace: (runId: string, itemId: string) =>
    request<AgentTrace>(`${run(runId)}/agent/lines/${encodeURIComponent(itemId)}/trace`, undefined, hasTraceShape),
  rulesUsed: (runId: string) => request<AgentRulesUsed>(`${run(runId)}/rules-used`, undefined, hasRulesShape),
  /** The CRS file; the filename is the server's. */
  exportCrs: (runId: string, copy: "internal" | "contractor") =>
    fetchSpreadsheet(`${run(runId)}/agent/crs?copy=${copy}`, "GET", `CRS_${runId}_${copy}.xlsx`),
};
