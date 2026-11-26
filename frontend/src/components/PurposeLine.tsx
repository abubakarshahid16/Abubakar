/**
 * ONE LINE AT THE TOP OF EVERY MAIN SCREEN: what it is for and what to do next (owner, 26 Nov 2026, G9, E4). One home for the words,
 * so every main screen says it the same way; a record's own page (one review, one query, one document) has none.
 */
import type { ViewId } from "./Shell";

//  Reviews has none here: its page already opens with its own line ("To check a new file, pick it and press Start review ...").
export const PURPOSE: Partial<Record<ViewId, string>> = {
  technicalQueries:
    "Technical Queries and CFCs: open a query, check the question and the contract clauses found for it, then approve the draft reply.",
  chat: "Ask: type a question about our documents; every answer names the document and the page it comes from.",
  documents: "Documents: upload our documents and find them; each one is read page by page before the app uses it.",
};

export function PurposeLine({ view }: { view: ViewId }) {
  const line = PURPOSE[view];
  if (!line) return null;
  return (
    <p className="border-b border-ink-700 bg-ink-850 px-6 py-2 text-sm text-slateish-300" data-testid="screen-purpose">
      {line}
    </p>
  );
}
