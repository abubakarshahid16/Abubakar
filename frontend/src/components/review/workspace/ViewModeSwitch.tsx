/**
 * v2.2: the small "Simple | Detailed" switch, one control for both pages
 * (the first page and the review page). It sits in the normal page flow
 * (never absolutely placed), so it cannot cover the title or the "Try new
 * design" switch on a narrow screen. The choice itself lives in useViewMode.
 */
import type { ViewMode } from "./useViewMode";

export function ViewModeSwitch({ mode, onMode }: { mode: ViewMode; onMode: (mode: ViewMode) => void }) {
  const button = (value: ViewMode, label: string) => (
    <button
      type="button"
      aria-pressed={mode === value}
      onClick={() => onMode(value)}
      title={value === "simple"
        ? "Show only what you need to finish the review"
        : "Also show the engineer pages: how it was reviewed, findings, standards"}
      className={`px-3 py-1 text-xs font-semibold ${
        mode === value ? "bg-ink-700 text-slateish-100" : "text-slateish-400 hover:text-slateish-200"
      }`}
    >
      {label}
    </button>
  );
  return (
    <div role="group" aria-label="View" className="inline-flex shrink-0 overflow-hidden rounded-full border border-ink-600" data-testid="view-mode-switch">
      {button("simple", "Simple")}
      {button("detailed", "Detailed")}
    </div>
  );
}

