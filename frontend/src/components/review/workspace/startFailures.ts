/**
 * Order 14 (G3): a review start that failed is never silent.
 *
 * The screen that pressed Start may be gone by the time the answer is read (a 401 sends the page to Sign in). So the failure is kept
 * here, in memory, per paper: the paper's row says "Not reviewed: the start failed (<reason>)" until a start works, and the Sign in
 * screen says why it appeared when the sign-in ended on a start. Nothing is stored on disk and nothing is sent anywhere.
 */
import { useSyncExternalStore } from "react";

import type { ApiError } from "../../../types/api";

export const SIGN_IN_ENDED_REASON = "your sign-in ended";
export const SIGN_IN_ENDED_LINE = "Your sign-in ended; sign in and press Review again";
const NO_REASON = "the server gave no reason";

const failures = new Map<string, string>();
let signInEnded = false;
const listeners = new Set<() => void>();
let version = 0;

function changed() {
  version += 1;
  for (const l of listeners) l();
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

/** A 401 answers with code "unauthenticated" (or, when the body was lost, the page's own sign-in words). */
export function isSignInEnded(error: ApiError): boolean {
  return error.code === "unauthenticated" || /not signed in, or your session has expired/i.test(error.message ?? "");
}

/** The reason in plain words for a refused start; never empty. */
export function startFailureReason(error: ApiError, words: string): string {
  if (isSignInEnded(error)) return SIGN_IN_ENDED_REASON;
  const text = (words || error.message || "").trim().replace(/[.\s]+$/, "");
  return text || NO_REASON;
}

export function recordStartFailure(documentId: string, reason: string, endedSignIn = false): void {
  failures.set(documentId, reason);
  if (endedSignIn) signInEnded = true;
  changed();
}

export function clearStartFailure(documentId: string): void {
  if (failures.delete(documentId)) changed();
}

export function clearSignInEnded(): void {
  if (signInEnded) { signInEnded = false; changed(); }
}

export function startFailureOf(documentId: string): string | null {
  return failures.get(documentId) ?? null;
}

/** The failed-start reason of one paper, live. */
export function useStartFailure(documentId: string): string | null {
  useSyncExternalStore(subscribe, () => version);
  return startFailureOf(documentId);
}

/** True while the sign-in ended on a review start and the reader has not signed in again. */
export function useSignInEndedOnStart(): boolean {
  return useSyncExternalStore(subscribe, () => signInEnded);
}

/** Tests only. */
export function resetStartFailures(): void {
  failures.clear();
  signInEnded = false;
  changed();
}
