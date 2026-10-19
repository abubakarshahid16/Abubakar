/** Section 5: time, from `created_at`, `completed_at` and the reader's own
 *  `seconds`. Per-stage seconds live in the run trace, a separate record
 *  (`/review/<run>/steps`), not on the run object - so they are linked, not
 *  shown here. */
import type { ReviewRunSummary } from "../../../types/api";
import { whenLabel } from "../reviewFormat";
import { durationLabel, durationSeconds, readerOf } from "./howData";
import { Fact, FactList, HowSection, type HowSectionMeta } from "./HowPrimitives";

export const TIME_META: HowSectionMeta = {
  id: "time", number: 5, title: "Time",
  explains: "When the review started and finished, how long it took, and how much of that the AI reader used.",
};

export function TimeSection({ run, onOpenSteps }: { run: ReviewRunSummary; onOpenSteps?: () => void }) {
  const seconds = durationSeconds(run.created_at, run.completed_at);
  const reader = readerOf(run);
  const readerSeconds = typeof reader?.seconds === "number" ? Math.round(reader.seconds) : null;
  return (
    <HowSection meta={TIME_META}>
      <FactList label="Time">
        <Fact label="Created" fact={{ value: whenLabel(run.created_at) || null, source: "created_at" }} testId="time-created" />
        <Fact label="Completed" fact={{ value: whenLabel(run.completed_at) || null, source: "completed_at" }} testId="time-completed" />
        <Fact label="Duration" testId="time-duration"
          fact={{ value: seconds === null ? null : durationLabel(seconds), source: "completed_at - created_at" }} />
        <Fact label="AI reader time" testId="time-reader"
          fact={{ value: readerSeconds === null ? null : durationLabel(readerSeconds), source: "requirement_split.reader.seconds" }} />
        <Fact label="Per stage" testId="time-stages"
          fact={{ value: null, source: "the run object; stage timings are in the step-by-step record" }} />
      </FactList>
      {onOpenSteps && (
        <p className="text-sm print:hidden">
          <button type="button" onClick={onOpenSteps} className="text-signal-300 underline-offset-2 hover:underline">
            Open the step-by-step record for the seconds per stage
          </button>
        </p>
      )}
    </HowSection>
  );
}
