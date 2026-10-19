/** OWNER: builder A. The tab strip (PLACEHOLDER - planner team). */
import { WORKSPACE_TABS, WORKSPACE_TAB_LABELS, type WorkspaceTabsProps } from "./contract";

export function WorkspaceTabs({ tab, onTab, children }: WorkspaceTabsProps) {
  return (
    <div>
      <div role="tablist" aria-label="Review sections">
        {WORKSPACE_TABS.map((t) => (
          <button key={t} type="button" role="tab" aria-selected={t === tab} onClick={() => onTab(t)}>
            {WORKSPACE_TAB_LABELS[t]}
          </button>
        ))}
      </div>
      <div role="tabpanel">{children}</div>
    </div>
  );
}
