/** SPEC 4, 5 and 6: the four tiles (each a FILTER of the list), the line of how firm the result is, the rule book chips and the one
 *  line for rule books not held. */
import type { PointsListing } from "../../../api/reviewPoints";
import { TILE_LABELS, TILE_ORDER, firmnessLine, tileLine } from "./words";

export type TileKey = (typeof TILE_ORDER)[number];

export function Tiles({ counts, selected, onSelect }: { counts: PointsListing["counts"]; selected: TileKey | null; onSelect: (t: TileKey | null) => void }) {
  const firm = firmnessLine(counts);
  return (
    <div data-testid="v2-tiles" className="space-y-1">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {TILE_ORDER.map((t) => {
          const c = counts.tiles[t];
          const on = selected === t;
          return (
            <button key={t} type="button" aria-pressed={on} onClick={() => onSelect(on ? null : t)} data-testid={`v2-tile-${t}`}
              className={`rounded-[var(--radius-md)] border p-3 text-left ${on ? "border-signal-400 bg-ink-700" : "border-ink-600 bg-ink-850 hover:bg-ink-800"}`}>
              <span className="block text-xs text-slateish-400">{TILE_LABELS[t]}</span>
              <span className="block text-3xl font-semibold text-slateish-100">{c.total}</span>
              <span className="block min-h-[1rem] text-xs text-slateish-300">{tileLine(t, c)}</span>
            </button>
          );
        })}
      </div>
      <p className="text-xs text-slateish-400">
        {selected ? `Showing: ${TILE_LABELS[selected]}. ` : "Showing: every point. "}Click a tile to filter the list.
      </p>
      {firm && <p data-testid="v2-firm" className="text-xs text-slateish-300">{firm}</p>}
    </div>
  );
}

export function BookChips({ counts, selected, onSelect }: { counts: PointsListing["counts"]; selected: string | null; onSelect: (b: string | null) => void }) {
  const chip = (on: boolean) => `rounded-full border px-3 py-1 text-xs ${on ? "border-signal-400 bg-ink-700 text-slateish-100" : "border-ink-600 text-slateish-300 hover:bg-ink-800"}`;
  return (
    <div data-testid="v2-books" role="group" aria-label="Rule books" className="flex flex-wrap gap-2">
      <button type="button" aria-pressed={selected === null} className={chip(selected === null)} onClick={() => onSelect(null)}>All rule books</button>
      {counts.rule_books.map((b) => (
        <button key={b.name} type="button" aria-pressed={selected === b.name} className={chip(selected === b.name)} onClick={() => onSelect(selected === b.name ? null : b.name)}>
          {b.name} ({b.points})
        </button>
      ))}
      {counts.other_rule_books_points > 0 && (
        <span className="px-1 text-xs text-slateish-400" title={counts.other_rule_books_note ?? undefined}>
          {counts.other_rule_books_points} on rule books you may not read
        </span>
      )}
    </div>
  );
}

export function NotHeldLine({ counts, onSeeAll }: { counts: PointsListing["counts"]; onSeeAll: () => void }) {
  const h = counts.not_held;
  if (!h.total) return null;
  const names = h.names.join(", ");
  return (
    <p data-testid="v2-not-held" className="text-xs text-slateish-300">
      Not checked, rule book not held: {names}{h.more > 0 ? ` and ${h.more} more` : ""}.{" "}
      <button type="button" onClick={onSeeAll} className="text-signal-300 underline-offset-2 hover:underline">See all</button>
    </p>
  );
}
