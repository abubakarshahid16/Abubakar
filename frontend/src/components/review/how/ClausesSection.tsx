/** Section 3: the clauses, from `requirement_split` (and `applicability`,
 *  `clause_coverage` where the run stored them). */
import type { ReviewRunSummary } from "../../../types/api";
import { NOT_RECORDED, clauseFacts, uncheckedShare } from "./howData";
import { Fact, FactList, HowSection, ReasonTable, type HowSectionMeta } from "./HowPrimitives";

export const CLAUSES_META: HowSectionMeta = {
  id: "clauses", number: 3, title: "Clauses",
  explains: "Of all the clauses in the standards used, how many apply to this document, how many of those were actually checked, and why the rest were not.",
};

export function ClausesSection({ run }: { run: ReviewRunSummary }) {
  const c = clauseFacts(run);
  const share = uncheckedShare(run);
  const top = (rows: { reason: string; count: number }[]) =>
    [...rows].sort((a, b) => b.count - a.count).slice(0, 8);
  const applicability = run.applicability ?? null;
  return (
    <HowSection meta={CLAUSES_META}>
      <FactList label="Clauses">
        <Fact label="Clauses in scope (repeats counted once)" fact={c.total} testId="clauses-total" />
        <Fact label="Apply to this document" fact={c.applied} testId="clauses-applied" />
        <Fact label="Checked" fact={c.checked} testId="clauses-checked" />
        <Fact label="Apply but were not checked" fact={c.notChecked} testId="clauses-not-checked" />
        <Fact label="Do not apply" fact={c.doesNotApply} testId="clauses-not-applicable" />
        <Fact label="Repeats ignored" fact={c.repeatsIgnored} testId="clauses-repeats"
          detail="(the same standard and text, counted once)" />
      </FactList>
      <p data-testid="clauses-unchecked-share" className="text-sm text-slateish-200">
        <span className="font-medium">Unchecked share:</span>{" "}
        {share
          ? `${share.percent}% - ${share.numerator.toLocaleString()} not checked of the ${share.denominator.toLocaleString()} that apply (applies_not_checked / (checked + applies_not_checked))`
          : `${NOT_RECORDED} (no clause applies, or the run stored no split)`}
        {c.storedShare.value !== null && (
          <span className="block text-xs text-slateish-500">
            The engine stored the same share as {Math.round(c.storedShare.value * 1000) / 10}% (requirement_split.unchecked_share).
          </span>
        )}
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        <ReasonTable caption="Why clauses that apply were not checked" testId="clauses-not-checked-reasons"
          rows={c.notCheckedReasons} source="requirement_split.applies_not_checked_reasons" />
        <ReasonTable caption="Top reasons a clause does not apply" testId="clauses-not-applicable-reasons"
          rows={top(c.doesNotApplyReasons)} source="requirement_split.does_not_apply_reasons" />
      </div>
      <p className="text-sm text-slateish-300" data-testid="clauses-applicability">
        How "does not apply" was decided (from applicability):{" "}
        {applicability
          ? `the document's equipment is ${applicability.submittal_equipment.length ? applicability.submittal_equipment.join(", ") : "not named"} (source: ${applicability.equipment_source ?? "not recorded"}); `
            + `${applicability.checked_general.toLocaleString()} general clauses checked, ${applicability.checked_matching.toLocaleString()} matching-equipment clauses checked, `
            + `${applicability.kept_equipment_unknown.toLocaleString()} kept because the equipment was unknown, ${applicability.not_applied.toLocaleString()} not applied.`
          : NOT_RECORDED}
      </p>
      <p className="text-sm text-slateish-300" data-testid="clauses-coverage-line">
        Clause coverage as the engine stored it (from clause_coverage.line):{" "}
        {run.clause_coverage ? run.clause_coverage.line : NOT_RECORDED}
        {run.clause_coverage && !run.clause_coverage.adds_up && (
          <span className="text-warn-500"> The stored counts do not add up; the engine flagged this itself.</span>
        )}
      </p>
    </HowSection>
  );
}
