import { useCallback, useEffect, useRef, useState } from "react";

import { auth, onSignedOut, setToken } from "./api/client";
import {
  hasAdminCapability,
  Shell,
  useConnection,
  type ThemeMode,
  type ViewId,
} from "./components/Shell";
import { DisconnectedState } from "./components/states";
import { AdminScreen } from "./views/AdminScreen";
import { ChatView } from "./views/ChatView";
import { DashboardView } from "./views/DashboardView";
import { DocumentsView } from "./views/DocumentsView";
import { IngestionView } from "./views/IngestionView";
import { LoginView, RoleBadge, type LoginOutcome } from "./views/LoginView";
import { AnalysisModeScreen } from "./views/AnalysisModeScreen";
import { ReportsScreen } from "./views/ReportsScreen";
import { DeliverablesView } from "./views/DeliverablesView";
import { SubmittalReviewView } from "./views/SubmittalReviewView";
import type { AuthStatus, Me } from "./types/api";
import { parseRoute, pathForView, titleForView, type AppRoute } from "./routing";

//: One key, named once. A typo in a second literal is a preference that
//: silently never persists.
const THEME_KEY = "rag-intelligence-theme";

//: The key this app wrote before the product rename. READ ONCE, NEVER WRITTEN.
//: Dropping it outright would silently put every user who had chosen light mode
//: back into dark: the new key reads `null`, the code falls through to the
//: "dark" default, and nothing errors. No test can catch it either - tests
//: start from an empty localStorage, where both keys behave identically. The
//: effect below writes the new key on mount, so the value migrates on first
//: load; this line can be deleted once no browser in use still holds it.
const LEGACY_THEME_KEY = "nabaa-theme";

/** Whether this deployment wants a sign-in, and who is signed in.
 *
 *  `checking` matters: rendering the login form while the answer is still in
 *  flight shows a sign-in screen to a deployment that has authentication
 *  switched off, which is worse than a moment of nothing.
 *
 *  `unknown` matters more. It is what happens when the backend cannot be
 *  reached at all, and it must NOT hold the screen blank: the connection
 *  banner owns that condition and has to be visible to own it. Without this
 *  state the whole app rendered nothing whenever the API was down - a blank
 *  page where there used to be "the backend is not running".
 */
type Session =
  | { s: "checking" }
  | { s: "unknown" }
  | { s: "disabled" }
  | { s: "required"; me: Me | null };

export default function App({ initialView = "documents" }: { initialView?: ViewId } = {}) {
  // The view the app opens on. A prop rather than a hard-coded literal so that
  // "the reader is somehow already on this view" is expressible - which is the
  // only way to assert that the admin gate is the gate, rather than the
  // absence of a navigation button being the gate. There is no router yet; if
  // one lands, this is where a deep link arrives.
  const [route, setRoute] = useState<AppRoute>(() => {
    // Unit tests intentionally render isolated views without owning the
    // browser address bar. Production builds always follow the URL.
    if (import.meta.env.MODE === "test") return { kind: "view", view: initialView };
    if (initialView !== "documents") return { kind: "view", view: initialView };
    return parseRoute(window.location.pathname);
  });
  const view = route.kind === "view" ? route.view : initialView;
  const onNavigate = useCallback((next: ViewId, recordId?: string) => {
    const nextPath = pathForView(next, recordId);
    if (import.meta.env.MODE !== "test") window.history.pushState({ __epcRoute: true }, "", nextPath);
    setRoute({ kind: "view", view: next, recordId });
  }, []);
  useEffect(() => {
    const onPopState = () => setRoute(parseRoute(window.location.pathname));
    window.addEventListener("popstate", onPopState);
    return () => {
      window.removeEventListener("popstate", onPopState);
      // Test renders mount/unmount the whole app repeatedly. Do not let a
      // previous in-memory navigation change the next independent render;
      // real browser refreshes and pasted links still use their URL normally.
      if (window.history.state?.__epcRoute) window.history.replaceState({}, "", "/");
    };
  }, []);
  useEffect(() => {
    document.title = route.kind === "forbidden" ? "Access denied · EPC Intelligence" : titleForView(route.view);
  }, [route]);
  const { connection, recheck } = useConnection();
  const [session, setSession] = useState<Session>({ s: "checking" });

  // The bearer token, mirrored here ONLY so the admin screen can be handed one.
  //
  // api/client.ts owns the token and deliberately exposes no getter (it is a
  // module-level variable, never localStorage), and AdminScreen's transport
  // needs to attach it. This is the same value that was just passed to
  // setToken, held in a ref rather than state so that reading it never causes
  // a render, and cleared everywhere the client's copy is cleared. It is not
  // persisted and not logged.
  const tokenRef = useRef<string | null>(null);
  // Stable across renders on purpose: AdminScreen memoises its transport on
  // this identity, and a fresh arrow each render would rebuild the client,
  // re-run its load effect and re-render forever.
  const readToken = useCallback(() => tokenRef.current, []);

  // The mode is discovered from the API, never from /api/health - health is
  // unauthenticated and was narrowed deliberately, and putting auth_mode on it
  // would re-widen exactly the surface that was reduced.
  const check = useCallback(async () => {
    const r = await auth.me();
    if (r.ok) {
      setSession(r.data.required ? { s: "required", me: r.data.user } : { s: "disabled" });
    } else if (r.disconnected) {
      // A disconnected backend is NOT a signed-out user, and it is not a
      // reason to render nothing. Hand the screen to the connection banner,
      // which is what distinguishes "backend offline" from "wrong password".
      setSession({ s: "unknown" });
    } else if (r.error.code === "unauthenticated") {
      setSession({ s: "required", me: null });
    } else {
      setSession({ s: "unknown" });
    }
  }, []);

  useEffect(() => {
    void check();
  }, [check]);

  // Ask again once the backend comes back, so a reader who started the app
  // before the API was up is not left permanently unidentified.
  useEffect(() => {
    if (connection.state === "online" && session.s === "unknown") void check();
  }, [connection.state, session.s, check]);

  // The client clears the token on any 401 and calls this. No auto-retry and
  // no refresh flow: there is no refresh token by design.
  useEffect(() => {
    onSignedOut(() => {
      tokenRef.current = null;
      setSession({ s: "required", me: null });
    });
    return () => onSignedOut(null);
  }, []);

  const signIn = useCallback(
    async ({ email, password }: { email: string; password: string }): Promise<LoginOutcome> => {
      const r = await auth.login(email, password);
      if (r.ok) {
        setToken(r.data.token);
        tokenRef.current = r.data.token;
        setSession({ s: "required", me: r.data.user });
        return { ok: true };
      }
      if (r.disconnected) return { ok: false, kind: "offline" };
      return {
        ok: false,
        kind: r.error.code === "rate_limited" ? "rate_limited" : "credentials",
        message: r.error.message,
      };
    },
    [],
  );

  const signOut = useCallback(() => {
    setToken(null);
    tokenRef.current = null;
    setSession({ s: "required", me: null });
  }, []);

  const resetPassword = useCallback(async (resetToken: string, password: string) => {
    const result = await auth.resetPassword(resetToken, password);
    if (result.ok) return { ok: true as const };
    if (result.disconnected) return { ok: false as const, message: "The backend is not running." };
    return { ok: false as const, message: result.error.message };
  }, []);

  // NOT a blank screen while the check is in flight. A blank page is
  // indistinguishable from a crash, and this one resolves in milliseconds on
  // loopback. The app renders, claims no identity, and swaps to the login
  // screen only once the backend has actually said a sign-in is required.
  //
  // Under `demo_required` an unauthenticated caller's requests resolve to an
  // empty scope, so the momentary views are empty rather than leaky.

  // The login screen sits ABOVE the Shell, not inside it, so it carries no
  // navigation to views the reader cannot reach. `connected` is passed
  // through because "the backend is down" and "that password is wrong" must
  // never look like the same failure.

  //: Dark or light, remembered across reloads.
  //:
  //: The toggle in the Shell was wired to a handler nobody supplied, so
  //: clicking it changed a value that went nowhere. The [data-theme] blocks in
  //: index.css were complete and correct and simply unreachable.
  //:
  //: Stamping the attribute does MORE than switch the toggle on. The bare
  //: @theme block still carries the pre-redesign palette - ground #070b10,
  //: secondary #7d90a4 at 4.1:1, below the accessibility floor for the sizes
  //: it is used at. The CORRECTED dark values live in [data-theme="dark"], so
  //: until something stamps, every reader gets the old contrast whether or not
  //: they ever touch the toggle.
  const [theme, setTheme] = useState<ThemeMode>(() => {
    // A private window throws on READ, not just on write, so the fallback has
    // to sit around the read as well.
    try {
      const saved =
        localStorage.getItem(THEME_KEY) ?? localStorage.getItem(LEGACY_THEME_KEY);
      return saved === "light" || saved === "dark" ? saved : "dark";
    } catch {
      return "dark";
    }
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    // A forgotten preference is a nuisance; a crash on a blocked storage API
    // is a broken app. The theme still applies for this session either way.
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* storage unavailable - not worth telling the reader about */
    }
  }, [theme]);

  // `/api/auth/me`'s answer, reassembled. `checking` and `unknown` are null:
  // the question has not been answered, and an unanswered question grants
  // nothing.
  const authStatus: AuthStatus | null =
    session.s === "disabled"
      ? { required: false, user: null }
      : session.s === "required"
        ? { required: true, user: session.me }
        : null;

  // The single decision. Both the navigation entry and the screen itself read
  // THIS - so there is no arrangement of view state in which one exists
  // without the other.
  const canAdmin = hasAdminCapability(authStatus);

  if (session.s === "required" && session.me === null) {
    return <LoginView onLogin={signIn} onResetPassword={resetPassword}
      connected={connection.state !== "offline"} />;
  }

  return (
    <Shell
      view={view}
      onNavigate={onNavigate}
      connection={connection}
      auth={authStatus}
      theme={theme}
      onThemeChange={setTheme}
      identity={
        // Nothing is claimed while the backend is unreachable. "Authentication
        // disabled" is a statement about the deployment, and it must not be
        // made on the strength of a request that never arrived.
        session.s === "unknown" || session.s === "checking" ? undefined : (
          <RoleBadge
            me={session.s === "required" ? session.me : null}
            onLogout={signOut}
          />
        )
      }
    >
      {/* ONE connection-level error at a time. With the backend down this
          rendered its banner AND let the view render its own failed-request
          card, so an amber "backend is not running" and a red "HTTP 502"
          appeared together. The shell owns this condition; the view is not
          rendered at all while it holds. */}
      {connection.state === "offline" ? (
        <DisconnectedState onRetry={recheck} />
      ) : route.kind === "forbidden" ? (
        <main className="mx-auto w-full max-w-3xl px-4 py-10" role="alert">
          <h1 className="text-2xl font-semibold text-slateish-100">This address cannot be opened</h1>
          <p className="mt-2 text-sm text-slateish-300">
            The address <code className="rounded bg-ink-800 px-1.5 py-0.5">{route.path}</code> is not an available workspace route.
            The backend still enforces authorization; no data was exposed.
          </p>
        </main>
      ) : (
        <>
          {view === "documents" && (
            <DocumentsView connection={connection} onRetryConnection={recheck} isAdmin={canAdmin} />
          )}
          {view === "chat" && (
            <ChatView connection={connection} onRetryConnection={recheck} onNavigate={onNavigate} />
          )}
          {view === "ingestion" && (
            <IngestionView connection={connection} onRetryConnection={recheck} />
          )}
          {view === "dashboard" && (
            <DashboardView connection={connection} onRetryConnection={recheck} />
          )}
          {view === "analysis" && <AnalysisModeScreen />}
          {view === "reports" && <ReportsScreen />}
          {view === "deliverables" && <DeliverablesView />}
          {view === "review" && <SubmittalReviewView onNavigate={onNavigate} />}
          {/* `canAdmin &&` is the gate, not the absence of a nav entry. Setting
              the view to "admin" by any other means - a stale state value, a
              devtools poke - renders nothing at all. The server is the real
              boundary (every /api/admin route 404s a non-admin), and this is
              the UI keeping the same answer. */}
          {view === "admin" && canAdmin && <AdminScreen tokenProvider={readToken} />}
        </>
      )}
    </Shell>
  );
}
