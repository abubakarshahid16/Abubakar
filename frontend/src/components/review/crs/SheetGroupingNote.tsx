/**
 * Order 139 part 2: the sheet's two once-said lines about its rows. When the
 * server sent no grouping, that every finding is shown as a row of its own
 * (`UNGROUPED_NOTE`); and how many findings the file lists in its Review
 * notes instead of as comment rows (`serverNotesLine`). Nothing when neither.
 */
import { type CrsRow, groupingNote, serverNotesLine } from "./crsRows";

export function SheetGroupingNote({ rows, notes }: { rows: CrsRow[]; notes: number }) {
  const ungrouped = groupingNote(rows);
  const noted = serverNotesLine(notes);
  if (!ungrouped && !noted) return null;
  return (
    <div className="space-y-1 text-sm text-slateish-300" data-testid="sheet-grouping-note">
      {ungrouped && <p role="note">{ungrouped}</p>}
      {noted && <p>{noted}</p>}
    </div>
  );
}
