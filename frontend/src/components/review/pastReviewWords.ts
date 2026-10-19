/**
 * Order 123 item 5: the words of one past review on the Submittals list
 * (`PastReviews`). Kept apart from the component so the component file
 * exports components only.
 */
import type { ReviewRunSummary } from "../../types/api";
import { inboxStateOf, stateLabel } from "./inbox/inboxState";

/** The run's result in plain words. The engineer's code wins; the machine's
 *  code alone is a suggestion and says so (a guess is shown as a guess until
 *  a human confirms it). A run that did not finish says where it stopped. */
export function pastResult(run: ReviewRunSummary): string {
  if (run.engineer_final_code) {
    const who = run.decided_by_name ? ` by ${run.decided_by_name}` : "";
    return `Code ${run.engineer_final_code}, decided${who}`;
  }
  if (run.status === "completed" && run.recommended_code) {
    return `Suggested code ${run.recommended_code}, not decided yet`;
  }
  return stateLabel(inboxStateOf(run));
}

/** FINDINGS, NOT COMMENTS (A-1126): `findings_total` counts findings, and the
 *  sheet groups many into one comment row. Only a finished run states it. */
export function pastFindings(run: ReviewRunSummary): string {
  if (run.status !== "completed" || typeof run.findings_total !== "number") return "";
  const n = run.findings_total;
  return `${n.toLocaleString("en-US")} finding${n === 1 ? "" : "s"} recorded`;
}
