/**
 * Order 121 Part A: the issue gate as the comment sheet reads it - the hook
 * that loads it, the split of its open items into the sheet's comment rows
 * and the rest, and what is left before Sign and export, in plain words.
 * The box itself is `BeforeYouSign.tsx`.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { reviews as reviewsApi } from "../../../api/client";
import type { CrsIssueGate, ReviewRunSummary } from "../../../types/api";
import { type CrsRow, unreadPhrase } from "./crsRows";

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
    else { setGate(null); setError(gateReadError(result?.error.message)); }
  }, [runId]);
  useEffect(() => { void reload(); }, [reload, version]);
  return { gate, error, reload };
}

/** v2.1 (N2): a failed read of what is left before signing, in a plain
 *  sentence; the server's own words, when it sent any, follow as a detail. */
export const GATE_READ_FAILED = "Could not check what is left before signing. Try again in a moment.";

export function gateReadError(detail: string | null | undefined): string {
  const raw = (detail ?? "").trim();
  return raw ? `${GATE_READ_FAILED} Details: ${raw}` : GATE_READ_FAILED;
}

/** v2.1 (W1): the server's blockers that have plain words of their own. Any
 *  other blocker is already plain words from the server and passes as is. */
const BLOCKER_WORDS: Record<string, string> = {
  "no page coverage is recorded for this run, so no page can be called read":
    "the record of which pages were read is missing for this review, so no page can be called read yet",
};

export function plainBlocker(blocker: string): string {
  return BLOCKER_WORDS[blocker] ?? blocker;
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

/** Order 127: the box's page counts, from the gate alone. `left` is what is
 *  still to tick (`gate.unread_pages`), `checked` the pages of the same list an
 *  engineer ticked (`gate.checked_pages`, absent = none), `notRead` their sum:
 *  the run's unread pages, the same list the header counts
 *  (`how_reviewed.unread_pages`). `pagesTotal` is null when not known, never 0. */
export interface UnreadPagesCount {
  left: number;
  checked: number;
  notRead: number;
  pagesTotal: number | null;
}

export function unreadPagesCount(gate: CrsIssueGate): UnreadPagesCount {
  const left = gate.unread_pages.length;
  const checked = (gate.checked_pages ?? []).length;
  return { left, checked, notRead: left + checked, pagesTotal: gate.pages_total ?? null };
}

/** Order 127: the box's count line, in the header's own words
 *  (`unreadPhrase`, the phrase the header uses). The count is
 *  every unread page of the run (left to tick + already ticked), so it is the
 *  same number the header names; what is left to tick is said after it. */
export function unreadPagesLine(gate: CrsIssueGate): { done: boolean; text: string } {
  const { left, checked, notRead, pagesTotal } = unreadPagesCount(gate);
  if (notRead === 0) {
    // An explicit null total is the server saying no page record is stored
    // (its NO_PAGE_COVERAGE blocker): nothing can be called read, so the box
    // must not say "Every page was read" (rule 4).
    if (gate.pages_total === null) return { done: false, text: "Which pages were read is not recorded on this run." };
    // A gate from a server before order 127 does not say which pages were
    // ticked, so a ticked page cannot be told from a read one.
    if (gate.checked_pages === undefined) return { done: true, text: "Every page was read or checked by an engineer." };
    return { done: true, text: "Every page was read." };
  }
  const head = unreadPhrase(notRead, pagesTotal);
  if (left === 0) return { done: true, text: `${head}; an engineer checked ${notRead === 1 ? "it" : `all ${notRead}`}.` };
  if (checked === 0) return { done: false, text: `${head}. Tick each one once you have checked it yourself.` };
  return { done: false, text: `${head}: ${checked} checked by an engineer, ${left} left to tick.` };
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
  if (split.unnumbered.length > 0) left.push(`decide ${plural(split.unnumbered.length, "other line", "other lines")} on the sheet`);
  if (split.others.length > 0) left.push(`decide ${plural(split.others.length, "other item", "other items")} on the issued copy`);
  // A blocker the box has no control for (no page record at all) is passed
  // on (in plain words where it has them) rather than hidden.
  if (left.length === 0 && !gate.issuable) left.push(...gate.blockers.map(plainBlocker));
  return left;
}
