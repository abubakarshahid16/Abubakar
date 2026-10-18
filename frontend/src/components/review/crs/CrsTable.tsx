/**
 * The CRS table (order 95 piece 2): the client's seven columns, one row per
 * comment, Tier A behind one line, a depth selector above.
 */
import { type CrsRow as Row, DEPTHS, type Depth, CRS_COLUMNS } from "./crsRows";
import { CrsRow, type RowMode } from "./CrsRow";
import type { TierCounts } from "./tiers";
import type { CrsDecisions, RemoveReason } from "./useCrsDecisions";

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
}

export function CrsTable(props: CrsTableProps) {
  const { rows, counts, depth, onDepth, showMet, onShowMet, spot, selectedKey, decisions, mode } = props;
  const hidden = counts.met + counts.notApplicable + counts.anotherDocument;
  const metShown = depth === "everything" || showMet;
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
        <span className="ml-auto text-xs text-slateish-500">Keys: J / K next and previous · E edit · R remove · Enter keep</span>
      </fieldset>

      <div className="overflow-x-auto rounded-[var(--radius-md)] border border-ink-700">
        <table role="grid" className="w-full min-w-[64rem] border-collapse text-left" aria-label="Comment resolution sheet">
          <thead className="bg-ink-850 text-xs uppercase tracking-wide text-slateish-400">
            <tr>
              <th scope="col" className="px-2 py-2">Tier</th>
              {CRS_COLUMNS.map((c) => <th key={c} scope="col" className="px-2 py-2">{c}</th>)}
              <th scope="col" className="px-2 py-2"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <CrsRow
                key={row.key} row={row} decision={decisions.decisionOf(row.key)} selected={row.key === selectedKey}
                opened={Boolean(decisions.state.opened[row.key])} spotCheck={row.tier.label === "Met" && spot.has(row.key) && !metShown}
                mode={mode?.key === row.key ? mode.kind : null}
                onSelect={() => props.onSelect(row)} onOpenEvidence={() => props.onOpenEvidence(row)}
                onMode={(kind) => props.onMode(row.key, kind)}
                onKeep={() => decisions.keep(row.key)}
                onEdit={(o, a) => decisions.edit(row.key, o, a)}
                onRemove={(reason: RemoveReason) => decisions.remove(row.key, reason)}
                onClear={() => decisions.clear(row.key)}
              />
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={CRS_COLUMNS.length + 2} className="px-3 py-4 text-sm text-slateish-300">No row to show at this depth.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {hidden > 0 && depth !== "everything" && (
        <p className="text-sm text-slateish-300" data-testid="met-line">
          {counts.met.toLocaleString()} met, {counts.notApplicable.toLocaleString()} not applicable
          {counts.anotherDocument > 0 ? `, ${counts.anotherDocument.toLocaleString()} for another document` : ""}
          {!showMet && spot.size > 0 ? ` (${spot.size} shown above as a spot check)` : ""}:{" "}
          <button type="button" onClick={() => onShowMet(!showMet)} className="text-signal-300 underline-offset-2 hover:underline">
            {showMet ? "hide" : "show"}
          </button>
        </p>
      )}
      {metShown && typeof props.clausesNotApplicable === "number" && props.clausesNotApplicable > 0 && (
        <p className="text-xs text-slateish-400">
          {props.clausesNotApplicable.toLocaleString()} clauses of the standards were judged not applicable to this equipment
          and were not compared; they are counted on the run, not listed here.
        </p>
      )}
    </div>
  );
}
