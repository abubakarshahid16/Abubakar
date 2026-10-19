/**
 * OWNER: builder C (v2.1 gap S3). The workspace's "CRS" tab: the existing
 * CRS page for this review, embedded, not rewritten. It is the same
 * `CrsSheetPage` the old behind-the-scenes "Comment Resolution Sheet" page
 * shows (panels/BehindTheScenes.tsx): the sheet as the server builds it,
 * the two transmittal numbers, the contractor's returned sheet import, each
 * comment's Open / Closed, the internal working copy and the review notes.
 *
 * Inside the workspace the sheet opens by itself and signing points to the
 * workspace's own Sign and export, so the reader never leaves this screen.
 *
 * Order 141 D: the sheet and its internal copy are read from the record, so
 * the workspace's decisions on screen are saved first (`beforeCopy`).
 */
import { CrsSheetPage } from "../../panels/BehindTheScenes";

export interface CrsTabPanelProps {
  runId: string;
  /** Saves the decisions on screen; null, or plain words why not. */
  beforeCopy?: () => Promise<string | null>;
}

export function CrsTabPanel({ runId, beforeCopy }: CrsTabPanelProps) {
  return (
    <section aria-label="Comment Resolution Sheet" data-testid="ws-crs-tab" className="space-y-3">
      <p className="text-sm text-slateish-300">
        The comment sheet as the contractor will see it. Enter the transmittal numbers, bring in the
        contractor&apos;s replies when they come back, and mark each comment Open or Closed.
      </p>
      <CrsSheetPage key={runId} runId={runId} inWorkspace beforeCopy={beforeCopy} />
    </section>
  );
}
