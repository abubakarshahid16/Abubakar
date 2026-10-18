/**
 * The datasheet, page by page, on the left of the Sheet screen (#967 PR 2).
 *
 * THE MARKS ON THE PAGE ARE THE SERVER'S. A page with cards is the run's
 * page image with EVERY card's value underlined on it by the server (#967
 * item 5): amber needs you, grey is answered - the same colours as the list
 * under the page. A value the server cannot place safely gets no mark, and
 * the sentence over the page says how many were placed out of how many. The
 * browser never draws a mark of its own guessing, because a mark in the
 * wrong place is worse than none. "The rule" still opens the standard's page
 * with that one clause boxed (#508).
 */
import { useEffect, useRef, useState } from "react";

import type { DocumentRecord, ReviewFinding } from "../../../types/api";
import { DocumentPreview } from "../../DocumentPreview";
import { EvidencePageImage } from "../EvidencePageImage";
import { type SheetCard, cardTitle, isTickFinding, marksOn } from "./sheetCards";
import { SheetPageImage } from "./SheetPageImage";

export interface PaneView {
  page: number | null;
  /** The rule's page instead of the datasheet's, when "The rule" was opened. */
  rule: ReviewFinding | null;
}

/** How long the page frame glows after "show it on the page" (#967 PR 4). */
export const PULSE_MS = 1200;

export function DocumentPane({ runId, submittal, cards, selected, view, pulse = 0, onPage, onSelectCard, onCloseRule }: {
  runId: string;
  submittal: DocumentRecord | null;
  cards: SheetCard[];
  selected: SheetCard | null;
  view: PaneView;
  /** Counts "show it on the page" asks (T, or the card's link): each one
   *  scrolls the page into view and pulses its frame once. */
  pulse?: number;
  onPage: (page: number) => void;
  onSelectCard: (card: SheetCard) => void;
  onCloseRule: () => void;
}) {
  const frame = useRef<HTMLDivElement | null>(null);
  const [pulsing, setPulsing] = useState(false);
  useEffect(() => {
    if (!pulse) return;
    const el = frame.current;
    if (el && typeof el.scrollIntoView === "function") {
      const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      el.scrollIntoView({ block: "center", behavior: still ? "auto" : "smooth" });
    }
    setPulsing(true);
    const timer = setTimeout(() => setPulsing(false), PULSE_MS);
    return () => clearTimeout(timer);
  }, [pulse]);
  const cardPages = [...new Set(cards.flatMap((c) => c.pages))];
  const total = submittal?.page_count ?? null;
  const pages = total ? Array.from({ length: total }, (_, i) => i + 1) : cardPages.sort((a, b) => a - b);
  const openPages = new Set(cards.filter((c) => c.state === "open").flatMap((c) => c.pages));
  const page = view.page ?? pages[0] ?? null;
  const onPageCards = cards.filter((c) => page !== null && c.pages.includes(page));
  const marks = marksOn(onPageCards, page);

  return (
    <section aria-label="The datasheet" className="space-y-3">
      {pages.length > 0 && (
        <nav aria-label="Pages" className="flex flex-wrap gap-1">
          {pages.map((p) => (
            <button
              key={p} type="button" onClick={() => onPage(p)}
              aria-current={p === page ? "page" : undefined}
              aria-label={`Page ${p}${openPages.has(p) ? ", needs your answer" : ""}`}
              className={`relative min-w-9 rounded-[var(--radius-sm)] border px-2 py-1 text-sm ${p === page ? "border-signal-500 text-slateish-100" : "border-ink-700 text-slateish-300 hover:border-ink-600"}`}
            >
              {p}
              {openPages.has(p) && (
                <span aria-hidden="true" className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-warn-500" />
              )}
            </button>
          ))}
        </nav>
      )}

      <div
        ref={frame} data-sheet-page="" data-pulsing={pulsing ? "true" : undefined}
        className={`rounded-[var(--radius-sm)] ${pulsing ? "sheet-pulse" : ""}`}
      >
        {view.rule ? (
          <div className="space-y-2">
            <button type="button" onClick={onCloseRule} className="text-xs text-signal-300 underline-offset-2 hover:underline">
              ← Back to the datasheet
            </button>
            <EvidencePageImage findingId={view.rule.id} side="standard" page={view.rule.standard_page ?? 1} />
          </div>
        ) : marks.length > 0 && page !== null ? (
          <SheetPageImage runId={runId} page={page} marks={marks} />
        ) : submittal && page !== null ? (
          <div className="h-[36rem] max-sm:h-[20rem]">
            <DocumentPreview doc={submittal} page={page} />
          </div>
        ) : (
          <p className="rounded-[var(--radius-sm)] border border-dashed border-ink-600 p-3 text-xs text-slateish-500">
            The datasheet could not be opened from this screen.
          </p>
        )}
      </div>

      {onPageCards.length > 0 && !view.rule && (
        <ul aria-label="Marked on this page" className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {onPageCards.map((c) => (
            <li key={c.key}>
              <button
                type="button" onClick={() => onSelectCard(c)}
                data-mark={c.state !== "open" ? "answered" : isTickFinding(c.findings[0]) ? "tick" : "open"}
                className={`underline decoration-2 underline-offset-4 ${c.state !== "open" ? "decoration-slateish-500 text-slateish-400" : isTickFinding(c.findings[0]) ? "decoration-signal-500 text-slateish-100" : "decoration-warn-500 text-slateish-100"} ${selected?.key === c.key ? "font-semibold" : ""}`}
              >
                {cardTitle(c)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
