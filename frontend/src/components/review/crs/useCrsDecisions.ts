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
 * ran out then loses nothing. The draft is on only where a review id is
 * given (`useCrsDecisions(runId)`, or the `CrsDraftContext` the app puts
 * around the workspace); the old comment sheet passes none and behaves
 * exactly as before. Every storage call is inside try/catch: a private
 * window simply means there is no draft.
 *
 * v2.1 round 2: a draft never comes back, and never saves, by itself. When
 * the screen opens with one, the hook offers it (`pendingRestore`) and the
 * screen asks "N decisions you had not saved were found. Bring them back?"
 * Only "Yes" (`restoreDraft`) puts them on screen, where they save as any
 * decision does; "Discard" (`discardDraft`) throws them away. Each entry
 * carries the record's state of its row when it was kept (`stamps`: the
 * row's state, and each finding's approval, comment and confirmation); on
 * "Yes" an entry whose row changed since, or is gone, is dropped and
 * counted (`restoreDropped`). On a signed review (`observeRecord(rows,
 * true)`) nothing is offered and the draft is removed.
 *
 * v2.1 follow-up: the rows marked opened carry the same stamp
 * (`openedStamps`). A mark comes back only once the record is known, and
 * only for a row still on the sheet whose record did not change since; a
 * "Needs you" row changed meanwhile must be opened again.
 *
 * The workspace tells the hook what the record holds through
 * `observeRecord`, which useAutosave calls with the rows it saves against.
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
  /** v2.1: how many decisions came back from this tab's draft after the
   *  reader chose "Yes" (0 until then, or when there is no draft here).
   *  Optional so stand-ins in tests need not set it. */
  restored?: number;
  /** v2.1 round 2: how many draft decisions "Yes" did NOT bring back,
   *  because their comment changed on the record, or left the sheet, since. */
  restoreDropped?: number;
  /** v2.1 round 2: a draft found when the screen opened, waiting for the
   *  reader's answer (null when there is none, or the review is signed). */
  pendingRestore?: { count: number } | null;
  /** "Yes": bring the draft's decisions back (those whose comment did not
   *  change since). Does nothing until the record has been observed. */
  restoreDraft?: () => void;
  /** "Discard": throw the draft away. */
  discardDraft?: () => void;
  /** Tell the hook what the record now holds (the sheet's rows), and
   *  whether the review is signed (`locked`: no draft is kept or offered). */
  observeRecord?: (rows: CrsRow[], locked: boolean) => void;
  /** Take these keys' decisions off the screen, the unsaved list and the
   *  draft (their comment is no longer on the sheet). */
  forget?: (keys: string[]) => void;
}

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

/** Someone is signed in (or a reload learned who): remove every draft in
 *  this tab that is not theirs. A sign-in that ran out keeps its drafts
 *  for the same person, but never for the next one: a draft can hold
 *  wording from the document, and they may not be granted it. */
export function keepOnlyDraftsOf(user: string | null): void {
  try {
    const mine = `${DRAFT_STORAGE_KEY}.${user ?? "anyone"}.`;
    const doomed: string[] = [];
    for (let i = 0; i < window.sessionStorage.length; i += 1) {
      const key = window.sessionStorage.key(i);
      if (key?.startsWith(`${DRAFT_STORAGE_KEY}.`) && !key.startsWith(mine)) doomed.push(key);
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

/** A draft as kept in storage: the decisions not saved yet, the rows
 *  opened, and per decision the record's state of its row at the time. */
export interface DecisionDraft extends DecisionState {
  stamps: Record<string, string>;
  /** Per row marked opened, the record's state of that row at the time. */
  openedStamps: Record<string, string>;
}

const EMPTY_DRAFT: DecisionDraft = { decisions: {}, opened: {}, stamps: {}, openedStamps: {} };

function stringsOf(value: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  if (value && typeof value === "object") {
    for (const [key, v] of Object.entries(value as Record<string, unknown>)) if (typeof v === "string") out[key] = v;
  }
  return out;
}

/** What the record holds for a row, as one string: the row's state and each
 *  finding's approval, engineer comment and confirmation. Two equal stamps
 *  mean nobody changed the row on the record in between. */
export function recordStamp(row: CrsRow): string {
  return JSON.stringify([
    row.priorState ?? null,
    row.findings.map((f) => [f.id, f.approval_status ?? null, f.engineer_comment ?? null, f.confirmed_by ?? null]),
  ]);
}

/** The draft, or an empty one when there is none (or it cannot be read). */
export function readDecisionDraft(runId: string | null): DecisionDraft {
  if (!runId) return EMPTY_DRAFT;
  try {
    const raw = window.sessionStorage.getItem(draftStorageKey(runId));
    if (!raw) return EMPTY_DRAFT;
    const parsed = JSON.parse(raw) as { decisions?: unknown; opened?: unknown; stamps?: unknown; openedStamps?: unknown };
    const decisions: Record<string, Decision> = {};
    if (parsed.decisions && typeof parsed.decisions === "object") {
      for (const [key, value] of Object.entries(parsed.decisions as Record<string, unknown>)) {
        if (isDecision(value)) decisions[key] = value;
      }
    }
    const opened: Record<string, true> = {};
    if (Array.isArray(parsed.opened)) for (const key of parsed.opened) if (typeof key === "string") opened[key] = true;
    return { decisions, opened, stamps: stringsOf(parsed.stamps), openedStamps: stringsOf(parsed.openedStamps) };
  } catch {
    return EMPTY_DRAFT;
  }
}

function removeDecisionDraft(runId: string): void {
  try { window.sessionStorage.removeItem(draftStorageKey(runId)); } catch { /* blocked storage */ }
}

function writeDecisionDraft(runId: string, draft: DecisionDraft): void {
  try {
    if (Object.keys(draft.decisions).length === 0) { removeDecisionDraft(runId); return; }
    window.sessionStorage.setItem(draftStorageKey(runId), JSON.stringify({
      decisions: draft.decisions, opened: Object.keys(draft.opened), stamps: draft.stamps,
      openedStamps: draft.openedStamps,
    }));
  } catch {
    /* blocked or full storage: the decisions live only on screen */
  }
}

/** Opened marks still waiting for the record (their stamps not checked yet). */
interface HeldOpened {
  opened: Record<string, true>;
  stamps: Record<string, string>;
}

/** The draft to keep now: what is unsaved on screen (stamped with the record
 *  as it is now), plus a draft still waiting for the reader's answer, plus
 *  opened marks still waiting for the record. */
function draftToKeep(
  state: DecisionState, unsaved: string[], rows: CrsRow[] | null, pending: DecisionDraft | null,
  held: HeldOpened | null = null,
): DecisionDraft {
  const decisions: Record<string, Decision> = { ...(pending?.decisions ?? {}) };
  const stamps: Record<string, string> = { ...(pending?.stamps ?? {}) };
  const byKey = new Map((rows ?? []).map((row) => [row.key, row]));
  for (const key of unsaved) {
    const decision = state.decisions[key];
    if (!decision) continue;
    decisions[key] = decision;
    const row = byKey.get(key);
    if (row) stamps[key] = recordStamp(row); else delete stamps[key];
  }
  for (const key of Object.keys(stamps)) if (!decisions[key]) delete stamps[key];
  const opened = { ...(held?.opened ?? {}), ...(pending?.opened ?? {}), ...state.opened };
  const openedStamps: Record<string, string> = { ...(held?.stamps ?? {}), ...(pending?.openedStamps ?? {}) };
  for (const key of Object.keys(state.opened)) {
    const row = byKey.get(key);
    if (row) openedStamps[key] = recordStamp(row);
  }
  for (const key of Object.keys(openedStamps)) if (!opened[key]) delete openedStamps[key];
  return { decisions, opened, stamps, openedStamps };
}

/** The opened marks whose row is still on the sheet and unchanged on the
 *  record since the mark was kept (a mark with no stamp is not kept). */
function checkedOpened(opened: Record<string, true>, stamps: Record<string, string>, rows: CrsRow[]): Record<string, true> {
  const byKey = new Map(rows.map((row) => [row.key, row]));
  const back: Record<string, true> = {};
  for (const key of Object.keys(opened)) {
    const row = byKey.get(key);
    const stamp = stamps[key];
    if (row && stamp && stamp === recordStamp(row)) back[key] = true;
  }
  return back;
}

/** A draft as first read: only decisions wait for an answer; rows opened
 *  alone come back by themselves (opening a row changes nothing on the
 *  record), but only once the record is known and their stamps checked. */
function splitDraft(draft: DecisionDraft): { pending: DecisionDraft | null; held: HeldOpened | null } {
  if (Object.keys(draft.decisions).length === 0) {
    return { pending: null, held: Object.keys(draft.opened).length ? { opened: draft.opened, stamps: draft.openedStamps } : null };
  }
  return { pending: draft, held: null };
}

export function useCrsDecisions(draftRunId?: string | null): CrsDecisions {
  const fromContext = useContext(CrsDraftContext);
  const runId = draftRunId === undefined ? fromContext : draftRunId;
  // The draft is read once per review (a different review id reads its own).
  const [draftFor, setDraftFor] = useState(runId);
  const [first] = useState(() => splitDraft(readDecisionDraft(runId)));
  const [state, setState] = useState<DecisionState>(() => ({ decisions: {}, opened: {} }));
  /** Opened marks from the draft, waiting for the record to check them. */
  const [held, setHeld] = useState<HeldOpened | null>(first.held);
  /** A draft waiting for "Yes" or "Discard": not on screen, never saved. */
  const [pending, setPending] = useState<DecisionDraft | null>(first.pending);
  const [restored, setRestored] = useState(0);
  const [restoreDropped, setRestoreDropped] = useState(0);
  /** What the record holds (observeRecord); null until it is known. */
  const [record, setRecord] = useState<{ rows: CrsRow[]; locked: boolean } | null>(null);
  /** The keys the last "Accept all" set to keep; null when there is nothing
   *  to undo. Any other decision clears it: undo is one step, and only
   *  ever touches what Accept all itself did. */
  const [accepted, setAccepted] = useState<string[] | null>(null);
  const [saved, setSaved] = useState<Record<string, Decision>>({});
  if (draftFor !== runId) {
    const next = splitDraft(readDecisionDraft(runId));
    setDraftFor(runId);
    setState({ decisions: {}, opened: {} });
    setHeld(next.held);
    setPending(next.pending);
    setSaved({});
    setAccepted(null);
    setRestored(0);
    setRestoreDropped(0);
    setRecord(null);
  }
  const locked = record?.locked ?? false;
  // The record is known: the held opened marks come back, checked.
  if (held && record) {
    const back = record.locked ? {} : checkedOpened(held.opened, held.stamps, record.rows);
    setHeld(null);
    if (Object.keys(back).length) setState((s) => ({ ...s, opened: { ...back, ...s.opened } }));
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

  const observeRecord = useCallback((rows: CrsRow[], isLocked: boolean) => {
    setRecord((prev) => (prev && prev.rows === rows && prev.locked === isLocked ? prev : { rows, locked: isLocked }));
  }, []);

  const forget = useCallback((keys: string[]) => {
    if (keys.length === 0) return;
    setAccepted(null);
    setState((s) => {
      if (!keys.some((key) => key in s.decisions)) return s;
      const decisions = { ...s.decisions };
      for (const key of keys) delete decisions[key];
      return { ...s, decisions };
    });
    setSaved((prev) => {
      if (!keys.some((key) => key in prev)) return prev;
      const next = { ...prev };
      for (const key of keys) delete next[key];
      return next;
    });
    setPending((p) => {
      if (!p || !keys.some((key) => key in p.decisions)) return p;
      const decisions = { ...p.decisions };
      const stamps = { ...p.stamps };
      for (const key of keys) { delete decisions[key]; delete stamps[key]; }
      return Object.keys(decisions).length ? { ...p, decisions, stamps } : null;
    });
  }, []);

  const restoreDraft = useCallback(() => {
    if (!pending || !record) return;
    if (record.locked) { setPending(null); return; }
    const byKey = new Map(record.rows.map((row) => [row.key, row]));
    const back: Record<string, Decision> = {};
    let dropped = 0;
    for (const [key, decision] of Object.entries(pending.decisions)) {
      const row = byKey.get(key);
      const stamp = pending.stamps[key];
      // Gone from the sheet, kept with no stamp, or changed on the record
      // since: it is not brought back (the reader decides it afresh).
      if (!row || !stamp || stamp !== recordStamp(row)) { dropped += 1; continue; }
      back[key] = decision;
    }
    setAccepted(null);
    // A decision the reader took meanwhile wins over the draft's.
    const openedBack = checkedOpened(pending.opened, pending.openedStamps, record.rows);
    setState((s) => ({ decisions: { ...back, ...s.decisions }, opened: { ...openedBack, ...s.opened } }));
    setRestored(Object.keys(back).length);
    setRestoreDropped(dropped);
    setPending(null);
  }, [pending, record]);

  const discardDraft = useCallback(() => {
    setPending(null);
    setRestored(0);
    setRestoreDropped(0);
  }, []);

  // Keep the draft in step with what is not saved yet (and with a draft
  // still waiting for an answer); nothing left removes it (a save clears
  // it this way). A signed review keeps no draft at all.
  useEffect(() => {
    if (!runId || draftFor !== runId) return;
    if (locked) { removeDecisionDraft(runId); return; }
    writeDecisionDraft(runId, draftToKeep(state, unsaved, record?.rows ?? null, pending, held));
  }, [runId, draftFor, state, unsaved, record, pending, held, locked]);

  const pendingRestore = useMemo(
    () => (pending && !locked ? { count: Object.keys(pending.decisions).length } : null), [pending, locked]);

  // One object per change of state, not one per render: what depends on it
  // (the keyboard listener, the row callbacks) stays put between renders.
  return useMemo(() => ({
    state, unsaved, markSaved, decisionOf, keep, edit, remove, clear, markOpened, remaining, acceptAll, canUndo, undo,
    restored, restoreDropped, pendingRestore, restoreDraft, discardDraft, observeRecord, forget,
  }), [state, unsaved, markSaved, decisionOf, keep, edit, remove, clear, markOpened, remaining, acceptAll, canUndo, undo,
    restored, restoreDropped, pendingRestore, restoreDraft, discardDraft, observeRecord, forget]);
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
