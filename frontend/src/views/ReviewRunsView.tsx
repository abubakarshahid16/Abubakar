/**
 * AI Submittal Review: the runs, their findings, and what an engineer does
 * about them.
 *
 * MASTER PLAN SECTION 16, STAGE 3. The run list answers "what has been
 * reviewed and what did it conclude"; selecting one answers "which standards
 * were compared and why each is on the list"; selecting a finding answers
 * "what does the clause say, what did the contractor submit, and where can I
 * read both".
 *
 * THE HONESTY RULES ARE THE DESIGN, not decoration on it (CLAUDE.md rule 4):
 * every count carries its denominator, the recommended code is shown with the
 * recommendation's own words, the completeness line says its denominator is
 * NOMINAL, and MISSING_INFORMATION is neither coloured nor worded as a
 * failure.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { api, reviews as reviewsApi } from "../api/client";
import type {
  DocumentRecord, ReviewFinding, ReviewRunStandard, ReviewRunSummary,
} from "../types/api";
import { FindingDetail } from "../components/review/FindingDetail";
import { FindingsTable } from "../components/review/FindingsTable";
import { ReviewCodePanel } from "../components/review/ReviewCodePanel";
import {
  STATUS_ORDER, completenessLine, statusLabel, statusTone, whenLabel,
  withDenominator,
} from "../components/review/reviewFormat";

type Phase =
  | { kind: "loading" }
  | { kind: "ready" }
  | { kind: "error"; message: string };

export function ReviewRunsView({ openRunId }: { openRunId?: string } = {}) {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [runs, setRuns] = useState<ReviewRunSummary[]>([]);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [findings, setFindings] = useState<ReviewFinding[]>([]);
  const [standards, setStandards] = useState<ReviewRunStandard[] | null>(null);
  const [showStandards, setShowStandards] = useState(false);
  const [selectedFinding, setSelectedFinding] = useState<string | null>(null);
  const [launch, setLaunch] = useState<{ kind: "idle" } | { kind: "running" } | { kind: "error"; message: string }>({ kind: "idle" });
  const [target, setTarget] = useState("");

  const loadRuns = useCallback(async () => {
    const result = await reviewsApi.reviewRuns();
    if (!result.ok) {
      setPhase({ kind: "error", message: result.error.message });
      return;
    }
    setRuns(result.data.runs);
    setPhase({ kind: "ready" });
  }, []);

  useEffect(() => { void loadRuns(); }, [loadRuns]);

  // ARRIVING FROM THE DASHBOARD BUTTON. The reader pressed something that
  // said it would run a review; this is the run it started, opened for them
  // rather than left for them to find in a list.
  useEffect(() => {
    if (openRunId && openRunId !== selectedRun) void openRun(openRunId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openRunId]);

  useEffect(() => {
    // BOTH SIDES OF EVERY CITATION. The submittals fill the run picker; the
    // standards are what the findings cite, and without their records the
    // detail panel cannot open the cited page and says the document is
    // unreadable - which is a different and untrue statement.
    void Promise.all([
      api.documents({ document_role: ["CONTRACTOR_SUBMITTAL"] }),
      api.documents({ document_role: ["COMPANY_STANDARD"], limit: 100 }),
    ]).then(([subs, stds]) => {
      const rows: DocumentRecord[] = [];
      if (subs.ok) rows.push(...subs.data);
      if (stds.ok) rows.push(...stds.data);
      setDocuments(rows);
    });
  }, []);

  const loadFindings = useCallback(async (runId: string) => {
    const result = await reviewsApi.list({ review_run_id: runId });
    if (!result.ok) {
      setPhase({ kind: "error", message: result.error.message });
      return;
    }
    setFindings(result.data.findings);
  }, []);

  const openRun = useCallback(async (runId: string) => {
    setSelectedRun(runId);
    setSelectedFinding(null);
    setShowStandards(false);
    // THE STANDARDS ARE LOADED WITH THE RUN, not only when the "why?" panel
    // is opened, because the findings table needs their FILENAMES. A table
    // that printed `doc_a3df49861559` where the standard's name belongs is
    // asking an engineer to recognise a hash.
    const [, listed] = await Promise.all([
      loadFindings(runId),
      reviewsApi.reviewRunStandards(runId),
    ]);
    setStandards(listed.ok ? listed.data.standards : []);
  }, [loadFindings]);

  const run = useMemo(
    () => runs.find((item) => item.review_run_id === selectedRun) ?? null,
    [runs, selectedRun],
  );
  const finding = useMemo(
    () => findings.find((item) => item.id === selectedFinding) ?? null,
    [findings, selectedFinding],
  );

  /** Standard document id -> the filename an engineer would recognise. */
  const standardNames = useMemo(() => {
    const map = new Map<string, string>();
    for (const item of standards ?? []) {
      if (item.filename) map.set(item.standard_document_id, item.filename);
    }
    return map;
  }, [standards]);

  const submittals = useMemo(
    () => documents.filter((doc) => doc.document_role === "CONTRACTOR_SUBMITTAL"),
    [documents],
  );

  async function start() {
    if (!target) return;
    setLaunch({ kind: "running" });
    const result = await reviewsApi.startReviewRun(target);
    if (!result.ok) {
      // SHOWN AS THE API RETURNED IT. A refusal - "a review of this submittal
      // is already running" - is a real answer, and retrying it silently
      // would leave the reader watching a button that appears to do nothing.
      setLaunch({ kind: "error", message: result.error.message });
      return;
    }
    setLaunch({ kind: "idle" });
    await loadRuns();
    await openRun(result.data.review_run_id);
  }


  return (
    <main className="mx-auto w-full max-w-7xl space-y-6" aria-labelledby="review-runs-title">
      <header>
        <p className="text-sm font-semibold uppercase tracking-[0.16em] text-signal-400">
          AI Submittal Review
        </p>
        <h1 id="review-runs-title" className="mt-2 text-3xl font-semibold text-slateish-100">
          Review runs
        </h1>
        <p className="mt-2 max-w-3xl text-slateish-300">
          Each run compares one contractor submittal against the standards that
          apply to it, and records a finding per requirement with both
          citations.
        </p>
      </header>

      <section className="rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-4">
        <h2 className="text-sm font-semibold text-slateish-200">Run a review</h2>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <label className="text-xs text-slateish-400" htmlFor="review-target">
            Submittal
          </label>
          <select
            id="review-target" value={target}
            onChange={(event) => setTarget(event.target.value)}
            className="min-w-[18rem] rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-slateish-100"
          >
            <option value="">Choose a contractor submittal…</option>
            {submittals.map((doc) => (
              <option key={doc.id} value={doc.id}>{doc.filename}</option>
            ))}
          </select>
          <button
            type="button" onClick={() => void start()}
            disabled={!target || launch.kind === "running"}
            className="rounded-[var(--radius-sm)] bg-signal-500 px-4 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50"
          >
            {launch.kind === "running" ? "Running…" : "Run AI review"}
          </button>
          {launch.kind === "running" && (
            <span aria-live="polite" className="text-sm text-slateish-300">
              Selecting applicable standards and comparing requirements. This
              can take a minute.
            </span>
          )}
        </div>
        {launch.kind === "error" && (
          <p role="alert" className="mt-2 rounded-[var(--radius-sm)] border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
            {launch.message}
          </p>
        )}
      </section>

      {phase.kind === "loading" && <p className="text-slateish-300">Loading review runs…</p>}
      {phase.kind === "error" && (
        <p role="alert" className="rounded-[var(--radius-md)] border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-rose-200">
          {phase.message}
        </p>
      )}

      {phase.kind === "ready" && runs.length === 0 && <EmptyRuns />}

      {phase.kind === "ready" && runs.length > 0 && (
        <section aria-labelledby="runs-list-title" className="space-y-3">
          <h2 id="runs-list-title" className="text-lg font-semibold text-slateish-100">
            {runs.length.toLocaleString()} {runs.length === 1 ? "run" : "runs"}
          </h2>
          <ul className="space-y-3">
            {runs.map((item) => (
              <li key={item.review_run_id}>
                <RunCard
                  run={item}
                  selected={item.review_run_id === selectedRun}
                  onOpen={() => void openRun(item.review_run_id)}
                />
              </li>
            ))}
          </ul>
        </section>
      )}

      {run && (
        <section className="space-y-4 rounded-[var(--radius-md)] border border-ink-700 bg-ink-900 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-lg font-semibold text-slateish-100">
              {run.submittal_filename}
            </h2>
            <button
              type="button" onClick={() => setShowStandards((value) => !value)}
              className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-sm text-signal-300"
            >
              {run.standards_in_scope} standards in scope — why?
            </button>
          </div>

          {showStandards && (
            <StandardsInScope standards={standards} />
          )}

          <ReviewCodePanel run={run} onDecided={() => { void loadRuns(); }} />

          <FindingsTable
            findings={findings} selectedId={selectedFinding}
            standardNames={standardNames}
            onSelect={(item) => setSelectedFinding(item.id)}
          />

          {finding && (
            <FindingDetail
              finding={finding} documents={documents}
              standardNames={standardNames}
              onChanged={() => { void loadFindings(run.review_run_id); }}
            />
          )}
        </section>
      )}
    </main>
  );
}

function RunCard({ run, selected, onOpen }: {
  run: ReviewRunSummary; selected: boolean; onOpen: () => void;
}) {
  const completeness = completenessLine(run);
  return (
    <button
      type="button" onClick={onOpen}
      className={`w-full rounded-[var(--radius-md)] border p-4 text-left ${selected ? "border-signal-500 bg-signal-500/5" : "border-ink-700 bg-ink-850 hover:border-ink-600"}`}
    >
      <div className="flex flex-wrap items-baseline gap-3">
        <span className="font-semibold text-slateish-100">{run.submittal_filename}</span>
        {run.equipment_tags.map((tag) => (
          <span key={tag} className="rounded-full border border-ink-600 bg-ink-800 px-2 py-0.5 text-xs text-slateish-300">
            {tag}
          </span>
        ))}
        <span className="ml-auto text-xs text-slateish-400">{whenLabel(run.created_at)}</span>
      </div>
      <p className="mt-1 text-xs text-slateish-400">
        {run.standards_in_scope} standards in scope · status {run.status}
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        {STATUS_ORDER.filter((status) => run.by_status[status]).map((status) => (
          <span key={status} className={`rounded-full border px-2 py-0.5 text-xs ${statusTone(status)}`}>
            {statusLabel(status)} {withDenominator(run.by_status[status] ?? 0, run.findings_total)}
          </span>
        ))}
      </div>
      {run.failure_reason && (
        <p className="mt-2 text-sm text-rose-200">
          This run failed — {run.failure_reason}
        </p>
      )}
      {run.recommended_code && (
        <p className="mt-3 text-sm text-slateish-200">
          <span className="font-semibold">{run.recommended_code}</span>
          {run.recommended_reason ? <span className="text-slateish-400"> — {run.recommended_reason}</span> : null}
        </p>
      )}
      {completeness && (
        <p className="mt-1 text-xs text-slateish-500">{completeness}</p>
      )}
    </button>
  );
}

function StandardsInScope({ standards }: { standards: ReviewRunStandard[] | null }) {
  if (standards === null) return <p className="text-sm text-slateish-400">Loading standards…</p>;
  if (standards.length === 0) {
    return (
      <p className="text-sm text-slateish-400">
        No standards were selected for this run.
      </p>
    );
  }
  return (
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
        </li>
      ))}
    </ul>
  );
}

function EmptyRuns() {
  return (
    <section className="rounded-[var(--radius-md)] border border-dashed border-ink-600 bg-ink-850 p-6">
      <h2 className="text-lg font-semibold text-slateish-100">No reviews have been run yet</h2>
      <p className="mt-2 max-w-2xl text-sm text-slateish-300">
        A review takes one contractor submittal, works out which company
        standards apply to it, and compares every requirement it can against
        the values on the datasheet. It records one finding per requirement,
        each with the clause it came from and the page of the submittal it was
        compared against.
      </p>
      <p className="mt-2 max-w-2xl text-sm text-slateish-400">
        To start one: choose a contractor submittal above and select
        <span className="font-semibold text-slateish-200"> Run AI review</span>.
        If the list is empty, upload a datasheet on the Documents page first
        and set its role to contractor submittal.
      </p>
    </section>
  );
}
