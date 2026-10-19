import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { auth, onSignedOut, setToken } from "./api/client";
import {
  hasAdminCapability,
  Shell,
  useConnection,
  type ThemeMode,
  type ViewId,
} from "./components/Shell";
import { DisconnectedState } from "./components/states";
import { CommandPalette } from "./components/CommandPalette";
import { AdminScreen } from "./views/AdminScreen";
import { ChatView } from "./views/ChatView";
import { RecentChats } from "./components/chat/RecentChats";
import { DashboardView } from "./views/DashboardView";
import { StandardsView } from "./views/StandardsView";
import { DocumentsView } from "./views/DocumentsView";
import { IngestionView } from "./views/IngestionView";
import { LoginView, RoleBadge, type LoginOutcome } from "./views/LoginView";
import { AnalysisModeScreen } from "./views/AnalysisModeScreen";
import { ReportsScreen } from "./views/ReportsScreen";
import { DeliverablesView } from "./views/DeliverablesView";
import { SubmittalsLandingView } from "./views/SubmittalsLandingView";
import type { AuthStatus, Me } from "./types/api";
import { FinishedReviewNotice } from "./components/review/workspace/FinishedReviewNotice";
import { clearWatchedReviews, setWatchOwner } from "./components/review/workspace/reviewWatch";
import { ReviewWorkspace } from "./components/review/workspace/ReviewWorkspace";
import { WORKSPACE_PANEL, reviewPageFor, workspaceSearch } from "./components/review/workspace/workspaceRoute";
import type { WorkspaceLocation, WorkspaceTab } from "./components/review/workspace/contract";
import { LeaveConfirm } from "./components/review/workspace/LeaveConfirm";
import { type LeaveSaver, LeaveSaverContext, useLeaveGuard } from "./components/review/workspace/useLeaveGuard";
import { CrsDraftContext, clearDecisionDrafts, keepOnlyDraftsOf, setDraftOwner } from "./components/review/crs/useCrsDecisions";
import { NavigationContext } from "./components/NavLink";
import { parseRoute, pathForView, titleForView, type AppRoute } from "./routing";

//: One key, named once. A typo in a second literal is a preference that
//: silently never persists.
const THEME_KEY = "rag-intelligence-theme";

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
  // Workspace v2: the query string keeps the reader's place on the review
  // workspace (tab, open row, panel). Read from the address on load, exactly
  // like the route, so a refresh - or a sign-in in between, which sits above
  // the Shell and leaves this state alone - lands in the same place.
  const [search, setSearch] = useState<string>(() => {
    if (import.meta.env.MODE === "test" || initialView !== "documents") return "";
    return window.location.search;
  });
  const view = route.kind === "view" ? route.view : initialView;
  // v2.1 (N1): the address the app is showing now, so a Back press that
  // the reader takes back (unsaved decisions, "Stay here") can put it back.
  const shownAddress = useRef<string>(
    import.meta.env.MODE === "test" ? "/" : window.location.pathname + window.location.search);
  const onNavigate = useCallback((next: ViewId, recordId?: string, panel?: string) => {
    const nextPath = pathForView(next, recordId, panel);
    if (import.meta.env.MODE !== "test") window.history.pushState({ __epcRoute: true }, "", nextPath);
    shownAddress.current = nextPath;
    setSearch("");
    setRoute({ kind: "view", view: next, recordId, ...(panel ? { panel } : {}) });
  }, []);
  // The owner replaced the old review design permanently (19 Oct 2026):
  // every review address opens the workspace or its first page. Old
  // screens' addresses are mapped in ONE place (workspaceRoute.reviewPageFor)
  // and replaced in the address bar below, so old bookmarks still work.
  const reviewPage = useMemo(() => (
    route.kind === "view" && route.view === "review" ? reviewPageFor(route.recordId, route.panel, search) : null
  ), [route, search]);
  const workspaceLocation: WorkspaceLocation | null = reviewPage?.kind === "workspace" ? reviewPage.location : null;
  // Only the workspace's own address keeps its third segment.
  const workspacePanel = route.kind === "view" && route.panel === WORKSPACE_PANEL ? WORKSPACE_PANEL : undefined;
  // An old screen's address (or the old inbox): show where it now leads,
  // without a new history entry.
  useEffect(() => {
    if (!reviewPage?.redirected) return;
    const url = new URL(reviewPage.address, window.location.origin);
    window.history.replaceState({ ...(window.history.state ?? {}), __epcRoute: true }, "", reviewPage.address);
    shownAddress.current = reviewPage.address;
    setSearch(url.search);
    setRoute(parseRoute(url.pathname));
  }, [reviewPage]);
  // Tab / row / panel changes replace the address: no new history entry.
  const onWorkspaceLocationChange = useCallback((next: WorkspaceLocation) => {
    const nextSearch = workspaceSearch(next);
    const nextPath = pathForView("review", next.runId, workspacePanel) + nextSearch;
    window.history.replaceState({ ...(window.history.state ?? {}), __epcRoute: true }, "", nextPath);
    shownAddress.current = nextPath;
    setSearch(nextSearch);
  }, [workspacePanel]);
  // Links from the workspace's own pieces (the finished notice, "Review
  // again"): the plain run address opens the workspace.
  const openRunInWorkspace = useCallback((runId: string) => onNavigate("review", runId), [onNavigate]);
  // v2.2: "Preview CRS" on the first page opens a review straight on one tab.
  const openRunOnTab = useCallback((runId: string, tab: WorkspaceTab) => {
    const nextSearch = workspaceSearch({ runId, tab, row: null, panel: null, documentId: null });
    const nextPath = pathForView("review", runId) + nextSearch;
    if (import.meta.env.MODE !== "test") window.history.pushState({ __epcRoute: true }, "", nextPath);
    shownAddress.current = nextPath;
    setSearch(nextSearch);
    setRoute({ kind: "view", view: "review", recordId: runId });
  }, []);
  // Decisions on the workspace screen that are not saved yet (it reports
  // them; 0 on every other screen).
  const workspaceUnsaved = useRef(0);
  const onWorkspaceUnsaved = useCallback((count: number) => { workspaceUnsaved.current = count; }, []);
  // v2.1 (N1): THE ONE NAVIGATION GUARD. Every way out of the workspace
  // below asks through it, in the page, while anything is unsaved; the
  // decisions are also kept as a draft in this tab (useCrsDecisions), so
  // leaving loses nothing. The workspace's own buttons (its "Reviews" link,
  // "Review again", "Open" on a past review) ask through this same guard
  // (its `leaveGuard` prop), so they get the plain `onNavigate` and are
  // never asked twice.
  // v2.1 round 2: the workspace's automatic saving puts its "save now" here
  // (LeaveSaverContext), so the question can offer "Save and leave".
  const workspaceSaver = useRef<LeaveSaver | null>(null);
  const registerWorkspaceSaver = useCallback((save: LeaveSaver | null) => { workspaceSaver.current = save; }, []);
  const saveWorkspace = useCallback(
    () => (workspaceSaver.current ? workspaceSaver.current() : Promise.resolve(false)), []);
  const leaveGuard = useLeaveGuard(() => workspaceUnsaved.current, saveWorkspace);
  const { guard } = leaveGuard;
  const guardedNavigate = useCallback((next: ViewId, recordId?: string, panel?: string) => {
    guard("navigate", () => onNavigate(next, recordId, panel));
  }, [guard, onNavigate]);
  // "Open it" on the finished notice leaves whatever screen the reader is
  // on, the workspace included, so it goes through the guard. False tells
  // the notice the reader has not left (yet), so it stays on screen.
  const openFinishedRun = useCallback((runId: string): boolean =>
    guard("navigate", () => openRunInWorkspace(runId)), [guard, openRunInWorkspace]);
  // Browser Back / Forward. The address has already changed when this
  // fires, so with unsaved decisions it is put back first (one entry on
  // top of where Back pointed); the reader's answer then decides. "Leave"
  // steps back off that entry (history.back, the next popstate shown
  // without asking): pushing a second entry would leave the review's
  // address behind it, and the next Back would open the review again.
  const guardRef = useRef(guard);
  useEffect(() => { guardRef.current = guard; }, [guard]);
  const skipNextPop = useRef(false);
  useEffect(() => {
    const show = (address: string) => {
      const url = new URL(address, window.location.origin);
      shownAddress.current = url.pathname + url.search;
      setSearch(url.search);
      setRoute(parseRoute(url.pathname));
    };
    const onPopState = () => {
      const target = window.location.pathname + window.location.search;
      if (skipNextPop.current) { skipNextPop.current = false; show(target); return; }
      const before = shownAddress.current;
      const samePage = new URL(before, window.location.origin).pathname === window.location.pathname;
      if (samePage || workspaceUnsaved.current <= 0) { show(target); return; }
      window.history.pushState({ __epcRoute: true }, "", before);
      guardRef.current("back", () => {
        // Step back onto where Back pointed; that popstate only shows it.
        skipNextPop.current = true;
        window.history.back();
      });
    };
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
    document.title = route.kind === "forbidden" ? "Access denied · RAG Intelligence System" : titleForView(route.view);
  }, [route]);
  const { connection, recheck } = useConnection();
  // The conversation open on the Chat screen, held here because two places
  // choose it: the chat itself (a new conversation) and the recent-chats list
  // in the navigation.
  const [chatId, setChatId] = useState<string | null>(null);
  const [chatVersion, setChatVersion] = useState(0);
  const bumpChats = useCallback(() => setChatVersion((v) => v + 1), []);
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
      // Whose decision drafts may come back, said BEFORE the workspace can
      // draw (it reads its draft as it first draws).
      if (!r.data.required) setDraftOwner(null);
      else if (r.data.user) {
        setDraftOwner(r.data.user.id);
        keepOnlyDraftsOf(r.data.user.id);
      }
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

  // The watch list belongs to whoever is signed in (no one with sign-in off).
  const watchOwner = session.s === "required" ? session.me?.id ?? null : null;
  const watchOwnerKnown = session.s === "disabled" || (session.s === "required" && session.me !== null);
  useEffect(() => {
    if (watchOwnerKnown) setWatchOwner(watchOwner);
  }, [watchOwner, watchOwnerKnown]);

  // The client clears the token on any 401 and calls this. No auto-retry and
  // no refresh flow: there is no refresh token by design.
  // v2.1 (N1): a sign-in that ran out keeps the decision drafts (they are
  // kept under the person's id): signing in again as the same person brings
  // them back on the same review. Only a chosen sign-out removes them.
  useEffect(() => {
    onSignedOut(() => {
      tokenRef.current = null;
      clearWatchedReviews();
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
        setDraftOwner(r.data.user?.id ?? null);
        // Another person's draft (their sign-in ran out on this tab) goes.
        keepOnlyDraftsOf(r.data.user?.id ?? null);
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
    // The "review ready" list names files: the next person to sign in on
    // this tab must not see the last person's.
    clearWatchedReviews();
    // The reader chose to sign out (and was asked first if anything was
    // unsaved): their decision drafts in this tab go too.
    clearDecisionDrafts();
    setSession({ s: "required", me: null });
  }, []);
  const guardedSignOut = useCallback(() => { guard("signout", signOut); }, [guard, signOut]);

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
    <NavigationContext.Provider value={guardedNavigate}>
    <Shell
      view={view}
      onNavigate={guardedNavigate}
      connection={connection}
      auth={authStatus}
      theme={theme}
      onThemeChange={setTheme}
      navExtra={
        // Recent chats live in the navigation, on the Chat screen only: the
        // conversation list used to take a column of the chat itself.
        view === "chat" && route.kind !== "forbidden" && connection.state !== "offline" ? (
          <RecentChats
            currentId={chatId}
            version={chatVersion}
            onOpen={setChatId}
            onNew={() => setChatId(null)}
            onDeleted={(id) => setChatId((c) => (c === id ? null : c))}
          />
        ) : undefined
      }
      identity={
        // Nothing is claimed while the backend is unreachable. "Authentication
        // disabled" is a statement about the deployment, and it must not be
        // made on the strength of a request that never arrived.
        session.s === "unknown" || session.s === "checking" ? undefined : (
          <RoleBadge
            me={session.s === "required" ? session.me : null}
            onLogout={guardedSignOut}
          />
        )
      }
    >
      {/* Workspace v2: "Your review is ready" on any page (it renders
          nothing until a watched review finishes). */}
      <FinishedReviewNotice onOpenRun={openFinishedRun} panelOpen={workspaceLocation?.panel === "evidence"} />
      {/* v2.1 (N1): the guard's question, in the page. */}
      <LeaveConfirm pending={leaveGuard.pending} onLeave={leaveGuard.leave} onStay={leaveGuard.stay}
        onSaveAndLeave={leaveGuard.saveAndLeave} saving={leaveGuard.saving} saveError={leaveGuard.saveError} />
      {/* ONE connection-level error at a time. With the backend down this
          rendered its banner AND let the view render its own failed-request
          card, so an amber "backend is not running" and a red "HTTP 502"
          appeared together. The shell owns this condition; the view is not
          rendered at all while it holds. */}
      {/* The chat is the one view that holds state the server cannot hand
          back on a reload: the transcript on screen and a request in flight.
          Unmounting it for an outage threw both away and replayed its entrance
          animation on recovery, so it stays mounted - HIDDEN, not shown beside
          the banner, which keeps the one-error-at-a-time rule above. */}
      {view === "chat" && route.kind !== "forbidden" && (
        <div className="contents" hidden={connection.state === "offline"}>
          <ChatView
            connection={connection}
            onRetryConnection={recheck}
            onNavigate={onNavigate}
            conversationId={chatId}
            onConversationChange={setChatId}
            onListChanged={bumpChats}
          />
        </div>
      )}
      {connection.state === "offline" ? (
        <DisconnectedState onRetry={recheck} />
      ) : route.kind === "forbidden" ? (
        <section className="mx-auto w-full max-w-3xl px-4 py-10" role="alert" aria-labelledby="forbidden-title">
          <h1 id="forbidden-title" className="text-2xl font-semibold text-slateish-100">This address cannot be opened</h1>
          <p className="mt-2 text-sm text-slateish-300">
            The address <code className="rounded bg-ink-800 px-1.5 py-0.5">{route.path}</code> is not an available workspace route.
            The backend still enforces authorization; no data was exposed.
          </p>
        </section>
      ) : (
        <>
          <CommandPalette onNavigate={guardedNavigate} auth={authStatus} connection={connection} />
          {view === "documents" && (
            <DocumentsView connection={connection} onRetryConnection={recheck} isAdmin={canAdmin} />
          )}
          {view === "ingestion" && (
            <IngestionView connection={connection} onRetryConnection={recheck} />
          )}
          {view === "dashboard" && (
            <DashboardView
              connection={connection} onRetryConnection={recheck}
              onOpenReview={(runId) => onNavigate("review", runId)}
              onOpenDocuments={() => onNavigate("documents")}
              onOpenDeliverables={() => onNavigate("deliverables")}
              isAdmin={canAdmin}
            />
          )}
          {view === "standards" && <StandardsView isAdmin={canAdmin} />}
          {view === "analysis" && <AnalysisModeScreen />}
          {view === "reports" && <ReportsScreen />}
          {view === "deliverables" && <DeliverablesView />}
          {/* The review workspace replaced the old review design
              permanently (owner, 19 Oct 2026): `/review` is its first page,
              `/review/<run>` (and `/review/<run>/workspace`) the workspace.
              Old screens' addresses lead here through reviewPageFor. */}
          {view === "review" && workspaceLocation && (
            /* v2.1 (N1): decisions not saved yet are kept as a draft
               for this review in this tab. */
            <CrsDraftContext.Provider value={workspaceLocation.runId}>
              <LeaveSaverContext.Provider value={registerWorkspaceSaver}>
              <ReviewWorkspace
                key={workspaceLocation.runId} location={workspaceLocation}
                onLocationChange={onWorkspaceLocationChange}
                onBack={() => onNavigate("review")}
                onOpenRun={openRunInWorkspace}
                onUnsavedChange={onWorkspaceUnsaved}
                leaveGuard={guard}
                isAdmin={canAdmin}
              />
              </LeaveSaverContext.Provider>
            </CrsDraftContext.Provider>
          )}
          {view === "review" && reviewPage?.kind === "landing" && (
            <SubmittalsLandingView
              workspace isAdmin={canAdmin}
              onOpenRun={(runId) => onNavigate("review", runId)}
              onOpenRunTab={openRunOnTab}
            />
          )}
          {/* `canAdmin &&` is the gate, not the absence of a nav entry. Setting
              the view to "admin" by any other means - a stale state value, a
              devtools poke - renders nothing at all. The server is the real
              boundary (every /api/admin route 404s a non-admin), and this is
              the UI keeping the same answer. */}
          {view === "admin" && canAdmin && <AdminScreen tokenProvider={readToken} />}
        </>
      )}
    </Shell>
    </NavigationContext.Provider>
  );
}
