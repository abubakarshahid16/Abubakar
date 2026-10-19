/**
 * Order 121 Part A: the issue gate as the comment sheet reads it - the hook
 * that loads it, the split of its open items into the sheet's comment rows
 * and the rest, and what is left before Sign and export, in plain words.
 * The box itself is `BeforeYouSign.tsx`.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { reviews as reviewsApi } from "../../../api/client";
import type { CrsIssueGate, ReviewRunSummary } from "../../../types/api";
import type { CrsRow } from "./crsRows";

/** The server's own floor (`crs_issue.MIN_REASON_LENGTH`): asked for here
 *  first, so its refusal is not news. */
export const MIN_SIGN_REASON = 10;

export interface IssueGateState {
  gate: CrsIssueGate | null;
  error: string | null;
  reload: () => Promise<void>;
}

/** The run's issue gate, read again whenever `version` changes (the run or
 *  its findings were re-read). Only the newest answer is kept. */
export function useIssueGate(runId: string, version: unknown): IssueGateState {
  const [gate, setGate] = useState<CrsIssueGate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const latest = useRef(0);
  useEffect(() => () => { latest.current += 1; }, []);
  const reload = useCallback(async () => {
    const mine = ++latest.current;
    let result: Awaited<ReturnType<typeof reviewsApi.crsIssueGate>> | null = null;
    try {
      result = await reviewsApi.crsIssueGate(runId);
    } catch {
      result = null;
    }
    if (mine !== latest.current) return;
    if (result?.ok) { setGate(result.data); setError(null); }
    else { setGate(null); setError(result?.error.message || "Could not check what is left before signing."); }
  }, [runId]);
  useEffect(() => { void reload(); }, [reload, version]);
  return { gate, error, reload };
}

export interface GateSplit {
  /** Comment numbers with an undecided item, ascending. */
  comments: number[];
  /** The first row behind each of those comment numbers. */
  rowFor: Map<number, CrsRow>;
  /** Rows ON this sheet with an undecided item but no comment number (a Met
   *  or not-applicable row): each is opened and decided on its own, never in
   *  bulk, so nothing on the sheet is decided unseen. */
  unnumbered: CrsRow[];
  /** Undecided items that are not rows on this sheet at all. */
  others: CrsIssueGate["open_findings"];
}

export function splitOpenItems(gate: CrsIssueGate, rows: CrsRow[]): GateSplit {
  const byFinding = new Map<string, CrsRow>();
  for (const row of rows) for (const f of row.findings) byFinding.set(f.id, row);
  const rowFor = new Map<number, CrsRow>();
  const unnumbered = new Map<string, CrsRow>();
  const others: CrsIssueGate["open_findings"] = [];
  for (const item of gate.open_findings) {
    const row = byFinding.get(item.finding_id);
    if (!row) others.push(item);
    else if (row.commentNo !== null) { if (!rowFor.has(row.commentNo)) rowFor.set(row.commentNo, row); }
    else unnumbered.set(row.key, row);
  }
  return { comments: [...rowFor.keys()].sort((a, b) => a - b), rowFor, unnumbered: [...unnumbered.values()], others };
}

export function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

function commentList(numbers: number[]): string {
  return `${numbers.length === 1 ? "comment" : "comments"} ${numbers.join(", ")}`;
}

/** What still stands between the sheet and Sign and export, in plain words;
 *  empty when nothing does. Only the gate is read, so the workspace's one
 *  numbers helper can call it with the gate alone. */
export function signLeft(state: Pick<IssueGateState, "gate">, run: ReviewRunSummary, rows: CrsRow[]): string[] {
  const { gate } = state;
  if (!gate) return ["what is left could not be checked"];
  const left: string[] = [];
  if (!run.engineer_final_code && !gate.final_code_recorded) left.push("record the final code");
  if (gate.unread_pages.length > 0) left.push(`tick ${plural(gate.unread_pages.length, "unread page", "unread pages")}`);
  const split = splitOpenItems(gate, rows);
  if (split.comments.length > 0) left.push(`decide ${commentList(split.comments)}`);
  if (split.unnumbered.length > 0) left.push(`decide ${plural(split.unnumbered.length, "other row", "other rows")} on the sheet`);
  if (split.others.length > 0) left.push(`decide ${plural(split.others.length, "other item", "other items")} on the issued copy`);
  // A blocker the box has no control for (no page record at all) is passed
  // on in the server's words rather than hidden.
  if (left.length === 0 && !gate.issuable) left.push(...gate.blockers);
  return left;
}
