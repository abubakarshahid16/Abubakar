/**
 * OWNER: builder A (v2.2 view modes: builder B). The tab strip of the
 * workspace.
 *
 * A proper tab list: one tab in the Tab order at a time (the selected one),
 * Left / Right arrows move and select (wrapping), Home / End jump to the
 * first / last tab. Selecting a tab is the parent's job (`onTab`), so the
 * address keeps the place.
 *
 * v2.2: in Simple view the strip shows "Comment sheet", "CRS preview and
 * replies" and one "Details" tab. Details holds the engineer tabs in a
 * second small row (its own tab list, same keys). The Details row is open,
 * and Details selected, exactly when the current tab is one of those, so a
 * link to ?tab=steps opens on the steps tab with the row open. Every tab
 * stays reachable in both views.
 */
import { useRef, type KeyboardEvent } from "react";

import { WORKSPACE_TABS, WORKSPACE_TAB_LABELS, type WorkspaceTab, type WorkspaceTabsProps } from "./contract";

const tabId = (tab: WorkspaceTab) => `ws-tab-${tab}`;
const tabPanelId = (tab: WorkspaceTab) => `ws-tabpanel-${tab}`;
const DETAILS_ID = "ws-tab-details";

/** The tabs a manager or new user needs, in Simple view. */
export const SIMPLE_TABS: readonly WorkspaceTab[] = ["sheet", "crs"];
/** The engineer tabs, under "Details" in Simple view. */
export const DETAIL_TABS: readonly WorkspaceTab[] = ["how", "findings", "standards", "steps", "numbers"];

type Slot = WorkspaceTab | "details";

/** Arrow / Home / End over one row of tabs: the next slot, or null. */
function nextSlot<T>(list: readonly T[], current: T, key: string): T | null {
  const index = Math.max(0, list.indexOf(current));
  if (key === "ArrowRight") return list[(index + 1) % list.length];
  if (key === "ArrowLeft") return list[(index - 1 + list.length) % list.length];
  if (key === "Home") return list[0];
  if (key === "End") return list[list.length - 1];
  return null;
}

const MAIN_CLASS = {
  on: "-mb-px border-b-2 border-signal-300 px-3 py-2 text-sm font-semibold text-slateish-100",
  off: "px-3 py-2 text-sm text-slateish-300 hover:text-slateish-100",
};
const SMALL_CLASS = {
  on: "rounded-[var(--radius-sm)] bg-ink-700 px-2 py-1 text-xs font-semibold text-slateish-100",
  off: "rounded-[var(--radius-sm)] px-2 py-1 text-xs text-slateish-300 hover:text-slateish-100",
};

export function WorkspaceTabs({ tab, onTab, mode = "detailed", children }: WorkspaceTabsProps) {
  const refs = useRef<Partial<Record<Slot, HTMLButtonElement | null>>>({});
  // The engineer tab Details goes back to (the last one seen; first "how").
  const lastDetail = useRef<WorkspaceTab>(DETAIL_TABS[0]);
  const simple = mode === "simple";
  const inDetails = DETAIL_TABS.includes(tab);
  if (inDetails) lastDetail.current = tab;

  const select = (slot: Slot) => {
    onTab(slot === "details" ? lastDetail.current : slot);
    refs.current[slot]?.focus();
  };

  const mainSlots: readonly Slot[] = simple ? [...SIMPLE_TABS, "details"] : WORKSPACE_TABS;
  const mainCurrent: Slot = simple && inDetails ? "details" : tab;

  function onKeys(list: readonly Slot[], current: Slot) {
    return (event: KeyboardEvent<HTMLDivElement>) => {
      const next = nextSlot(list, current, event.key);
      if (next === null) return;
      event.preventDefault();
      select(next);
    };
  }

  function tabButton(t: WorkspaceTab, small: boolean) {
    const selected = t === tab;
    const cls = small ? SMALL_CLASS : MAIN_CLASS;
    return (
      <button
        key={t} type="button" role="tab" id={tabId(t)}
        ref={(el) => { refs.current[t] = el; }}
        aria-selected={selected} aria-controls={tabPanelId(t)} tabIndex={selected ? 0 : -1}
        onClick={() => onTab(t)}
        className={selected ? cls.on : cls.off}
      >
        {WORKSPACE_TAB_LABELS[t]}
      </button>
    );
  }

  return (
    <div className="space-y-3">
      <div
        role="tablist" aria-label="Review sections" onKeyDown={onKeys(mainSlots, mainCurrent)}
        className="flex flex-wrap gap-1 border-b border-ink-700"
      >
        {mainSlots.map((slot) => (slot === "details" ? (
          <button
            key="details" type="button" role="tab" id={DETAILS_ID}
            ref={(el) => { refs.current.details = el; }}
            aria-selected={inDetails} aria-expanded={inDetails} aria-controls="ws-details-row"
            tabIndex={inDetails ? 0 : -1} data-testid="ws-details-tab"
            onClick={() => select("details")}
            className={inDetails ? MAIN_CLASS.on : MAIN_CLASS.off}
          >
            Details
          </button>
        ) : tabButton(slot, false)))}
      </div>
      {simple && inDetails && (
        <div
          role="tablist" aria-label="Details" id="ws-details-row" data-testid="ws-details-row"
          onKeyDown={onKeys(DETAIL_TABS, tab)}
          className="flex flex-wrap gap-1"
        >
          {DETAIL_TABS.map((t) => tabButton(t, true))}
        </div>
      )}
      <div role="tabpanel" id={tabPanelId(tab)} aria-labelledby={tabId(tab)} tabIndex={0}>
        {children}
      </div>
    </div>
  );
}
