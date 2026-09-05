/**
 * Application shell: sidebar, Sunday POC navigation, and the connection banner.
 *
 * Documents, Chat and Dashboard are built. Ingestion is listed but visibly
 * marked, so the navigation never implies capability that does not exist.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { api, type Health } from "../api/client";

export type ViewId =
  | "documents"
  | "chat"
  | "analysis"
  | "ingestion"
  | "dashboard"
  | "reports";

export type ThemeMode = "dark" | "light";

interface NavItem {
  id: ViewId;
  label: string;
  hint: string;
  built: boolean;
}

export const NAV: NavItem[] = [
  { id: "dashboard", label: "Dashboard", hint: "Metrics, models, readiness", built: true },
  { id: "documents", label: "Documents", hint: "Upload, inspect, verify", built: true },
  { id: "chat", label: "Chat", hint: "Ask questions with citations", built: true },
  { id: "analysis", label: "Analysis", hint: "Summary, gaps, advice", built: true },
  { id: "reports", label: "Reports", hint: "Frozen evidence, as PDF", built: true },
  { id: "ingestion", label: "Ingestion", hint: "Queue and throughput", built: true },
];

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
  theme: ThemeMode;
  onThemeChange: (theme: ThemeMode) => void;
  children: React.ReactNode;
}) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="flex min-h-screen flex-col bg-ink-900 md:flex-row">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-ink-700 focus:px-3 focus:py-2 focus:text-slateish-200"
      >
        Skip to content
      </a>

      <header className="flex items-center justify-between border-b border-ink-700 px-4 py-3 md:hidden">
        <span className="font-semibold tracking-wide text-slateish-200">Nabaa</span>
        <div className="flex items-center gap-2">
          <ThemeToggle theme={theme} onChange={onThemeChange} compact />
          <button
            type="button"
            aria-expanded={menuOpen}
            aria-controls="sidebar-nav"
            onClick={() => setMenuOpen((o) => !o)}
            className="rounded border border-ink-600 px-3 py-1 text-sm text-slateish-300"
          >
            {menuOpen ? "Close" : "Menu"}
          </button>
        </div>
      </header>

      <nav
        id="sidebar-nav"
        aria-label="Main"
        className={`${menuOpen ? "block" : "hidden"} w-full shrink-0 border-b border-ink-700 bg-ink-850 md:block md:w-64 md:border-b-0 md:border-r`}
      >
        <div className="hidden px-5 py-5 md:block">
          <span className="block text-lg font-semibold tracking-wide text-slateish-200">Nabaa</span>
          <span className="mt-0.5 block text-xs text-slateish-400">
            enterprise FEED intelligence
          </span>
          <div className="mt-3 rounded-md border border-ink-600 bg-ink-800 px-3 py-2">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-slateish-400">
              Sunday POC lane
            </p>
            <p className="mt-1 text-xs leading-relaxed text-slateish-300">
              Local evidence, scoped access, cited analysis and auditable reports.
            </p>
          </div>
        </div>

        <ul className="space-y-1 px-3 pb-4">
          {NAV.map((item) => {
            const active = item.id === view;
            return (
              <li key={item.id}>
                <button
                  type="button"
                  aria-current={active ? "page" : undefined}
                  aria-disabled={!item.built}
                  onClick={() => {
                    onNavigate(item.id);
                    setMenuOpen(false);
                  }}
                  className={[
                    "flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition-colors",
                    active
                      ? "bg-ink-700 text-slateish-200"
                      : "text-slateish-300 hover:bg-ink-800",
                    item.built ? "" : "opacity-70",
                  ].join(" ")}
                >
                  <span>
                    <span className="block">{item.label}</span>
                    <span className="block text-xs text-slateish-400">{item.hint}</span>
                  </span>
                  {!item.built && (
                    <span className="ml-2 shrink-0 rounded border border-ink-500 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slateish-400">
                      not built
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>

        <div className="border-t border-ink-700 px-5 py-4">
          {/* Identity sits ABOVE the connection badge on purpose: "who am I"
              and "is the backend up" are different questions and a reader
              must not have to disentangle one from the other. */}
          {identity && <div className="mb-3">{identity}</div>}
          <ConnectionBadge connection={connection} />
          {/* The answer model's exact name and version used to sit here,
              read from /api/health - which is unauthenticated, so it was
              fingerprinting material available with no login. Health now says
              only WHETHER a model is configured. The name is on the Dashboard,
              which reads the scoped /api/metrics. */}
          {connection.state === "online" && (
            <p className="mt-2 font-mono text-[11px] text-slateish-400">
              {connection.health.answer_model_present
                ? "answer model configured"
                : "no answer model configured"}
            </p>
          )}
          <div className="mt-4">
            <ThemeToggle theme={theme} onChange={onThemeChange} />
          </div>
          <div className="mt-4 space-y-1.5 text-[11px] text-slateish-400">
            <p className="flex items-center justify-between gap-2">
              <span>Private boundary</span>
              <span className="font-mono text-signal-400">local</span>
            </p>
            <p className="flex items-center justify-between gap-2">
              <span>Public market</span>
              <span className="font-mono text-warn-500">sample only</span>
            </p>
            <p className="flex items-center justify-between gap-2">
              <span>Reports</span>
              <span className="font-mono text-signal-400">frozen PDF</span>
            </p>
          </div>
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
        "inline-grid grid-cols-2 rounded-md border border-ink-600 bg-ink-900 p-0.5",
        compact ? "text-[11px]" : "w-full text-xs",
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
              "rounded px-2 py-1 font-medium capitalize transition-colors",
              active
                ? "bg-ink-700 text-slateish-100"
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
