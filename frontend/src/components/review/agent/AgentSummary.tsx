/**
 * What the AI reviewer decided about the paper and how the lines split.
 * Counts are per class and apart, over the lines of this review only; no
 * percentage. A null cost renders nothing (never 0).
 */
import type { AgentRunSummary } from "../../../types/api";
import { PaperTextNotice, paperTextStopped } from "./PaperTextNotice";
import { CLASS_ORDER, CLASS_STYLE, NOT_REVIEWED_NOTE, isKnownClass, modeWords } from "./agentWords";

export function AgentSummary({ summary }: { summary: AgentRunSummary }) {
  const counts = summary.counts_by_class;
  const known = CLASS_ORDER.filter((c) => c in counts);
  const other = Object.keys(counts).filter((c) => !isKnownClass(c));
  const cost = summary.usd;
  return (
    <section aria-labelledby="agent-summary-title" data-testid="agent-summary" className="space-y-3">
      <h2 id="agent-summary-title" className="text-lg font-semibold text-slateish-100">AI review summary</h2>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-[max-content_1fr]">
        <dt className="text-slateish-400">Paper kind</dt>
        <dd className="text-slateish-100">{summary.paper_kind} <span className="text-slateish-400">(decided by: {summary.paper_kind_source})</span></dd>
        <dt className="text-slateish-400">Review</dt>
        <dd className="text-slateish-100" data-testid="agent-mode">{modeWords(summary.mode)}</dd>
        {summary.mode === "general review" && (
          <>
            <dt className="text-slateish-400">Project papers</dt>
            <dd className="text-slateish-100" data-testid="agent-project-papers">
              {(summary.project_papers_used ?? []).length > 0
                ? `Project papers used: ${summary.project_papers_used.map((p) => p.name).join(", ")}`
                : "No project paper was given to check against"}
            </dd>
          </>
        )}
        <dt className="text-slateish-400">Equipment type</dt>
        <dd className="text-slateish-100">{summary.equipment_type ? summary.equipment_type : "not known"}</dd>
        {cost != null && (<><dt className="text-slateish-400">Cost</dt><dd className="text-slateish-100">USD {cost.toFixed(2)}</dd></>)}
        {summary.models.length > 0 && (<><dt className="text-slateish-400">Models</dt><dd className="text-slateish-100">{summary.models.join(", ")}</dd></>)}
      </dl>
      {(summary.equipment_notes ?? []).length > 0 && (
        <ul data-testid="equipment-notes" className="list-disc pl-5 text-sm text-slateish-100">
          {summary.equipment_notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      )}
      <PaperTextNotice paperText={summary.paper_text} />
      {summary.stop_reason && !paperTextStopped(summary.paper_text) && (
        <p role="status" data-testid="agent-stop-reason"
          className="rounded-[var(--radius-sm)] border border-warn-500/50 bg-warn-500/10 px-3 py-2 text-sm text-slateish-100">
          This review stopped early: {summary.stop_reason}. The lines below are the ones finished before it stopped.
        </p>
      )}
      <div>
        <h3 className="text-sm font-semibold text-slateish-200">Lines of this review, by class (each class counted apart)</h3>
        {known.length + other.length === 0 ? (
          <p className="text-sm text-slateish-400">No lines were written for this review.</p>
        ) : (
          <ul className="mt-1 space-y-1 text-sm">
            {known.map((c) => (
              <li key={c} data-testid={`count-${c}`} className={`pl-2 ${CLASS_STYLE[c].border}`}>
                <span aria-hidden="true">{CLASS_STYLE[c].mark} </span>{c}: <span className="font-mono">{counts[c]}</span>{c === "Not reviewed" ? ` (${NOT_REVIEWED_NOTE})` : ""}
              </li>
            ))}
            {other.map((c) => (
              <li key={c} className="pl-2 text-warn-500">Unknown class (data error) {c}: <span className="font-mono">{counts[c]}</span></li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <h3 className="text-sm font-semibold text-slateish-200">Rule books we do not hold</h3>
        {summary.missing_books.length === 0 ? (
          <p className="text-sm text-slateish-400">None: every rule book this paper cites is held.</p>
        ) : (
          <>
            <ul className="mt-1 list-disc pl-5 text-sm text-slateish-100">
              {summary.missing_books.map((b) => <li key={b}>{b}</li>)}
            </ul>
            <p className="text-xs text-slateish-400">Listed only: these are not counted against the review.</p>
          </>
        )}
      </div>
    </section>
  );
}
