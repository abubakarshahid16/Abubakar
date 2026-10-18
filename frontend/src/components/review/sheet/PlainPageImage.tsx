/**
 * Order 85a (#967): a datasheet page with no card on it, as the server's page
 * image in the same viewer as a marked page. It used to be the original PDF
 * in a frame 152 px tall - a thin strip nobody could read.
 */
import { documentsApi } from "../../../api/client";
import { useAuthedImage } from "../../useAuthedImage";
import { ZoomablePage } from "./ZoomablePage";

export function PlainPageImage({ documentId, page }: { documentId: string; page: number }) {
  const image = useAuthedImage(documentsApi.pageImageUrl(documentId, page));
  if (image.loading) return <p className="text-xs text-slateish-400">Loading page {page}…</p>;
  if (image.failed || !image.src) {
    return (
      <p role="alert" className="rounded-[var(--radius-sm)] border border-dashed border-ink-600 p-3 text-xs text-slateish-500">
        Page {page} could not be loaded from this screen.
      </p>
    );
  }
  return (
    <ZoomablePage
      src={image.src} alt={`Datasheet page ${page}`}
      caption={<p data-testid="sheet-marks" className="text-xs text-slateish-400">No value on this page has a card.</p>}
    />
  );
}
