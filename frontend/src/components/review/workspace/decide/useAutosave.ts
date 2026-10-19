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
 * nothing is saved, so Undo only ever takes back decisions on screen (the
 * record has no "unconfirm").
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { CrsRow } from "../../crs/crsRows";
import { saveCrsDecisions } from "../../crs/saveCrsDecisions";
import type { CrsDecisions, Decision } from "../../crs/useCrsDecisions";
import type { AutosaveStatus } from "../contract";

/** How long after the last decision the save starts. */
export const AUTOSAVE_DELAY_MS = 1200;

export interface UseAutosaveArgs {
  runId: string;
  rows: CrsRow[];
  decisions: CrsDecisions;
  /** Read the run again after something reached the record. */
  refresh: () => Promise<void>;
  /** Hold saving (an Undo is on offer). */
  paused?: boolean;
  /** Save nothing and start no timer (a signed review). Edits on screen stay
   *  unsaved and visible. */
  disabled?: boolean;
  delayMs?: number;
}

function same(a: Decision | undefined, b: Decision | undefined): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

/** "Comment 3: the server said no" -> one plain line for the saving line. */
function failureWords(failed: { message: string }[]): string {
  const first = failed[0]?.message ?? "the record did not answer";
  return failed.length === 1 ? first : `${failed.length} decisions did not save. ${first}`;
}

export function useAutosave({
  runId, rows, decisions, refresh, paused = false, disabled = false, delayMs = AUTOSAVE_DELAY_MS,
}: UseAutosaveArgs): AutosaveStatus {
  const [phase, setPhase] = useState<AutosaveStatus["phase"]>("idle");
  const [message, setMessage] = useState<string | null>(null);
  const latest = useRef({ rows, decisions, refresh });
  useEffect(() => { latest.current = { rows, decisions, refresh }; });
  const inFlight = useRef(false);
  const again = useRef(false);
  /** The unsaved set that last failed: not tried again by itself. */
  const failedSig = useRef<string | null>(null);

  const signature = useMemo(
    () => JSON.stringify(decisions.unsaved.map((key) => [key, decisions.state.decisions[key] ?? null])),
    [decisions.unsaved, decisions.state.decisions],
  );

  /** The newest saveNow, for the timer and for a save asked mid-save. */
  const saveNowRef = useRef<() => Promise<void>>(async () => {});

  const disabledRef = useRef(disabled);
  useEffect(() => { disabledRef.current = disabled; });
  const saveNow = useCallback(async () => {
    if (disabledRef.current) return;
    if (inFlight.current) { again.current = true; return; }
    const { rows: rowsNow, decisions: d } = latest.current;
    const keys = [...d.unsaved];
    if (keys.length === 0) return;
    const sent: Record<string, Decision> = {};
    for (const key of keys) if (d.state.decisions[key]) sent[key] = d.state.decisions[key];
    const sig = JSON.stringify(keys.map((key) => [key, sent[key] ?? null]));
    inFlight.current = true;
    setPhase("saving");
    setMessage(null);
    let outcome: Awaited<ReturnType<typeof saveCrsDecisions>>;
    try {
      outcome = await saveCrsDecisions(runId, rowsNow, sent, keys);
    } catch {
      outcome = { saved: [], failed: [{ key: "", message: "the connection dropped while saving" }], wrote: false };
    }
    // Only what is still the same on screen counts as saved.
    const now = latest.current.decisions;
    now.markSaved(outcome.saved.filter((key) => same(now.state.decisions[key], sent[key])));
    if (outcome.failed.length > 0) {
      failedSig.current = sig;
      setPhase("failed");
      setMessage(failureWords(outcome.failed));
    } else {
      failedSig.current = null;
      setPhase("saved");
    }
    if (outcome.wrote) {
      try { await latest.current.refresh(); } catch { /* the next read catches up */ }
    }
    inFlight.current = false;
    if (again.current) { again.current = false; void saveNowRef.current(); }
  }, [runId]);
  useEffect(() => { saveNowRef.current = saveNow; }, [saveNow]);

  const pending = decisions.unsaved.length > 0;
  useEffect(() => {
    if (!pending || paused || disabled || signature === failedSig.current) return;
    const timer = setTimeout(() => { void saveNowRef.current(); }, delayMs);
    return () => clearTimeout(timer);
  }, [signature, pending, paused, disabled, delayMs]);

  return useMemo(() => ({ phase, message, waiting: paused && pending, saveNow }), [phase, message, paused, pending, saveNow]);
}
