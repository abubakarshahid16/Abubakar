import { useCallback, useEffect, useState } from "react";

import { auth, onSignedOut, setToken } from "./api/client";
import { Shell, useConnection, type ThemeMode, type ViewId } from "./components/Shell";
import { DisconnectedState } from "./components/states";
import { ChatView } from "./views/ChatView";
import { DashboardView } from "./views/DashboardView";
import { DocumentsView } from "./views/DocumentsView";
import { IngestionView } from "./views/IngestionView";
import { LoginView, RoleBadge, type LoginOutcome } from "./views/LoginView";
import { AnalysisModeScreen } from "./views/AnalysisModeScreen";
import { ReportsScreen } from "./views/ReportsScreen";
import type { Me } from "./types/api";

//: One key, named once. A typo in a second literal is a preference that
//: silently never persists.
const THEME_KEY = "nabaa-theme";

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

export default function App() {
  const [view, setView] = useState<ViewId>("documents");
  const { connection, recheck } = useConnection();
  const [session, setSession] = useState<Session>({ s: "checking" });

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
    onSignedOut(() => setSession({ s: "required", me: null }));
    return () => onSignedOut(null);
  }, []);

  const signIn = useCallback(
    async ({ email, password }: { email: string; password: string }): Promise<LoginOutcome> => {
      const r = await auth.login(email, password);
      if (r.ok) {
        setToken(r.data.token);
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
    setSession({ s: "required", me: null });
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
      const saved = localStorage.getItem(THEME_KEY);
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

  if (session.s === "required" && session.me === null) {
    return <LoginView onLogin={signIn} connected={connection.state !== "offline"} />;
  }

  return (
    <Shell
      view={view}
      onNavigate={setView}
      connection={connection}
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
      ) : (
        <>
          {view === "documents" && (
            <DocumentsView connection={connection} onRetryConnection={recheck} />
          )}
          {view === "chat" && (
            <ChatView connection={connection} onRetryConnection={recheck} />
          )}
          {view === "ingestion" && (
            <IngestionView connection={connection} onRetryConnection={recheck} />
          )}
          {view === "dashboard" && (
            <DashboardView connection={connection} onRetryConnection={recheck} />
          )}
          {view === "analysis" && <AnalysisModeScreen />}
          {view === "reports" && <ReportsScreen />}
        </>
      )}
    </Shell>
  );
}
