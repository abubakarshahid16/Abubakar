/**
 * OWNER: builder A. The one-screen review workspace (PLACEHOLDER - planner
 * team). Composes: B's ActionBar + SheetCountsLine + SignOffPanel, C's
 * WorkspaceSheet (with its evidence drawer), D's ReviewAgainButton, and the
 * tabs. See SPEC.md section 3.
 */
import type { ReviewWorkspaceProps } from "./contract";

export function ReviewWorkspace({ location }: ReviewWorkspaceProps) {
  return (
    <section aria-label="Review workspace" data-testid="review-workspace" data-run={location.runId}>
      <p className="text-slateish-300">The new review screen is being built.</p>
    </section>
  );
}
