import type { FactBatchConfirmation } from "../../../types/api";

/** "N confirmed, M now have a verdict, K still need you" - every count says whose it is. */
export function resultLine(done: FactBatchConfirmation): string {
  const verdicts = Math.max(0, done.held_before - done.held_after);
  const confirmed = `${done.confirmed} confirmed${done.already_confirmed ? ` (${done.already_confirmed} already were)` : ""}`;
  return `${confirmed}; in this review ${verdicts} finding${verdicts === 1 ? "" : "s"} now ${verdicts === 1 ? "has" : "have"} a verdict, `
    + `${done.held_after} still wait${done.held_after === 1 ? "s" : ""} for a value nobody has confirmed.`;
}
