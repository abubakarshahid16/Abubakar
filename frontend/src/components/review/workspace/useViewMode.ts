/**
 * v2.2: the "Simple / Detailed" view switch, shared by the first page and
 * the review page. Simple (the default) shows what a manager or a new user
 * needs; Detailed shows every engineer tab. The choice is remembered in this
 * browser; storage is wrapped in try/catch (a private window throws).
 * Every engineer screen stays reachable in Simple view (under "Details").
 */
import { useCallback, useEffect, useState } from "react";

export type ViewMode = "simple" | "detailed";

export const VIEW_MODE_KEY = "rag.workspace.viewMode";
const EVENT = "rag-workspace-view-mode";

export function readViewMode(): ViewMode {
  try {
    return localStorage.getItem(VIEW_MODE_KEY) === "detailed" ? "detailed" : "simple";
  } catch {
    return "simple";
  }
}

export function writeViewMode(mode: ViewMode): void {
  try {
    localStorage.setItem(VIEW_MODE_KEY, mode);
  } catch {
    /* storage unavailable: the choice lasts this page only */
  }
}

/** Both pages share one choice; a change on one page shows on the other. */
export function useViewMode(): { mode: ViewMode; setMode: (mode: ViewMode) => void } {
  const [mode, setModeState] = useState<ViewMode>(readViewMode);
  useEffect(() => {
    const onChange = (event: Event) => {
      const next = (event as CustomEvent<ViewMode>).detail;
      if (next === "simple" || next === "detailed") setModeState(next);
    };
    window.addEventListener(EVENT, onChange);
    return () => window.removeEventListener(EVENT, onChange);
  }, []);
  const setMode = useCallback((next: ViewMode) => {
    writeViewMode(next);
    setModeState(next);
    window.dispatchEvent(new CustomEvent<ViewMode>(EVENT, { detail: next }));
  }, []);
  return { mode, setMode };
}
