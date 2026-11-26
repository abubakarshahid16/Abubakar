/** The new look's status colours, as words (owner, 26 Nov 2026): done green, check amber, late red, info blue, plain grey. */
export type ChipTone = "done" | "check" | "late" | "info" | "plain";

/** The chip tone of a review's status line (the words `rowStatus` already says). */
export function reviewStatusTone(status: string): ChipTone {
  const s = status.toLowerCase();
  if (s.startsWith("signed off")) return "done";
  if (s.includes("late") || s.includes("overdue") || s.includes("failed") || s.includes("stopped")) return "late";
  if (s.includes("not signed off") || s.includes("changed since") || s.includes("waiting") || s.includes("check")) return "check";
  if (s.includes("running") || s.includes("queued")) return "info";
  return "plain";
}
