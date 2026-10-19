/**
 * OWNER: builder D. Watched reviews and the finished notice's store.
 *
 * A review takes minutes. Whoever starts one (a new review, "Review again")
 * calls `watchRun`, then may go anywhere in the app; `FinishedReviewNotice`
 * (mounted once in the Shell) uses `useFinishedReviews` and says "Your
 * review of X is ready" wherever the reader is.
 *
 * ONE MODULE STORE, MIRRORED TO sessionStorage. The store survives a
 * component re-mount (it lives in the module); sessionStorage keeps the
 * watch list across a refresh of the same tab. Every storage read and write
 * is inside try/catch: a private window or blocked site data simply means
 * the list lives only as long as the page.
 *
 * POLLING. While at least one run is watched, `useFinishedReviews` reads
 * each watched run with `reviewsApi.reviewRun(id)` every WATCH_POLL_MS.
 * A run that is completed or failed moves to "finished"; a run the server
 * no longer knows (null) or a cancelled run is dropped quietly. A read that
 * fails keeps the run watched and is tried again next time.
 */
import { useEffect, useSyncExternalStore } from "react";

import { reviews as reviewsApi } from "../../../api/client";
import type { FinishedReview } from "./contract";

/** How often watched runs are read while any is still going. */
export const WATCH_POLL_MS = 10_000;

/** The sessionStorage key. Versioned so a future shape change can ignore
 *  old data. With a signed-in user the key carries their id
 *  (`watchStorageKey`), so one person's file names never show for another. */
export const WATCH_STORAGE_KEY = "review-workspace.watched.v1";

interface WatchedRun {
  runId: string;
  filename: string | null;
}

interface WatchState {
  watched: WatchedRun[];
  finished: FinishedReview[];
  /** Finished runs read from the server in THIS page (not stored). A notice
   *  restored from storage is shown only once the server has said, again,
   *  that the run exists for whoever is signed in now. */
  verified: string[];
}

const EMPTY: WatchState = { watched: [], finished: [], verified: [] };

const FINISHED_STATUSES = new Set(["completed", "failed"]);
const DROPPED_STATUSES = new Set(["cancelled"]);

/** Whose watch list this page holds: a user id, or null with sign-in off
 *  (or before anyone is known). */
let owner: string | null = null;
/** Bumped whenever the list is swapped or cleared, so a read that was in
 *  flight never writes its answers into the next person's list. */
let epoch = 0;

/** The storage key for a user (null: sign-in off). */
export function watchStorageKey(user: string | null = owner): string {
  return user ? `${WATCH_STORAGE_KEY}.${user}` : WATCH_STORAGE_KEY;
}

function isWatched(value: unknown): value is WatchedRun {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.runId === "string" && v.runId !== ""
    && (v.filename === null || typeof v.filename === "string");
}

function isFinished(value: unknown): value is FinishedReview {
  return isWatched(value) && typeof (value as unknown as Record<string, unknown>).status === "string";
}

function readStorage(): WatchState {
  try {
    const raw = window.sessionStorage.getItem(watchStorageKey());
    if (!raw) return EMPTY;
    const parsed = JSON.parse(raw) as { watched?: unknown; finished?: unknown };
    return {
      watched: Array.isArray(parsed.watched) ? parsed.watched.filter(isWatched) : [],
      finished: Array.isArray(parsed.finished) ? parsed.finished.filter(isFinished) : [],
      verified: [],
    };
  } catch {
    return EMPTY;
  }
}

function writeStorage(next: WatchState): void {
  try {
    window.sessionStorage.setItem(watchStorageKey(), JSON.stringify({ watched: next.watched, finished: next.finished }));
  } catch {
    /* blocked storage: the list lives in the module only */
  }
}

let state: WatchState = readStorage();
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

function setState(next: WatchState): void {
  state = next;
  writeStorage(next);
  notify();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

function snapshot(): WatchState {
  return state;
}

/** Say whose watch list this page holds (App, once it knows who is signed
 *  in; null with sign-in off). A different person gets their own list,
 *  never the one in memory. */
export function setWatchOwner(user: string | null): void {
  if (user === owner) return;
  owner = user;
  epoch += 1;
  checking = false;
  state = readStorage();
  notify();
}

/** Sign-out: forget every watched and finished review, in memory and in
 *  this tab's storage (the signed-in user's key and the shared one). */
export function clearWatchedReviews(): void {
  try {
    window.sessionStorage.removeItem(watchStorageKey());
    window.sessionStorage.removeItem(WATCH_STORAGE_KEY);
  } catch {
    /* blocked storage: nothing was stored */
  }
  owner = null;
  epoch += 1;
  checking = false;
  state = EMPTY;
  notify();
}

/** Start watching a run. Watching the same run twice keeps one entry
 *  (the filename is filled in if it was missing). */
export function watchRun(runId: string, filename: string | null = null): void {
  if (!runId) return;
  const existing = state.watched.find((w) => w.runId === runId);
  if (existing) {
    if (existing.filename === null && filename !== null) {
      setState({
        ...state,
        watched: state.watched.map((w) => (w.runId === runId ? { runId, filename } : w)),
      });
    }
    return;
  }
  setState({
    watched: [...state.watched, { runId, filename }],
    // Starting the same run again (unlikely) clears an old notice for it.
    finished: state.finished.filter((f) => f.runId !== runId),
    verified: state.verified.filter((id) => id !== runId),
  });
}

function dismiss(runId: string): void {
  if (!state.finished.some((f) => f.runId === runId)) return;
  setState({
    ...state,
    finished: state.finished.filter((f) => f.runId !== runId),
    verified: state.verified.filter((id) => id !== runId),
  });
}

function unverified(s: WatchState): FinishedReview[] {
  return s.finished.filter((f) => !s.verified.includes(f.runId));
}

let checking = false;

/** Reads every watched run once and moves finished ones; reads each
 *  finished run restored from storage once, and drops it when the server
 *  no longer knows it. Exported for tests. */
export async function checkWatchedRuns(): Promise<void> {
  const toRecheck = unverified(state);
  if (checking || (state.watched.length === 0 && toRecheck.length === 0)) return;
  checking = true;
  const mine = epoch;
  try {
    const [results, rechecked] = await Promise.all([
      Promise.all(state.watched.map(async (w) => ({ w, result: await reviewsApi.reviewRun(w.runId) }))),
      Promise.all(toRecheck.map(async (f) => ({ f, result: await reviewsApi.reviewRun(f.runId) }))),
    ]);
    // Signed out (or someone else signed in) while reading: the answers
    // belong to a list this page no longer holds.
    if (mine !== epoch) return;
    const done: FinishedReview[] = [];
    const drop = new Set<string>();
    for (const { w, result } of results) {
      if (!result.ok) continue; // try again next time
      const run = result.data;
      if (run === null) { drop.add(w.runId); continue; }
      const status = run.status || "";
      if (FINISHED_STATUSES.has(status)) {
        done.push({ runId: w.runId, filename: w.filename ?? run.submittal_filename ?? null, status });
        drop.add(w.runId);
      } else if (DROPPED_STATUSES.has(status)) {
        drop.add(w.runId);
      }
    }
    const confirmed: string[] = [];
    const forget = new Set<string>();
    for (const { f, result } of rechecked) {
      if (!result.ok) continue; // stays hidden; tried again next time
      if (result.data === null) forget.add(f.runId);
      else confirmed.push(f.runId);
    }
    if (drop.size === 0 && confirmed.length === 0 && forget.size === 0) return;
    const finished = [
      ...state.finished.filter((f) => !forget.has(f.runId) && !done.some((d) => d.runId === f.runId)),
      ...done,
    ];
    setState({
      watched: state.watched.filter((w) => !drop.has(w.runId)),
      finished,
      verified: [...new Set([...state.verified, ...confirmed, ...done.map((d) => d.runId)])]
        .filter((id) => finished.some((f) => f.runId === id)),
    });
  } finally {
    checking = false;
  }
}

/** Finished watched reviews the server has confirmed in this page, and a
 *  way to dismiss each. Polls while any watched run is still going, or a
 *  restored notice still has to be confirmed. */
export function useFinishedReviews(): { finished: FinishedReview[]; dismiss: (runId: string) => void } {
  const current = useSyncExternalStore(subscribe, snapshot, snapshot);
  const anyToRead = current.watched.length > 0 || unverified(current).length > 0;

  useEffect(() => {
    if (!anyToRead) return undefined;
    void checkWatchedRuns();
    const timer = window.setInterval(() => { void checkWatchedRuns(); }, WATCH_POLL_MS);
    return () => window.clearInterval(timer);
  }, [anyToRead]);

  const shown = current.finished.filter((f) => current.verified.includes(f.runId));
  return { finished: shown, dismiss };
}

/** TESTS ONLY: reload the store from sessionStorage, as a page refresh would. */
export function reloadWatchStoreForTests(): void {
  checking = false;
  owner = null;
  epoch += 1;
  state = readStorage();
  notify();
}
