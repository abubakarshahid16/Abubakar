/**
 * OWNER: builder A. The tab strip of the workspace.
 *
 * A proper tab list: one tab in the Tab order at a time (the selected one),
 * Left / Right arrows move and select (wrapping), Home / End jump to the
 * first / last tab. Selecting a tab is the parent's job (`onTab`), so the
 * address keeps the place.
 */
import { useRef, type KeyboardEvent } from "react";

import { WORKSPACE_TABS, WORKSPACE_TAB_LABELS, type WorkspaceTab, type WorkspaceTabsProps } from "./contract";

const tabId = (tab: WorkspaceTab) => `ws-tab-${tab}`;
const tabPanelId = (tab: WorkspaceTab) => `ws-tabpanel-${tab}`;

export function WorkspaceTabs({ tab, onTab, children }: WorkspaceTabsProps) {
  const refs = useRef<Partial<Record<WorkspaceTab, HTMLButtonElement | null>>>({});

  function move(event: KeyboardEvent<HTMLDivElement>) {
    const index = WORKSPACE_TABS.indexOf(tab);
    let next: number | null = null;
    if (event.key === "ArrowRight") next = (index + 1) % WORKSPACE_TABS.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + WORKSPACE_TABS.length) % WORKSPACE_TABS.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = WORKSPACE_TABS.length - 1;
    if (next === null) return;
    event.preventDefault();
    const target = WORKSPACE_TABS[next];
    onTab(target);
    refs.current[target]?.focus();
  }

  return (
    <div className="space-y-3">
      <div
        role="tablist" aria-label="Review sections" onKeyDown={move}
        className="flex flex-wrap gap-1 border-b border-ink-700"
      >
        {WORKSPACE_TABS.map((t) => {
          const selected = t === tab;
          return (
            <button
              key={t} type="button" role="tab" id={tabId(t)}
              ref={(el) => { refs.current[t] = el; }}
              aria-selected={selected} aria-controls={tabPanelId(t)} tabIndex={selected ? 0 : -1}
              onClick={() => onTab(t)}
              className={selected
                ? "-mb-px border-b-2 border-signal-300 px-3 py-2 text-sm font-semibold text-slateish-100"
                : "px-3 py-2 text-sm text-slateish-300 hover:text-slateish-100"}
            >
              {WORKSPACE_TAB_LABELS[t]}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" id={tabPanelId(tab)} aria-labelledby={tabId(tab)} tabIndex={0}>
        {children}
      </div>
    </div>
  );
}
