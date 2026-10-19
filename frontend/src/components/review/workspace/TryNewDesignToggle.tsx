/**
 * OWNER: builder A. The visible "Try new design" switch. Shown on the
 * Submittals landing and on the workspace (to switch back). The choice is
 * per browser; the parent stores it (`useWorkspaceSwitch`).
 */
import type { TryNewDesignToggleProps } from "./contract";

export function TryNewDesignToggle({ on, onChange }: TryNewDesignToggleProps) {
  return (
    <div className="flex justify-end">
      <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-slateish-300">
        <input
          type="checkbox" role="switch" checked={on} aria-checked={on}
          onChange={(e) => onChange(e.target.checked)}
        />
        Try new design
      </label>
    </div>
  );
}
