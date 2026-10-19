/**
 * v2.1 (N1): the ONE way out of the review workspace while decisions are
 * not saved yet.
 *
 * Every way of leaving goes through `guard(kind, go)`: the browser's Back
 * button, the main menu, the command palette, "Open this point on the cards
 * view", the How tab's link to Documents, the finished notice's "Open it",
 * turning "Try new design" off, and signing out. With nothing unsaved, `go`
 * runs at once. Otherwise nothing moves yet: the app shows `LeaveConfirm`
 * in the page (the same "Yes / Cancel" pattern the sheet uses for "Keep all
 * remaining") and runs `go` only if the reader chooses to leave.
 *
 * Leaving does not throw the decisions away: the workspace keeps them as a
 * draft in this browser tab (useCrsDecisions), and they come back when the
 * same person opens the same review again. Only signing out removes the
 * draft, and the confirm says so.
 */
import { useCallback, useLayoutEffect, useRef, useState } from "react";

/** How the reader is leaving: it changes only the words of the question. */
export type LeaveKind = "navigate" | "back" | "switch" | "signout";

export interface PendingLeave {
  kind: LeaveKind;
  /** Decisions not saved yet when the reader tried to leave. */
  count: number;
}

export interface LeaveGuard {
  /** Run `go` now (returns true), or ask first (returns false). */
  guard: (kind: LeaveKind, go: () => void) => boolean;
  /** The question on screen, or null. */
  pending: PendingLeave | null;
  /** The reader chose to leave: run what was asked for. */
  leave: () => void;
  /** The reader chose to stay: nothing happens. */
  stay: () => void;
}

/** `unsaved` reads how many decisions are not saved yet, at the moment of
 *  leaving (the workspace reports it; 0 anywhere else). */
export function useLeaveGuard(unsaved: () => number): LeaveGuard {
  const [pending, setPending] = useState<PendingLeave | null>(null);
  const next = useRef<(() => void) | null>(null);
  const unsavedRef = useRef(unsaved);
  useLayoutEffect(() => { unsavedRef.current = unsaved; }, [unsaved]);

  const guard = useCallback((kind: LeaveKind, go: () => void) => {
    const count = unsavedRef.current();
    if (count <= 0) { go(); return true; }
    next.current = go;
    setPending({ kind, count });
    return false;
  }, []);
  const leave = useCallback(() => {
    const go = next.current;
    next.current = null;
    setPending(null);
    go?.();
  }, []);
  const stay = useCallback(() => {
    next.current = null;
    setPending(null);
  }, []);
  return { guard, pending, leave, stay };
}

function decisions(n: number): string {
  return `${n} ${n === 1 ? "decision" : "decisions"}`;
}

/** The question's words, per way of leaving. Exported for tests. */
export function leaveWords(kind: LeaveKind, count: number): { text: string; leave: string } {
  const head = `You have ${decisions(count)} on this review that ${count === 1 ? "is" : "are"} not saved yet.`;
  if (kind === "signout") {
    return {
      text: `${head} Signing out removes ${count === 1 ? "it" : "them"} from this browser tab. Save first if you want to keep ${count === 1 ? "it" : "them"}.`,
      leave: "Sign out without saving",
    };
  }
  if (kind === "switch") {
    return {
      text: `${head} The old screen does not show ${count === 1 ? "it" : "them"}; ${count === 1 ? "it is" : "they are"} kept in this browser tab and come back when you open this review in the new design again. Save first to be safe.`,
      leave: "Go to the old screen",
    };
  }
  return {
    text: `${head} If you leave, ${count === 1 ? "it is" : "they are"} kept in this browser tab and come back when you open this review again. Save first to be safe.`,
    leave: "Leave this review",
  };
}
