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

/** The sessionStorage key. Versioned so a future shape change can ignore old data. */
export const WATCH_STORAGE_KEY = "review-workspace.watched.v1";

interface WatchedRun {
  runId: string;
  filename: string | null;
}

interface WatchState {
  watched: WatchedRun[];
  finished: FinishedReview[];
}

const FINISHED_STATUSES = new Set(["completed", "failed"]);
const DROPPED_STATUSES = new Set(["cancelled"]);

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
    const raw = window.sessionStorage.getItem(WATCH_STORAGE_KEY);
    if (!raw) return { watched: [], finished: [] };
    const parsed = JSON.parse(raw) as { watched?: unknown; finished?: unknown };
    return {
      watched: Array.isArray(parsed.watched) ? parsed.watched.filter(isWatched) : [],
      finished: Array.isArray(parsed.finished) ? parsed.finished.filter(isFinished) : [],
    };
  } catch {
    return { watched: [], finished: [] };
  }
}

function writeStorage(next: WatchState): void {
  try {
    window.sessionStorage.setItem(WATCH_STORAGE_KEY, JSON.stringify(next));
  } catch {
    /* blocked storage: the list lives in the module only */
  }
}

let state: WatchState = readStorage();
const listeners = new Set<() => void>();

function setState(next: WatchState): void {
  state = next;
  writeStorage(next);
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

function snapshot(): WatchState {
  return state;
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
  });
}

function dismiss(runId: string): void {
  if (!state.finished.some((f) => f.runId === runId)) return;
  setState({ ...state, finished: state.finished.filter((f) => f.runId !== runId) });
}

let checking = false;

/** Reads every watched run once and moves finished ones. Exported for tests. */
export async function checkWatchedRuns(): Promise<void> {
  if (checking || state.watched.length === 0) return;
  checking = true;
  try {
    const results = await Promise.all(
      state.watched.map(async (w) => ({ w, result: await reviewsApi.reviewRun(w.runId) })),
    );
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
    if (drop.size === 0) return;
    setState({
      watched: state.watched.filter((w) => !drop.has(w.runId)),
      finished: [...state.finished.filter((f) => !done.some((d) => d.runId === f.runId)), ...done],
    });
  } finally {
    checking = false;
  }
}

/** Finished watched reviews, and a way to dismiss each. Polls while any
 *  watched run is still going. */
export function useFinishedReviews(): { finished: FinishedReview[]; dismiss: (runId: string) => void } {
  const current = useSyncExternalStore(subscribe, snapshot, snapshot);
  const anyWatched = current.watched.length > 0;

  useEffect(() => {
    if (!anyWatched) return undefined;
    void checkWatchedRuns();
    const timer = window.setInterval(() => { void checkWatchedRuns(); }, WATCH_POLL_MS);
    return () => window.clearInterval(timer);
  }, [anyWatched]);

  return { finished: current.finished, dismiss };
}

/** TESTS ONLY: reload the store from sessionStorage, as a page refresh would. */
export function reloadWatchStoreForTests(): void {
  checking = false;
  state = readStorage();
  for (const listener of listeners) listener();
}
