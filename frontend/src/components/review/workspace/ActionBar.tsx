/** OWNER: builder B. "What you need to do" bar (PLACEHOLDER - planner team). */
import type { ActionBarProps } from "./contract";

export function ActionBar({ steps, onAction }: ActionBarProps) {
  return (
    <div role="region" aria-label="What you need to do" data-testid="ws-action-bar">
      {steps.map((s) => (
        <button key={s.id} type="button" disabled={!s.enabled} onClick={() => onAction(s.id)}>{s.label}</button>
      ))}
    </div>
  );
}
