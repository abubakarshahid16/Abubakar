/** Section 7: the result, from `recommended_code`, `recommended_reason`,
 *  `recommended_details` and the engineer's own decision beside them. */
import type { ReviewRunSummary } from "../../../types/api";
import { whenLabel } from "../reviewFormat";
import { Fact, FactList, HowSection, type HowSectionMeta } from "./HowPrimitives";

export const RESULT_META: HowSectionMeta = {
  id: "result", number: 7, title: "Result",
  explains: "The review code the system proposed and why, and the code the engineer finally chose. The engineer's decision stands beside the machine's, never instead of it.",
};

export function ResultSection({ run }: { run: ReviewRunSummary }) {
  const who = [run.decided_by_name, whenLabel(run.decided_at)].filter(Boolean).join(", ");
  const decided = run.engineer_final_code
    ? (who ? `${run.engineer_final_code} (${who})` : run.engineer_final_code)
    : null;
  return (
    <HowSection meta={RESULT_META}>
      <FactList label="Result">
        <Fact label="Recommended code" fact={{ value: run.recommended_code ?? null, source: "recommended_code" }} testId="result-code" />
        <Fact label="Recommended reason" fact={{ value: run.recommended_reason ?? null, source: "recommended_reason" }} testId="result-reason" />
        <Fact label="Recommended details" fact={{ value: run.recommended_details ?? null, source: "recommended_details" }} testId="result-details" />
        <Fact label="Engineer's final code" testId="result-final"
          fact={{ value: decided, source: "engineer_final_code, decided_by_name, decided_at" }}
          detail={run.override_reason ? `- reason: ${run.override_reason} (override_reason)` : undefined} />
        <Fact label="Findings" testId="result-findings"
          fact={{ value: run.findings_total ?? null, source: "findings_total" }}
          detail={Object.keys(run.by_status ?? {}).length
            ? `(by status: ${Object.entries(run.by_status).map(([k, v]) => `${k} ${v}`).join(", ")}; from by_status)`
            : undefined} />
      </FactList>
      {run.status === "failed" && (
        <p role="alert" className="text-sm text-danger-500">
          This run failed{run.failure_reason ? `: ${run.failure_reason}` : ""} (failure_reason).
        </p>
      )}
    </HowSection>
  );
}
