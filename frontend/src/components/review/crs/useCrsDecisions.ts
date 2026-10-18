/**
 * The engineer's decisions on the CRS-first Sheet (order 95 piece 2).
 *
 * TODO(order 95 piece 6, Part of #967): LOCAL STATE ONLY. Keep, edited
 * wording and Remove-with-reason live in this hook until piece 6 (record
 * and removal reasons) persists them with who, when and why. Until then a
 * reload loses them, and the screen says so.
 */
import { useCallback, useState } from "react";

import type { CrsRow } from "./crsRows";

/** The closed list of reasons for leaving a comment off the sheet (spec 1.2). */
export const REMOVE_REASONS = [
  "Not applicable to this equipment",
  "Contractor already complies",
  "Extraction wrong",
  "Accept deviation",
  "Duplicate",
] as const;
export type RemoveReason = (typeof REMOVE_REASONS)[number];

export type Decision =
  | { kind: "keep" }
  | { kind: "edit"; observation: string; requiredAction: string }
  | { kind: "remove"; reason: RemoveReason };

export interface DecisionState {
  /** Row key -> the engineer's decision. A row with none is kept by default,
   *  but not yet confirmed by anyone. */
  decisions: Record<string, Decision>;
  /** Rows the engineer has opened at least once (Tier C must be, spec 1.2). */
  opened: Record<string, true>;
}

export interface CrsDecisions {
  state: DecisionState;
  decisionOf: (key: string) => Decision | null;
  keep: (key: string) => void;
  edit: (key: string, observation: string, requiredAction: string) => void;
  remove: (key: string, reason: RemoveReason) => void;
  /** Back to "kept by default, not yet confirmed". */
  clear: (key: string) => void;
  markOpened: (key: string) => void;
  /** Which Comment rows "Accept all remaining" would keep: Tier B, without
   *  a decision yet, not already answered on the card view. Never Tier C. */
  remaining: (rows: CrsRow[]) => CrsRow[];
  acceptAll: (rows: CrsRow[]) => number;
  canUndo: boolean;
  undo: () => void;
}

const EMPTY: DecisionState = { decisions: {}, opened: {} };

export function useCrsDecisions(): CrsDecisions {
  const [state, setState] = useState<DecisionState>(EMPTY);
  const [before, setBefore] = useState<DecisionState | null>(null);

  const set = useCallback((key: string, decision: Decision | null) => {
    setState((s) => {
      const decisions = { ...s.decisions };
      if (decision) decisions[key] = decision; else delete decisions[key];
      return { ...s, decisions };
    });
  }, []);

  const remaining = useCallback((rows: CrsRow[]) => rows.filter((r) =>
    r.tier.tier === "B" && !state.decisions[r.key] && r.priorState === "open"), [state.decisions]);

  const acceptAll = useCallback((rows: CrsRow[]) => {
    const targets = remaining(rows);
    if (targets.length === 0) return 0;
    setBefore(state);
    setState((s) => {
      const decisions = { ...s.decisions };
      for (const r of targets) decisions[r.key] = { kind: "keep" };
      return { ...s, decisions };
    });
    return targets.length;
  }, [remaining, state]);

  const undo = useCallback(() => {
    if (!before) return;
    setState(before);
    setBefore(null);
  }, [before]);

  return {
    state,
    decisionOf: (key) => state.decisions[key] ?? null,
    keep: (key) => set(key, { kind: "keep" }),
    edit: (key, observation, requiredAction) => set(key, { kind: "edit", observation, requiredAction }),
    remove: (key, reason) => set(key, { kind: "remove", reason }),
    clear: (key) => set(key, null),
    markOpened: (key) => setState((s) => (s.opened[key] ? s : { ...s, opened: { ...s.opened, [key]: true } })),
    remaining,
    acceptAll,
    canUndo: before !== null,
    undo,
  };
}

/** The words of a decision in the status column. */
export function decisionWords(decision: Decision | null, row: CrsRow): string {
  if (!decision) return row.status;
  if (decision.kind === "keep") return "Kept";
  if (decision.kind === "edit") return "Kept, your wording";
  return `Removed: ${decision.reason}`;
}

/** The row's words after the engineer's edits, if any. */
export function wordingOf(decision: Decision | null, row: CrsRow): { observation: string; requiredAction: string } {
  if (decision?.kind === "edit") return { observation: decision.observation, requiredAction: decision.requiredAction };
  return { observation: row.observation, requiredAction: row.requiredAction };
}
