/** Section 6: versions, from `code_version`, `config_version` (shown as
 *  "not sent to this page" when the runs list leaves them out) and
 *  `standards_change`. */
import type { ReviewRunSummary } from "../../../types/api";
import { NOT_SENT } from "./howData";
import { Fact, FactList, HowSection, type HowSectionMeta } from "./HowPrimitives";

export const VERSIONS_META: HowSectionMeta = {
  id: "versions", number: 6, title: "Versions",
  explains: "Which version of the review code and settings produced this result, and what changed in the rule books since the previous review of the same document.",
};

export function VersionsSection({ run, onOpenRun }: { run: ReviewRunSummary; onOpenRun?: (runId: string) => void }) {
  const change = run.standards_change ?? null;
  return (
    <HowSection meta={VERSIONS_META}>
      <FactList label="Versions">
        {/* The runs list does not send these today: absent says so, rather
            than claiming the run never recorded them. Null = not recorded. */}
        <Fact label="Review code version" fact={{ value: run.code_version ?? null, source: "code_version" }} testId="versions-code"
          missingText={run.code_version === undefined ? NOT_SENT : undefined} />
        <Fact label="Settings version" fact={{ value: run.config_version ?? null, source: "config_version" }} testId="versions-settings"
          missingText={run.config_version === undefined ? NOT_SENT : undefined} />
        <Fact label="Previous completed run" testId="versions-previous"
          fact={{ value: change?.previous_run_id ?? null, source: "standards_change.previous_run_id" }}
          detail={change && onOpenRun ? (
            <button type="button" onClick={() => onOpenRun(change.previous_run_id)}
              className="text-signal-300 underline-offset-2 hover:underline print:hidden">open it</button>
          ) : undefined} />
        <Fact label="Standards used in this review but not last time" testId="versions-added"
          fact={{ value: change ? change.added : null, source: "standards_change.added" }} />
        <Fact label="Standards not used in this review (used last time)" testId="versions-removed"
          fact={{ value: change ? change.removed : null, source: "standards_change.removed" }} />
      </FactList>
      <p className="text-sm text-slateish-300">Run id: <code className="rounded bg-ink-800 px-1">{run.review_run_id}</code></p>
    </HowSection>
  );
}
