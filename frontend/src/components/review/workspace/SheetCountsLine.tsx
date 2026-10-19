/** OWNER: builder B. The sheet header's count line (PLACEHOLDER - planner team). */
import type { SheetCountsLineProps } from "./contract";

export function SheetCountsLine({ numbers }: SheetCountsLineProps) {
  return <p data-testid="ws-sheet-counts"><span data-count="comments">{numbers.comments}</span> comments</p>;
}
