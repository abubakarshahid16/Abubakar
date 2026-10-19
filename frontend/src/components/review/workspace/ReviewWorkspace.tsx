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
 *
 * v2.1 (builder B): decisions save by themselves (decide/useAutosave), with
 * "Keep all remaining comments" and its Undo above the sheet; Sign opens the
 * preview-and-confirm step (sign/SignConfirm) instead of issuing at once;
 * "Upload missing standards" opens the missing standards panel; the
 * contractor's copy and replies are a tab; the honesty footer sits under the
 * sheet; and the page makes room for the open evidence panel.
 *
 * v2.1 (integrator): ONE sign flow. Sign (bar or sign-off panel) -> the
 * checks in useSignOff.sign -> the one SignConfirm below (always mounted,
 * open while useSignOff says so) -> "Issue to contractor" ->
 * issueConfirmed -> issueContractorCopy. Leaving asks through the app's one
 * in-page guard (`leaveGuard`, useLeaveGuard), never window.confirm. Every
 * "Review again" (header and missing standards panel) uses the same rule,
 * useReviewAgain. None of them is handed the runs list this screen read on
 * opening: a final code recorded or a signature made since would make that
 * list say "nothing decided" and start a fresh review without asking, so
 * each press reads the document's latest review again (loadPriorDecision).
 *
 * v2.1 round 2 (F1):
 *  - A signed review is READ ONLY: no decision panel, no Keep / Edit /
 *    Remove, no table keys, no "Keep all remaining", and automatic saving is
 *    off (`disabled: numbers.signed`). The footer says "Signed on <date>"
 *    and the sign-off offers "Download the issued copy".
 *  - Any run that did not complete (failed, cancelled, or a status this
 *    screen does not know) shows a plain sentence and a "New review" button,
 *    never an empty sheet.
 *  - Opening an older review when a newer review of the same document exists
 *    says so with a link to the newer one, and Sign asks first.
 *  - "Review again" is not offered to someone who is not an administrator.
 */
import { type ReactNode, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import type { ReviewRunMissingReference, ReviewRunStandard, ReviewRunSummary } from "../../../types/api";
import { HowReviewedView } from "../../../views/HowReviewedView";
import { progressLine, runStatusLabel } from "../reviewFormat";
import { BehindTheScenes } from "../panels/BehindTheScenes";
import { ReviewJobControl } from "../panels/ReviewJobControl";
import { useCrsDecisions } from "../crs/useCrsDecisions";
import { useIssueGate } from "../crs/issueGate";
import { CrsFooter } from "../crs/CrsFooter";
import { CrsTabPanel } from "./crs/CrsTabPanel";
import { KeepAllRemaining } from "./decide/KeepAllRemaining";
import { RestoreDraftLine } from "./decide/RestoreDraftLine";
import { useAutosave } from "./decide/useAutosave";
import { useSigner } from "./decide/useSignerName";
import { SignConfirm } from "./sign/SignConfirm";
import { MissingStandardsPanel } from "./standards/MissingStandardsPanel";
import { ActionBar } from "./ActionBar";
import { actionSteps, computeReviewNumbers } from "./numbers";
import { ReviewAgainButton, useReviewAgain } from "./ReviewAgainButton";
import { LeaveConfirm } from "./LeaveConfirm";
import { useLeaveGuard } from "./useLeaveGuard";
import { SheetCountsLine } from "./SheetCountsLine";
import { SignOffPanel } from "./SignOffPanel";
import { useSignOff } from "./useSignOff";
import { useViewMode } from "./useViewMode";
import { ViewModeSwitch } from "./ViewModeSwitch";
import { useWorkspaceRun } from "./useWorkspaceRun";
import { WorkspaceSheet } from "./WorkspaceSheet";
import { PastReviewsButton } from "./PastReviewsButton";
import { WorkspaceTabs } from "./WorkspaceTabs";
import {
  LEAVE_WARNING, WORKSPACE_TABS, type ActionStep, type ActionStepId, type ReviewNumbers, type ReviewWorkspaceProps,
  type SignOff, type WorkspaceLocation, type WorkspaceTab,
} from "./contract";

/** How long "Undo" stays on offer after "Keep all remaining comments";
 *  those decisions save once it is gone. */
export const UNDO_WINDOW_MS = 10_000;

/** W4 / D2: while the evidence panel is open on a wide screen, the page
 *  keeps the panel's width free on the right, so the table's buttons, the
 *  bar's Save now and Sign are never under it. */
export const PANEL_ROOM = "lg:pr-[37rem]";

/** The behind-the-scenes panels that are tabs here. */
const PANEL_TABS: readonly WorkspaceTab[] = ["findings", "standards", "steps", "numbers"];

function isTab(value: string | undefined): value is WorkspaceTab {
  return value !== undefined && (WORKSPACE_TABS as readonly string[]).includes(value);
}

/** v2.2: remembers that the reader hid the one-line help (this browser). */
export const REVIEW_HELP_HIDDEN_KEY = "rag.workspace.reviewHelpHidden";

function readHelpHidden(): boolean {
  try {
    return localStorage.getItem(REVIEW_HELP_HIDDEN_KEY) === "1";
  } catch {
    return false;
  }
}

function writeHelpHidden(): void {
  try {
    localStorage.setItem(REVIEW_HELP_HIDDEN_KEY, "1");
  } catch {
    /* storage unavailable: hidden for this page only */
  }
}

/** v2.2: the one-line help under the title, in plain words. Every fact
 *  comes from the page's one `computeReviewNumbers` result and its
 *  `actionSteps`; nothing is counted here. Null when no line is true (for
 *  example the final code is not known yet, or Sign still waits for pages
 *  or standards): no line rather than a wrong one. */
export function reviewHelpWords(numbers: ReviewNumbers, steps: readonly ActionStep[]): string | null {
  if (numbers.signed) {
    return "This review is signed. The CRS was issued; you can still read it and import the contractor's replies.";
  }
  if (numbers.undecided > 0) {
    return "Go through each comment: Keep it, Edit the wording, or Remove it. Your choices save by themselves.";
  }
  if (numbers.finalCodeRecorded === false) {
    return "All comments are decided. Record the final code, then preview the CRS and sign.";
  }
  if (steps.find((s) => s.id === "sign")?.enabled) {
    return "Everything is done. Preview the CRS, then sign to issue it to the contractor.";
  }
  return null;
}

function ReviewHelpLine({ words }: { words: string | null }) {
  const [hidden, setHidden] = useState(readHelpHidden);
  if (hidden || !words) return null;
  return (
    <p data-testid="ws-review-help" className="flex flex-wrap items-baseline gap-2 text-sm text-slateish-300">
      <span>{words}</span>
      <button type="button" aria-label="Hide this help" onClick={() => { writeHelpHidden(); setHidden(true); }}
        className="text-xs text-signal-300 underline-offset-2 hover:underline">
        Hide
      </button>
    </p>
  );
}

/** Why a review that is not running has no sheet, in one plain sentence. */
export function notFinishedWords(run: ReviewRunSummary): string {
  if (run.status === "failed") return `This review failed${run.failure_reason ? `: ${run.failure_reason}` : "."}`;
  if (run.status === "cancelled") return "This review was cancelled before it finished, so there is no sheet to show.";
  return "This review did not finish, so there is no sheet to show.";
}

/** "15 Oct 2026" style date for the newer-review line; "" when not known. */
function dayOf(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString();
}

/** Queued / running / anything else that is not "completed": the same
 *  states and words CrsSheetView shows. A run that did not finish (failed,
 *  cancelled or unknown) says why in plain words and offers "New review",
 *  so a document whose last review did not finish is never a dead end. */
function RunNotReady({ run, active, onBack, onChanged, onOpenRun, openRun, beforeStart, isAdmin }: {
  run: ReviewRunSummary; active: boolean; onBack: () => void; onChanged: () => void;
  onOpenRun: (runId: string) => void; openRun: (runId: string) => void; beforeStart: (go: () => void) => void;
  isAdmin?: boolean;
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
          <p role="alert" data-testid="ws-not-finished" className="text-danger-500">{notFinishedWords(run)}</p>
          {run.submittal_document_id && isAdmin !== false && (
            <ReviewAgainButton documentId={run.submittal_document_id} filename={run.submittal_filename} label="New review"
              beforeStart={beforeStart} onStarted={onOpenRun} onOpenRun={openRun} />
          )}
          {run.submittal_document_id && isAdmin === false && (
            <p className="text-sm text-slateish-400">Only an administrator can start a review.</p>
          )}
        </>
      )}
      <button type="button" onClick={onBack} className="text-sm text-signal-300 underline-offset-2 hover:underline">← Reviews</button>
    </section>
  );
}

/** v2.2 round 2: in Simple view a part a manager rarely needs is folded
 *  behind one summary line. It stays in the page, only folded (the honesty
 *  footer must always be there). Detailed view shows it open, as before. */
function FoldInSimple({ simple, summary, testId, children }: {
  simple: boolean; summary: string; testId: string; children: ReactNode;
}) {
  if (!simple) return <>{children}</>;
  return (
    <details data-testid={testId}>
      <summary className="cursor-pointer text-xs text-slateish-300">{summary}</summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}

export function ReviewWorkspace({
  location, onLocationChange, onBack, onOpenRun, onUnsavedChange, leaveGuard, isAdmin,
}: ReviewWorkspaceProps) {
  const { runId } = location;
  const view = useViewMode();
  const data = useWorkspaceRun(runId);
  const { load, run, findings, rows, standardsState, missingStandardIds, standardNames, submittal, summary, readiness, active, refresh, refreshError } = data;
  const newerRun = data.newerRun ?? null;
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

  // "Review again" asks before it starts anything (beforeStart), so it
  // opens the new run without asking a second time.

  // Keep the document in the address once the run names it, so a refresh
  // before the run loads still knows the document.
  const runDocumentId = run?.submittal_document_id ?? null;
  useEffect(() => {
    if (runDocumentId && location.documentId !== runDocumentId) onLocationChange({ ...location, documentId: runDocumentId });
  }, [runDocumentId, location, onLocationChange]);

  // D3: "Keep all remaining comments" offers Undo for a short while; saving
  // waits until it is gone, so Undo never has to take back a saved decision.
  const [undoOffered, setUndoOffered] = useState(false);
  const undoTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (undoTimer.current) clearTimeout(undoTimer.current); }, []);
  const endUndo = useCallback(() => {
    if (undoTimer.current) clearTimeout(undoTimer.current);
    undoTimer.current = null;
    setUndoOffered(false);
  }, []);
  const keepAll = useCallback(() => {
    const kept = decisions.acceptAll(rows);
    if (kept > 0) {
      if (undoTimer.current) clearTimeout(undoTimer.current);
      setUndoOffered(true);
      undoTimer.current = setTimeout(() => { undoTimer.current = null; setUndoOffered(false); }, UNDO_WINDOW_MS);
    }
    return kept;
  }, [decisions, rows]);
  const undoKeepAll = useCallback(() => { decisions.undo(); endUndo(); }, [decisions, endUndo]);
  const canUndo = undoOffered && decisions.canUndo;

  const numbers = useMemo(() => (run ? computeReviewNumbers({
    run, findings, rows, summary,
    missingStandards: missingStandardIds,
    readiness, decisions: decisions.state, unsaved: decisions.unsaved, gate: issueGate.gate,
  }) : null), [run, findings, rows, summary, missingStandardIds, readiness, decisions.state, decisions.unsaved, issueGate.gate]);
  // D4: decisions save by themselves; never on a signed review (read only).
  // "Save now" (and "Save and leave") ends the Undo offer first
  // (beforeSaveNow): the reader chose to put them on record.
  const autosaveRaw = useAutosave({
    runId, rows, decisions, refresh, paused: canUndo, disabled: numbers?.signed ?? false, beforeSaveNow: endUndo,
  });
  // The bar and sign-off only need "save now" to finish (the leave question
  // uses the raw one, which says whether everything saved).
  const autosave = useMemo(() => ({
    ...autosaveRaw, saveNow: async () => { await autosaveRaw.saveNow(); },
  }), [autosaveRaw]);

  // v2.1 (N1): every move away from the workspace's own buttons asks
  // through the app's ONE guard (in the page, never a browser pop-up), so
  // the reader sees one style of question and is never asked twice. Drawn
  // on its own (no app guard), the workspace keeps the same guard itself,
  // with its own "Save and leave".
  const unsavedRef = useRef(unsavedCount);
  useLayoutEffect(() => { unsavedRef.current = unsavedCount; }, [unsavedCount]);
  const ownGuard = useLeaveGuard(useCallback(() => unsavedRef.current, []), autosaveRaw.saveNow);
  const guard = leaveGuard ?? ownGuard.guard;
  const beforeLeave = useCallback((go: () => void) => { guard("navigate", go); }, [guard]);
  const leave = useCallback(() => beforeLeave(onBack), [beforeLeave, onBack]);
  const openRun = useCallback((id: string) => beforeLeave(() => onOpenRun(id)), [beforeLeave, onOpenRun]);

  const steps = useMemo(() => (numbers ? actionSteps(numbers) : []), [numbers]);
  const signOffRaw = useSignOff({ runId, rows, decisions, refresh, numbers });
  const signer = useSigner();
  // S2: Sign (from the bar or the sign-off panel) runs the issuing checks in
  // useSignOff and, when nothing is left, opens the ONE preview-and-confirm
  // step below (useSignOff owns whether it is open). Only its "Issue to
  // contractor" issues, through issueConfirmed. Save goes through the same
  // automatic saving, so two saves never race.
  const [standardsOpen, setStandardsOpen] = useState(false);
  // T1: "Review again" in the missing standards panel asks exactly what the
  // header's "Review again" asks (unsaved decisions, then signed / final
  // code / nothing changed), through the same rule.
  const standardsAgain = useReviewAgain({
    documentId: run?.submittal_document_id ?? "", filename: run?.submittal_filename ?? null,
    onStarted: onOpenRun, onOpenRun: openRun, beforeStart: beforeLeave,
    disabled: !run?.submittal_document_id,
  });

  const tabNow = location.tab;
  useEffect(() => {
    if (pagesAsked === 0 || tabNow !== "sheet") return;
    const box = document.querySelector<HTMLElement>('[data-testid="sign-pages"]');
    // Simple view: "Before you sign" may be folded; open it so the ticks show.
    const fold = box?.closest("details");
    if (fold) fold.open = true;
    box?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }, [pagesAsked, tabNow]);

  const go = (patch: Partial<WorkspaceLocation>) => onLocationChange({ ...location, ...patch });
  const onTab = (tab: WorkspaceTab) => go({ tab });
  const openRowKey = location.panel === "evidence" ? location.row : null;
  const onOpenRow = (rowKey: string | null) => go({ row: rowKey, panel: rowKey ? "evidence" : null });

  const signOff: SignOff = useMemo(() => ({
    ...signOffRaw,
    save: autosave.saveNow,
    sign: async () => {
      // The preview is a dialog of its own: the evidence panel closes first.
      if (location.panel) onLocationChange({ ...location, row: null, panel: null });
      await signOffRaw.sign();
    },
  }), [signOffRaw, autosave.saveNow, location, onLocationChange]);

  const onAction = (id: ActionStepId) => {
    if (id === "standards") {
      // T1 / S1: the missing standards panel opens under the bar.
      setStandardsOpen((open) => !open);
    }
    else if (id === "decide") {
      const first = numbers?.undecidedKeys[0] ?? null;
      // Nothing left to decide but something unsaved: save it now.
      if (!first && (numbers?.unsaved ?? 0) > 0) { void autosave.saveNow(); return; }
      go({ tab: "sheet", row: first, panel: first ? "evidence" : null });
    }
    else if (id === "code") {
      // The control opens in the bar itself (ActionBar).
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
    go({ tab: isTab(panel) && (PANEL_TABS.includes(panel) || panel === "crs") ? panel : "sheet" });
  };

  const leaveQuestion = leaveGuard ? null
    : (
      <LeaveConfirm pending={ownGuard.pending} onLeave={ownGuard.leave} onStay={ownGuard.stay}
        onSaveAndLeave={ownGuard.saveAndLeave} saving={ownGuard.saving} saveError={ownGuard.saveError} />
    );

  if (load.kind === "loading") return <p className="text-slateish-300" data-testid="review-workspace">Loading the sheet…</p>;
  if (load.kind === "error" || !run || !numbers) {
    return (
      <p role="alert" data-testid="review-workspace" className="rounded-[var(--radius-md)] border border-danger-500/40 bg-danger-500/10 px-4 py-3 text-danger-500">
        {load.kind === "error" ? load.message : "This review could not be found."}
      </p>
    );
  }
  const refreshLine = refreshError
    ? <p role="status" data-testid="ws-refresh-error" className="text-sm text-slateish-400">{refreshError}</p>
    : null;
  // Only a completed review has a sheet: anything else (failed, cancelled,
  // a status this screen does not know) says so in plain words.
  if (active || run.status !== "completed") {
    return (
      <>
        {leaveQuestion}
        <RunNotReady run={run} active={active} onBack={leave} onChanged={() => void refresh()} onOpenRun={onOpenRun}
          openRun={openRun} beforeStart={beforeLeave} isAdmin={isAdmin} />
        {refreshLine}
      </>
    );
  }

  const readOnly = numbers.signed;
  const newerAt = newerRun ? dayOf(newerRun.created_at) : "";
  const tab = location.tab;
  const panelOpen = tab === "sheet" && openRowKey !== null;
  const missingNames = numbers.standardsKnown ? numbers.missingStandards : (missingStandardIds ?? []);
  const missingList = missingNames.map((name) => {
    const ref = standardsState.missing.find((m) => m.identifier === name) as { id?: string } | undefined;
    return ref?.id ? { id: ref.id, name } : { name };
  });
  return (
    <section
      className={`mx-auto w-full max-w-7xl space-y-4 ${panelOpen ? PANEL_ROOM : ""}`} aria-labelledby="ws-title"
      data-testid="review-workspace" data-run={runId} data-panel-open={panelOpen ? "true" : "false"}
    >
      {leaveQuestion}
      <header className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={leave} className="text-sm text-signal-300 underline-offset-2 hover:underline">← Reviews</button>
        <h1 id="ws-title" className="min-w-[12rem] flex-1 truncate text-2xl font-semibold text-slateish-100">
          {run.submittal_filename ?? "Review"}
        </h1>
        <ViewModeSwitch mode={view.mode} onMode={view.setMode} />
        {run.submittal_document_id && isAdmin !== false && (
          <ReviewAgainButton documentId={run.submittal_document_id} filename={run.submittal_filename}
            beforeStart={beforeLeave} onStarted={onOpenRun} onOpenRun={openRun} />
        )}
        {run.submittal_document_id && isAdmin === false && (
          <span data-testid="ws-review-again-admin-only" className="text-xs text-slateish-400">
            Only an administrator can start a review.
          </span>
        )}
      </header>
      <ReviewHelpLine words={reviewHelpWords(numbers, steps)} />
      {run.submittal_document_id && data.documentRuns && data.documentRuns.length > 1 && (
        <div data-testid="ws-past-reviews">
          <PastReviewsButton documentId={run.submittal_document_id} runs={data.documentRuns}
            onOpenRun={openRun} currentRunId={runId} />
        </div>
      )}
      {newerRun && (
        <p role="status" data-testid="ws-newer-review"
          className="flex flex-wrap items-center gap-2 rounded-[var(--radius-sm)] border border-warn-500/50 bg-warn-500/10 px-3 py-2 text-sm text-slateish-100">
          <span>A newer review of this document exists{newerAt ? ` (${newerAt})` : ""}.</span>
          <button type="button" onClick={() => openRun(newerRun.review_run_id)}
            className="font-semibold text-signal-300 underline-offset-2 hover:underline">
            Open it
          </button>
        </p>
      )}

      <ActionBar run={run} numbers={numbers} steps={steps} onAction={onAction} signOff={signOff}
        autosave={autosave} onCodeRecorded={() => { void refresh(); void issueGate.reload(); }} />
      {refreshLine}
      {/* v2.1 round 2: a draft found on opening is asked about first. */}
      <RestoreDraftLine decisions={decisions} />
      {standardsOpen && (
        <div className="space-y-2">
          <MissingStandardsPanel runId={runId} documentId={run.submittal_document_id ?? null} missing={missingList}
            onReviewAgain={standardsAgain.press} known={numbers.standardsKnown} isAdmin={isAdmin} />
          {standardsAgain.busy && <p role="status" className="text-sm text-slateish-400">Starting a new review…</p>}
          <div className="flex flex-col items-start gap-1">{standardsAgain.question}</div>
          <button type="button" onClick={() => { setStandardsOpen(false); go({ tab: "standards" }); }}
            className="text-sm text-signal-300 underline-offset-2 hover:underline">
            See every standard this review used
          </button>
        </div>
      )}
      <SignConfirm
        runId={runId} open={signOffRaw.confirmOpen} onClose={signOffRaw.closeConfirm}
        onIssued={() => { void issueGate.reload(); }}
        summary={{ comments: numbers.comments, finalCode: numbers.finalCode, signer: signer.name, signInOff: signer.signInOff }}
        // Not known whether a newer review exists (the document's reviews
        // could not be read, or not yet): the step asks before issuing.
        newerReview={newerRun ? { at: newerAt || null }
          : run?.submittal_document_id && data.documentRuns == null ? "unknown" : null}
      />

      <WorkspaceTabs tab={tab} onTab={onTab} mode={view.mode}>
        {tab === "sheet" && (
          <div className="space-y-2">
            <SheetCountsLine numbers={numbers} />
            {!readOnly && (
              <KeepAllRemaining count={numbers.remainingToKeep} onKeep={keepAll} canUndo={canUndo} onUndo={undoKeepAll} />
            )}
            <WorkspaceSheet
              runId={runId} run={run} rows={rows} submittal={submittal} standardNames={standardNames}
              decisions={decisions} openRowKey={openRowKey} onOpenRow={onOpenRow} numbers={numbers} readOnly={readOnly}
              showKeys={view.mode === "detailed"} serverNotes={data.serverNotes ?? 0}
              footer={(
                <>
                  <SignOffPanel numbers={numbers} signOff={signOff} run={run} rows={rows} gate={issueGate}
                    onRunChanged={() => void refresh()} onJump={(row) => onOpenRow(row.key)}
                    folded={view.mode === "simple"} />
                  {/* S4: the honesty footer, as under the comment sheet. v2.2
                      round 2: Simple view folds it behind one line; it stays
                      on the page (the honesty rule), only folded. */}
                  <FoldInSimple simple={view.mode === "simple"} testId="ws-honesty-fold"
                    summary="How these comments were counted">
                    <CrsFooter
                      run={run}
                      counts={{
                        met: numbers.met, notApplicable: numbers.notApplicableRows, anotherDocument: numbers.anotherDocument,
                        comment: numbers.comments - numbers.needsYou, needsYou: numbers.needsYou,
                      }}
                      standards={standardsState.standards} missing={standardsState.missing}
                      standardsError={standardsState.error} rejected={numbers.removed}
                      signedAt={numbers.signedAt}
                    />
                  </FoldInSimple>
                </>
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
        {tab === "crs" && <CrsTabPanel runId={runId} />}
        {PANEL_TABS.includes(tab) && (
          <BehindTheScenes
            embedded
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
