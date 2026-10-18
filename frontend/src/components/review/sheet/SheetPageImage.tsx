/**
 * #967 item 5: the datasheet page with every card's value underlined on it
 * by the server, amber (needs you) or grey (answered).
 *
 * THE MARKS ARE THE SERVER'S OR ABSENT. The server places each value the
 * way the side-by-side view places one (#508/#785) and draws it on the
 * render; a value it cannot place safely gets no mark. The sentence over
 * the page says how many were placed out of how many were asked, so an
 * unmarked value is never taken for "nothing to see here". Only finding ids
 * and states travel in the URL.
 */
import { reviews as reviewsApi } from "../../../api/client";
import { useAuthedImage } from "../../useAuthedImage";
import { type PageMark, marksSentence } from "./sheetCards";
import { ZoomablePage } from "./ZoomablePage";

export function SheetPageImage({ runId, page, marks }: { runId: string; page: number; marks: PageMark[] }) {
  const image = useAuthedImage(reviewsApi.sheetPageImageUrl(runId, page, marks));
  if (image.loading) {
    return <p className="text-xs text-slateish-400">Loading page {page}…</p>;
  }
  if (image.failed || !image.src) {
    return (
      <p role="alert" className="rounded-[var(--radius-sm)] border border-dashed border-ink-600 p-3 text-xs text-slateish-500">
        Page {page} could not be loaded from this screen.
      </p>
    );
  }
  // Order 85a: the readable viewer (80% of the window, zoom, full page),
  // not a fit-to-512-px thumbnail.
  return (
    <ZoomablePage
      src={image.src} alt={`Datasheet page ${page}, values with a card underlined`}
      caption={<p data-testid="sheet-marks" className="text-xs text-slateish-400">{marksSentence(image.marksLocated, image.marksTotal)}</p>}
    />
  );
}
