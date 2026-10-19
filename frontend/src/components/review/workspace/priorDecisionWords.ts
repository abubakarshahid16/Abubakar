/**
 * v2.1: the "asks first" question before a fresh review, in plain words.
 * One wording for every place that starts a fresh review of a document
 * (the landing rows, the workspace header, the drop zone). Kept on its own
 * so screens and tests that stand in for `newReview` still get the words.
 */
import type { PriorDecision } from "./newReview";

/** The ask-first question, in plain words; one wording for every button
 *  that starts a fresh review (rows, workspace, drop zone). */
export function priorDecisionWords(prior: PriorDecision): string {
  switch (prior.kind) {
    case "signed":
      return "The latest review of this document is already signed. Start a new review anyway? The signed review stays as it is.";
    case "final_code":
      return `An engineer already chose the final code "${prior.finalCode}" on the latest review of this document. `
        + "Start a new review anyway? That review stays as it is.";
    case "nothing_changed":
      return "Nothing has changed since the latest review of this document (same file, same standards), "
        + "so a new review will most likely say the same. Start a new review anyway? That review stays as it is.";
    default:
      return "Could not check whether the latest review of this document is already signed. Start a new review anyway?";
  }
}
