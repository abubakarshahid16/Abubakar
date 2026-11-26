/**
 * ONE LINE AT THE TOP OF EVERY MAIN SCREEN: what it is for and what to do next (owner, 26 Nov 2026, G9, E4). One home for the words,
 * so every main screen says it the same way; a record's own page (one review, one query, one document) has none.
 */
import type { ViewId } from "./Shell";

export const PURPOSE: Partial<Record<ViewId, string>> = {
  review: "Reviews: pick a contractor document and start its review; open a finished review to decide each comment and sign the sheet.",
  technicalQueries:
    "Technical Queries and CFCs: open a query, check the question and the contract clauses found for it, then approve the draft reply.",
  chat: "Ask: type a question about our documents; every answer names the document and the page it comes from.",
  documents: "Documents: upload our documents and find them; each one is read page by page before the app uses it.",
};

export function PurposeLine({ view }: { view: ViewId }) {
  const line = PURPOSE[view];
  if (!line) return null;
  return (
    <p className="mx-auto w-full max-w-6xl px-4 pt-4 text-sm text-slateish-300" data-testid="screen-purpose">
      {line}
    </p>
  );
}
