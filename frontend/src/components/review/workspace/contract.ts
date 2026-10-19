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

import type {
  DocumentRecord, ReviewFinding, ReviewReadiness, ReviewRunSummary, ReviewRunTierSummary,
} from "../../../types/api";
import type { StandardsState } from "../panels/BehindTheScenes";
import type { CrsRow } from "../crs/crsRows";
import type { CrsDecisions, DecisionState } from "../crs/useCrsDecisions";

export type { CrsRow, CrsDecisions, DecisionState, StandardsState };

/* ------------------------------------------------------------------ A: URL */

/** The tabs inside the workspace. "sheet" is the comment sheet (default). */
/** Same words CrsSheetView uses when leaving with unsaved decisions. */
export const LEAVE_WARNING = "Some decisions on this sheet are not saved yet. Leave without saving them?";

export const WORKSPACE_TABS = ["sheet", "how", "findings", "standards", "steps", "numbers"] as const;
export type WorkspaceTab = (typeof WORKSPACE_TABS)[number];

/** Plain-English tab names, in display order. */
export const WORKSPACE_TAB_LABELS: Record<WorkspaceTab, string> = {
  sheet: "Comment sheet",
  how: "How this was reviewed",
  findings: "Findings",
  standards: "Standards",
  steps: "Steps",
  numbers: "Numbers",
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
   *  (`standardsState.missing` mapped to their identifier strings). */
  missingStandards: string[];
  readiness: ReviewReadiness | null;
  decisions: DecisionState;
  /** `CrsDecisions.unsaved`. */
  unsaved: string[];
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
  /** Clauses that do not apply (requirement_split.does_not_apply when the
   *  run holds it, else the rows' not-applicable count). */
  notApplicable: number;
  anotherDocument: number;
  /** Findings an engineer already removed. */
  removed: number;
  /** Pages not read, sorted, unique (headlineFieldsOf + readiness). */
  unreadPages: number[];
  /** Missing standard identifiers, unique. */
  missingStandards: string[];
  /** Comment rows with no decision yet and not agreed earlier. */
  undecided: number;
  /** Their row keys, in sheet order (the "Decide comments" button opens the first). */
  undecidedKeys: string[];
  /** Tier C rows not opened yet in this session. */
  unopenedNeedsYou: number;
  /** Decisions on screen not saved yet. */
  unsaved: number;
  /** True when a contractor copy was issued (run.crs_issued_at). */
  signed: boolean;
  signedAt: string | null;
}

export type ActionStepId = "standards" | "pages" | "decide" | "sign";

/** One button of the "What you need to do" bar, in bar order. */
export interface ActionStep {
  id: ActionStepId;
  /** Plain words with the count, e.g. "Upload missing standards (2)". */
  label: string;
  /** The count shown; null for "sign". */
  count: number | null;
  /** Nothing left to do for this step. */
  done: boolean;
  /** Can be pressed. "sign" is enabled only when every other step is done
   *  and nothing is unsaved. */
  enabled: boolean;
  /** Optional one-line help, e.g. "Pages 4, 9 and 12". */
  detail?: string;
}

/** What `useSignOff` returns: the existing sign path (downloadCrs "issue",
 *  the same route CrsSheetView's Sign and export uses) plus saving. */
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
}

export interface WorkspaceTabsProps {
  tab: WorkspaceTab;
  onTab: (tab: WorkspaceTab) => void;
  /** The tab's content (A renders it). */
  children?: ReactNode;
}

export interface TryNewDesignToggleProps {
  on: boolean;
  onChange: (on: boolean) => void;
}

export interface ActionBarProps {
  run: ReviewRunSummary;
  numbers: ReviewNumbers;
  /** `actionSteps(numbers)`. */
  steps: ActionStep[];
  onAction: (id: ActionStepId) => void;
  signOff: SignOff;
}

export interface SheetCountsLineProps {
  numbers: ReviewNumbers;
}

export interface SignOffPanelProps {
  numbers: ReviewNumbers;
  signOff: SignOff;
}

export interface UseSignOffArgs {
  runId: string;
  rows: CrsRow[];
  decisions: CrsDecisions;
  refresh: () => Promise<void>;
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
