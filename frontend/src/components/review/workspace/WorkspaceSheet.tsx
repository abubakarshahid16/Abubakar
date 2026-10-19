/**
 * OWNER: builder C. The workspace's comment sheet (PLACEHOLDER - planner
 * team): CrsTable over plainRow(rows), with depth / show-met / selection /
 * edit-remove state as CrsSheetView keeps it, and WorkspaceEvidence on the
 * right when `openRowKey` is set. The only comment list on the screen.
 */
import type { WorkspaceSheetProps } from "./contract";

export function WorkspaceSheet({ rows, footer }: WorkspaceSheetProps) {
  return (
    <div data-testid="ws-sheet" data-rows={rows.length}>
      {footer}
    </div>
  );
}
