/**
 * OWNER: builder B. D4: the workspace saves decisions by itself.
 *
 * A short pause after the last decision, the unsaved ones go to the record
 * through the comment sheet's own `saveCrsDecisions` (no new route). Only a
 * decision that is still the same on screen when the answer comes back is
 * marked saved, so a decision changed while saving is sent again next time.
 * A failed save says why in plain words and is not retried in a loop: it is
 * tried again when a decision changes, or on "Save now".
 *
 * While the Undo of "Keep all remaining comments" is offered (`paused`),
 * nothing is saved by itself, so Undo only ever takes back decisions on
 * screen (the record has no "unconfirm"). Only "Save now" (which ends the
 * Undo offer) saves while paused. v2.1 round 2: that holds for every path,
 * the timer and the "save again" after a save that was already running:
 * saves run one after another, and each one that was not asked for by
 * "Save now" checks the pause when its turn comes.
 *
 * `disabled` (a signed review): no timer and no save at all, "Save now"
 * included; decisions not saved stay on screen, shown as not saved.
 *
 * A decision whose comment is no longer on the sheet is taken off the
 * screen, the unsaved list and the draft (`decisions.forget`), so Sign is
 * never held by something that can never save. Order 141 D: how many were
 * taken off this visit is kept (`dropped`), so a later save that works never
 * says "every decision is on the record" about them.
 *
 * The hook also tells the decisions what the record holds
 * (`decisions.observeRecord`), which the draft uses, and puts its save in
 * the app's `LeaveSaverContext`, for "Save and leave".
 */
import { useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import type { CrsRow } from "../../crs/crsRows";
import { type SaveFailure, saveCrsDecisions } from "../../crs/saveCrsDecisions";
import type { CrsDecisions, Decision } from "../../crs/useCrsDecisions";
import type { AutosaveStatus } from "../contract";
import { LeaveSaverContext } from "../useLeaveGuard";

/** How long after the last decision the save starts. */
export const AUTOSAVE_DELAY_MS = 1200;

export interface UseAutosaveArgs {
  runId: string;
  rows: CrsRow[];
  decisions: CrsDecisions;
  /** Read the run again after something reached the record. */
  refresh: () => Promise<void>;
  /** Hold saving (an Undo is on offer). "Save now" still saves. */
  paused?: boolean;
  /** No timers and no saves at all (the review is signed). */
  disabled?: boolean;
  /** Runs before every save the reader asked for ("Save now", "Save and
   *  leave"): the workspace ends the Undo offer here. */
  beforeSaveNow?: () => void;
  delayMs?: number;
}

/** The status, with `saveNow` saying whether nothing is left unsaved. */
export type AutosaveResult = Omit<AutosaveStatus, "saveNow"> & { saveNow: () => Promise<boolean> };

function same(a: Decision | undefined, b: Decision | undefined): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

/** The failures as plain words ("Comment 3 was not saved. Try again in a
 *  moment.") and the server's own words folded under them. */
export function failureWords(failed: SaveFailure[]): { message: string; detail: string | null } {
  if (failed.length === 0) return { message: "The decisions were not saved. Try again in a moment.", detail: null };
  const first = failed[0];
  const firstWords = first.words ?? first.message;
  const message = failed.length === 1 ? firstWords : `${failed.length} decisions were not saved. ${firstWords}`;
  const details = failed.map((f) => f.detail).filter((d): d is string => Boolean(d));
  return { message, detail: details.length ? details.join("; ") : null };
}

export function useAutosave({
  runId, rows, decisions, refresh, paused = false, disabled = false, beforeSaveNow, delayMs = AUTOSAVE_DELAY_MS,
}: UseAutosaveArgs): AutosaveResult {
  const [phase, setPhase] = useState<AutosaveStatus["phase"]>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const [detail, setDetail] = useState<string | null>(null);
  const [dropped, setDropped] = useState(0);
  const latest = useRef({ rows, decisions, refresh, paused, disabled, beforeSaveNow });
  useLayoutEffect(() => { latest.current = { rows, decisions, refresh, paused, disabled, beforeSaveNow }; });
  /** Saves run one after another, never two at once. */
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  /** What this hook put on the record, per key: a save that runs before the
   *  screen has caught up with the last one does not send it again. */
  const putOnRecord = useRef(new Map<string, string>());
  /** The unsaved set that last failed: not tried again by itself. */
  const failedSig = useRef<string | null>(null);

  // The draft needs what the record holds; a signed review keeps none.
  const observeRecord = decisions.observeRecord;
  useEffect(() => { observeRecord?.(rows, disabled); }, [observeRecord, rows, disabled]);

  const signature = useMemo(
    () => JSON.stringify(decisions.unsaved.map((key) => [key, decisions.state.decisions[key] ?? null])),
    [decisions.unsaved, decisions.state.decisions],
  );

  /** One save. `asked`: the reader asked for it ("Save now"), so a pause
   *  does not hold it. True when nothing is left unsaved afterwards. */
  const runSave = useCallback(async (asked: boolean): Promise<boolean> => {
    const { rows: rowsNow, decisions: d, paused: pausedNow, disabled: off } = latest.current;
    if (off) return d.unsaved.length === 0;
    if (!asked && pausedNow) return false;
    const keys = d.unsaved.filter((key) => {
      const decision = d.state.decisions[key];
      return decision && putOnRecord.current.get(key) !== JSON.stringify(decision);
    });
    if (keys.length === 0) return true;
    // Nothing to save against until the sheet is read.
    if (rowsNow.length === 0) return false;
    const sent: Record<string, Decision> = {};
    for (const key of keys) sent[key] = d.state.decisions[key];
    const sig = JSON.stringify(keys.map((key) => [key, sent[key] ?? null]));
    setPhase("saving");
    setMessage(null);
    setDetail(null);
    let outcome: Awaited<ReturnType<typeof saveCrsDecisions>>;
    try {
      outcome = await saveCrsDecisions(runId, rowsNow, sent, keys);
    } catch {
      outcome = {
        saved: [], missing: [], wrote: false,
        failed: [{ key: "", message: "the connection dropped while saving",
          words: "The decisions were not saved. The connection dropped while saving; try again in a moment.", detail: null }],
      };
    }
    // Only what is still the same on screen counts as saved.
    const now = latest.current.decisions;
    const savedNow = outcome.saved.filter((key) => same(now.state.decisions[key], sent[key]));
    for (const key of savedNow) putOnRecord.current.set(key, JSON.stringify(sent[key]));
    now.markSaved(savedNow);
    const missing = outcome.missing ?? [];
    if (missing.length > 0) {
      now.forget?.(missing);
      setDropped((n) => n + missing.length);
    }
    let ok: boolean;
    if (outcome.failed.length > 0) {
      failedSig.current = sig;
      const words = failureWords(outcome.failed);
      setPhase("failed");
      setMessage(words.message);
      setDetail(words.detail);
      // A decision only taken off (its comment left the sheet) holds nothing.
      ok = outcome.failed.every((f) => missing.includes(f.key));
    } else {
      failedSig.current = null;
      setPhase("saved");
      ok = true;
    }
    if (outcome.wrote) {
      try { await latest.current.refresh(); } catch { /* the next read catches up */ }
    }
    return ok;
  }, [runId]);

  const enqueue = useCallback((asked: boolean): Promise<boolean> => {
    const run = queue.current.then(() => runSave(asked));
    queue.current = run.catch(() => false);
    return run.catch(() => false);
  }, [runSave]);

  /** "Save now": ends the Undo offer (beforeSaveNow) and saves even while
   *  paused; never on a disabled (signed) review. */
  const saveNow = useCallback(async (): Promise<boolean> => {
    if (latest.current.disabled) return latest.current.decisions.unsaved.length === 0;
    latest.current.beforeSaveNow?.();
    return enqueue(true);
  }, [enqueue]);

  // "Save and leave" in the app's question uses this same save.
  const register = useContext(LeaveSaverContext);
  useEffect(() => {
    if (!register) return;
    register(saveNow);
    return () => register(null);
  }, [register, saveNow]);

  const pending = decisions.unsaved.length > 0;
  useEffect(() => {
    if (!pending || paused || disabled || signature === failedSig.current) return;
    const timer = setTimeout(() => { void enqueue(false); }, delayMs);
    return () => clearTimeout(timer);
  }, [signature, pending, paused, disabled, delayMs, enqueue]);

  return useMemo(() => ({ phase, message, detail, waiting: paused && pending && !disabled, dropped, saveNow }),
    [phase, message, detail, paused, pending, disabled, dropped, saveNow]);
}
