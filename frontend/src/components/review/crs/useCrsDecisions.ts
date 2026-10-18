/**
 * The engineer's decisions on the CRS-first Sheet (order 95 piece 2).
 *
 * Order 95 piece 6c: decisions stay on this screen until ONE "Save
 * decisions" press (`saveCrsDecisions`). The hook knows which decisions
 * differ from what was last saved; the screen holds Sign and export, and
 * warns before leaving, while any do.
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

/** Each reason's code, as `crs_issue.REMOVAL_REASONS` keys them (piece 6a). */
export const REMOVE_REASON_CODES: Record<RemoveReason, string> = {
  "Not applicable to this equipment": "not_applicable",
  "Contractor already complies": "already_complies",
  "Extraction wrong": "extraction_wrong",
  "Accept deviation": "accept_deviation",
  "Duplicate": "duplicate",
};

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
  /** Keys whose decision differs from the one last saved (a decision taken
   *  and not saved yet). A cleared key is not counted: nothing is sent to
   *  take a saved decision back. */
  unsaved: string[];
  /** The record now holds these keys' decisions as they are on screen. */
  markSaved: (keys: string[]) => void;
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
  /** The keys the last "Accept all" set to keep; null when there is nothing
   *  to undo. Any other decision clears it: undo is one step, and only
   *  ever touches what Accept all itself did. */
  const [accepted, setAccepted] = useState<string[] | null>(null);
  const [saved, setSaved] = useState<Record<string, Decision>>({});

  const set = useCallback((key: string, decision: Decision | null) => {
    setAccepted(null);
    setState((s) => {
      const decisions = { ...s.decisions };
      if (decision) decisions[key] = decision; else delete decisions[key];
      return { ...s, decisions };
    });
  }, []);

  const remaining = useCallback((rows: CrsRow[]) => rows.filter((r) =>
    r.tier.tier === "B" && !state.decisions[r.key] && r.priorState === "open"), [state.decisions]);

  const acceptAll = useCallback((rows: CrsRow[]) => {
    const targets = remaining(rows).map((r) => r.key);
    if (targets.length === 0) return 0;
    setAccepted(targets);
    setState((s) => {
      const decisions = { ...s.decisions };
      for (const key of targets) decisions[key] = { kind: "keep" };
      return { ...s, decisions };
    });
    return targets.length;
  }, [remaining]);

  /** Clears only the keys Accept all set that are still "keep"; every other
   *  decision, taken before or after, stays. */
  const undo = useCallback(() => {
    if (!accepted) return;
    setState((s) => {
      const decisions = { ...s.decisions };
      for (const key of accepted) if (decisions[key]?.kind === "keep") delete decisions[key];
      return { ...s, decisions };
    });
    setAccepted(null);
  }, [accepted]);

  const unsaved = Object.keys(state.decisions).filter((key) => !sameDecision(state.decisions[key], saved[key]));
  const markSaved = useCallback((keys: string[]) => {
    setSaved((prev) => {
      const next = { ...prev };
      for (const key of keys) if (state.decisions[key]) next[key] = state.decisions[key];
      return next;
    });
  }, [state.decisions]);

  return {
    state,
    unsaved,
    markSaved,
    decisionOf: (key) => state.decisions[key] ?? null,
    keep: (key) => set(key, { kind: "keep" }),
    edit: (key, observation, requiredAction) => set(key, { kind: "edit", observation, requiredAction }),
    remove: (key, reason) => set(key, { kind: "remove", reason }),
    clear: (key) => set(key, null),
    markOpened: (key) => setState((s) => (s.opened[key] ? s : { ...s, opened: { ...s.opened, [key]: true } })),
    remaining,
    acceptAll,
    canUndo: accepted !== null,
    undo,
  };
}

function sameDecision(a: Decision | undefined, b: Decision | undefined): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
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
