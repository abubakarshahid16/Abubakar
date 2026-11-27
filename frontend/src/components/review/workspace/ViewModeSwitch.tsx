/**
 * v2.2: the small "Simple | Detailed" switch, one control for both pages
 * (the first page and the review page). It sits in the normal page flow
 * (never absolutely placed), so it cannot cover the title or the "Try new
 * design" switch on a narrow screen. The choice itself lives in useViewMode.
 */
import type { ViewMode } from "./useViewMode";
import { Button } from "../../kit/Kit";

export function ViewModeSwitch({ mode, onMode }: { mode: ViewMode; onMode: (mode: ViewMode) => void }) {
  const button = (value: ViewMode, label: string) => (
    // the shared kit's small button; the chosen one shows the kit's "on" state (H's gate, 27 Nov 2026: the old pill was a third look)
    <Button size="sm" aria-pressed={mode === value} onClick={() => onMode(value)}
      title={value === "simple"
        ? "Show only what you need to finish the review"
        : "Also show the engineer pages: how it was reviewed, comments, standards"}>
      {label}
    </Button>
  );
  return (
    <div role="group" aria-label="View" className="kit-row kit-gap-2 shrink-0" data-testid="view-mode-switch">
      {button("simple", "Simple")}
      {button("detailed", "Detailed")}
    </div>
  );
}

