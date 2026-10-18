/**
 * The honesty footer (order 95 piece 2, spec 1.2): run id, date, code
 * version, pages read / not read, standards used / missing, counts per
 * tier. Every number is one the run stored or one the table above shows;
 * a value the run does not hold renders as nothing, never 0.
 */
import type { ReviewRunMissingReference, ReviewRunStandard, ReviewRunSummary } from "../../../types/api";
import { pageList, whenLabel } from "../reviewFormat";
import type { TierCounts } from "./tiers";

export interface CrsFooterProps {
  run: ReviewRunSummary;
  counts: TierCounts;
  standards: ReviewRunStandard[] | null;
  missing: ReviewRunMissingReference[];
  standardsError: string | null;
  /** The run's code version when the record carries one (the review job's). */
  codeVersion?: string | null;
}

function pagesLine(run: ReviewRunSummary): string {
  const pc = run.page_coverage;
  if (!pc) return "Pages read: not recorded on this run.";
  if (pc.pages_total === null || pc.pages_total === undefined) return "Pages: none accounted for.";
  const read = pc.fact_pages.length;
  const unread = pc.pages_not_read_into_fields;
  return `Pages read: ${read} of ${pc.pages_total}${unread.length ? `; not read: ${pageList(unread)}` : "; not read: none"}.`;
}

export function CrsFooter({ run, counts, standards, missing, standardsError, codeVersion }: CrsFooterProps) {
  const used = standards ? standards.filter((s) => s.included) : null;
  const standardsLine = standardsError
    ? `Standards: the list could not be loaded (${standardsError}).`
    : used
      ? `Standards used: ${used.length}${used.length ? ` (${used.map((s) => s.filename ?? s.standard_document_id).join(", ")})` : ""}`
        + `; missing from the library: ${missing.length}${missing.length ? ` (${missing.map((m) => m.identifier).join(", ")})` : ""}.`
      : "";
  const when = whenLabel(run.completed_at ?? run.created_at);
  return (
    <footer className="space-y-1 border-t border-ink-700 pt-3 text-xs text-slateish-400" data-testid="crs-footer" aria-label="How this sheet was made">
      <p>
        Run {run.review_run_id}{when ? ` · ${when}` : ""}{codeVersion ? ` · code ${codeVersion}` : ""}
        {run.decided_by_name && run.decided_at ? ` · code chosen by ${run.decided_by_name} on ${whenLabel(run.decided_at)}` : ""}
      </p>
      <p>{pagesLine(run)}</p>
      {standardsLine && <p>{standardsLine}</p>}
      <p>
        Rows on this sheet: {counts.comment} Comment, {counts.needsYou} Needs you, {counts.met} Met, {counts.notApplicable} Not applicable
        {run.requirement_split ? ` · clauses: ${run.requirement_split.checked} checked, ${run.requirement_split.applies_not_checked} apply but not checked, ${run.requirement_split.does_not_apply} not applicable` : ""}.
      </p>
      <p>Not signed yet. Signing records who and when on the exported file.</p>
    </footer>
  );
}
