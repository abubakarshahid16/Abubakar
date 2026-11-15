/**
 * The documents a review would send to Claude, and the ones it will not (owner, 12 Nov 2026: "the screen lists every document
 * that will leave the Mac before the review starts"). Props only: the plan's `documents.leaving` and `not_sent`; no fetching,
 * so the review page and the older "Check it" panel show the same list. Titles are file names as the library shows them,
 * never internal ids; a document the reader may not open is counted, never named.
 */
import type { LeavingDocument, NotSentDocument } from "../../../api/reviewPlan";

export function LeavingList({ leaving, notSent, notReadable, textLeaves }: {
  leaving: LeavingDocument[];
  notSent: NotSentDocument[];
  notReadable: number;
  /** Whether any text leaves at all under the chosen engine. False = Local only (or a part kept on this computer). */
  textLeaves: boolean;
}) {
  const nothing = !textLeaves || leaving.length === 0;
  return (
    <div className="space-y-2 text-sm" data-testid="leaving-list">
      {nothing ? (
        <p className="font-medium text-slateish-100">Nothing leaves this Mac.</p>
      ) : (
        <>
          <p className="font-medium text-slateish-100">These documents will be sent to Claude</p>
          <ul className="space-y-1">
            {leaving.map((d) => (
              <li key={d.id} className="text-slateish-200">
                <span className="font-medium">{d.title}</span>
                <span className="text-slateish-400"> - {d.kind}, {d.why}</span>
              </li>
            ))}
          </ul>
          <p className="text-xs text-slateish-400">
            {leaving.length} document(s), of the documents you may read.
          </p>
          <p className="text-xs text-slateish-400">
            A rule book found only during the review is not sent; the result lists it.
          </p>
        </>
      )}
      {notSent.length > 0 && (
        <>
          <p className="font-medium text-slateish-100">These will not be sent</p>
          <ul className="space-y-1">
            {notSent.map((d, i) => (
              <li key={d.id ?? `${d.name}-${i}`} className="text-slateish-300">
                <span className="font-medium">{d.title ?? d.name}</span>
                <span className="text-slateish-400"> - {d.reason}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {notReadable > 0 && (
        <p className="text-xs text-slateish-400">
          {notReadable} more document(s) cited are ones you may not read; they are not named and will not be sent.
        </p>
      )}
    </div>
  );
}
