/**
 * The CRS-first Sheet (order 95 piece 2, spec 1.2; Part of #967).
 *
 * The comment sheet IS the screen: the client's seven columns, one row per
 * comment, three tier words (Comment / Needs you / Met), Keep / Edit
 * wording / Remove per row, Accept all remaining with one-step undo, Sign
 * and export wired to the existing CRS export. Served at
 * `/review/<run>/crs-sheet` and, since the owner's yes (order 115,
 * `routing.CRS_SHEET_IS_DEFAULT`), at `/review/<run>`; the card view is at
 * `/review/<run>/cards`.
 *
 * NOTHING HERE CHANGES A VERDICT. Tiers come from the server's run summary
 * (order 95 piece 1, #1111: `GET /api/reviews/runs/{id}/summary`), the one
 * place that decides them; when it does not answer (a server without the
 * route, or a failed read) the screen falls back to `crs/tiers.ts`, the same
 * rules, and says so in one small line. Display only; the export is the server's existing route and the server still
 * refuses the contractor's copy while anything is open.
 *
 * Order 95 piece 6c: decisions stay on screen until one "Save decisions"
 * press (`saveCrsDecisions`); Sign and export wait, and leaving warns,
 * while any are not saved.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, reviews as reviewsApi } from "../api/client";
import type { DocumentRecord, ReviewFinding, ReviewRunSummary, ReviewRunTierSummary } from "../types/api";
import { downloadCrs } from "../components/review/downloadCrs";
import { progressLine, runStatusLabel } from "../components/review/reviewFormat";
import type { StandardsState } from "../components/review/panels/BehindTheScenes";
import { ReviewJobControl } from "../components/review/panels/ReviewJobControl";
import { CrsEvidenceDrawer } from "../components/review/crs/CrsEvidenceDrawer";
import { CrsFooter } from "../components/review/crs/CrsFooter";
import { CrsHeader } from "../components/review/crs/CrsHeader";
import { CrsTable } from "../components/review/crs/CrsTable";
import type { RowMode } from "../components/review/crs/CrsRow";
import {
  type CrsRow, type Depth, buildCrsRows, headlineFieldsOf, rowCounts, splitRejected, spotCheckKeys, visibleRows,
} from "../components/review/crs/crsRows";
import { commentPages, firstRowOnPage, stepRow } from "../components/review/crs/evidenceNav";
import { runFactsOf, serverTiersOf } from "../components/review/crs/tiers";
import { saveCrsDecisions } from "../components/review/crs/saveCrsDecisions";
import { useCrsDecisions } from "../components/review/crs/useCrsDecisions";
import { useCrsKeys } from "../components/review/crs/useCrsKeys";

type Load = { kind: "loading" } | { kind: "ready" } | { kind: "error"; message: string };
type Sign = { busy: boolean; message: string | null; error: string | null };
type Save = Sign;

const LEAVE_WARNING = "Some decisions on this sheet are not saved yet. Leave without saving them?";

export interface CrsSheetViewProps {
  runId: string;
  onBack: () => void;
  onOpenCards: () => void;
}

function useRunData(runId: string) {
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [run, setRun] = useState<ReviewRunSummary | null>(null);
  const [findings, setFindings] = useState<ReviewFinding[]>([]);
  const [standardsState, setStandardsState] = useState<StandardsState>({ standards: null, missing: [], error: null });
  const [submittal, setSubmittal] = useState<DocumentRecord | null>(null);
  // The server's tiers (#1111). Null = it did not answer (404 on a server
  // without the route, or any failure): the screen's own tiers stand in.
  const [summary, setSummary] = useState<ReviewRunTierSummary | null>(null);

  // Order 117 item 6: only the newest load may paint. A slow answer for the
  // run the reader just left, or a 3-second poll overtaken by the next one,
  // must never replace what is on screen with an older or another run's data.
  const latest = useRef(0);
  useEffect(() => () => { latest.current += 1; }, []);
  const refresh = useCallback(async () => {
    const mine = ++latest.current;
    const [runs, listed, stds, sum] = await Promise.all([
      reviewsApi.reviewRun(runId), reviewsApi.list({ review_run_id: runId }), reviewsApi.reviewRunStandards(runId),
      reviewsApi.reviewRunSummary(runId),
    ]);
    if (mine !== latest.current) return;
    if (!runs.ok) { setLoad({ kind: "error", message: runs.error.message }); return; }
    const found = runs.data;
    if (!found) { setLoad({ kind: "error", message: "This review run could not be found." }); return; }
    if (!listed.ok) { setLoad({ kind: "error", message: listed.error.message }); return; }
    setRun(found);
    setFindings(listed.data.findings);
    setSummary(sum.ok ? sum.data : null);
    setStandardsState(stds.ok
      ? { standards: stds.data.standards, missing: stds.data.missing_references ?? [], error: null }
      : { standards: null, missing: [], error: stds.error.message });
    setLoad({ kind: "ready" });
  }, [runId]);
  useEffect(() => { void refresh(); }, [refresh]);

  const submittalId = run?.submittal_document_id ?? null;
  useEffect(() => {
    if (!submittalId) return;
    let current = true;
    void api.document(submittalId).then((r) => { if (current) setSubmittal(r.ok ? r.data : null); });
    return () => { current = false; };
  }, [submittalId]);

  const active = run?.status === "queued" || run?.status === "running";
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => { void refresh(); }, 3000);
    return () => clearInterval(timer);
  }, [active, refresh]);

  return { load, run, findings, standardsState, submittal, summary, active, refresh };
}

/** Sign and export = the existing CRS issue route (the same one the card
 *  view's Send uses; the server still refuses it while anything is open);
 *  the working copy = the internal export. No new endpoint. */
function useExport(runId: string, refresh: () => Promise<void>) {
  const [sign, setSign] = useState<Sign>({ busy: false, message: null, error: null });
  async function exportSheet(copy: "internal" | "issue") {
    setSign({ busy: true, message: null, error: null });
    const message = await downloadCrs(runId, copy);
    if (message) { setSign({ busy: false, message: null, error: message }); return; }
    setSign({
      busy: false, error: null,
      message: copy === "issue" ? "Signed and exported. The issued copy was downloaded and kept on record." : "Working copy downloaded. It is not signed.",
    });
    if (copy === "issue") void refresh();
  }
  return { sign, exportSheet };
}

function RunNotReady({ run, active, onBack, onChanged }: { run: ReviewRunSummary; active: boolean; onBack: () => void; onChanged: () => void }) {
  return (
    <section className="mx-auto w-full max-w-7xl space-y-3" aria-labelledby="crs-title">
      <h1 id="crs-title" className="text-2xl font-semibold text-slateish-100">{run.submittal_filename ?? "Review"}</h1>
      {active ? (
        <>
          <p aria-live="polite" className="text-slateish-300" data-testid="review-progress">
            {run.status === "queued" ? "Waiting to start"
              : run.job ? progressLine(run.job.progress_done, run.job.progress_total, run.job.progress_label) : runStatusLabel(run.status)}
          </p>
          <ReviewJobControl run={run} onChanged={onChanged} />
        </>
      ) : (
        <p role="alert" className="text-danger-500">This review failed{run.failure_reason ? `: ${run.failure_reason}` : "."}</p>
      )}
      <button type="button" onClick={onBack} className="text-sm text-signal-300 underline-offset-2 hover:underline">← Reviews</button>
    </section>
  );
}

/** Order 95 piece 4: the drawer moves along the rows the engineer sees. A
 *  row not in that list (filtered out meanwhile) gets no position. */
function drawerNav(shown: CrsRow[], row: CrsRow, open: (row: CrsRow) => void) {
  const index = shown.findIndex((r) => r.key === row.key);
  if (index < 0) return undefined;
  const prev = stepRow(shown, row.key, -1);
  const next = stepRow(shown, row.key, 1);
  return { index, total: shown.length, onPrev: prev ? () => open(prev) : null, onNext: next ? () => open(next) : null };
}

/** Order 117: where the keyboard goes back to when the drawer closes. The
 *  element that opened it, when that is outside the drawer; the row's own
 *  evidence button when the click landed on the row itself (a row cannot
 *  hold focus); and the earlier target when the drawer is already open. */
function returnTarget(prev: HTMLElement | null, rowKey: string): HTMLElement | null {
  const active = document.activeElement as HTMLElement | null;
  if (active?.closest?.("[role=dialog]")) return prev;
  if (active && active !== document.body) return active;
  const tr = Array.from(document.querySelectorAll<HTMLElement>("tr[data-row-key]")).find((el) => el.dataset.rowKey === rowKey);
  return tr?.querySelector<HTMLElement>("button") ?? prev;
}

export function CrsSheetView({ runId, onBack, onOpenCards }: CrsSheetViewProps) {
  const { load, run, findings, standardsState, submittal, summary, active, refresh } = useRunData(runId);
  const [depth, setDepth] = useState<Depth>("standard");
  const [showMet, setShowMet] = useState(false);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [drawerKey, setDrawerKey] = useState<string | null>(null);
  const [mode, setMode] = useState<{ key: string; kind: RowMode } | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [kept, setKept] = useState<number | null>(null);
  const { sign, exportSheet } = useExport(runId, refresh);
  const [returnTo, setReturnTo] = useState<HTMLElement | null>(null);
  const decisions = useCrsDecisions();
  const [save, setSave] = useState<Save>({ busy: false, message: null, error: null });
  const unsavedCount = decisions.unsaved.length;
  useEffect(() => {
    if (unsavedCount === 0) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = LEAVE_WARNING; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [unsavedCount]);

  const standardNames = useMemo(() => new Map(
    (standardsState.standards ?? []).filter((s) => s.filename).map((s) => [s.standard_document_id, s.filename as string])),
  [standardsState.standards]);
  const facts = useMemo(() => runFactsOf(run, standardsState.standards, standardsState.missing), [run, standardsState]);
  const server = useMemo(() => (summary ? serverTiersOf(summary.rows) : null), [summary]);
  const rows = useMemo(() => buildCrsRows(findings, facts, standardNames, server), [findings, facts, standardNames, server]);
  const counts = useMemo(() => rowCounts(rows), [rows]);
  // Order 112: the headline counts the table's rows (their tiers are the
  // server's when it sent them) and names the findings behind the comment
  // rows second; its stored fields are the server's when it sent them.
  const headlineCounts = counts;
  const findingsInComments = useMemo(
    () => rows.filter((r) => r.tier.tier !== "A").reduce((n, r) => n + r.findings.length, 0), [rows]);
  const headlineFields = useMemo(() => (run ? headlineFieldsOf(run, summary?.how_reviewed ?? null) : undefined), [run, summary]);
  const rejected = useMemo(() => summary?.counts.removed ?? splitRejected(findings).rejected, [summary, findings]);
  const spot = useMemo(() => spotCheckKeys(rows, runId), [rows, runId]);
  const shown = useMemo(() => visibleRows(rows, depth, showMet, spot), [rows, depth, showMet, spot]);
  const unopened = rows.filter((r) => r.tier.tier === "C" && !decisions.state.opened[r.key]);
  const drawerRow = rows.find((r) => r.key === drawerKey) ?? null;
  const pagesWithComments = useMemo(() => commentPages(shown), [shown]);

  // Order 117: these stay the same between renders, so the memoised rows
  // and the keyboard listener are not rebuilt on every key press.
  const { markOpened, keep } = decisions;
  const openEvidence = useCallback((row: CrsRow) => {
    setReturnTo((prev) => returnTarget(prev, row.key));
    markOpened(row.key);
    setDrawerKey(row.key);
  }, [markOpened]);
  const selectRow = useCallback((row: CrsRow) => setSelectedKey(row.key), []);
  const changeMode = useCallback((key: string, kind: RowMode) => setMode(kind ? { key, kind } : null), []);

  const keyActions = useMemo(() => ({
    select: (row: CrsRow) => setSelectedKey(row.key),
    edit: (row: CrsRow) => { if (row.tier.tier !== "A") setMode({ key: row.key, kind: "edit" }); },
    remove: (row: CrsRow) => { if (row.tier.tier !== "A") setMode({ key: row.key, kind: "remove" }); },
    keep: (row: CrsRow) => { if (row.tier.tier !== "A") keep(row.key); },
  }), [keep]);
  useCrsKeys(shown, selectedKey, keyActions, drawerRow === null);

  if (load.kind === "loading") return <p className="text-slateish-300">Loading the sheet…</p>;
  if (load.kind === "error" || !run) {
    return <p role="alert" className="rounded-[var(--radius-md)] border border-danger-500/40 bg-danger-500/10 px-4 py-3 text-danger-500">{load.kind === "error" ? load.message : "This review run could not be found."}</p>;
  }
  if (active || run.status === "failed") return <RunNotReady run={run} active={active} onBack={onBack} onChanged={() => void refresh()} />;

  const remaining = decisions.remaining(rows).length;
  const saveDecisions = async () => {
    setSave({ busy: true, message: null, error: null });
    const outcome = await saveCrsDecisions(runId, rows, decisions.state.decisions, decisions.unsaved);
    decisions.markSaved(outcome.saved);
    setSave({
      busy: false,
      message: outcome.saved.length > 0 ? `${outcome.saved.length} ${outcome.saved.length === 1 ? "decision" : "decisions"} saved to the record.` : null,
      error: outcome.failed.length > 0
        ? `${outcome.failed.length} not saved: ${outcome.failed.map((f) => f.message).join("; ")}`
        : null,
    });
    if (outcome.wrote) void refresh();  // a half-saved row too: its next save sends only the rest
  };
  const leave = () => { if (unsavedCount === 0 || window.confirm(LEAVE_WARNING)) onBack(); };
  return (
    <section className="mx-auto w-full max-w-7xl space-y-5" aria-labelledby="crs-title">
      <CrsHeader
        run={run} submittal={submittal} counts={headlineCounts} headlineFields={headlineFields} findingsInComments={findingsInComments}
        tierSource={summary ? "server" : "screen"} unopened={unopened} remaining={remaining}
        save={{ unsaved: unsavedCount, busy: save.busy, onSave: () => void saveDecisions(), message: save.message, error: save.error }}
        acceptAll={{
          confirming, kept, canUndo: decisions.canUndo,
          onAsk: () => setConfirming(true), onCancel: () => setConfirming(false),
          onConfirm: () => { setKept(decisions.acceptAll(rows)); setConfirming(false); },
          onUndo: () => { decisions.undo(); setKept(null); },
        }}
        sign={{ busy: sign.busy, message: sign.message, error: sign.error, onSign: () => void exportSheet("issue"), onWorkingCopy: () => void exportSheet("internal") }}
        onBack={leave}
      />
      <CrsTable
        rows={shown} allRows={rows} counts={counts} depth={depth} onDepth={setDepth} showMet={showMet} onShowMet={setShowMet}
        spot={spot} selectedKey={selectedKey} onSelect={selectRow} onOpenEvidence={openEvidence}
        mode={mode} onMode={changeMode} decisions={decisions}
        clausesNotApplicable={run.requirement_split?.does_not_apply ?? null}
      />
      <CrsFooter run={run} counts={counts} standards={standardsState.standards} missing={standardsState.missing} standardsError={standardsState.error} rejected={rejected} />
      {drawerRow && (
        <CrsEvidenceDrawer row={drawerRow} runId={runId} standardNames={standardNames} returnTo={returnTo}
          onClose={() => setDrawerKey(null)} onOpenCards={onOpenCards}
          nav={drawerNav(shown, drawerRow, (row) => { decisions.markOpened(row.key); setDrawerKey(row.key); })}
          pager={{
            pageCount: submittal?.page_count ?? null, commentPages: pagesWithComments,
            onPage: (page) => {
              const row = firstRowOnPage(shown, page);
              if (row) { decisions.markOpened(row.key); setDrawerKey(row.key); }
              return row !== null;
            },
          }} />
      )}
    </section>
  );
}
