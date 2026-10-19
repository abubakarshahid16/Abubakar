/**
 * Order 139 part 2: the sheet's two once-said lines about its rows. When the
 * server sent no grouping, that every finding is shown as a row of its own
 * (`UNGROUPED_NOTE`); and how many findings the file lists in its Review
 * notes instead of as comment rows (`serverNotesLine`); and (release 1b) that
 * the grouping shown is from the last time it could be read
 * (`STALE_GROUPING_NOTE`, `stale`). Nothing when none.
 */
import { type CrsRow, STALE_GROUPING_NOTE, groupingNote, serverNotesLine } from "./crsRows";

export function SheetGroupingNote({ rows, notes, stale = false }: { rows: CrsRow[]; notes: number; stale?: boolean }) {
  const ungrouped = groupingNote(rows);
  const noted = serverNotesLine(notes);
  if (!ungrouped && !noted && !stale) return null;
  return (
    <div className="space-y-1 text-sm text-slateish-300" data-testid="sheet-grouping-note">
      {stale && <p role="note" data-testid="stale-grouping-note">{STALE_GROUPING_NOTE}</p>}
      {ungrouped && <p role="note">{ungrouped}</p>}
      {noted && <p>{noted}</p>}
    </div>
  );
}
