/** Section 6: versions, from `code_version`, `config_version` (when the
 *  run carries them) and `standards_change`. */
import type { ReviewRunSummary } from "../../../types/api";
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
        <Fact label="Review code version" fact={{ value: run.code_version ?? null, source: "code_version" }} testId="versions-code" />
        <Fact label="Settings version" fact={{ value: run.config_version ?? null, source: "config_version" }} testId="versions-settings" />
        <Fact label="Previous run" testId="versions-previous"
          fact={{ value: change?.previous_run_id ?? null, source: "standards_change.previous_run_id" }}
          detail={change && onOpenRun ? (
            <button type="button" onClick={() => onOpenRun(change.previous_run_id)}
              className="text-signal-300 underline-offset-2 hover:underline print:hidden">open it</button>
          ) : undefined} />
        <Fact label="Standards added since the previous run" testId="versions-added"
          fact={{ value: change ? change.added : null, source: "standards_change.added" }} />
        <Fact label="Standards removed since the previous run" testId="versions-removed"
          fact={{ value: change ? change.removed : null, source: "standards_change.removed" }} />
      </FactList>
      <p className="text-sm text-slateish-300">Run id: <code className="rounded bg-ink-800 px-1">{run.review_run_id}</code></p>
    </HowSection>
  );
}
