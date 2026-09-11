/**
 * Poll fast while something is happening, slowly while nothing is.
 *
 * The Documents screen polled every 3 seconds whether or not the worker was
 * doing anything: 20 requests a minute against a 15 W CPU that is also
 * answering questions, forever, on an idle corpus.
 *
 * WHY A HOOK AND NOT A CONSTANT. The two screens that need this have
 * different "busy" signals - Documents can see it in the document list it
 * already has, Ingestion reads the worker - and both must return to the fast
 * interval the instant an upload starts, without waiting out a 30 second
 * tick. Putting the rule in one place is what makes both of those testable.
 *
 * STRICTMODE. React double-invokes effects in development, so an effect that
 * creates a timer and does not clear it leaks one on every mount - and every
 * navigation between screens is a mount. The cleanup here clears the interval
 * AND flips a cancelled flag, because an in-flight request can resolve after
 * the timer is gone and would otherwise set state on an unmounted component.
 * `usePoll.test.ts` mounts under StrictMode and asserts the timer count
 * returns to zero.
 */
import { useEffect, useRef } from "react";

/** Something is happening: poll fast. */
export const FAST_MS = 3000;

/** Nothing is happening. Still polls, because work can start elsewhere - an
 *  upload from another tab, a worker picking up a queued document - and a
 *  screen that never refreshes is a screen that lies until reloaded. */
export const IDLE_MS = 30000;

export function pollInterval(busy: boolean): number {
  return busy ? FAST_MS : IDLE_MS;
}

/**
 * Run `tick` immediately, then on an interval that follows `busy`.
 *
 * Changing `busy` restarts the interval, so going busy polls again within
 * milliseconds rather than after the remaining idle wait.
 */
export function usePoll(tick: () => void, busy: boolean): void {
  // The callback is held in a ref so a new function identity on every render
  // does not restart the timer - only `busy` does. Without this the interval
  // would be torn down and rebuilt on every state update, which polls far
  // more often than either constant says.
  const latest = useRef(tick);
  useEffect(() => {
    latest.current = tick;
  }, [tick]);

  // `repeat=false` (tests and static previews) must run the tick exactly
  // ONCE, on mount, and never again - not even if `busy` changes after that
  // first call resolves. `busy` used to sit in this effect's own dependency
  // array unconditionally, so a caller whose "busy" signal is derived from
  // the tick's own result (Documents: not-yet-settled documents) flipped it
  // after the first fetch came back, tore the effect down, and reran it -
  // a second, unwanted fetch a test never asked for and could race against.
  // Splitting the two concerns into separate effects, keyed on `repeat`
  // itself rather than folded into one shared dependency array, is what
  // keeps the run-once path un-triggerable by anything but a real remount.
  useEffect(() => {
    if (repeat) return;
    latest.current();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repeat]);

  useEffect(() => {
    if (!repeat) return;
    let cancelled = false;
    const run = () => {
      if (!cancelled) latest.current();
    };
    run();
    const timer = window.setInterval(run, pollInterval(busy));
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [busy]);
}
