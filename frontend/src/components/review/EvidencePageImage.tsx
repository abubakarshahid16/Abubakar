/**
 * R21 / #508: one side of a finding, as the page it cites, with the
 * finding's own stored text boxed on it by the server.
 *
 * THE BOX IS EITHER RIGHT OR ABSENT. The server only boxes the stored quote
 * (or a shorter piece of the same text); when it cannot place it - a value
 * too short to locate safely, or text not on that page - the page comes back
 * unboxed and this says so in words. An unboxed page is never presented as
 * "the evidence is here".
 */
import { reviews as reviewsApi } from "../../api/client";
import { useAuthedImage } from "../useAuthedImage";

/** #785: what the box on the page is, in words - a label box is never
 *  called "the value". */
const BOXED: Record<string, string> = {
  quote: "The cited text is boxed on the page.",
  clause_text: "The cited clause is boxed on the page.",
  clause_heading: "The clause heading is boxed on the page.",
  value_position: "The value read is boxed where the reader found it.",
  source_line: "The line the value was read from is boxed.",
  value_once: "The value read is boxed (it appears once on this page).",
  label: "The field's label is boxed; the value read sits beside it.",
  where_to_look: "No value was found. The field's label is boxed - the only place the datasheet prints it; look beside it.",
};

export function EvidencePageImage({ findingId, side, page, box }: {
  findingId: string;
  side: "submittal" | "standard";
  page: number;
  /** #785: the kind of box the server draws, from the evidence route. */
  box?: string | null;
}) {
  const image = useAuthedImage(reviewsApi.evidenceImageUrl(findingId, side));
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
  return (
    <figure className="space-y-1">
      <p data-testid="evidence-located" className="text-xs text-slateish-400">
        {image.answerLocated === true
          ? (box && BOXED[box]) || BOXED.quote
          : "The cited text could not be placed on this page, so no box is drawn - read the page itself."}
      </p>
      <img
        src={image.src}
        alt={`${side === "submittal" ? "Submittal" : "Standard"} page ${page}`}
        className="max-h-[32rem] w-full rounded-[var(--radius-sm)] border border-ink-700 bg-white object-contain"
      />
    </figure>
  );
}
