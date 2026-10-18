/**
 * "How this was reviewed" (order 95, spec 1.4, piece 5 of #967): one page
 * per run, at `/review/<run>/how`, linked from the Sheet header. Written for
 * the person who asks "what did the machine actually do?" - a manager, an
 * auditor - and for printing: it is attached to audits.
 *
 * DISPLAY ONLY. Every number is one the engine stored on the run object
 * (`GET /api/reviews/runs`: `page_coverage` with its `reading` record,
 * `requirement_split` with its `reader`, `applicability`, `clause_coverage`,
 * `ai_numbers`, `ai_check_status`, `standards_change`, the time and result
 * fields) or the run's stored standards record; each is printed with the
 * field it came from. Nothing is counted here beyond the length of a stored
 * list or the sum of stored fields (named beside the number). A field the
 * run does not hold reads "not recorded on this run" - never 0, never
 * blank; a field the runs list does not send at all (the code and settings
 * versions today) reads "not sent to this page".
 */
import { useEffect, useState } from "react";

import { reviews as reviewsApi } from "../api/client";
import type { ReviewRunSummary } from "../types/api";
import { AI_META, AiStepsSection } from "../components/review/how/AiStepsSection";
import { CLAUSES_META, ClausesSection } from "../components/review/how/ClausesSection";
import { PAGES_META, PagesSection } from "../components/review/how/PagesSection";
import { RESULT_META, ResultSection } from "../components/review/how/ResultSection";
import { STANDARDS_META, StandardsSection, type StandardsRecord } from "../components/review/how/StandardsSection";
import { TIME_META, TimeSection } from "../components/review/how/TimeSection";
import { VERSIONS_META, VersionsSection } from "../components/review/how/VersionsSection";
import type { HowSectionMeta } from "../components/review/how/HowPrimitives";
import { runStatusLabel, whenLabel } from "../components/review/reviewFormat";

const SECTIONS: HowSectionMeta[] = [PAGES_META, STANDARDS_META, CLAUSES_META, AI_META, TIME_META, VERSIONS_META, RESULT_META];

type Load = { kind: "loading" } | { kind: "ready"; run: ReviewRunSummary } | { kind: "error"; message: string };
type Standards = { record: StandardsRecord | null; error: string | null };

export function HowReviewedView({ runId, onBack, onOpenRun, onOpenSteps }: {
  runId: string;
  /** Back to this run's sheet. */
  onBack: () => void;
  /** Open another run (the previous one) on its sheet. */
  onOpenRun?: (runId: string) => void;
  /** The step-by-step record of this run (`/review/<run>/steps`). */
  onOpenSteps?: () => void;
}) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [standards, setStandards] = useState<Standards>({ record: null, error: null });

  useEffect(() => {
    // The App keys this view by run id, so a new run is a fresh mount and
    // the initial "loading" state stands; nothing is set synchronously here.
    let alive = true;
    void Promise.all([reviewsApi.reviewRuns(), reviewsApi.reviewRunStandards(runId)]).then(([runs, stds]) => {
      if (!alive) return;
      if (!runs.ok) { setLoad({ kind: "error", message: runs.error.message }); return; }
      const found = runs.data.runs.find((r) => r.review_run_id === runId);
      if (!found) { setLoad({ kind: "error", message: "This review run could not be found." }); return; }
      setLoad({ kind: "ready", run: found });
      // A FAILED LIST IS NOT AN EMPTY ONE: the section says it could not be
      // loaded rather than "no standards were used".
      setStandards(stds.ok
        ? { record: { standards: stds.data.standards, missing: stds.data.missing_references ?? [] }, error: null }
        : { record: null, error: stds.error.message });
    });
    return () => { alive = false; };
  }, [runId]);

  return (
    <section className="mx-auto w-full max-w-6xl space-y-5" aria-labelledby="how-title" data-testid="how-reviewed">
      <header className="space-y-2">
        <button type="button" onClick={onBack} className="text-sm text-signal-300 underline-offset-2 hover:underline print:hidden">
          ← Back to the sheet
        </button>
        <h1 id="how-title" className="text-2xl font-semibold text-slateish-100">How this was reviewed</h1>
        {load.kind === "ready" && (
          <p className="text-sm text-slateish-300" data-testid="how-subtitle">
            {load.run.submittal_filename ?? "Document name not recorded"} · run {load.run.review_run_id}
            {load.run.status ? ` · ${runStatusLabel(load.run.status)}` : ""}
            {load.run.completed_at ? ` · ${whenLabel(load.run.completed_at)}` : ""}
          </p>
        )}
        <p className="text-sm text-slateish-400">
          Every number on this page is one the review stored when it ran, printed with the field it came from.
          Nothing is recounted here. A field this run did not store reads "not recorded on this run".
        </p>
      </header>

      {load.kind === "loading" && <p className="text-slateish-300">Loading the run record…</p>}
      {load.kind === "error" && (
        <p role="alert" className="rounded-[var(--radius-md)] border border-danger-500/40 bg-danger-500/10 px-4 py-3 text-danger-500">
          {load.message}
        </p>
      )}

      {load.kind === "ready" && (
        <div className="grid gap-6 lg:grid-cols-[12rem_minmax(0,1fr)]">
          <nav aria-label="Sections of this page" className="print:hidden lg:sticky lg:top-4 lg:self-start">
            <ol className="flex flex-wrap gap-x-3 gap-y-1 text-sm lg:flex-col">
              {SECTIONS.map((s) => (
                <li key={s.id}>
                  <a href={`#${s.id}`} className="text-signal-300 underline-offset-2 hover:underline">
                    {s.number}. {s.title}
                  </a>
                </li>
              ))}
            </ol>
          </nav>
          <div className="min-w-0 space-y-5">
            <PagesSection run={load.run} />
            <StandardsSection run={load.run} record={standards.record} error={standards.error} />
            <ClausesSection run={load.run} />
            <AiStepsSection run={load.run} />
            <TimeSection run={load.run} onOpenSteps={onOpenSteps} />
            <VersionsSection run={load.run} onOpenRun={onOpenRun} />
            <ResultSection run={load.run} />
            <p className="text-xs text-slateish-500">
              Printed from the run record of {load.run.review_run_id}
              {load.run.completed_at ? `, completed ${whenLabel(load.run.completed_at)}` : ""}.
            </p>
          </div>
        </div>
      )}
    </section>
  );
}
