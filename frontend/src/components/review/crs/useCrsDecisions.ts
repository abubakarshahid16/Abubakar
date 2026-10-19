/**
 * The engineer's decisions on the CRS-first Sheet (order 95 piece 2).
 *
 * Order 95 piece 6c: decisions stay on this screen until ONE "Save
 * decisions" press (`saveCrsDecisions`). The hook knows which decisions
 * differ from what was last saved; the screen holds Sign and export, and
 * warns before leaving, while any do.
 *
 * v2.1 (N1): on the review workspace the decisions not saved yet are also
 * kept as a DRAFT in this tab's sessionStorage, one per review and per
 * signed-in person. Leaving the screen, pressing Back, or a sign-in that
 * ran out then loses nothing: the draft comes back the next time the same
 * person opens the same review in this tab, and it is removed once nothing
 * is left unsaved (a save, or every decision taken back). The draft is on
 * only where a review id is given (`useCrsDecisions(runId)`, or the
 * `CrsDraftContext` the app puts around the workspace); the old comment
 * sheet passes none and behaves exactly as before. Every storage call is
 * inside try/catch: a private window simply means there is no draft.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

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
  /** v2.1: how many decisions came back from this tab's draft when the
   *  screen opened (0 when none did, or there is no draft here). Optional
   *  so stand-ins in tests need not set it. */
  restored?: number;
}

const EMPTY: DecisionState = { decisions: {}, opened: {} };

/** The draft's sessionStorage key prefix. Versioned so a later change of
 *  shape can ignore old drafts. */
export const DRAFT_STORAGE_KEY = "crs-decisions.draft.v1";

/** Whose drafts this page reads and writes: a user id, or null with
 *  sign-in off. Set by the app (`setDraftOwner`) as soon as it knows who
 *  signed in, before the workspace draws, so one person never gets
 *  another's draft. */
let draftOwner: string | null = null;

export function setDraftOwner(user: string | null): void {
  draftOwner = user;
}

/** The storage key of one review's draft for a person. */
export function draftStorageKey(runId: string, user: string | null = draftOwner): string {
  return `${DRAFT_STORAGE_KEY}.${user ?? "anyone"}.${runId}`;
}

/** Sign-out (the reader chose it): forget every draft this person kept in
 *  this tab. A sign-in that simply ran out does NOT call this. */
export function clearDecisionDrafts(user: string | null = draftOwner): void {
  try {
    const prefix = `${DRAFT_STORAGE_KEY}.${user ?? "anyone"}.`;
    const doomed: string[] = [];
    for (let i = 0; i < window.sessionStorage.length; i += 1) {
      const key = window.sessionStorage.key(i);
      if (key?.startsWith(prefix)) doomed.push(key);
    }
    for (const key of doomed) window.sessionStorage.removeItem(key);
  } catch {
    /* blocked storage: nothing was kept */
  }
}

/** The review whose decisions get a draft, given by the app around the
 *  workspace. Null (the default) means no draft. */
export const CrsDraftContext = createContext<string | null>(null);

const REASONS = new Set<string>(REMOVE_REASONS);

function isDecision(value: unknown): value is Decision {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  if (v.kind === "keep") return true;
  if (v.kind === "edit") return typeof v.observation === "string" && typeof v.requiredAction === "string";
  return v.kind === "remove" && typeof v.reason === "string" && REASONS.has(v.reason);
}

/** The draft, or an empty state when there is none (or it cannot be read). */
export function readDecisionDraft(runId: string | null): DecisionState {
  if (!runId) return EMPTY;
  try {
    const raw = window.sessionStorage.getItem(draftStorageKey(runId));
    if (!raw) return EMPTY;
    const parsed = JSON.parse(raw) as { decisions?: unknown; opened?: unknown };
    const decisions: Record<string, Decision> = {};
    if (parsed.decisions && typeof parsed.decisions === "object") {
      for (const [key, value] of Object.entries(parsed.decisions as Record<string, unknown>)) {
        if (isDecision(value)) decisions[key] = value;
      }
    }
    const opened: Record<string, true> = {};
    if (Array.isArray(parsed.opened)) for (const key of parsed.opened) if (typeof key === "string") opened[key] = true;
    return { decisions, opened };
  } catch {
    return EMPTY;
  }
}

function writeDecisionDraft(runId: string, state: DecisionState, unsaved: string[]): void {
  try {
    const key = draftStorageKey(runId);
    if (unsaved.length === 0) { window.sessionStorage.removeItem(key); return; }
    const decisions: Record<string, Decision> = {};
    for (const k of unsaved) if (state.decisions[k]) decisions[k] = state.decisions[k];
    window.sessionStorage.setItem(key, JSON.stringify({ decisions, opened: Object.keys(state.opened) }));
  } catch {
    /* blocked or full storage: the decisions live only on screen */
  }
}

export function useCrsDecisions(draftRunId?: string | null): CrsDecisions {
  const fromContext = useContext(CrsDraftContext);
  const runId = draftRunId === undefined ? fromContext : draftRunId;
  // The draft is read once per review (a different review id reads its own).
  const [draftFor, setDraftFor] = useState(runId);
  const [state, setState] = useState<DecisionState>(() => readDecisionDraft(runId));
  const [restored, setRestored] = useState(() => Object.keys(state.decisions).length);
  /** The keys the last "Accept all" set to keep; null when there is nothing
   *  to undo. Any other decision clears it: undo is one step, and only
   *  ever touches what Accept all itself did. */
  const [accepted, setAccepted] = useState<string[] | null>(null);
  const [saved, setSaved] = useState<Record<string, Decision>>({});
  if (draftFor !== runId) {
    const next = readDecisionDraft(runId);
    setDraftFor(runId);
    setState(next);
    setSaved({});
    setAccepted(null);
    setRestored(Object.keys(next.decisions).length);
  }

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

  const unsaved = useMemo(
    () => Object.keys(state.decisions).filter((key) => !sameDecision(state.decisions[key], saved[key])),
    [state.decisions, saved]);
  const markSaved = useCallback((keys: string[]) => {
    setSaved((prev) => {
      const next = { ...prev };
      for (const key of keys) if (state.decisions[key]) next[key] = state.decisions[key];
      return next;
    });
  }, [state.decisions]);

  // Order 117: the per-row actions never change, so a memoised row given
  // them does not re-render when another row's decision does.
  const decisionOf = useCallback((key: string) => state.decisions[key] ?? null, [state.decisions]);
  const keep = useCallback((key: string) => set(key, { kind: "keep" }), [set]);
  const edit = useCallback((key: string, observation: string, requiredAction: string) =>
    set(key, { kind: "edit", observation, requiredAction }), [set]);
  const remove = useCallback((key: string, reason: RemoveReason) => set(key, { kind: "remove", reason }), [set]);
  const clear = useCallback((key: string) => set(key, null), [set]);
  const markOpened = useCallback((key: string) =>
    setState((s) => (s.opened[key] ? s : { ...s, opened: { ...s.opened, [key]: true } })), []);
  const canUndo = accepted !== null;

  // Keep the draft in step with what is not saved yet; nothing unsaved
  // removes it (a save clears it this way).
  useEffect(() => {
    if (runId && draftFor === runId) writeDecisionDraft(runId, state, unsaved);
  }, [runId, draftFor, state, unsaved]);

  // One object per change of state, not one per render: what depends on it
  // (the keyboard listener, the row callbacks) stays put between renders.
  return useMemo(() => ({
    state, unsaved, markSaved, decisionOf, keep, edit, remove, clear, markOpened, remaining, acceptAll, canUndo, undo, restored,
  }), [state, unsaved, markSaved, decisionOf, keep, edit, remove, clear, markOpened, remaining, acceptAll, canUndo, undo, restored]);
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
