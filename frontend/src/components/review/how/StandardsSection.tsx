/**
 * Section 2: the standards. The count is the run's own `standards_in_scope`;
 * the names come from the run's stored standards record
 * (`GET /api/reviews/runs/{id}/standards`: `review_applicable_standards` and
 * the cited-but-missing references). Per-standard clause counts are shown
 * only where the run stored one (`requirements_not_applied`,
 * `table_values_not_compared`); otherwise NOT_RECORDED.
 */
import type {
  ReviewRunHeldForConfirmation, ReviewRunMissingReference, ReviewRunStandard, ReviewRunSummary,
} from "../../../types/api";
import { NavLink } from "../../NavLink";
import { selectionMethodWords } from "../panels/selectionMethodWords";
import { NOT_RECORDED } from "./howData";
import { Fact, FactList, HowSection, type HowSectionMeta } from "./HowPrimitives";

export const STANDARDS_META: HowSectionMeta = {
  id: "standards", number: 2, title: "Standards",
  explains: "Which rule books the document was checked against, which ones it names that the library does not hold (those clauses were not checked), and what each one contributed.",
};

export interface StandardsRecord {
  standards: ReviewRunStandard[];
  missing: ReviewRunMissingReference[];
  /** #620: Company standards left out while they wait for an administrator. */
  held?: ReviewRunHeldForConfirmation | null;
}

const STANDARDS_SOURCE = "the run's standards record (GET /api/reviews/runs/{id}/standards)";

/** The stored per-standard counts the run carries, by standard id. */
function storedCounts(run: ReviewRunSummary, id: string): string | null {
  const parts: string[] = [];
  for (const group of run.requirements_not_applied ?? []) {
    for (const s of group.standards) {
      if (s.standard_document_id === id) parts.push(`${s.count} clause(s) not applied to this equipment (requirements_not_applied)`);
    }
  }
  for (const t of run.table_values_not_compared ?? []) {
    if (t.standard_document_id === id) parts.push(`${t.count} table value(s) not compared (table_values_not_compared)`);
  }
  return parts.length ? parts.join("; ") : null;
}

function StandardRow({ item, run }: { item: ReviewRunStandard; run: ReviewRunSummary }) {
  const counts = storedCounts(run, item.standard_document_id);
  return (
    <li className="py-1.5 text-sm">
      <span className="font-medium text-slateish-100">{item.filename ?? item.standard_document_id}</span>
      <span className="ml-2 text-xs text-slateish-400">
        {/* v2.1 (T2): plain words, the stored code in the tooltip. */}
        <span title={item.selection_method ?? undefined} data-testid="how-standard-chosen-by">
          {selectionMethodWords(item.selection_method).words}
        </span>
      </span>
      <p className="text-xs text-slateish-400">
        Clauses contributed: {counts ?? NOT_RECORDED}
        {counts ? "" : " (this review stores no count per standard)"}
      </p>
    </li>
  );
}

export function StandardsSection({ run, record, error }: {
  run: ReviewRunSummary;
  /** Null while loading or when the load failed (`error` then says so). */
  record: StandardsRecord | null;
  error: string | null;
}) {
  const included = record?.standards.filter((s) => s.included) ?? null;
  const cited = included?.filter((s) => s.selection_method === "referenced") ?? null;
  return (
    <HowSection meta={STANDARDS_META}>
      <FactList label="Standards">
        <Fact label="Standards in scope" testId="standards-in-scope"
          fact={{ value: run.standards_in_scope ?? null, source: "standards_in_scope" }} />
        <Fact label="Cited by the document and in the library" testId="standards-cited"
          fact={{ value: cited ? cited.length : null, source: `${STANDARDS_SOURCE}, selection_method "referenced"` }} />
        <Fact label="Cited by the document but missing from the library" testId="standards-missing-count"
          fact={{ value: record ? record.missing.length : null, source: `${STANDARDS_SOURCE}, missing_references` }}
          detail="- their clauses were not checked" />
      </FactList>
      {error !== null && (
        <p role="alert" className="text-sm text-danger-500">
          The standards record for this run could not be loaded ({error}). It is not known which standards were used.
        </p>
      )}
      {included && included.length > 0 && (
        <div>
          <p className="text-sm text-slateish-300">In the library and used (from {STANDARDS_SOURCE}):</p>
          <ul data-testid="standards-held" className="divide-y divide-ink-700">
            {included.map((item) => <StandardRow key={item.standard_document_id} item={item} run={run} />)}
          </ul>
        </div>
      )}
      {included && included.length === 0 && <p className="text-sm text-slateish-400">No standard was selected for this review.</p>}
      {record?.held && (
        // #620: the run's own sentence, with its boundary; never a bare count.
        <p data-testid="standards-held-for-confirmation" className="text-sm text-warn-500">{record.held.sentence}</p>
      )}
      {record && record.missing.length > 0 && (
        <div>
          <p className="text-sm text-warn-500">Missing from the library, so not checked:</p>
          <ul data-testid="standards-missing" className="divide-y divide-ink-700">
            {record.missing.map((m) => (
              <li key={m.identifier} className="flex flex-wrap items-baseline gap-x-3 py-1.5 text-sm">
                <span className="font-medium text-slateish-100">{m.identifier}</span>
                <span className="text-xs text-slateish-400">{m.status}</span>
                <NavLink view="documents" className="text-signal-300 underline-offset-2 hover:underline print:hidden">
                  Upload it on the Documents screen
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      )}
    </HowSection>
  );
}
