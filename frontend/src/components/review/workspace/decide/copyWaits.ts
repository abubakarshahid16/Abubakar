/**
 * Order 141 D: every copy of the comment sheet (the CRS tab's sheet, its
 * internal copy, the working copy) is built by the server from the RECORD,
 * never from the screen. So before one is read the workspace saves every
 * decision on screen (which ends a "Keep all" Undo offer, as "Save now"
 * does); when that cannot be done, these are the plain words the screen
 * shows instead of a copy that silently leaves the decisions out.
 */

function them(count: number): string {
  return count === 1 ? "it" : "them";
}

/** Decisions on screen that did not reach the record. */
export function notSavedForCopy(count: number): string {
  const n = Math.max(1, count);
  const lead = n === 1 ? "1 decision is" : `${n.toLocaleString()} decisions are`;
  return `${lead} not saved yet, so the CRS would not show ${them(n)}. Press Save now at the top, then try again.`;
}

/** A draft found on opening, still waiting for "Bring them back" or "Discard". */
export function draftWaitsForCopy(count: number): string {
  const lead = count === 1 ? "1 decision you had not saved earlier is" : `${count.toLocaleString()} decisions you had not saved earlier are`;
  return `${lead} waiting for your answer above (bring ${them(count)} back or discard ${them(count)}), so the CRS would not show ${them(count)}.`;
}
