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
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, reviews as reviewsApi } from "../api/client";
import type {
  CrsPreview, CrsReviewNote, DocumentRecord, ReviewFinding, ReviewReadiness,
  ReviewRunMissingReference, ReviewRunStandard, ReviewRunSummary,
} from "../types/api";
import { FindingDetail } from "../components/review/FindingDetail";
import { FindingsTable } from "../components/review/FindingsTable";
import { ReviewCodePanel } from "../components/review/ReviewCodePanel";
import { StandardOverrideControl } from "../components/review/StandardOverrideControl";
import {
  STATUS_ORDER, completenessLine, groupRunsByDocument, kindCounts, pageCoverageLine,
  pageList, pagesReadLine, statusLabel, statusTone, standardsChangeLine, summaryTotals,
  whenLabel, withDenominator,
} from "../components/review/reviewFormat";

type Phase =
  | { kind: "loading" }
  | { kind: "ready" }
  | { kind: "error"; message: string };

export function ReviewRunsView(
  { openRunId, onOpenStandards }: { openRunId?: string; onOpenStandards?: () => void } = {},
) {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [runs, setRuns] = useState<ReviewRunSummary[]>([]);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [findings, setFindings] = useState<ReviewFinding[]>([]);
  const [standards, setStandards] = useState<ReviewRunStandard[] | null>(null);
  const [missingStandards, setMissingStandards] = useState<ReviewRunMissingReference[]>([]);
  const [showStandards, setShowStandards] = useState(false);
  const [selectedFinding, setSelectedFinding] = useState<string | null>(null);
  const [launch, setLaunch] = useState<{ kind: "idle" } | { kind: "running" } | { kind: "error"; message: string }>({ kind: "idle" });
  const [target, setTarget] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [preview, setPreview] = useState<CrsPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const findingsRef = useRef<HTMLElement | null>(null);
  // Owner order section 3: the readiness strip, and the question asked when
  // a re-run cannot say anything new.
  const [readiness, setReadiness] = useState<ReviewReadiness | null>(null);
  const [confirmRerun, setConfirmRerun] = useState(false);

  /** Fetch the CRS with the bearer token and hand it to the browser.
   *
   *  A plain `<a href>` would be simpler and would not work: it cannot send
   *  the Authorization header, so the request arrives unauthenticated and the
   *  route answers 404 - which would look like a missing run rather than a
   *  missing token. The filename comes from the SERVER's
   *  Content-Disposition, so one definition of "what is this file called"
   *  exists rather than two that can disagree.
   */
  async function exportCrs(runId: string, copy: "internal" | "issue" = "internal") {
    setExporting(true);
    setExportError(null);
    const result = await reviewsApi.exportCrs(runId, copy);
    setExporting(false);
    if (!result.ok) {
      setExportError(result.error.message);
      return;
    }
    const url = URL.createObjectURL(result.data.blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = result.data.filename;
    link.click();
    URL.revokeObjectURL(url);
  }

  /** Show the CRS in the application, or hide it again.
   *
   *  THE DELIVERABLE WITHOUT LEAVING THE APPLICATION. Downloading the .xlsx
   *  and opening Excel was the only way to see what this system produces,
   *  which in front of a client means leaving the screen to show the screen's
   *  own output. The download is untouched: this is a second way to LOOK at
   *  the same sheet, never a second answer about what it says - the server
   *  builds both from one builder.
   *
   *  Fetched on open rather than with the run, because most visits to a run
   *  are about its findings, and a sheet nobody asked to see is a request
   *  nobody asked for. */
  async function togglePreview(runId: string) {
    if (preview) {
      setPreview(null);
      setPreviewError(null);
      return;
    }
    setPreviewing(true);
    setPreviewError(null);
    const result = await reviewsApi.previewCrs(runId);
    setPreviewing(false);
    if (!result.ok) {
      // SHOWN AS THE API RETURNED IT, like the export error beside it. A 404
      // here means this caller may not read the submittal, and inventing a
      // friendlier sentence would hide which of the two it was.
      setPreviewError(result.error.message);
      return;
    }
    setPreview(result.data);
  }

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

  // P3: A QUEUED OR RUNNING REVIEW IS WATCHED until it finishes - the request
  // no longer waits for it. Polling stops by itself when nothing is active.
  const active = runs.some((r) => r.status === "queued" || r.status === "running");
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => { void loadRuns(); }, 3000);
    return () => clearInterval(timer);
  }, [active, loadRuns]);

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
    // THE SHEET BELONGS TO THE RUN THAT WAS OPEN. Leaving it on screen while
    // a different run loads shows one submittal's comments under another
    // submittal's name - the reader has no way to tell it is stale.
    setPreview(null);
    setPreviewError(null);
    // THE STANDARDS ARE LOADED WITH THE RUN, not only when the "why?" panel
    // is opened, because the findings table needs their FILENAMES. A table
    // that printed `doc_a3df49861559` where the standard's name belongs is
    // asking an engineer to recognise a hash.
    const [, listed] = await Promise.all([
      loadFindings(runId),
      reviewsApi.reviewRunStandards(runId),
    ]);
    setStandards(listed.ok ? listed.data.standards : []);
    setMissingStandards(listed.ok ? listed.data.missing_references ?? [] : []);
  }, [loadFindings]);

  // THE FINDINGS ARE WHY THE READER CLICKED. With a dozen runs listed the
  // panel rendered thousands of pixels below the fold, so a click looked
  // like it had done nothing. The panel now renders above the list and the
  // view moves to it. Guarded: jsdom and older engines have no
  // scrollIntoView, and the selection still works without one.
  useEffect(() => {
    const el = findingsRef.current;
    if (!selectedRun || el === null) return;
    if (typeof el.scrollIntoView !== "function") return;
    el.scrollIntoView({ block: "start" });
  }, [selectedRun]);

  const run = useMemo(
    () => runs.find((item) => item.review_run_id === selectedRun) ?? null,
    [runs, selectedRun],
  );

  // 2g: THE PICKER AND THE PANEL NAME THE SAME DOCUMENT. They were two pieces
  // of state: the dropdown kept whatever was last chosen while the panel
  // showed whichever run was opened, so one document sat above another's
  // findings. Opening a run now sets the picker to its submittal...
  useEffect(() => {
    if (run) setTarget(run.submittal_document_id);
  }, [run]);

  // ...and choosing a submittal opens its latest run, or closes the panel
  // when it has none - never leaving another document's run on screen.
  function pickTarget(documentId: string) {
    setTarget(documentId);
    const latest = runs
      .filter((item) => item.submittal_document_id === documentId)
      .sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""))[0];
    if (latest) {
      void openRun(latest.review_run_id);
    } else {
      setSelectedRun(null);
      setFindings([]);
      setPreview(null);
    }
  }
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

  const loadReadiness = useCallback(async (documentId: string) => {
    if (!documentId) { setReadiness(null); return; }
    const result = await reviewsApi.readiness(documentId);
    // A readiness the server would not give is shown as nothing: the strip
    // is a help before running, not a gate, and the run button still works.
    setReadiness(result.ok ? result.data : null);
  }, []);

  useEffect(() => {
    setConfirmRerun(false);
    void loadReadiness(target);
  }, [target, loadReadiness]);

  /** Owner order section 3: "Nothing changed since the last run" is asked
   *  about BEFORE running - the same inputs give the same result, and a
   *  re-run the engineer expected to differ is time lost. */
  function requestRun() {
    if (readiness?.nothing_changed && !confirmRerun) {
      setConfirmRerun(true);
      return;
    }
    setConfirmRerun(false);
    void start();
  }

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
    void loadReadiness(target);
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
            onChange={(event) => pickTarget(event.target.value)}
            className="min-w-[18rem] rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-slateish-100"
          >
            <option value="">Choose a contractor submittal…</option>
            {submittals.map((doc) => (
              <option key={doc.id} value={doc.id}>{doc.filename}</option>
            ))}
          </select>
          <button
            type="button" onClick={requestRun}
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
        {target && readiness && readiness.submittal_document_id === target && (
          <ReadinessStrip readiness={readiness} onOpenStandards={onOpenStandards} />
        )}
        {confirmRerun && (
          <div role="alertdialog" aria-label="Nothing changed since the last run"
            className="mt-3 space-y-2 rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 p-3 text-sm">
            <p className="font-medium text-slateish-100">Nothing changed since the last run.</p>
            <p className="text-slateish-300">
              No datasheet value was read and no standard was added since then,
              so a new run will give the same result. Upload a missing standard
              or re-read the unread pages first, or run it again anyway.
            </p>
            <div className="flex gap-2">
              <button type="button" onClick={requestRun}
                className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-slateish-100">
                Run again anyway
              </button>
              <button type="button" onClick={() => setConfirmRerun(false)}
                className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-slateish-300">
                Cancel
              </button>
            </div>
          </div>
        )}
      </section>

      {phase.kind === "loading" && <p className="text-slateish-300">Loading review runs…</p>}
      {phase.kind === "error" && (
        <p role="alert" className="rounded-[var(--radius-md)] border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-rose-200">
          {phase.message}
        </p>
      )}

      {phase.kind === "ready" && runs.length === 0 && <EmptyRuns />}

      {run && (
        <section ref={findingsRef} className="space-y-4 rounded-[var(--radius-md)] border border-ink-700 bg-ink-900 p-4">
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
            {/* THE EXPORT. An <a href> cannot carry the bearer token, the
                same constraint `useAuthedImage` exists for, so the file is
                fetched with the header and handed to the browser as a blob.
                READ ACCESS SUFFICES and the server says so: exporting writes
                nothing, decides nothing and records no judgement. */}
            <button
              type="button" onClick={() => void exportCrs(run.review_run_id)}
              disabled={exporting}
              className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-sm text-slateish-200 disabled:opacity-50"
            >
              {exporting ? "Preparing…" : "Export CRS - internal review copy"}
            </button>
            {/* Owner order 2f: the contractor's copy. No "AI Review Comments"
                column and no unconfirmed AI item - only confirmed comments. */}
            <button
              type="button" onClick={() => void exportCrs(run.review_run_id, "issue")}
              disabled={exporting}
              className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-sm text-slateish-200 disabled:opacity-50"
            >
              Export CRS - issue to contractor
            </button>
            {/* THE SAME SHEET, ON SCREEN. It reads from a sibling route that
                the server builds from the same builder as the file above, so
                this is the deliverable rather than a summary of it. */}
            <button
              type="button" onClick={() => void togglePreview(run.review_run_id)}
              disabled={previewing}
              aria-expanded={preview !== null}
              className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-sm text-slateish-200 disabled:opacity-50"
            >
              {previewing ? "Loading…" : preview ? "Hide CRS preview" : "Preview CRS"}
            </button>
          </div>

          {exportError && (
            <p role="alert" className="rounded-[var(--radius-sm)] border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {exportError}
            </p>
          )}

          {previewError && (
            <p role="alert" className="rounded-[var(--radius-sm)] border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {previewError}
            </p>
          )}

          {preview && <CrsPreviewSheet preview={preview} />}

          {showStandards && (
            <StandardsInScope standards={standards} missing={missingStandards} />
          )}
          {showStandards && run && (
            <StandardOverrideControl
              runId={run.review_run_id}
              decided={Boolean(run.engineer_final_code)}
              onChanged={(changed, missing) => {
                setStandards(changed);
                setMissingStandards(missing);
                void loadFindings(run.review_run_id);
                void loadRuns();
              }}
            />
          )}

          <ReviewCodePanel run={run} onDecided={() => { void loadRuns(); }} />

          <RunSummary findings={findings} />

          <ReviewNotes key={run.review_run_id} runId={run.review_run_id} />

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

      {phase.kind === "ready" && runs.length > 0 && (
        <section aria-labelledby="runs-list-title" className="space-y-3">
          <h2 id="runs-list-title" className="text-lg font-semibold text-slateish-100">
            {runs.length.toLocaleString()} {runs.length === 1 ? "run" : "runs"}
          </h2>
          {/* Owner order section 3: RUNS GROUPED PER DOCUMENT, latest first.
              The earlier runs of a document are collapsed; each says what
              changed from the one before it. */}
          <ul className="space-y-3">
            {groupRunsByDocument(runs).map((group) => (
              <li key={group.documentId} className="space-y-1">
                <RunCard
                  run={group.latest}
                  selected={group.latest.review_run_id === selectedRun}
                  onOpen={() => void openRun(group.latest.review_run_id)}
                />
                <ReviewJobControl run={group.latest} onChanged={() => { void loadRuns(); }} />
                {group.earlier.length > 0 && (
                  <details className="ps-4" data-testid="earlier-runs">
                    <summary className="cursor-pointer text-xs text-slateish-400">
                      {group.earlier.length} earlier {group.earlier.length === 1 ? "run" : "runs"} of this document
                    </summary>
                    <ul className="mt-2 space-y-2">
                      {group.earlier.map((item) => (
                        <li key={item.review_run_id} className="space-y-1">
                          <RunCard
                            run={item}
                            selected={item.review_run_id === selectedRun}
                            onOpen={() => void openRun(item.review_run_id)}
                          />
                          <ReviewJobControl run={item} onChanged={() => { void loadRuns(); }} />
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

    </main>
  );
}

/** Owner order section 3: what the review can use, before it is run. Every
 *  count carries its denominator and is about this caller's documents. */
function ReadinessStrip({ readiness, onOpenStandards }: {
  readiness: ReviewReadiness; onOpenStandards?: () => void;
}) {
  const pages = pagesReadLine(readiness);
  const missing = readiness.standards_missing;
  return (
    <div data-testid="readiness-strip"
      className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-[var(--radius-sm)] border border-ink-700 bg-ink-900 px-3 py-2 text-sm text-slateish-200">
      {pages && (
        <span>
          {pages}
          {readiness.unread_pages.length > 0 && (
            <span className="text-slateish-400"> (not read: {pageList(readiness.unread_pages)})</span>
          )}
        </span>
      )}
      {readiness.standards_cited > 0 && (
        <span>
          Standards cited: {readiness.standards_held.length} held, {missing.length} missing
          {" "}(of {readiness.standards_cited})
        </span>
      )}
      {missing.length > 0 && onOpenStandards && (
        <button type="button" onClick={onOpenStandards}
          className="rounded-[var(--radius-sm)] border border-ink-600 px-2 py-0.5 text-xs text-signal-300">
          Upload missing standards
        </button>
      )}
      {readiness.last_run_id && (
        <span className="text-slateish-400" data-testid="readiness-changes">
          {readiness.nothing_changed
            ? "Nothing changed since the last run."
            : readiness.changes.join(" · ")}
        </span>
      )}
    </div>
  );
}

/** Owner order section 3: the run's four totals in plain words, and its
 *  comments by kind. The boundary is printed with the numbers. */
function RunSummary({ findings }: { findings: ReviewFinding[] }) {
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
      </p>
    </section>
  );
}

/** Owner order section 3: the engineer's internal notes on screen,
 *  collapsed. Fetched when opened - the same notes the internal CRS copy
 *  carries on its "Review notes" sheet, from the same builder. */
function ReviewNotes({ runId }: { runId: string }) {
  const [notes, setNotes] = useState<CrsReviewNote[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <details className="text-sm" data-testid="review-notes"
      onToggle={(event) => {
        if (!(event.currentTarget as HTMLDetailsElement).open || notes !== null) return;
        void reviewsApi.previewCrs(runId).then((r) => {
          if (!r.ok) { setError(r.error.message); return; }
          setNotes(r.data.review_notes ?? []);
        });
      }}>
      <summary className="cursor-pointer text-slateish-200">Review notes - internal</summary>
      {error && <p role="alert" className="mt-1 text-xs text-rose-300">{error}</p>}
      {notes === null && !error && <p className="mt-1 text-xs text-slateish-400">Loading…</p>}
      {notes !== null && notes.length === 0 && (
        <p className="mt-1 text-xs text-slateish-400">No internal notes for this run.</p>
      )}
      {notes !== null && notes.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs text-slateish-300">
          {notes.map((n, i) => (
            <li key={i}>
              <span className="font-medium text-slateish-200">{n.note}</span>
              {n.standard ? ` - ${n.standard}` : ""}
              {n.count != null ? ` (${n.count})` : ""}
              {n.detail ? `: ${n.detail}` : ""}
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}

/** P3: cancel a queued or running review. Shown beside the card, not inside
 *  it - the card is itself a button. The server's answer is shown as given. */
function ReviewJobControl({ run, onChanged }: { run: ReviewRunSummary; onChanged: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const job = run.job;
  if (!job || !(run.status === "queued" || run.status === "running") || job.cancel_requested) return null;
  return (
    <div className="flex items-center gap-2 ps-4">
      <button type="button" className="text-xs text-rose-300 underline"
        onClick={() => {
          void reviewsApi.cancelJob(job.id).then((r) => {
            if (!r.ok) { setError(r.error.message); return; }
            setError(null);
            onChanged();
          });
        }}>
        Cancel this review
      </button>
      {error && <span role="alert" className="text-xs text-rose-300">{error}</span>}
    </div>
  );
}

function RunCard({ run, selected, onOpen }: {
  run: ReviewRunSummary; selected: boolean; onOpen: () => void;
}) {
  const completeness = completenessLine(run);
  const pageCoverage = pageCoverageLine(run);
  // 2g: the plain reason already opens "Checked N datasheet fields" when
  // the run was gated for completeness; the line is not printed twice.
  const reasonStatesCount = (run.recommended_reason ?? "").startsWith("Checked ");
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
      {run.job && (run.status === "queued" || run.status === "running") && (
        <p className="mt-1 text-xs text-signal-400" data-testid="review-progress">
          {run.status === "queued"
            ? "Waiting to start"
            : `Step ${Math.min((run.job.progress_done ?? 0) + 1, run.job.progress_total ?? 3)} of ${run.job.progress_total ?? 3}: ${run.job.progress_label ?? "working"}`}
          {run.job.cancel_requested ? " · cancellation requested, stopping at the next step" : ""}
        </p>
      )}
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
      {/* ONCE, NOT TWICE: shown whenever the reason does not already say
          how many fields were checked. The nominal estimate is under
          "Details" in the code panel, never on the card (2g). */}
      {completeness && !reasonStatesCount && (
        <p className="mt-1 text-xs text-slateish-500">{completeness}</p>
      )}
      {pageCoverage && (
        <p className="mt-1 text-xs text-slateish-500" data-testid="page-coverage">
          {pageCoverage}
        </p>
      )}
      {standardsChangeLine(run) && (
        <p className="mt-1 text-xs text-slateish-400" data-testid="standards-change">
          {standardsChangeLine(run)}
        </p>
      )}
    </button>
  );
}

/** The Comment Resolution Sheet as the workbook lays it out.
 *
 *  RECOGNISABLY THE WORKBOOK: the header block over the seven columns the
 *  client's template defines, the rows in the order the sheet numbers them,
 *  and the recommended review code on its own line underneath. Every value
 *  comes from the route verbatim - the labels are the client's wording, not
 *  this screen's, so nothing here re-types what their document says.
 */
function CrsPreviewSheet({ preview }: { preview: CrsPreview }) {
  return (
    <section
      aria-label="Comment Resolution Sheet preview"
      className="space-y-3 overflow-x-auto rounded-[var(--radius-md)] border border-ink-700 bg-ink-850 p-4"
    >
      <div className="space-y-1 text-center">
        {/* The title carries the newline the sheet merges across row 1. */}
        <p className="whitespace-pre-line text-sm font-semibold text-slateish-100">
          {preview.title}
        </p>
        <p className="text-sm font-semibold text-slateish-100">{preview.subtitle}</p>
      </div>

      <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[auto_1fr]">
        {preview.header.map((field) => (
          <div key={field.label} className="contents">
            <dt className="text-xs font-semibold text-slateish-200">{field.label}</dt>
            {/* BLANK IS BLANK. The transmittal numbers are empty because
                nobody has issued one, and a placeholder here would be this
                screen inventing provenance the document does not have. */}
            <dd className="text-xs text-slateish-300">{field.value}</dd>
          </div>
        ))}
      </dl>

      <table className="w-full min-w-[56rem] border-collapse text-xs">
        <thead>
          <tr>
            {preview.columns.map((column) => (
              <th
                key={column} scope="col"
                className="border border-ink-600 bg-ink-800 px-2 py-1 text-left font-semibold text-slateish-200"
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {preview.rows.map((row) => (
            <tr key={row.item_no}>
              <td className="border border-ink-600 px-2 py-1 text-center align-top text-slateish-300">
                {row.item_no}
              </td>
              <td className="border border-ink-600 px-2 py-1 align-top text-slateish-300">
                {row.document_name}
              </td>
              <td className="border border-ink-600 px-2 py-1 align-top text-slateish-300">
                {row.page_section}
              </td>
              <td className="whitespace-pre-line border border-ink-600 px-2 py-1 align-top text-slateish-200">
                {row.comment}
              </td>
              <td className="border border-ink-600 px-2 py-1 align-top text-slateish-300">
                {row.comment_by}
              </td>
              {/* THE CONTRACTOR'S TWO COLUMNS, EMPTY AND PRESENT. They are
                  theirs to fill in the file they receive; dropping them here
                  would hide the shape of the document, and writing anything
                  in them would put words in their mouth. */}
              <td className="border border-ink-600 px-2 py-1 align-top" />
              <td className="border border-ink-600 px-2 py-1 align-top" />
              {/* Owner order 2f: the last column, internal copy only. */}
              {preview.columns.length > 7 && (
                <td className="whitespace-pre-line border border-ink-600 px-2 py-1 align-top text-slateish-200">
                  {row.ai_review_comment}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>

      {/* Owner order 2f: the engineer's internal notes, on their own sheet -
          never in COMPANY Comments, and not in the contractor's copy. */}
      {(preview.review_notes ?? []).length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-slateish-200">
            Review notes - internal ({(preview.review_notes ?? []).length})
          </summary>
          <table className="mt-2 w-full border-collapse">
            <thead>
              <tr>
                {["Note", "Standard", "Count", "Detail"].map((h) => (
                  <th key={h} scope="col" className="border border-ink-600 bg-ink-800 px-2 py-1 text-left font-semibold text-slateish-200">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(preview.review_notes ?? []).map((n, i) => (
                <tr key={i}>
                  <td className="border border-ink-600 px-2 py-1 align-top text-slateish-200">{n.note}</td>
                  <td className="border border-ink-600 px-2 py-1 align-top text-slateish-300">{n.standard}</td>
                  <td className="border border-ink-600 px-2 py-1 align-top text-slateish-300">{n.count ?? ""}</td>
                  <td className="border border-ink-600 px-2 py-1 align-top text-slateish-300">{n.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      {/* NULL RENDERS AS NOTHING. A run with no recommendation shows no line
          at all rather than an empty or placeholder code. */}
      {preview.recommended_code && (
        <p className="text-xs text-slateish-200">
          <span className="font-semibold">{preview.recommended_code_label}</span>{" "}
          <span className="font-semibold">{preview.recommended_code}</span>
          {preview.recommended_code_reason
            ? <span className="text-slateish-400"> — {preview.recommended_code_reason}</span>
            : null}
        </p>
      )}
      {/* B10: whether an engineer decided the code, or it is still the AI's. */}
      {preview.recommended_code && preview.recommended_code_status && (
        <p className="text-xs text-warn-500" data-testid="crs-code-status">
          {preview.recommended_code_status}
        </p>
      )}
    </section>
  );
}

function StandardsInScope({ standards, missing }: {
  standards: ReviewRunStandard[] | null; missing: ReviewRunMissingReference[];
}) {
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
