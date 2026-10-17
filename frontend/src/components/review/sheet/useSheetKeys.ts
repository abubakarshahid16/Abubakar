import { useEffect } from "react";

import type { SheetCard } from "./sheetCards";

/** The owner's keyboard flow: J / K next and previous card, Enter agrees,
 *  N says not needed, T shows the selected card's value on the page (#967
 *  PR 4). Never while typing, and never with a modifier held. */
export function useSheetKeys(
  cards: SheetCard[], selected: SheetCard | null, select: (card: SheetCard) => void,
  showOnPage?: () => void,
) {
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target && (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) || target.isContentEditable)) return;
      const at = cards.findIndex((c) => c.key === selected?.key);
      const key = event.key.toLowerCase();
      if ((key === "j" || key === "k") && cards.length > 0) {
        const step = key === "j" ? 1 : -1;
        select(cards[(at + step + cards.length) % cards.length]);
        event.preventDefault();
        return;
      }
      if (key === "t" && selected && showOnPage) {
        showOnPage();
        event.preventDefault();
        return;
      }
      if (!selected || selected.state !== "open") return;
      // Enter on a focused button is that button's own click, not "agree".
      if (key === "enter" && target?.tagName === "BUTTON") return;
      const action = key === "enter" ? "agree" : key === "n" ? "not-needed" : null;
      if (!action) return;
      const button = document.querySelector<HTMLButtonElement>(
        `[data-selected-card] [data-action="${action}"]`);
      if (button && !button.disabled) {
        button.click();
        event.preventDefault();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cards, selected, select, showOnPage]);
}
