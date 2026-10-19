/**
 * OWNER: builder B. THE ONE SOURCE OF NUMBERS (PLACEHOLDER - planner team).
 * Pure: no fetching, no React. Every count on the workspace comes from
 * `computeReviewNumbers`; nothing else in the workspace counts rows.
 */
import type { ActionStep, ReviewNumbers, ReviewNumbersInput } from "./contract";
import type { ReviewRunSummary } from "../../../types/api";

/** PLACEHOLDER: all zero. Builder B implements (SPEC.md section 4). */
export function computeReviewNumbers(input: ReviewNumbersInput): ReviewNumbers {
  return {
    comments: 0, needsYou: 0, findingsInComments: 0, met: 0, notApplicable: 0, anotherDocument: 0,
    removed: 0, unreadPages: [], missingStandards: [], undecided: 0, undecidedKeys: [],
    unopenedNeedsYou: 0, unsaved: input.unsaved.length,
    signed: Boolean(input.run.crs_issued_at), signedAt: input.run.crs_issued_at ?? null,
  };
}

/** PLACEHOLDER: the four buttons in bar order, nothing to do. */
export function actionSteps(numbers: ReviewNumbers): ActionStep[] {
  return [
    { id: "standards", label: "Upload missing standards", count: numbers.missingStandards.length, done: true, enabled: false },
    { id: "pages", label: "Check unread pages", count: numbers.unreadPages.length, done: true, enabled: false },
    { id: "decide", label: "Decide comments", count: numbers.undecided, done: true, enabled: false },
    { id: "sign", label: "Sign and export", count: null, done: numbers.signed, enabled: false },
  ];
}

/** PLACEHOLDER: the one-line verdict at the top of the bar. */
export function verdictLine(_numbers: ReviewNumbers, run: ReviewRunSummary): string {
  return run.submittal_filename ?? "Review";
}
