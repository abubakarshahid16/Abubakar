import { useEffect, useState } from "react";
import { NEW_LOOK } from "../look";
import { api, structuredSearch } from "../api/client";
import { hasAdminCapability, type Connection, type ViewId } from "./Shell";
import type { AuthStatus } from "../types/api";

const NAV_COMMANDS: Array<{ id: ViewId; label: string }> = [
  { id: "dashboard", label: "Open dashboard" }, { id: "documents", label: "Open documents" },
  { id: "standards", label: "Open standards library" }, { id: "chat", label: "Open chat" },
  { id: "analysis", label: "Open analysis" }, { id: "reports", label: "Open reports" },
  { id: "deliverables", label: "Open deliverables" }, { id: "review", label: "Open guided review" },
  { id: "ingestion", label: "Open ingestion" },
];

type SearchLink = { key: string; label: string; view: ViewId; recordId?: string };

export function CommandPalette({ onNavigate, auth, connection }: {
  onNavigate: (view: ViewId, recordId?: string) => void;
  auth: AuthStatus | null;
  connection: Connection;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [results, setResults] = useState<SearchLink[]>([]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault(); setOpen(true); setMessage(null);
      }
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => {
    if (!open || query.trim().length < 2) { setResults([]); setMessage(null); return; }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      void Promise.all([api.search(query.trim()), structuredSearch(query.trim())]).then(([plain, structured]) => {
        if (cancelled) return;
        const links = new Map<string, SearchLink>();
        if (plain.ok) {
          for (const hit of plain.data.hits) {
            if (hit.document_id) links.set(`document:${hit.document_id}`, {
              key: `document:${hit.document_id}`, label: hit.filename, view: "documents", recordId: hit.document_id,
            });
          }
        }
        if (structured.ok) {
          for (const item of structured.data.results) {
            const key = item.document_id ? `document:${item.document_id}` : `${item.kind}:${item.id}`;
            if (links.has(key)) continue;
            links.set(key, {
              key, label: `${item.kind}: ${item.label}`,
              view: item.document_id ? "documents" : "deliverables",
              recordId: item.document_id ?? undefined,
            });
          }
        }
        const found = [...links.values()].slice(0, 8);
        setResults(found);
        setMessage(found.length ? null : plain.ok || structured.ok
          ? `No results for “${query.trim()}”.` : "Search could not be completed. Try again.");
      }).catch(() => {
        if (!cancelled) setMessage("Search could not be completed. Try again.");
      });
    }, 180);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [open, query]);
  // the new look: no floating pill over every page's content (H's audit, 27 Nov 2026 (h)); Ctrl K still opens the palette
  if (!open && NEW_LOOK) return null;
  if (!open) return <button type="button" className="fixed bottom-4 right-4 rounded-full border border-ink-600 bg-ink-850 px-3 py-2 text-xs text-slateish-300 shadow-[var(--shadow-floating)]" onClick={() => setOpen(true)}>Ctrl K</button>;
  const commands = [...NAV_COMMANDS, ...(hasAdminCapability(auth) ? [{ id: "admin" as ViewId, label: "Open administration" }] : [])]
    .filter(item => item.label.toLowerCase().includes(query.toLowerCase()));
  return <div className="fixed inset-0 z-50 bg-ink-950/70 p-4" role="presentation" onMouseDown={() => setOpen(false)}>
    <section role="dialog" aria-modal="true" aria-label="Command palette" className="mx-auto mt-16 max-w-xl rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-3 shadow-[var(--shadow-floating)]" onMouseDown={event => event.stopPropagation()}>
      <input autoFocus value={query} onChange={event => setQuery(event.target.value)} placeholder="Search or jump to…" className="w-full rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-3 py-3 text-slateish-100" />
      {message && <p role="status" className="px-2 py-3 text-sm text-slateish-300">{message}</p>}
      <ul className="mt-2 space-y-1">{commands.map(item => <li key={item.id}>
        <button type="button" className="w-full rounded-[var(--radius-sm)] px-3 py-2 text-left text-sm text-slateish-200 hover:bg-ink-700" onClick={() => { setOpen(false); onNavigate(item.id); }}>{item.label}</button>
      </li>)}</ul>
      {connection.state === "offline" && <p className="mt-2 text-xs text-warn-500">Search is unavailable while the backend is offline.</p>}
      {results.length > 0 && <div className="mt-3 border-t border-ink-700 pt-2">
        <p className="px-2 text-xs uppercase tracking-wide text-slateish-500">Search results</p>
        <ul>{results.map(result => <li key={result.key}>
          <button type="button" className="w-full rounded-[var(--radius-sm)] px-2 py-2 text-left text-sm text-slateish-200 hover:bg-ink-700" onClick={() => { setOpen(false); onNavigate(result.view, result.recordId); }}>{result.label}</button>
        </li>)}</ul>
      </div>}
    </section>
  </div>;
}
