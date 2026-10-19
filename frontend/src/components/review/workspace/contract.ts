/**
 * Review workspace v2: THE SHARED CONTRACT (planner team).
 *
 * Every type the five builders share lives here, and every public function
 * or component is re-exported from the one file that owns it. Builders
 * import from "./contract" (or the owning file) and never redefine these
 * shapes. Only the planner / integrator edits this file; a builder who
 * needs a change asks for it in their report instead of editing it.
 *
 * See SPEC.md in this folder for the design, the file ownership table and
 * each builder's acceptance checks.
 */
import type { ReactNode } from "react";

import type { LeaveKind } from "./useLeaveGuard";

import type {
  CrsIssueGate, DocumentRecord, ReviewFinding, ReviewReadiness, ReviewRunSummary, ReviewRunTierSummary,
} from "../../../types/api";
import type { StandardsState } from "../panels/BehindTheScenes";
import type { CrsRow } from "../crs/crsRows";
import type { CrsDecisions, DecisionState } from "../crs/useCrsDecisions";
import type { IssueGateState } from "../crs/issueGate";

export type { CrsRow, CrsDecisions, DecisionState, StandardsState };

/* ------------------------------------------------------------------ A: URL */

/** The tabs inside the workspace. "sheet" is the comment sheet (default). */
/** Same words CrsSheetView uses when leaving with unsaved decisions. */
export const LEAVE_WARNING = "Some decisions on this sheet are not saved yet. Leave without saving them?";

export const WORKSPACE_TABS = ["sheet", "how", "findings", "standards", "steps", "numbers", "crs"] as const;
export type WorkspaceTab = (typeof WORKSPACE_TABS)[number];

/** Plain-English tab names, in display order. */
export const WORKSPACE_TAB_LABELS: Record<WorkspaceTab, string> = {
  sheet: "Comment sheet",
  how: "How this was reviewed",
  findings: "Findings",
  standards: "Standards",
  steps: "Steps",
  numbers: "Numbers",
  // The comment sheet as issued: the contractor's replies, transmittal
  // numbers, which comments are open or closed (the old "crs" page).
  crs: "CRS preview and replies",
};

/** The right-hand panel. Only the evidence drawer for now. */
export type WorkspacePanel = "evidence";

/** Everything that keeps the reader's place. The run is the path
 *  (`/review/<run>/workspace`); the rest is the query string
 *  (`?tab=standards&row=<rowKey>&panel=evidence&doc=<documentId>`). */
export interface WorkspaceLocation {
  runId: string;
  tab: WorkspaceTab;
  /** CrsRow.key of the row open in the sheet / drawer; null when none. */
  row: string | null;
  panel: WorkspacePanel | null;
  /** The submittal document. Optional in the URL (the run names it); kept
   *  so a refresh before the run loads still knows the document. */
  documentId: string | null;
}

/** The query-string part of a location (everything but the run id). */
export type WorkspaceQuery = Omit<WorkspaceLocation, "runId">;

/* ----------------------------------------------------- A: the run's data */

export type WorkspaceLoad = { kind: "loading" } | { kind: "ready" } | { kind: "error"; message: string };

/** What `useWorkspaceRun(runId)` returns: the same reads CrsSheetView makes,
 *  plus the submittal's readiness (for the unread pages list), and the
 *  sheet rows already built with `buildCrsRows`. */
export interface WorkspaceRunData {
  load: WorkspaceLoad;
  run: ReviewRunSummary | null;
  findings: ReviewFinding[];
  rows: CrsRow[];
  standardsState: StandardsState;
  /** Identifiers of the missing standards (`standardsState.missing`), or
   *  null when the standards read failed or has not answered: "not known",
   *  never an empty list. */
  missingStandardIds: string[] | null;
  /** standard_document_id -> filename, for the sheet's clause column. */
  standardNames: Map<string, string>;
  submittal: DocumentRecord | null;
  /** The server's run summary (#1111); null when it did not answer. */
  summary: ReviewRunTierSummary | null;
  /** `reviewsApi.readiness(submittalId)`; null until loaded or on failure. */
  readiness: ReviewReadiness | null;
  /** queued or running. */
  active: boolean;
  refresh: () => Promise<void>;
}

/* ------------------------------------------------------------ B: numbers */

/** Everything `computeReviewNumbers` reads. Pure data, no fetching. */
export interface ReviewNumbersInput {
  run: ReviewRunSummary;
  /** Every finding of the run, removed ones included (for the removed count). */
  findings: ReviewFinding[];
  rows: CrsRow[];
  summary: ReviewRunTierSummary | null;
  /** Identifiers of standards the submittal cites that the library lacks
   *  (`missingStandardIds` from useWorkspaceRun). null = not known (the
   *  standards read failed), never treated as none. */
  missingStandards: string[] | null;
  /** null = not known (loading or failed), never treated as none. */
  readiness: ReviewReadiness | null;
  decisions: DecisionState;
  /** `CrsDecisions.unsaved`. */
  unsaved: string[];
  /** The run's issue gate (`useIssueGate(...).gate`, the same read the
   *  comment sheet's "Before you sign" box uses). null = not known (loading
   *  or failed), never treated as clear. */
  gate: CrsIssueGate | null;
}

/** THE ONE SOURCE OF NUMBERS. Every count the workspace shows comes from
 *  this object and nowhere else. */
export interface ReviewNumbers {
  /** Comment rows on the sheet (Tier B + Tier C). */
  comments: number;
  /** Tier C rows ("Needs you"). Included in `comments`. */
  needsYou: number;
  /** Findings behind the comment rows (a row can stand on many). */
  findingsInComments: number;
  met: number;
  /** ROWS on the sheet whose kind is "not applicable" (`rowCounts(rows)`),
   *  exactly what CrsSheetView hands its table. */
  notApplicableRows: number;
  /** CLAUSES of the standards judged not to apply
   *  (`headlineFieldsOf(...).doesNotApply`); not rows on the sheet. null =
   *  the run does not say. */
  notApplicableClauses: number | null;
  anotherDocument: number;
  /** Findings an engineer already removed. */
  removed: number;
  /** Pages still to check, sorted, unique. When the issue gate is known: the
   *  pages it still wants ticked (so the bar and "Before you sign" agree);
   *  else the run's one list (order 127, `headlineFieldsOf`), or readiness's
   *  pages when the run does not hold that list. */
  unreadPages: number[];
  /** Missing standard identifiers, unique. Only the full list when
   *  `standardsKnown`; otherwise what was read so far. */
  missingStandards: string[];
  /** False while the standards read or the page checks (readiness) are
   *  not known. Then the missing standards count is unknown: the step is
   *  not done and no number is shown. */
  standardsKnown: boolean;
  /** False while neither the issue gate nor a current page ledger
   *  (readiness) is known, or while the gate says there is no page record.
   *  Then the
   *  unread pages count is unknown: the step is not done and no number is
   *  shown. */
  pagesKnown: boolean;
  /** True when the issue gate says the run has no page record at all ("no
   *  page coverage" blocker). Then `pagesKnown` is false and the pages step
   *  says the record is missing. */
  pageRecordMissing: boolean;
  /** Comment rows with no decision yet and not agreed earlier. */
  undecided: number;
  /** Their row keys, in sheet order (the "Decide comments" button opens the first). */
  undecidedKeys: string[];
  /** Tier C rows not opened yet in this session. A row an engineer already
   *  decided in an earlier session (`priorState` "agreed") counts as opened:
   *  an old review never has to be opened row by row again. */
  unopenedNeedsYou: number;
  /** Comment rows "Keep all remaining comments" would keep right now: the
   *  same rule as `useCrsDecisions.remaining` (Tier B, no decision yet, not
   *  answered earlier). Never a "Needs you" row. */
  remainingToKeep: number;
  /** The engineer's final code once recorded (`run.engineer_final_code`). */
  finalCode: string | null;
  /** True when the final code is recorded (the run or the issue gate says
   *  so); false when the gate says it is not; null while not known. */
  finalCodeRecorded: boolean | null;
  /** Decisions on screen not saved yet. */
  unsaved: number;
  /** What the issue gate still wants before Sign and export, in plain
   *  words (`signLeft` from crs/issueGate.ts, the comment sheet's rule):
   *  "record the final code", "tick 2 unread pages", ... Empty when nothing
   *  is left; never empty while the gate is not known. */
  signLeft: string[];
  /** True when a contractor copy was issued (run.crs_issued_at). */
  signed: boolean;
  signedAt: string | null;
}

/** v2.2: "preview" (Preview CRS) sits between the final code and Sign: a
 *  read-only look at the sheet as the contractor gets it. */
export type ActionStepId = "standards" | "pages" | "decide" | "code" | "preview" | "sign";

/** One button of the "What you need to do" bar, in bar order. */
export interface ActionStep {
  id: ActionStepId;
  /** Plain words with the count, e.g. "Upload missing standards (2)". */
  label: string;
  /** The count shown; null for "code", "preview" and "sign". */
  count: number | null;
  /** Nothing left to do for this step. */
  done: boolean;
  /** Can be pressed. "sign" is enabled only when every other step is done
   *  and nothing is unsaved. */
  enabled: boolean;
  /** Optional one-line help, e.g. "Pages 4, 9 and 12". */
  detail?: string;
}

/** What `useSignOff` returns: saving, the working copy, and Sign and
 *  export through `issueContractorCopy` (crs/issueContractorCopy.ts), the one
 *  shared issuing path CrsSheetView uses too. */
export interface SignOff {
  busy: boolean;
  message: string | null;
  error: string | null;
  /** Saves the on-screen decisions (`saveCrsDecisions`). */
  save: () => Promise<void>;
  /** Signs and downloads the contractor copy. */
  sign: () => Promise<void>;
  /** Downloads the unsigned working copy. */
  workingCopy: () => Promise<void>;
}

/* ------------------------------------------------------- C: plain words */

/** Which table a code is looked up in. "any" tries every table in the
 *  order listed in PLAIN_KINDS. */
export const PLAIN_KINDS = ["reason", "tier", "removal", "trust", "code", "status", "runStatus", "engine", "rule"] as const;
export type PlainKind = (typeof PLAIN_KINDS)[number] | "any";

/** One plain-words answer: what the manager reads, and the raw code folded
 *  under "Details" (null when the code IS already plain words). */
export interface PlainEntry {
  words: string;
  detail: string | null;
}

/* ---------------------------------------------- D: new review and notice */

export type NewReviewPhase =
  | { kind: "idle" }
  | { kind: "uploading"; percent: number }
  | { kind: "marking" }   // setting the role to contractor submittal
  | { kind: "waiting" }   // the document is still being read in
  | { kind: "starting" }  // asking for the review
  | { kind: "started"; runId: string }
  | { kind: "error"; message: string };

export type NewReviewOutcome =
  | { ok: true; documentId: string; runId: string }
  | { ok: false; message: string };

export type ReviewAgainOutcome = { ok: true; runId: string } | { ok: false; message: string };

/** A watched review that finished while the reader was elsewhere. */
export interface FinishedReview {
  runId: string;
  filename: string | null;
  /** "completed" or "failed" (the run's status). */
  status: string;
}

/* -------------------------------------------------------- E: past reviews */

/** One row of "Past reviews (N)". */
export interface PastReview {
  runId: string;
  createdAt: string | null;
  /** Plain words: the engineer's final code, else the recommended code,
   *  else the run's status in plain words. */
  result: string;
  /** Comment rows of that run; null when not known (never 0 for unknown). */
  commentCount: number | null;
  signed: boolean;
  status: string;
}

/* ---------------------------------------------- component prop contracts */

export interface ReviewWorkspaceProps {
  location: WorkspaceLocation;
  /** Replace the URL's query (tab/row/panel) without a new history entry. */
  onLocationChange: (next: WorkspaceLocation) => void;
  onBack: () => void;
  onOpenRun: (runId: string) => void;
  isAdmin?: boolean;
  /** Told how many decisions are on screen only, so the app can ask before
   *  a move it makes itself (turning off "Try new design") drops them. */
  onUnsavedChange?: (count: number) => void;
  /** v2.1 (N1): the app's one navigation guard (useLeaveGuard). Every way
   *  out of the workspace from its own buttons asks through it, so there is
   *  one in-page question and nobody is asked twice. Left out (a workspace
   *  drawn on its own, as in tests), the workspace keeps a guard of its own
   *  and shows the same question. */
  leaveGuard?: (kind: LeaveKind, go: () => void) => boolean;
}

export interface WorkspaceTabsProps {
  tab: WorkspaceTab;
  onTab: (tab: WorkspaceTab) => void;
  /** v2.2: "simple" shows Comment sheet, CRS preview and replies and one
   *  "Details" tab that holds the engineer tabs in a second small row;
   *  "detailed" (the default here) shows every tab in one strip. */
  mode?: "simple" | "detailed";
  /** The tab's content (A renders it). */
  children?: ReactNode;
}

export interface TryNewDesignToggleProps {
  on: boolean;
  onChange: (on: boolean) => void;
}

/** The workspace's automatic saving of decisions (workspace/decide/useAutosave). */
export interface AutosaveStatus {
  /** idle: nothing saved yet this visit; saving; saved: everything on
   *  screen is saved; failed: the last try did not save (see `message`). */
  phase: "idle" | "saving" | "saved" | "failed";
  /** Plain words for a failed save; null otherwise. */
  message: string | null;
  /** v2.1 round 2: the server's own words for a failed save, shown folded
   *  under `message`; null (or absent) when there are none. */
  detail?: string | null;
  /** True while an "Undo" of "Keep all remaining comments" is offered:
   *  saving waits until it is gone, so Undo never has to unsave anything. */
  waiting: boolean;
  /** Order 141 D: decisions taken off this visit because their comment is
   *  no longer on the sheet (never saved); absent or 0 when none. */
  dropped?: number;
  /** Save every unsaved decision now. */
  saveNow: () => Promise<void>;
}

export interface ActionBarProps {
  run: ReviewRunSummary;
  numbers: ReviewNumbers;
  /** `actionSteps(numbers)`. */
  steps: ActionStep[];
  onAction: (id: ActionStepId) => void;
  signOff: SignOff;
  /** The saving line ("Saved" / "Saving..." / "Not saved: why") and
   *  "Save now". Absent: no saving line. */
  autosave?: AutosaveStatus;
  /** The final code was recorded from the bar: read the run again. */
  onCodeRecorded?: () => void;
  /** Order 141 D: decisions in a draft from an earlier visit still waiting
   *  for "Bring them back" / "Discard" (absent or 0 when none). */
  draftWaiting?: number;
}

export interface SheetCountsLineProps {
  numbers: ReviewNumbers;
}

export interface SignOffPanelProps {
  numbers: ReviewNumbers;
  signOff: SignOff;
  run: ReviewRunSummary;
  rows: CrsRow[];
  /** The issue gate the comment sheet uses (`useIssueGate`), shown as its
   *  "Before you sign" box: final code, unread page ticks, open items. */
  gate: IssueGateState;
  /** The run changed (the final code was recorded): read it again. */
  onRunChanged: () => void;
  /** Open a comment row's evidence on the sheet. */
  onJump: (row: CrsRow) => void;
}

export interface UseSignOffArgs {
  runId: string;
  rows: CrsRow[];
  decisions: CrsDecisions;
  refresh: () => Promise<void>;
  /** The shared numbers: Sign checks `unsaved`, `unopenedNeedsYou` and
   *  `signLeft` from here before it asks the server. null = not loaded. */
  numbers: ReviewNumbers | null;
  /** Order 141 D: runs before the working copy is downloaded; saves the
   *  decisions on screen and answers null, or plain words why the copy
   *  would leave decisions out (then nothing is downloaded). */
  beforeCopy?: () => Promise<string | null>;
}

export interface WorkspaceSheetProps {
  runId: string;
  run: ReviewRunSummary;
  rows: CrsRow[];
  submittal: DocumentRecord | null;
  standardNames: Map<string, string>;
  decisions: CrsDecisions;
  /** The row whose evidence is open (URL `row` with `panel=evidence`). */
  openRowKey: string | null;
  onOpenRow: (rowKey: string | null) => void;
  /** The one source of counts: the table's folded "met / not applicable"
   *  line shows these, never its own count of the rows. */
  numbers: ReviewNumbers;
  /** Rendered under the table: B's SignOffPanel. */
  footer?: ReactNode;
}

export interface PlainTermProps {
  code: string | null | undefined;
  kind?: PlainKind;
}

export interface NewReviewDropZoneProps {
  onStarted: (runId: string) => void;
}

export interface ReviewAgainButtonProps {
  documentId: string;
  filename?: string | null;
  onStarted: (runId: string) => void;
  /** Asked before anything starts; false stops the press (for example the
   *  reader chose to stay with unsaved decisions). */
  mayStart?: () => boolean;
}

export interface FinishedReviewNoticeProps {
  onOpenRun: (runId: string) => void;
}

export interface PastReviewsButtonProps {
  documentId: string;
  /** The landing page's runs list, already loaded (no extra request to count). */
  runs: ReviewRunSummary[];
  onOpenRun: (runId: string) => void;
}

export interface PastReviewsListProps {
  reviews: PastReview[];
  onOpenRun: (runId: string) => void;
}

/* ------------------------------------------------------------ re-exports */

// A
export {
  WORKSPACE_PANEL, WORKSPACE_OPT_IN_KEY, parseWorkspaceQuery, workspaceSearch, isWorkspaceScreen,
} from "./workspaceRoute";
export { useWorkspaceSwitch, readWorkspaceOptIn, writeWorkspaceOptIn } from "./useWorkspaceSwitch";
export { useWorkspaceRun } from "./useWorkspaceRun";
export { ReviewWorkspace } from "./ReviewWorkspace";
export { WorkspaceTabs } from "./WorkspaceTabs";
export { TryNewDesignToggle } from "./TryNewDesignToggle";
// B
export { computeReviewNumbers, actionSteps, verdictLine } from "./numbers";
export { useSignOff } from "./useSignOff";
export { ActionBar } from "./ActionBar";
export { SheetCountsLine } from "./SheetCountsLine";
export { SignOffPanel } from "./SignOffPanel";
// C
export { PLAIN_WORDS, plainWords, plainText, plainRow } from "./plainWords";
export { PlainTerm } from "./PlainTerm";
export { WorkspaceSheet } from "./WorkspaceSheet";
export { WorkspaceEvidence } from "./WorkspaceEvidence";
// D
export { startNewReview, markAsContractorSubmittal, reviewAgain } from "./newReview";
export { watchRun, useFinishedReviews } from "./reviewWatch";
export { NewReviewDropZone } from "./NewReviewDropZone";
export { ReviewAgainButton } from "./ReviewAgainButton";
export { FinishedReviewNotice } from "./FinishedReviewNotice";
// E
export { pastReviewsOf, loadPastReviews, loadCommentCount } from "./pastReviews";
export { PastReviewsButton } from "./PastReviewsButton";
export { PastReviewsList } from "./PastReviewsList";
