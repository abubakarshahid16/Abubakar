/**
 * OWNER: builder A. The one-screen review workspace (SPEC.md sections 3 and 7).
 *
 * Composes: B's ActionBar + SheetCountsLine + SignOffPanel, C's
 * WorkspaceSheet (with its evidence drawer), D's ReviewAgainButton, the
 * existing HowReviewedView and behind-the-scenes panels, all under one tab
 * strip. Every count comes from ONE `computeReviewNumbers` result. The
 * reader's place (tab, open row, panel) lives in the address; this
 * component only reads `location` and asks for changes via
 * `onLocationChange`, so a refresh reopens the same place.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import type { ReviewRunMissingReference, ReviewRunStandard, ReviewRunSummary } from "../../../types/api";
import { HowReviewedView } from "../../../views/HowReviewedView";
import { progressLine, runStatusLabel } from "../reviewFormat";
import { BehindTheScenes } from "../panels/BehindTheScenes";
import { ReviewJobControl } from "../panels/ReviewJobControl";
import { useCrsDecisions } from "../crs/useCrsDecisions";
import { useIssueGate } from "../crs/issueGate";
import { ActionBar } from "./ActionBar";
import { actionSteps, computeReviewNumbers } from "./numbers";
import { ReviewAgainButton } from "./ReviewAgainButton";
import { SheetCountsLine } from "./SheetCountsLine";
import { SignOffPanel } from "./SignOffPanel";
import { useSignOff } from "./useSignOff";
import { useWorkspaceRun } from "./useWorkspaceRun";
import { WorkspaceSheet } from "./WorkspaceSheet";
import { WorkspaceTabs } from "./WorkspaceTabs";
import {
  LEAVE_WARNING, WORKSPACE_TABS, type ActionStepId, type ReviewWorkspaceProps, type WorkspaceLocation, type WorkspaceTab,
} from "./contract";

/** The behind-the-scenes panels that are tabs here. */
const PANEL_TABS: readonly WorkspaceTab[] = ["findings", "standards", "steps", "numbers"];

function isTab(value: string | undefined): value is WorkspaceTab {
  return value !== undefined && (WORKSPACE_TABS as readonly string[]).includes(value);
}

/** Queued / running / failed: the same states and words CrsSheetView shows.
 *  A failed run also offers "Review again", so a document whose last review
 *  failed is never a dead end. */
function RunNotReady({ run, active, onBack, onChanged, onOpenRun, openRun, mayLeave }: {
  run: ReviewRunSummary; active: boolean; onBack: () => void; onChanged: () => void;
  onOpenRun: (runId: string) => void; openRun: (runId: string) => void; mayLeave: () => boolean;
}) {
  return (
    <section className="mx-auto w-full max-w-7xl space-y-3" aria-labelledby="ws-title" data-testid="review-workspace">
      <h1 id="ws-title" className="text-2xl font-semibold text-slateish-100">{run.submittal_filename ?? "Review"}</h1>
      {active ? (
        <>
          <p aria-live="polite" className="text-slateish-300" data-testid="review-progress">
            {run.status === "queued" ? "Waiting to start"
              : run.job ? progressLine(run.job.progress_done, run.job.progress_total, run.job.progress_label) : runStatusLabel(run.status)}
          </p>
          <ReviewJobControl run={run} onChanged={onChanged} />
        </>
      ) : (
        <>
          <p role="alert" className="text-danger-500">This review failed{run.failure_reason ? `: ${run.failure_reason}` : "."}</p>
          {run.submittal_document_id && (
            <ReviewAgainButton documentId={run.submittal_document_id} filename={run.submittal_filename}
              mayStart={mayLeave} onStarted={onOpenRun} onOpenRun={openRun} />
          )}
        </>
      )}
      <button type="button" onClick={onBack} className="text-sm text-signal-300 underline-offset-2 hover:underline">← Reviews</button>
    </section>
  );
}

export function ReviewWorkspace({ location, onLocationChange, onBack, onOpenRun, onUnsavedChange }: ReviewWorkspaceProps) {
  const { runId } = location;
  const data = useWorkspaceRun(runId);
  const { load, run, findings, rows, standardsState, missingStandardIds, standardNames, submittal, summary, readiness, active, refresh, refreshError } = data;
  const decisions = useCrsDecisions();
  // The issue gate, read exactly as the comment sheet reads it (again
  // whenever the run or its findings are): what the server still wants
  // before the contractor's copy.
  const gateVersion = useMemo(() => ({ run, findings }), [run, findings]);
  const issueGate = useIssueGate(runId, gateVersion);
  // "Check unread pages" leads to the tick boxes in "Before you sign".
  const [pagesAsked, setPagesAsked] = useState(0);
  // A count clicked inside the steps panel narrows the findings panel (#791),
  // exactly as on the card view's behind-the-scenes pages.
  const [focusStatus, setFocusStatus] = useState<string | null>(null);

  const unsavedCount = decisions.unsaved.length;
  useEffect(() => {
    if (unsavedCount === 0) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = LEAVE_WARNING; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [unsavedCount]);
  useEffect(() => { onUnsavedChange?.(unsavedCount); }, [unsavedCount, onUnsavedChange]);
  // Clear the count when this screen goes away, so the app does not ask
  // about decisions that no longer exist.
  useEffect(() => () => onUnsavedChange?.(0), [onUnsavedChange]);

  // Every move away inside the app asks first, as CrsSheetView's `leave`
  // does: the decisions live only in this screen until they are saved.
  const mayLeave = useCallback(() => unsavedCount === 0 || window.confirm(LEAVE_WARNING), [unsavedCount]);
  const leave = useCallback(() => { if (mayLeave()) onBack(); }, [mayLeave, onBack]);
  const openRun = useCallback((id: string) => { if (mayLeave()) onOpenRun(id); }, [mayLeave, onOpenRun]);
  // "Review again" asks before it starts anything (mayStart), so it opens
  // the new run without asking a second time.

  // Keep the document in the address once the run names it, so a refresh
  // before the run loads still knows the document.
  const runDocumentId = run?.submittal_document_id ?? null;
  useEffect(() => {
    if (runDocumentId && location.documentId !== runDocumentId) onLocationChange({ ...location, documentId: runDocumentId });
  }, [runDocumentId, location, onLocationChange]);

  const numbers = useMemo(() => (run ? computeReviewNumbers({
    run, findings, rows, summary,
    missingStandards: missingStandardIds,
    readiness, decisions: decisions.state, unsaved: decisions.unsaved, gate: issueGate.gate,
  }) : null), [run, findings, rows, summary, missingStandardIds, readiness, decisions.state, decisions.unsaved, issueGate.gate]);
  const steps = useMemo(() => (numbers ? actionSteps(numbers) : []), [numbers]);
  const signOff = useSignOff({ runId, rows, decisions, refresh, numbers });

  const tabNow = location.tab;
  useEffect(() => {
    if (pagesAsked === 0 || tabNow !== "sheet") return;
    const box = document.querySelector<HTMLElement>('[data-testid="sign-pages"]');
    box?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }, [pagesAsked, tabNow]);

  const go = (patch: Partial<WorkspaceLocation>) => onLocationChange({ ...location, ...patch });
  const onTab = (tab: WorkspaceTab) => go({ tab });
  const openRowKey = location.panel === "evidence" ? location.row : null;
  const onOpenRow = (rowKey: string | null) => go({ row: rowKey, panel: rowKey ? "evidence" : null });

  const onAction = (id: ActionStepId) => {
    if (id === "standards") go({ tab: "standards" });
    else if (id === "decide") {
      const first = numbers?.undecidedKeys[0] ?? null;
      go({ tab: "sheet", row: first, panel: first ? "evidence" : null });
    }
    else if (id === "pages") {
      // The ActionBar lists the pages and offers "read again"; the ticks
      // live in "Before you sign" under the sheet, so go there.
      go({ tab: "sheet" });
      setPagesAsked((n) => n + 1);
    }
    // "sign" calls signOff.sign() inside the ActionBar.
  };

  // The behind-the-scenes panels carry their own small nav; inside the
  // workspace it moves between tabs. "Back to the sheet" (no panel) and any
  // panel that is not a tab here (the old "crs" page) land on the sheet.
  const onOpenPanel = (panel?: string) => {
    if (!panel) setFocusStatus(null);
    go({ tab: isTab(panel) && PANEL_TABS.includes(panel) ? panel : "sheet" });
  };

  if (load.kind === "loading") return <p className="text-slateish-300" data-testid="review-workspace">Loading the sheet…</p>;
  if (load.kind === "error" || !run || !numbers) {
    return (
      <p role="alert" data-testid="review-workspace" className="rounded-[var(--radius-md)] border border-danger-500/40 bg-danger-500/10 px-4 py-3 text-danger-500">
        {load.kind === "error" ? load.message : "This review run could not be found."}
      </p>
    );
  }
  const refreshLine = refreshError
    ? <p role="status" data-testid="ws-refresh-error" className="text-sm text-slateish-400">{refreshError}</p>
    : null;
  if (active || run.status === "failed") {
    return (
      <>
        <RunNotReady run={run} active={active} onBack={leave} onChanged={() => void refresh()} onOpenRun={onOpenRun} openRun={openRun} mayLeave={mayLeave} />
        {refreshLine}
      </>
    );
  }

  const tab = location.tab;
  return (
    <section
      className="mx-auto w-full max-w-7xl space-y-4" aria-labelledby="ws-title"
      data-testid="review-workspace" data-run={runId}
    >
      <header className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={leave} className="text-sm text-signal-300 underline-offset-2 hover:underline">← Reviews</button>
        <h1 id="ws-title" className="min-w-0 flex-1 truncate text-2xl font-semibold text-slateish-100">
          {run.submittal_filename ?? "Review"}
        </h1>
        {run.submittal_document_id && (
          <ReviewAgainButton documentId={run.submittal_document_id} filename={run.submittal_filename}
            mayStart={mayLeave} onStarted={onOpenRun} onOpenRun={openRun} />
        )}
      </header>

      <ActionBar run={run} numbers={numbers} steps={steps} onAction={onAction} signOff={signOff} />
      {refreshLine}

      <WorkspaceTabs tab={tab} onTab={onTab}>
        {tab === "sheet" && (
          <div className="space-y-2">
            <SheetCountsLine numbers={numbers} />
            <WorkspaceSheet
              runId={runId} run={run} rows={rows} submittal={submittal} standardNames={standardNames}
              decisions={decisions} openRowKey={openRowKey} onOpenRow={onOpenRow} numbers={numbers}
              footer={(
                <SignOffPanel numbers={numbers} signOff={signOff} run={run} rows={rows} gate={issueGate}
                  onRunChanged={() => void refresh()} onJump={(row) => onOpenRow(row.key)} />
              )}
            />
          </div>
        )}
        {tab === "how" && (
          <HowReviewedView
            key={runId} runId={runId}
            onBack={() => onTab("sheet")}
            onOpenRun={openRun}
            onOpenSteps={() => onTab("steps")}
          />
        )}
        {PANEL_TABS.includes(tab) && (
          <BehindTheScenes
            panel={tab} run={run} findings={findings} documents={submittal ? [submittal] : []}
            standardsState={standardsState} focusStatus={focusStatus}
            onOpenPanel={onOpenPanel}
            onFocusStatus={setFocusStatus}
            onStandardsChanged={(_changed: ReviewRunStandard[], _missing: ReviewRunMissingReference[]) => {
              // useWorkspaceRun owns the standards; read them again rather
              // than keep a second copy here.
              void refresh();
            }}
            onChanged={() => void refresh()}
          />
        )}
      </WorkspaceTabs>
    </section>
  );
}
