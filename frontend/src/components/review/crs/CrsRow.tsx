/**
 * One row of the CRS-first Sheet (order 95 piece 2): the client's seven columns,
 * the tier word, and Keep / Edit wording / Remove.
 */
import { useEffect, useRef, useState } from "react";

import type { CrsRow as Row } from "./crsRows";
import { type Decision, REMOVE_REASONS, type RemoveReason, decisionWords, wordingOf } from "./useCrsDecisions";

export type RowMode = "edit" | "remove" | null;

export interface CrsRowProps {
  row: Row;
  decision: Decision | null;
  selected: boolean;
  opened: boolean;
  /** Spec 1.2: a Met row surfaced as a spot check is said to be one. */
  spotCheck: boolean;
  mode: RowMode;
  onSelect: () => void;
  onOpenEvidence: () => void;
  onMode: (mode: RowMode) => void;
  onKeep: () => void;
  onEdit: (observation: string, requiredAction: string) => void;
  onRemove: (reason: RemoveReason) => void;
  onClear: () => void;
}

const TIER_CLASS: Record<string, string> = {
  A: "text-slateish-400",
  B: "text-warn-500",
  C: "text-danger-500 font-semibold",
};

export function CrsRow(props: CrsRowProps) {
  const { row, decision, selected, opened, spotCheck, mode, onSelect, onOpenEvidence, onMode } = props;
  const ref = useRef<HTMLTableRowElement | null>(null);
  useEffect(() => {
    if (selected && ref.current && typeof ref.current.scrollIntoView === "function") {
      ref.current.scrollIntoView({ block: "nearest" });
    }
  }, [selected]);
  const words = wordingOf(decision, row);
  const removed = decision?.kind === "remove";
  const tierWord = row.tier.reason ? `${row.tier.label}: ${row.tier.reason}` : row.tier.label;
  const label = `Comment ${row.commentNo ?? "-"}: ${row.item || row.observation}`;
  return (
    <tr
      ref={ref} onClick={() => { onSelect(); onOpenEvidence(); }} data-row-key={row.key} data-tier={row.tier.tier} aria-selected={selected}
      aria-label={label}
      className={`align-top ${selected ? "bg-ink-800" : "bg-ink-900"} ${removed ? "opacity-60" : ""} border-b border-ink-700`}
    >
      <td className={`px-2 py-2 text-xs ${TIER_CLASS[row.tier.tier]}`}>
        {tierWord}
        {spotCheck && <span className="block text-xs text-slateish-500">spot check</span>}
        {row.tier.tier === "C" && !opened && <span className="block text-xs text-slateish-400">not opened yet</span>}
      </td>
      <td className="px-2 py-2 text-sm text-slateish-200">
        <button type="button" onClick={(e) => { e.stopPropagation(); onSelect(); onOpenEvidence(); }}
          aria-label={`Open evidence for ${label}`}
          className="text-signal-300 underline-offset-2 hover:underline">
          {row.commentNo ?? "–"}
        </button>
      </td>
      <td className="px-2 py-2 text-sm text-slateish-200">{row.pageOrSection}</td>
      <td className="px-2 py-2 text-sm text-slateish-100">{row.item}</td>
      <td className="px-2 py-2 text-sm text-slateish-300">{row.clauseAndStandard}</td>
      {mode === "edit" ? (
        <EditCells row={row} words={words} onSave={(o, a) => { props.onEdit(o, a); onMode(null); }} onCancel={() => onMode(null)} />
      ) : (
        <>
          <td className={`px-2 py-2 text-sm text-slateish-200 ${removed ? "line-through" : ""}`}>{words.observation}</td>
          <td className={`px-2 py-2 text-sm text-slateish-100 ${removed ? "line-through" : ""}`}>{words.requiredAction}</td>
        </>
      )}
      <td className="px-2 py-2 text-sm text-slateish-300" data-testid="row-status">{decisionWords(decision, row)}</td>
      <td className="px-2 py-2 text-xs">
        {row.tier.tier !== "A" && mode !== "edit" && (
          <Actions {...props} />
        )}
      </td>
    </tr>
  );
}

function EditCells({ row, words, onSave, onCancel }: {
  row: Row; words: { observation: string; requiredAction: string };
  onSave: (observation: string, requiredAction: string) => void; onCancel: () => void;
}) {
  // The Observation is the review's own; only the Required action is the
  // engineer's wording (saved as `engineer_comment`, piece 6c).
  const observation = words.observation;
  const [action, setAction] = useState(words.requiredAction);
  const first = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => { first.current?.focus(); }, []);
  const field = "w-full rounded-[var(--radius-sm)] border border-ink-600 bg-ink-950 px-2 py-1 text-sm text-slateish-100";
  return (
    <td colSpan={2} className="px-2 py-2" onClick={(e) => e.stopPropagation()}>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="block text-xs text-slateish-400">
          Observation
          <textarea rows={3} value={observation} readOnly className={`${field} opacity-70`}
            aria-label={`Observation for comment ${row.commentNo ?? ""}`} />
        </label>
        <label className="block text-xs text-slateish-400">
          Required action
          <textarea ref={first} rows={3} value={action} onChange={(e) => setAction(e.target.value)} className={field}
            aria-label={`Required action for comment ${row.commentNo ?? ""}`} />
        </label>
      </div>
      <div className="mt-2 flex gap-2">
        <button type="button" onClick={() => onSave(observation.trim(), action.trim())}
          className="rounded-[var(--radius-sm)] bg-signal-500 px-3 py-1 text-xs font-semibold text-ink-950">Save wording</button>
        <button type="button" onClick={onCancel}
          className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-xs text-slateish-200">Cancel</button>
      </div>
    </td>
  );
}

function Actions({ row, decision, mode, onMode, onKeep, onRemove, onClear }: CrsRowProps) {
  const [reason, setReason] = useState<RemoveReason | "">("");
  const [error, setError] = useState("");
  const select = useRef<HTMLSelectElement | null>(null);
  useEffect(() => { if (mode === "remove") select.current?.focus(); }, [mode]);
  const no = row.commentNo ?? "";
  const btn = "rounded-[var(--radius-sm)] border border-ink-600 px-2 py-1 text-xs text-slateish-100 hover:border-ink-500";
  if (mode === "remove") {
    return (
      <div className="space-y-1" onClick={(e) => e.stopPropagation()}>
        <label htmlFor={`remove-${row.key}`} className="block text-slateish-400">Why remove comment {no}?</label>
        <select id={`remove-${row.key}`} ref={select} value={reason} onChange={(e) => { setReason(e.target.value as RemoveReason); setError(""); }}
          className="w-full rounded-[var(--radius-sm)] border border-ink-600 bg-ink-950 px-2 py-1 text-xs text-slateish-100">
          <option value="">Choose a reason</option>
          {REMOVE_REASONS.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <div className="flex gap-1">
          <button type="button" className={btn} data-action="remove-confirm" onClick={() => {
            if (!reason) { setError("Choose a reason first."); return; }
            onRemove(reason); onMode(null); setReason("");
          }}>Remove</button>
          <button type="button" className={btn} onClick={() => { onMode(null); setError(""); }}>Cancel</button>
        </div>
        {error && <p role="alert" className="text-danger-500">{error}</p>}
      </div>
    );
  }
  return (
    <div className="flex flex-wrap gap-1" onClick={(e) => e.stopPropagation()}>
      {decision?.kind === "remove" ? (
        <button type="button" className={btn} onClick={onClear} aria-label={`Put comment ${no} back`}>Put back</button>
      ) : (
        <>
          <button type="button" className={btn} data-action="keep" aria-pressed={decision?.kind === "keep"}
            onClick={onKeep} aria-label={`Keep comment ${no}`}>Keep</button>
          <button type="button" className={btn} data-action="edit" onClick={() => onMode("edit")}
            aria-label={`Edit wording of comment ${no}`}>Edit wording</button>
          <button type="button" className={btn} data-action="remove" onClick={() => onMode("remove")}
            aria-label={`Remove comment ${no}`}>Remove</button>
        </>
      )}
    </div>
  );
}
