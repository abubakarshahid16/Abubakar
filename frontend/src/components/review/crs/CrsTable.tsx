/**
 * The CRS table (order 95 piece 2): the client's seven columns, one row per
 * comment, Tier A behind one line, a depth selector above.
 *
 * Order 117: rows are memoised and get the same callbacks every render; a
 * long list (the "Everything" depth on a large review) shows its first 200
 * rows and a "Show more" button, and says how many it is showing of how many.
 */
import { useState } from "react";

import { type CrsRow as Row, DEPTHS, type Depth, CRS_COLUMNS } from "./crsRows";
import { CrsRow, type RowMode } from "./CrsRow";
import type { TierCounts } from "./tiers";
import type { CrsDecisions } from "./useCrsDecisions";

/** Rows drawn at first, and added per "Show more" press. */
export const ROW_PAGE = 200;

/** v2.1 (W1): each "Show" choice in plain words, shown under the choices
 *  (the choices' own names stay as they are). */
export const DEPTH_WORDS: Record<Depth, string> = {
  critical: "only what needs your judgement and clear failures.",
  standard: "every comment for the contractor.",
  everything: "also what met the standard or does not apply.",
};

export interface CrsTableProps {
  rows: Row[];
  allRows: Row[];
  counts: TierCounts;
  depth: Depth;
  onDepth: (depth: Depth) => void;
  showMet: boolean;
  onShowMet: (show: boolean) => void;
  spot: Set<string>;
  selectedKey: string | null;
  onSelect: (row: Row) => void;
  onOpenEvidence: (row: Row) => void;
  mode: { key: string; kind: RowMode } | null;
  onMode: (key: string, kind: RowMode) => void;
  decisions: CrsDecisions;
  /** #678: clauses the run judged not applicable; counted on the run, not rows here. */
  clausesNotApplicable: number | null;
  /** Workspace v2: the first column's heading. Absent = "Tier" (unchanged
   *  for the old sheet); the workspace passes a plain word. */
  tierHeader?: string;
  /** v2.1 round 2: a signed review is a record, not a draft: no Keep /
   *  Edit / Remove on any row and no key hint. Absent (false) on the old
   *  sheet, which is unchanged. */
  readOnly?: boolean;
  /** v2.2 round 2: the key hint line; the workspace's Simple view hides it. */
  showKeys?: boolean;
}

export function CrsTable(props: CrsTableProps) {
  const { rows, counts, depth, onDepth, showMet, onShowMet, spot, selectedKey, decisions, mode } = props;
  const hidden = counts.met + counts.notApplicable + counts.anotherDocument;
  const metShown = depth === "everything" || showMet;
  // How many rows to draw; back to one page when the depth changes, and
  // always far enough to include the selected row (J / K can reach past it).
  const [limit, setLimit] = useState({ depth, count: ROW_PAGE });
  const count = limit.depth === depth ? limit.count : ROW_PAGE;
  const selectedAt = selectedKey === null ? -1 : rows.findIndex((r) => r.key === selectedKey);
  const drawn = Math.max(count, selectedAt + 1);
  const visible = drawn >= rows.length ? rows : rows.slice(0, drawn);
  return (
    <div className="space-y-3">
      <fieldset className="flex flex-wrap items-center gap-2 text-sm">
        <legend className="sr-only">How much to show</legend>
        <span className="text-slateish-400">Show:</span>
        {DEPTHS.map((d) => (
          <label key={d.id} title={d.help} className={`cursor-pointer rounded-[var(--radius-sm)] border px-2 py-1 ${depth === d.id ? "border-signal-500 text-slateish-100" : "border-ink-700 text-slateish-300"}`}>
            <input type="radio" name="crs-depth" value={d.id} checked={depth === d.id} onChange={() => onDepth(d.id)} className="sr-only" />
            {d.label}
          </label>
        ))}
        {!props.readOnly && props.showKeys !== false && (
          <span className="ml-auto text-xs text-slateish-500">Keys: J / K next and previous · E edit · R remove · Enter keep</span>
        )}
        {/* v2.1 (W1): what each choice shows, said once in plain words. */}
        <p className="basis-full text-xs text-slateish-400" data-testid="crs-depth-help">
          {DEPTHS.map((d) => `${d.label}: ${DEPTH_WORDS[d.id]}`).join(" ")}
        </p>
      </fieldset>

      <div className="overflow-x-auto rounded-[var(--radius-md)] border border-ink-700">
        <table role="grid" className="w-full min-w-[64rem] border-collapse text-left" aria-label="Comment resolution sheet">
          <thead className="bg-ink-850 text-xs uppercase tracking-wide text-slateish-400">
            <tr>
              <th scope="col" className="px-2 py-2">{props.tierHeader ?? "Tier"}</th>
              {CRS_COLUMNS.map((c) => <th key={c} scope="col" className="px-2 py-2">{c}</th>)}
              <th scope="col" className="px-2 py-2"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <CrsRow
                key={row.key} row={row} decision={decisions.decisionOf(row.key)} selected={row.key === selectedKey}
                opened={Boolean(decisions.state.opened[row.key])} spotCheck={row.tier.label === "Met" && spot.has(row.key) && !metShown}
                mode={mode?.key === row.key ? mode.kind : null}
                onSelect={props.onSelect} onOpenEvidence={props.onOpenEvidence} onMode={props.onMode}
                onKeep={decisions.keep} onEdit={decisions.edit} onRemove={decisions.remove} onClear={decisions.clear}
                readOnly={props.readOnly}
              />
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={CRS_COLUMNS.length + 2} className="px-3 py-4 text-sm text-slateish-300">Nothing to show with this choice. Pick "Everything" to see all of it.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {visible.length < rows.length && (
        <p className="flex items-center gap-3 text-sm text-slateish-300" data-testid="crs-more">
          Showing the first {visible.length.toLocaleString()} of {rows.length.toLocaleString()} lines in this list.
          <button type="button" onClick={() => setLimit({ depth, count: drawn + ROW_PAGE })}
            className="rounded-[var(--radius-sm)] border border-ink-600 px-2 py-1 text-xs text-slateish-100 hover:border-ink-500">
            Show {Math.min(ROW_PAGE, rows.length - visible.length).toLocaleString()} more
          </button>
        </p>
      )}

      {hidden > 0 && depth !== "everything" && (
        <p className="text-sm text-slateish-300" data-testid="met-line">
          {counts.met.toLocaleString()} met, {counts.notApplicable.toLocaleString()} not applicable
          {counts.anotherDocument > 0 ? `, ${counts.anotherDocument.toLocaleString()} for another document` : ""}
          {!showMet && spot.size > 0 ? ` (${spot.size} shown above as a sample to check)` : ""}:{" "}
          <button type="button" onClick={() => onShowMet(!showMet)} className="text-signal-300 underline-offset-2 hover:underline">
            {showMet ? "hide" : "show"}
          </button>
        </p>
      )}
      {metShown && typeof props.clausesNotApplicable === "number" && props.clausesNotApplicable > 0 && (
        <p className="text-xs text-slateish-400">
          {props.clausesNotApplicable.toLocaleString()} requirements in the standards were judged not to apply to this equipment
          and were not compared; they are counted for the whole review, not listed here.
        </p>
      )}
    </div>
  );
}
