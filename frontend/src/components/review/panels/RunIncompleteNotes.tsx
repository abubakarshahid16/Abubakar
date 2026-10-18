/**
 * What this run could not check, on the Sheet screen's header (#967 PR 3).
 *
 * The honesty lines the old run card carried (B3 pages not read, #633 web
 * check and AI check incomplete, partial findings, the standards change
 * since the last run, the nominal completeness): a review that left parts
 * unchecked must never read as a complete one. Null renders as nothing.
 */
import type { ReviewRunSummary } from "../../../types/api";
import { completenessLine, pageCoverageLine, standardsChangeLine } from "../reviewFormat";

export function RunIncompleteNotes({ run }: { run: ReviewRunSummary }) {
  const completeness = completenessLine(run);
  const pageCoverage = pageCoverageLine(run);
  // 2g: the plain reason already opens "Checked N datasheet fields" when
  // the run was gated for completeness; the line is not printed twice.
  const reasonStatesCount = (run.recommended_reason ?? "").startsWith("Checked ");
  const lines = [
    completeness && !reasonStatesCount ? { id: "completeness", text: completeness, warn: false } : null,
    pageCoverage ? { id: "page-coverage", text: pageCoverage, warn: false } : null,
    standardsChangeLine(run) ? { id: "standards-change", text: standardsChangeLine(run), warn: false } : null,
    // #633: an incomplete check is a fact on the run, never left for a
    // reviewer to notice from an empty column. Never shown for a run where
    // the check simply never ran.
    run.web_check_status && !run.web_check_status.complete
      ? { id: "web-check-incomplete", text: run.web_check_status.plain, warn: true } : null,
    (run.partial_findings ?? 0) > 0
      ? { id: "partial-findings", warn: true,
          text: `${run.partial_findings} finding(s) were written before this review stopped. They are partial and no review code was recommended.` }
      : null,
    run.ai_check_status && !run.ai_check_status.complete
      ? { id: "ai-check-incomplete", text: run.ai_check_status.plain, warn: true } : null,
    // PF4 step 2 (#884): the run's own clause coverage, with its denominator,
    // as the run stored it; a run made before the record shows no line, and
    // a count that does not add up is the warning the line itself carries.
    run.clause_coverage
      ? { id: "clause-coverage", text: `Clause coverage: ${run.clause_coverage.line}.`, warn: !run.clause_coverage.adds_up }
      : null,
  ].filter((line): line is { id: string; text: string; warn: boolean } => line !== null);
  if (lines.length === 0) return null;
  return (
    <ul aria-label="What this review could not check" className="space-y-0.5 text-xs">
      {lines.map((line) => (
        <li key={line.id} data-testid={line.id} className={line.warn ? "text-warn-500" : "text-slateish-400"}>
          {line.text}
        </li>
      ))}
    </ul>
  );
}
