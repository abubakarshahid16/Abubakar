/**
 * "Sign-in expired, sign in again": the one place that decides to say it (order 4b).
 *
 * Every transport already reports a 401 to one place (`signOutOn401`, api/core),
 * which App hands to `on401` here. So a poll, a save, a page image and an upload
 * all end the same way, and a poll that swallows its own error cannot hide it.
 *
 * ARMED ONLY WHILE SIGNED IN. The server's switch (SESSION_EXPIRED_NOTICE_ENABLED)
 * arrives on the signed-in user. Not armed means no notice: the switch is off,
 * the page opened with no sign-in, or the reader chose to sign out (a late 401
 * from a request already sent is not an expiry). The first 401 disarms, so any
 * number of them show one notice; the sign-in form then replaces the screen, and
 * its pollers stop with it. A 403 never gets here.
 *
 * THE HEARTBEAT. Outside `/api/reviews`, `/api/metrics` and the other gated routes
 * an expired sign-in gets no 401: the server answers a read with an empty scope,
 * so the library looks empty and a poll sees nothing wrong. While armed, `/auth/me`
 * is asked at the idle pace (skipped while the tab is hidden, at once when shown).
 * Off, no timer exists and no request is made.
 */
import { useCallback, useRef, useState } from "react";

import { auth } from "../api/client";
import type { Me } from "../types/api";
import { usePoll } from "./usePoll";

export interface SessionExpired {
  /** Decisions not saved when it happened; the tab keeps them as a draft. */
  unsaved: number;
}

export function useSessionExpiry(unsaved: () => number) {
  const armed = useRef(false);
  const [watching, setWatching] = useState(false);
  const [expired, setExpired] = useState<SessionExpired | null>(null);

  /** Say who is signed in now (null: nobody, by choice). Clears any notice. */
  const signedInAs = useCallback((me: Me | null) => {
    armed.current = me?.session_expired_notice === true;
    setWatching(armed.current);
    setExpired(null);
  }, []);

  const on401 = useCallback(() => {
    if (!armed.current) return;
    armed.current = false;
    setWatching(false);
    setExpired({ unsaved: unsaved() });
  }, [unsaved]);

  usePoll(() => {
    if (armed.current) void auth.me();
  }, false, watching);

  return { expired, signedInAs, on401 };
}
