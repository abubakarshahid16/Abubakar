/**
 * Application shell: sidebar, Sunday POC navigation, and the connection banner.
 *
 * Documents, Chat and Dashboard are built. Ingestion is listed but visibly
 * marked, so the navigation never implies capability that does not exist.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { api, type Health } from "../api/client";
import type { AuthStatus } from "../types/api";

export type ViewId =
  | "documents"
  | "chat"
  | "analysis"
  | "ingestion"
  | "dashboard"
  | "reports"
  | "deliverables"
  | "admin"
  | "standards"
  | "review";

export type ThemeMode = "dark" | "light";
export type DensityMode = "comfortable" | "compact";

interface NavItem {
  id: ViewId;
  label: string;
  hint: string;
  built: boolean;
}

export const NAV: NavItem[] = [
  { id: "dashboard", label: "Dashboard", hint: "Metrics, models, readiness", built: true },
  { id: "review", label: "AI Submittal Review", hint: "Upload, AI review, findings, CRS", built: true },
  { id: "documents", label: "Documents", hint: "Upload, inspect, verify", built: true },
  { id: "standards", label: "Standards Library", hint: "Clauses, requirements, revisions", built: true },
  { id: "analysis", label: "Analysis Hub", hint: "Summary, gaps, advice", built: true },
  { id: "chat", label: "Document Q&A", hint: "Ask questions with citations", built: true },
  { id: "reports", label: "CRS & Reports", hint: "Frozen evidence, as PDF", built: true },
  { id: "deliverables", label: "Deliverables", hint: "WBS, revisions, due dates", built: true },
  { id: "ingestion", label: "Ingestion", hint: "Queue and throughput", built: true },
];

/** The one role name that means "may administer". `admin` is a CAPABILITY and
 *  not a discipline: it is a row in `roles` like any other, which is why
 *  `Me.roles` can carry both `IT` and `admin` for the same person. The backend
 *  says the same thing in `backend/app/admin.py` (`ADMIN_ROLE`). */
export const ADMIN_CAPABILITY = "admin";

/** The admin entry, kept out of NAV so that the six entries every reader gets
 *  stay a plain constant and the conditional one is impossible to render by
 *  accident. */
export const ADMIN_NAV: NavItem = {
  id: "admin",
  label: "Administration",
  hint: "Users, disciplines, access",
  built: true,
};

/**
 * Whether the caller holds the admin capability, ACCORDING TO THE API.
 *
 * The only input is the body of `/api/auth/me` - `Me.roles`, which is the one
 * field in the identity contract that carries this. Nothing here is inferred
 * from an email address, a display name, or anything else the client could
 * decide for itself.
 *
 * `null` (the answer has not arrived, or the backend could not be reached) is
 * NOT admin. An unanswered question is not a yes.
 *
 * The `required: false` case is a yes, and deliberately so: under
 * `AUTH_MODE=disabled` the backend's own `admin.current_admin` lets an
 * unidentified caller through, because under that mode every caller already
 * reads every document. A UI stricter than the routes it fronts would hide a
 * screen that the server is willing to serve, which is the exact defect this
 * change exists to remove. It is still the API's answer, not a guess: the
 * deployment said authentication is off.
 */
export function hasAdminCapability(auth: AuthStatus | null | undefined): boolean {
  if (!auth) return false;
  if (!auth.required) return true;
  return (auth.user?.roles ?? []).includes(ADMIN_CAPABILITY);
}

/** The navigation this caller gets. The admin entry is APPENDED, never
 *  disabled and never hidden with a class - a non-admin's DOM does not
 *  contain it at all, so there is nothing to un-hide with a devtools edit. */
export function navFor(auth: AuthStatus | null | undefined): NavItem[] {
  return hasAdminCapability(auth) ? [...NAV, ADMIN_NAV] : NAV;
}

export type Connection =
  | { state: "connecting" }
  | { state: "online"; health: Health; at: number }
  | { state: "offline"; since: number; lastHealth: Health | null };

/** Polls health. Exposed so screens can react to the backend going away. */
export function useConnection(intervalMs = 5000) {
  const [connection, setConnection] = useState<Connection>({ state: "connecting" });
  const lastHealth = useRef<Health | null>(null);

  const check = useCallback(async () => {
    const result = await api.health();
    if (result.ok) {
      lastHealth.current = result.data;
      setConnection({ state: "online", health: result.data, at: Date.now() });
    } else {
      setConnection((prev) => ({
        state: "offline",
        since: prev.state === "offline" ? prev.since : Date.now(),
        lastHealth: lastHealth.current,
      }));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      if (!cancelled) void check();
    };
    tick();
    const timer = window.setInterval(tick, intervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [check, intervalMs]);

  return { connection, recheck: check };
}

export function ConnectionBadge({ connection }: { connection: Connection }) {
  if (connection.state === "connecting") {
    return (
      <span className="flex items-center gap-2 text-xs text-slateish-400">
        <span aria-hidden className="h-2 w-2 rounded-full bg-slateish-400" />
        Connecting…
      </span>
    );
  }
  if (connection.state === "offline") {
    return (
      <span
        className="flex items-center gap-2 text-xs font-medium text-warn-500"
        role="status"
        aria-live="assertive"
      >
        <span aria-hidden className="h-2 w-2 rounded-full bg-warn-500" />
        Backend offline
      </span>
    );
  }
  const worker = connection.health.ingestion;
  // Only when nothing is being worked on. A document mid-embed is work, not a
  // fault, and this badge claimed otherwise on a healthy 1,400-page ingest.
  //
  // `busy` is a BOOLEAN from health, where current_document used to be a
  // document id. Health is unauthenticated, so it may say that work is
  // happening and must never say which document it is.
  if (worker.stalled && !worker.busy) {
    return (
      <span
        className="flex items-center gap-2 text-xs font-medium text-danger-500"
        role="status"
        aria-live="assertive"
      >
        <span aria-hidden className="h-2 w-2 rounded-full bg-danger-500" />
        Queue not moving
      </span>
    );
  }
  return (
    <span className="flex items-center gap-2 text-xs text-signal-400">
      <span aria-hidden className="h-2 w-2 rounded-full bg-signal-500" />
      Connected
    </span>
  );
}

export function Shell({
  view,
  onNavigate,
  connection,
  identity,
  auth,
  theme,
  onThemeChange,
  children,
}: {
  view: ViewId;
  onNavigate: (v: ViewId) => void;
  connection: Connection;
  /** Who is signed in, or a quiet note that authentication is off. Optional
   *  so every existing test that renders the Shell keeps working unchanged. */
  identity?: React.ReactNode;
  /** The body of `/api/auth/me`, verbatim. This is what decides whether the
   *  administration entry exists; see `hasAdminCapability`. Optional and
   *  defaulting to "not admin", so a caller that has not been taught about it
   *  gets the six-entry navigation rather than an accidental admin link. */
  auth?: AuthStatus | null;
  theme: ThemeMode;
  onThemeChange: (theme: ThemeMode) => void;
  children: React.ReactNode;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [density, setDensity] = useState<DensityMode>(() => {
    try { return localStorage.getItem("rag-intelligence-density") === "compact" ? "compact" : "comfortable"; }
    catch { return "comfortable"; }
  });
  const items = navFor(auth);
  useEffect(() => {
    document.documentElement.setAttribute("data-density", density);
    try { localStorage.setItem("rag-intelligence-density", density); } catch { /* memory-only fallback */ }
  }, [density]);

  return (
    <div className={`density-${density} flex flex-col bg-ink-900 md:flex-row`}>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-[var(--radius-sm)] focus:bg-ink-700 focus:px-3 focus:py-2 focus:text-slateish-200 focus:shadow-[var(--shadow-floating)]"
      >
        Skip to content
      </a>

      <header className="flex items-center justify-between border-b border-ink-700 px-4 py-3 md:hidden">
        <span className="font-semibold tracking-wide text-slateish-200">RAG Intelligence System</span>
        <div className="flex items-center gap-2">
          <ThemeToggle theme={theme} onChange={onThemeChange} compact />
          <button
            type="button"
            aria-expanded={menuOpen}
            aria-controls="sidebar-nav"
            onClick={() => setMenuOpen((o) => !o)}
            className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-sm text-slateish-300 motion-safe:transition-colors hover:border-signal-500/50"
          >
            {menuOpen ? "Close" : "Menu"}
          </button>
        </div>
      </header>

      <nav
        id="sidebar-nav"
        aria-label="Main"
        className={`${menuOpen ? "flex" : "hidden"} w-full shrink-0 flex-col border-b border-ink-700 bg-ink-850 shadow-[var(--shadow-raised)] md:flex md:w-64 md:shrink-0 md:self-start md:border-b-0 md:border-r md:sticky md:top-0`}
      >
        {/* THE HEADER PAYS FOR ITSELF IN NAV SPACE. At text-lg the product name
            wrapped to two lines in a 256px rail, and with the tagline and a
            bordered box beneath it the sidebar spent ~200px before the first
            nav item. Set on two deliberate lines at text-base it reads as a
            name rather than a wrap, and the privacy line - which is the
            product's single best argument and stays - is a sentence rather
            than a boxed callout. */}
        <div className="hidden px-4 pb-3 pt-5 md:block">
          {/* ONE TEXT NODE. A <br/> here set the name on two tidy lines and
              split it into two nodes, so `getByText("RAG Intelligence System")`
              stopped finding it - and a screen reader stopped hearing one
              name. It wraps on its own at this size; the wrap is cosmetic and
              the string must stay whole. */}
          <span className="block text-base font-semibold leading-tight tracking-tight text-slateish-100">
            RAG Intelligence System
          </span>
          <span className="mt-1 block text-xs leading-snug text-slateish-400">
            Cited answers from your own documents
          </span>
          <p className="mt-3 border-l-2 border-signal-500/40 ps-2.5 text-xs leading-relaxed text-slateish-400">
            <span className="font-medium text-slateish-300">Private by design.</span>{" "}
            Your documents stay on this machine, and every answer cites its
            document and page.
          </p>
        </div>

        {/* ADMINISTRATION IS A DIFFERENT KIND OF THING and is separated by a
            rule. In one flat list "Users, disciplines, access" read as a
            seventh place to do work, when it is the place to decide who may do
            work anywhere else. A non-admin simply has no seventh entry, so
            there is no gap where something was removed. */}
        <ul className="space-y-0.5 px-3 pb-4">
          {items.map((item, i) => {
            const active = item.id === view;
            const startsAdmin = item.id === "admin" && i > 0;
            // A RULE, NOT A HEADING. The first version put an "ADMINISTRATION"
            // label above an item already labelled "Administration", so the
            // word appeared twice in a row and read as a rendering fault. The
            // separator alone carries the meaning - this is a different kind
            // of destination - and the item names itself.
            return (
              <li key={item.id} className={startsAdmin ? "mt-3 border-t border-ink-700 pt-3" : ""}>
                <button
                  type="button"
                  aria-current={active ? "page" : undefined}
                  aria-disabled={!item.built}
                  onClick={() => {
                    onNavigate(item.id);
                    setMenuOpen(false);
                  }}
                  className={[
                    "relative flex w-full items-center justify-between overflow-hidden rounded-[var(--radius-sm)] px-3 py-1.5 text-left text-sm motion-safe:transition-colors",
                    active
                      ? "bg-signal-500/10 text-slateish-100 shadow-[var(--shadow-resting)] before:absolute before:inset-y-1 before:left-0 before:w-[3px] before:rounded-full before:bg-signal-500 before:content-['']"
                      : "text-slateish-300 hover:bg-ink-800",
                    item.built ? "" : "opacity-70",
                  ].join(" ")}
                >
                  <span className="min-w-0">
                    <span className="block leading-snug">{item.label}</span>
                    {/* The hint is orientation, not a label: it teaches the
                        screen once and is read past forever after. Dimmer and
                        a size down, so the seven destinations scan as seven
                        destinations rather than fourteen lines of equal
                        weight. */}
                    <span className="block truncate text-xs leading-snug text-slateish-500">
                      {item.hint}
                    </span>
                  </span>
                  {!item.built && (
                    <span className="ms-2 shrink-0 rounded-[var(--radius-full)] border border-ink-500 px-1.5 py-0.5 text-xs uppercase tracking-wide text-slateish-300">
                      not built
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>

        <div className="mt-auto border-t border-ink-700 px-4 py-4">
          {/* Identity sits ABOVE the connection badge on purpose: "who am I"
              and "is the backend up" are different questions and a reader
              must not have to disentangle one from the other. */}
          {identity && <div className="mb-3">{identity}</div>}
          <ConnectionBadge connection={connection} />
          {/* The answer model's exact name and version used to sit here,
              read from /api/health - which is unauthenticated, so it was
              fingerprinting material available with no login. Health now says
              only WHETHER a model is configured. The name is on the Dashboard,
              which reads /api/metrics. That endpoint was described as
              "scoped" here and in four other places while it was not:
              it resolved an access scope and discarded it, so every
              caller saw the whole corpus. Scoped as of the commit that
              corrected this comment. */}
          {connection.state === "online" && (
            <p className="mt-1.5 text-xs text-slateish-500">
              {connection.health.answer_model_present
                ? "Answer model configured"
                : "No answer model configured"}
            </p>
          )}
          <div className="mt-4">
            <ThemeToggle theme={theme} onChange={onThemeChange} />
          </div>
          <div className="mt-3 flex items-center gap-2 text-xs text-slateish-400" aria-label="Density">
            <span>Density</span>
            <button type="button" aria-pressed={density === "comfortable"} onClick={() => setDensity("comfortable")} className="min-h-11 rounded-[var(--radius-xs)] border border-ink-600 px-2 py-1">Comfortable</button>
            <button type="button" aria-pressed={density === "compact"} onClick={() => setDensity("compact")} className="min-h-11 rounded-[var(--radius-xs)] border border-ink-600 px-2 py-1">Compact</button>
          </div>
          {/* THREE STANDING FACTS ABOUT THE DEPLOYMENT, not live status - which
              is why they are quieter than the connection badge above and why
              the amber one is the only coloured word. They earn their place:
              each is a question a client asks in the first minute, and the
              middle one is the answer nobody volunteers unprompted. */}
          <dl className="mt-4 space-y-1 text-xs text-slateish-500">
            <div className="flex items-baseline justify-between gap-2">
              <dt>Documents</dt>
              <dd className="text-slateish-400">on this machine</dd>
            </div>
            <div className="flex items-baseline justify-between gap-2">
              <dt>Market data</dt>
              <dd className="text-warn-500">sample only until searched</dd>
            </div>
            <div className="flex items-baseline justify-between gap-2">
              <dt>Reports</dt>
              <dd className="text-slateish-400">frozen PDF</dd>
            </div>
          </dl>
        </div>
      </nav>

      <main id="main" className="min-w-0 flex-1 px-4 py-6 md:px-8">
        {children}
      </main>
    </div>
  );
}

function ThemeToggle({
  theme,
  onChange,
  compact = false,
}: {
  theme: ThemeMode;
  onChange: (theme: ThemeMode) => void;
  compact?: boolean;
}) {
  return (
    <div
      role="group"
      aria-label="Theme mode"
      className={[
        "inline-grid grid-cols-2 rounded-[var(--radius-full)] border border-ink-600 bg-ink-900 p-0.5",
        compact ? "text-xs" : "w-full text-xs",
      ].join(" ")}
    >
      {(["dark", "light"] as const).map((mode) => {
        const active = theme === mode;
        return (
          <button
            key={mode}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(mode)}
            className={[
              "rounded-[var(--radius-full)] px-2 py-1 font-medium capitalize motion-safe:transition-colors",
              active
                ? "bg-signal-500 text-ink-950 shadow-[var(--shadow-resting)]"
                : "text-slateish-400 hover:bg-ink-800 hover:text-slateish-200",
            ].join(" ")}
          >
            {mode}
          </button>
        );
      })}
    </div>
  );
}
