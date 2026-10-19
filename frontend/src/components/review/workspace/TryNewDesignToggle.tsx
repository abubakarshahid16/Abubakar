/**
 * OWNER: builder A (v2.1 placement: builder D). The visible "Try new design"
 * switch. Shown on the Submittals landing and on the workspace (to switch
 * back). The choice is per browser; the parent stores it
 * (`useWorkspaceSwitch`).
 *
 * v2.1 (W3): small, in the top right corner of the page, inside the page's
 * own top margin. It takes no line of its own, so it never sits above the
 * review's title (the wrapper has no height; the switch hangs into the
 * main area's top padding).
 */
import type { TryNewDesignToggleProps } from "./contract";

export function TryNewDesignToggle({ on, onChange }: TryNewDesignToggleProps) {
  return (
    <div className="relative h-0" data-testid="try-new-design">
      <label className="absolute -top-5 right-0 inline-flex cursor-pointer items-center gap-1.5 text-xs leading-4 text-slateish-400 hover:text-slateish-200">
        <input
          type="checkbox" role="switch" checked={on} aria-checked={on}
          onChange={(e) => onChange(e.target.checked)}
          className="h-3 w-3"
        />
        Try new design
      </label>
    </div>
  );
}
