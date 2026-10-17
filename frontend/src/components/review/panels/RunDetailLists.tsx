/** #678 / #453 / #598: the three groups of requirements, the requirements
 *  about another kind of equipment, and the table values not compared. Moved
 *  verbatim from `ReviewRunsView.tsx` (#967 PR 3). */
import type { RequirementSplit, RequirementSplitReason, RequirementsNotApplied, TableValuesNotCompared } from "../../../types/api";

/** #678: the three honest groups. "Not checked" and "does not apply" are
 *  different things and never one blended number; only "apply but not checked"
 *  counts against the run. */
export function RequirementSplitPanel({ split }: { split: RequirementSplit }) {
  const group = (label: string, count: number, reasons: RequirementSplitReason[], testId: string) => (
    <li data-testid={testId}>
      <span className="text-slateish-300">{`${count} ${label}`}</span>
      {count > 0 && reasons.length > 0 && (
        <ul className="mt-0.5 list-disc ps-5 text-xs text-slateish-400">
          {reasons.slice(0, 3).map((r) => (
            <li key={r.reason}>{`${r.reason} (${r.count})`}</li>
          ))}
        </ul>
      )}
    </li>
  );
  const applies = split.checked + split.applies_not_checked;
  return (
    <section aria-label="Requirements in scope" data-testid="requirement-split" className="text-sm">
      <p className="text-slateish-300">
        {`${split.total} requirements in scope`}
        {split.unchecked_share !== null &&
          `; ${split.applies_not_checked} of ${applies} (${Math.round(split.unchecked_share * 100)}%) of those that apply were not checked`}
      </p>
      <ul className="mt-1 space-y-1">
        {group("checked", split.checked, [], "split-checked")}
        {group("apply but were not checked", split.applies_not_checked, split.applies_not_checked_reasons, "split-not-checked")}
        {group("do not apply", split.does_not_apply, split.does_not_apply_reasons, "split-not-apply")}
      </ul>
    </section>
  );
}

/** #453: the requirements about a different kind of equipment, one expandable
 *  line per subject. They are counted, never dropped silently. */
export function RequirementsNotAppliedList({ lines }: { lines: RequirementsNotApplied[] }) {
  return (
    <ul className="space-y-1 text-sm" data-testid="requirements-not-applied">
      {lines.map((item) => (
        <li key={item.subject}>
          <details>
            <summary className="cursor-pointer text-slateish-300">{item.line}</summary>
            <ul className="mt-1 list-disc ps-5 text-xs text-slateish-400">
              {item.standards.map((standard) => (
                <li key={standard.standard_document_id}>
                  {standard.count} in {standard.standard_name}
                  {standard.clauses.length > 0 ? `, clauses ${standard.clauses.join(", ")}` : ""}
                </li>
              ))}
            </ul>
          </details>
        </li>
      ))}
    </ul>
  );
}

/** #598: the table cells this run did not compare, one expandable line per
 *  standard. They are counted, never dropped silently. */
export function TableValuesNotComparedList({ lines }: { lines: TableValuesNotCompared[] }) {
  return (
    <ul className="space-y-1 text-sm" data-testid="table-values-not-compared">
      {lines.map((item) => (
        <li key={item.standard_document_id}>
          <details>
            <summary className="cursor-pointer text-slateish-300">{item.line}</summary>
            <ul className="mt-1 list-disc ps-5 text-xs text-slateish-400">
              {item.tables.map((table, index) => (
                <li key={index}>
                  {table.count} on {table.page != null ? `page ${table.page}` : "an unnumbered page"}
                  {table.examples.length > 0 ? `, for example ${table.examples.join(", ")}` : ""}
                </li>
              ))}
            </ul>
          </details>
        </li>
      ))}
    </ul>
  );
}
