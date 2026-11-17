/** ONE rule for every final-code picker (the paper's code box and the three older pickers), order 14: when the reason field shows, and
 *  when it must be filled.
 *    - the chosen code differs from the proposal: shown and required (as before);
 *    - the chosen code lets the paper proceed (the first two codes of the policy order: Approved, Approved with Comments) while points
 *      are still to decide: shown and required (the server refuses it without a reason, 422);
 *    - the same, on a screen that cannot know whether points are open (`openPoints` null: a one-run screen): shown, not required here,
 *      so the engineer can type the reason the server may ask for. Never a dead end. */
import { REVIEW_CODES } from "../../types/api";

export const OPEN_REASON_LABEL = "Why it may proceed with points still to decide";
export const MAYBE_OPEN_REASON_LABEL = `${OPEN_REASON_LABEL} (needed if points of the paper are still to decide)`;

export interface ReasonRule {
  show: boolean;
  required: boolean;
  because: "differs" | "open" | "maybe_open" | null;
}

export function isApproving(code: string, codes: readonly string[] = REVIEW_CODES): boolean {
  return code !== "" && codes.slice(0, 2).includes(code);
}

export function reasonRule(
  code: string, proposed: string | null | undefined, openPoints: number | null, codes: readonly string[] = REVIEW_CODES,
): ReasonRule {
  if (proposed && code && code !== proposed) return { show: true, required: true, because: "differs" };
  if (isApproving(code, codes)) {
    if (openPoints == null) return { show: true, required: false, because: "maybe_open" };
    if (openPoints > 0) return { show: true, required: true, because: "open" };
  }
  return { show: false, required: false, because: null };
}

/** The field's label: the picker's own words for "differs", the shared words otherwise. */
export function reasonLabel(rule: ReasonRule, differsWords: string): string {
  if (rule.because === "open") return OPEN_REASON_LABEL;
  if (rule.because === "maybe_open") return MAYBE_OPEN_REASON_LABEL;
  return differsWords;
}
