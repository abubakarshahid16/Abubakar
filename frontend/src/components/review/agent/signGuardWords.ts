/** The signing guard's words (one home; see plainWords.ts for the rest). */
export const SIGN_GUARD_TICK = "I have read the AI review's points";

export function signGuardWarning(open: number | null): string {
  if (open == null) {
    return "The AI review of this document has points that could not be counted here, and they are not on this sheet.";
  }
  return `The AI review of this document has ${open.toLocaleString()} open ${open === 1 ? "point" : "points"} that ${open === 1 ? "is" : "are"} not on this sheet.`;
}

/** Why Sign waits, for the step list. */
export const SIGN_GUARD_WAITS = `Tick "${SIGN_GUARD_TICK}" under the sheet first.`;
