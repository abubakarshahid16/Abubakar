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
  if (image.loading || image.failed || !image.src) {
    return (
      <ZoomablePage
        src={null} alt={`Datasheet page ${page}`}
        status={image.loading ? `Loading page ${page}…` : <span role="alert">Page {page} could not be loaded from this screen.</span>}
      />
    );
  }
  return (
    <ZoomablePage
      src={image.src} alt={`Datasheet page ${page}`}
      caption={<p data-testid="sheet-marks" className="text-xs text-slateish-400">No value on this page has a card.</p>}
    />
  );
}
