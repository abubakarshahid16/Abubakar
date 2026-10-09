/** Where a passage sits, for a citation (W5b-01, #525).
 *
 *  A PDF passage is cited by page: "page 7" or "pages 7-9". A Word passage has
 *  no fixed pages, so it is cited by where it sits in the document: its heading
 *  path and paragraph, "4.2 > para 3" (`locator`, written by the backend). A
 *  locator is shown INSTEAD of a page number, never beside a made-up one. */
export interface Locatable {
  page_start: number;
  page_end: number;
  locator?: string | null;
}

export function citationWhere(p: Locatable): string {
  if (p.locator) return p.locator;
  return p.page_start === p.page_end
    ? `page ${p.page_start}`
    : `pages ${p.page_start}–${p.page_end}`;
}

/** True for a passage that has a real printed page to show (a PDF). */
export function hasPrintedPage(p: Pick<Locatable, "locator">): boolean {
  return !p.locator;
}
