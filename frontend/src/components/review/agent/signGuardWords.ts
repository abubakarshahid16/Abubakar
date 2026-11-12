/** The signing guard's words (one home; see plainWords.ts for the rest). */
export const SIGN_GUARD_TICK = "I have read the AI review's points";

export function signGuardWarning(open: number | null, blocked: "loading" | "error" | null = null): string {
  if (blocked === "loading") return "Reading the AI review of this document. Sign and export waits until it is read.";
  if (blocked === "error") {
    return "The state of the AI review of this document could not be read, so Sign and export is not available. Reload the page to try again.";
  }
  if (open == null) {
    return "The AI found points to look at that could not be counted here. They are not on this sheet.";
  }
  return `The AI found ${open.toLocaleString()} ${open === 1 ? "point" : "points"} to look at. ${open === 1 ? "It is" : "They are"} not on this sheet.`;
}

/** Why Sign waits, for the step list. */
export const SIGN_GUARD_WAITS = `Tick "${SIGN_GUARD_TICK}" under the sheet first.`;
