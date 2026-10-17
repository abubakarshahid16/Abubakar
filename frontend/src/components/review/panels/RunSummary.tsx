/** Moved verbatim from `ReviewRunsView.tsx` (#967 PR 3). */
import type { ReviewFinding } from "../../../types/api";
import { kindCounts, summaryTotals } from "../reviewFormat";

/** Owner order section 3: the run's four totals in plain words, and its
 *  comments by kind. The boundary is printed with the numbers. */
export function RunSummary({ findings }: { findings: ReviewFinding[] }) {
  const totals = summaryTotals(findings);
  const kinds = kindCounts(findings);
  if (totals.counted === 0 && kinds.cConfirmed + kinds.cUnconfirmed === 0) return null;
  const cell = (label: string, value: number) => (
    <div className="rounded-[var(--radius-sm)] border border-ink-700 bg-ink-850 px-3 py-2">
      <p className="text-xs text-slateish-400">{label}</p>
      <p className="text-lg font-semibold text-slateish-100">{value.toLocaleString()}</p>
    </div>
  );
  return (
    <section aria-label="Run summary" data-testid="run-summary" className="space-y-2">
      <div className="grid gap-2 sm:grid-cols-4">
        {cell("Meets", totals.meets)}
        {cell("Does not meet", totals.doesNotMeet)}
        {cell("Needs a decision", totals.needsDecision)}
        {cell("Could not be checked", totals.couldNotCheck)}
      </div>
      <p className="text-xs text-slateish-400">
        Of {totals.counted.toLocaleString()} requirement checks in this run
        {totals.notApplicable ? `, ${totals.notApplicable.toLocaleString()} not applicable` : ""}.
        {" "}AI engineering check items are drafts and are not counted here.
      </p>
      <p className="text-xs text-slateish-300" data-testid="kind-counts">
        By kind: A - checked against a standard {kinds.a} · B - datasheet check {kinds.b} ·
        {" "}C - AI engineering check {kinds.cConfirmed} confirmed, {kinds.cUnconfirmed} to confirm
        {(kinds.dConfirmed + kinds.dUnconfirmed) > 0 && (
          <> · D - public web check {kinds.dConfirmed} confirmed, {kinds.dUnconfirmed} to confirm</>
        )}
      </p>
    </section>
  );
}
