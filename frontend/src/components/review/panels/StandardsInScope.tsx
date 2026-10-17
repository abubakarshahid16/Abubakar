/** Owner order section 3 / B5: the standards this run applied, each with
 *  its method, reason and evidence, and the cited ones the library does not
 *  hold. Moved verbatim from `ReviewRunsView.tsx` (#967 PR 3). */
import type { ReviewRunMissingReference, ReviewRunStandard } from "../../../types/api";

export function StandardsInScope({ standards, missing, error }: {
  standards: ReviewRunStandard[] | null; missing: ReviewRunMissingReference[];
  error: string | null;
}) {
  // Before the loading check: a failed load leaves `standards` null, and a
  // spinner that never stops is its own false statement.
  if (error !== null) {
    return (
      <p role="alert" className="rounded-[var(--radius-md)] border border-danger-500/40 bg-danger-500/10 p-3 text-sm text-danger-500">
        The standards for this run could not be loaded - {error}. It is not
        known which standards were selected, or which cited standards are not
        held locally.
      </p>
    );
  }
  if (standards === null) return <p className="text-sm text-slateish-400">Loading standards…</p>;
  // B5: a cited standard the library does not hold was NOT checked. Shown
  // whether or not anything else was selected, so "no standards" never
  // hides "the ones it cites are missing".
  const notHeld = missing.length > 0 && (
    <div role="note" className="rounded-[var(--radius-md)] border border-warn-500/40 bg-warn-500/10 p-3 text-sm">
      <p className="font-medium text-warn-500">
        Cited by the submittal but not held locally - not checked ({missing.length})
      </p>
      <ul className="mt-1 list-disc ps-5 text-xs text-slateish-300">
        {missing.map((m) => <li key={m.identifier}>{m.identifier}</li>)}
      </ul>
    </div>
  );
  if (standards.length === 0) {
    return (
      <div className="space-y-2">
        {notHeld}
        <p className="text-sm text-slateish-400">
          No standards were selected for this run.
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-2">
    {notHeld}
    <ul className="space-y-2 rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-3">
      {standards.map((item) => (
        <li key={item.standard_document_id} className="text-sm">
          <span className="font-medium text-slateish-100">{item.filename ?? item.standard_document_id}</span>
          <span className="ml-2 rounded-full border border-ink-600 bg-ink-800 px-2 py-0.5 text-xs text-slateish-300">
            {item.selection_method ?? "unrecorded"}
          </span>
          {/* THE REASON, VERBATIM. A semantic match says in its own words
              that it is not a citation; re-wording it here would turn
              "something was retrieved" into "this standard applies". */}
          <p className="mt-0.5 text-xs text-slateish-400">{item.selection_reason}</p>
          {/* B5: THE EVIDENCE, verbatim from the document - the line the
              submittal cites it on, or the scope clause that decided it. */}
          {item.evidence_quote && (
            <p className="mt-0.5 text-xs text-slateish-500">
              Evidence{item.evidence_page != null ? `, page ${item.evidence_page}` : ""}: “{item.evidence_quote}”
            </p>
          )}
        </li>
      ))}
    </ul>
    </div>
  );
}
