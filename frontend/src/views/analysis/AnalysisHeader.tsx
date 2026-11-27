import { MoreText } from "../../components/MoreText";
import { Notice, PageHeader } from "../../components/kit/Kit";

/** The kit's page header and notices (H's audit #28 and #33, 27 Nov 2026): no one-off green subtitle under the title, and the rules in
 *  the kit's one notice box instead of a hand-made pill. */
export function AnalysisHeader() {
  return (
    <div className="border-b border-ink-700 pb-4">
      <PageHeader title="Analysis Hub" />
      <MoreText className="-mt-4 max-w-3xl" summary="Ask one engineering question about your documents; every answer shows the page it comes from.">
          <p className="text-sm text-slateish-300">
            Ask one engineering question, choose the work to run, and inspect only cited document evidence.
            Public evidence is isolated from private document context.
          </p>
          <div className="mt-4 grid gap-2 md:grid-cols-2">
            <Notice title="Evidence rule">A statement about a document is shown only when the page it comes from is found.</Notice>
            <Notice title="Recommendation rule">Advice is kept apart from what the documents say, and an engineer checks it.</Notice>
          </div>
      </MoreText>
      {/* An honesty label (rule 4: samples are labelled samples): always visible, never folded. */}
      <div className="mt-3 max-w-3xl">
        <Notice tone="warn" title="Market rule">Market prices shown here are sample data unless an approved market price service is switched on.</Notice>
      </div>
    </div>
  );
}
