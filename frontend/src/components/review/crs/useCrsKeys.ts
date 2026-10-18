import { useEffect } from "react";

import type { CrsRow } from "./crsRows";

export interface CrsKeyActions {
  select: (row: CrsRow) => void;
  edit: (row: CrsRow) => void;
  remove: (row: CrsRow) => void;
  keep: (row: CrsRow) => void;
}

/** Spec 1.2: J / K next and previous row, E edit the wording, R remove (asks
 *  for a reason), Enter keep. Never while typing, never with a modifier held,
 *  and never while the evidence drawer or a dialog has the keyboard. */
export function useCrsKeys(rows: CrsRow[], selectedKey: string | null, actions: CrsKeyActions, active = true) {
  useEffect(() => {
    if (!active) return;
    function onKey(event: KeyboardEvent) {
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target && (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) || target.isContentEditable)) return;
      if (target?.closest("[role=dialog]")) return;
      const at = rows.findIndex((r) => r.key === selectedKey);
      const key = event.key.toLowerCase();
      if ((key === "j" || key === "k") && rows.length > 0) {
        const step = key === "j" ? 1 : -1;
        actions.select(rows[(at + step + rows.length) % rows.length]);
        event.preventDefault();
        return;
      }
      const row = at >= 0 ? rows[at] : null;
      if (!row) return;
      // Enter on a focused button is that button's own click, not "keep".
      if (key === "enter" && target?.tagName === "BUTTON") return;
      const action = key === "e" ? actions.edit : key === "r" ? actions.remove : key === "enter" ? actions.keep : null;
      if (!action) return;
      action(row);
      event.preventDefault();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, selectedKey, actions, active]);
}
