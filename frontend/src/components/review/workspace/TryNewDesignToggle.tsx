/** OWNER: builder A. The visible "Try new design" switch (PLACEHOLDER). */
import type { TryNewDesignToggleProps } from "./contract";

export function TryNewDesignToggle({ on, onChange }: TryNewDesignToggleProps) {
  return (
    <label className="inline-flex items-center gap-2 text-sm text-slateish-300">
      <input type="checkbox" checked={on} onChange={(e) => onChange(e.target.checked)} />
      Try new design
    </label>
  );
}
