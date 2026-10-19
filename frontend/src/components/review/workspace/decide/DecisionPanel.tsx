/**
 * OWNER: builder B. D1: Keep / Edit wording / Remove (with a reason) for the
 * comment open in the evidence panel, so a comment is decided where its
 * evidence is read.
 *
 * Keys while the panel is open (the table's own keys sleep then):
 * Enter keeps, E edits the wording, R removes (asks for a reason). Never
 * while typing, never with a modifier held, and Enter on a focused button is
 * that button's own press. J / K and Escape stay the panel's own (next,
 * previous, close).
 *
 * After a decision the screen moves to the next undecided comment
 * (`onDecided`); the decision itself goes through `useCrsDecisions`, exactly
 * as the table's buttons do, and saves by itself (useAutosave).
 */
import { useEffect, useRef, useState } from "react";

import type { CrsRow } from "../../crs/crsRows";
import {
  type CrsDecisions, REMOVE_REASONS, type RemoveReason, decisionWords, wordingOf,
} from "../../crs/useCrsDecisions";

export interface DecisionPanelProps {
  row: CrsRow;
  decisions: CrsDecisions;
  /** A decision was just taken on `row`: move on. */
  onDecided: (rowKey: string) => void;
  /** Said under the buttons (e.g. "That was the last comment to decide."). */
  note?: string | null;
}

/** What the keys do in the panel; the words of the hint shown under it. */
export const PANEL_KEYS_HINT = "Keys: Enter keep · E edit wording · R remove · J / K next and previous · Esc close";

const BUTTON = "rounded-[var(--radius-sm)] border px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-50";

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);
}

export function DecisionPanel({ row, decisions, onDecided, note = null }: DecisionPanelProps) {
  const [mode, setMode] = useState<"edit" | "remove" | null>(null);
  const [action, setAction] = useState("");
  const [reason, setReason] = useState<RemoveReason | "">("");
  const [error, setError] = useState<string | null>(null);
  const keepRef = useRef<HTMLButtonElement | null>(null);
  const decision = decisions.decisionOf(row.key);

  // A new row: forms closed. (Set during render, React's way of resetting
  // state on a prop change.)
  const [rowFor, setRowFor] = useState(row.key);
  if (rowFor !== row.key) { setRowFor(row.key); setMode(null); setError(null); }

  // The panel gives the keyboard to Close when it opens; Keep takes it just
  // after, so Enter keeps (as the hint says) instead of closing the panel.
  useEffect(() => {
    const timer = setTimeout(() => keepRef.current?.focus(), 0);
    return () => clearTimeout(timer);
  }, []);

  const keep = () => { decisions.keep(row.key); onDecided(row.key); };
  const startEdit = () => {
    setAction(wordingOf(decision, row).requiredAction);
    setError(null);
    setMode("edit");
  };
  const startRemove = () => {
    setReason(decision?.kind === "remove" ? decision.reason : "");
    setError(null);
    setMode("remove");
  };
  const saveEdit = () => {
    if (!action.trim()) { setError("Write the required action first."); return; }
    decisions.edit(row.key, wordingOf(decision, row).observation, action.trim());
    setMode(null);
    onDecided(row.key);
  };
  const confirmRemove = () => {
    if (!reason) { setError("Choose why this comment is removed."); return; }
    decisions.remove(row.key, reason);
    setMode(null);
    onDecided(row.key);
  };

  const keys = useRef({ keep, startEdit, startRemove, mode });
  useEffect(() => { keys.current = { keep, startEdit, startRemove, mode }; });
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (isTyping(event.target) || keys.current.mode !== null) return;
      const key = event.key.toLowerCase();
      if (key === "enter") {
        // Enter on a focused button or link is that control's own press.
        const tag = (event.target as HTMLElement | null)?.tagName;
        if (tag === "BUTTON" || tag === "A" || tag === "SUMMARY") return;
        event.preventDefault();
        keys.current.keep();
      } else if (key === "e") { event.preventDefault(); keys.current.startEdit(); }
      else if (key === "r") { event.preventDefault(); keys.current.startRemove(); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const h = "text-xs font-semibold uppercase tracking-wide text-slateish-400";
  return (
    <section aria-label="Your decision" data-testid="ws-decide" data-row={row.key}
      className="space-y-2 rounded-[var(--radius-sm)] border border-signal-500/40 bg-ink-950/40 p-3">
      <h3 className={h}>Your decision</h3>
      <p className="text-sm text-slateish-200" data-testid="ws-decide-now">
        {decision ? `Now: ${decisionWords(decision, row)}.` : row.priorState === "agreed" ? "Kept earlier." : "No decision yet."}
      </p>
      {mode === null && (
        <div className="flex flex-wrap gap-2">
          <button ref={keepRef} type="button" onClick={keep} className={`${BUTTON} border-signal-500 bg-signal-500 text-ink-950`}>
            Keep
          </button>
          <button type="button" onClick={startEdit} className={`${BUTTON} border-ink-600 text-slateish-100`}>Edit wording</button>
          <button type="button" onClick={startRemove} className={`${BUTTON} border-ink-600 text-slateish-100`}>Remove with reason</button>
        </div>
      )}
      {mode === "edit" && (
        <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); saveEdit(); }}>
          <label className="block text-sm text-slateish-200">
            Required action (what the contractor must do)
            <textarea autoFocus rows={3} value={action} onChange={(e) => setAction(e.target.value)}
              className="mt-1 w-full rounded-[var(--radius-sm)] border border-ink-600 bg-ink-950 px-2 py-1 text-sm text-slateish-100" />
          </label>
          <div className="flex gap-2">
            <button type="submit" className={`${BUTTON} border-signal-500 bg-signal-500 text-ink-950`}>Use this wording</button>
            <button type="button" onClick={() => setMode(null)} className={`${BUTTON} border-ink-600 text-slateish-100`}>Cancel</button>
          </div>
        </form>
      )}
      {mode === "remove" && (
        <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); confirmRemove(); }}>
          <fieldset className="space-y-1">
            <legend className="text-sm text-slateish-200">Why remove this comment?</legend>
            {REMOVE_REASONS.map((r, i) => (
              <label key={r} className="flex items-center gap-2 text-sm text-slateish-200">
                <input type="radio" name={`ws-remove-${row.key}`} value={r} checked={reason === r} autoFocus={i === 0}
                  onChange={() => setReason(r)} />
                {r}
              </label>
            ))}
          </fieldset>
          <div className="flex gap-2">
            <button type="submit" className={`${BUTTON} border-signal-500 bg-signal-500 text-ink-950`}>Remove</button>
            <button type="button" onClick={() => setMode(null)} className={`${BUTTON} border-ink-600 text-slateish-100`}>Cancel</button>
          </div>
        </form>
      )}
      {error && <p role="alert" className="text-sm text-danger-500">{error}</p>}
      {note && <p role="status" data-testid="ws-decide-note" className="text-sm text-slateish-300">{note}</p>}
      <p className="text-xs text-slateish-500" data-testid="ws-decide-keys">{PANEL_KEYS_HINT}</p>
    </section>
  );
}
