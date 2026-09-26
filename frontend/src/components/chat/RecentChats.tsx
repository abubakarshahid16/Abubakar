/**
 * Recent chats, in the left navigation: search, open, delete.
 *
 * DELETE ASKS, THEN WAITS. The server's delete is permanent, so the row is
 * hidden at once and an Undo is offered for a few seconds; only when that
 * window closes is the delete sent. Leaving the page inside the window sends
 * it then - the reader said delete, and was not told otherwise. Until it is
 * sent nothing has been removed, which is why Undo can be honest.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../../api/client";
import type { ApiError, ConversationSummary } from "../../types/api";

export const UNDO_SECONDS = 6;

type Load = { s: "loading" } | { s: "ready" } | { s: "error"; error: ApiError; disconnected: boolean };

export function RecentChats({
  currentId,
  version,
  onOpen,
  onNew,
  onDeleted,
}: {
  currentId: string | null;
  /** bumped by the chat whenever the list may have changed */
  version: number;
  onOpen: (id: string) => void;
  onNew: () => void;
  /** a chat is gone (or about to be): the screen showing it must let go */
  onDeleted: (id: string) => void;
}) {
  const [list, setList] = useState<ConversationSummary[]>([]);
  const [load, setLoad] = useState<Load>({ s: "loading" });
  const [query, setQuery] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const [pending, setPending] = useState<ConversationSummary | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const timer = useRef<number | null>(null);
  const pendingRef = useRef<ConversationSummary | null>(null);

  const refresh = useCallback(async () => {
    const r = await api.conversations(50);
    if (r.ok) {
      setList(r.data.conversations);
      setLoad({ s: "ready" });
    } else {
      setLoad({ s: "error", error: r.error, disconnected: r.disconnected });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh, version]);

  const send = useCallback(
    async (c: ConversationSummary) => {
      const r = await api.deleteConversation(c.id);
      if (!r.ok) {
        // The row comes back, with the reason, rather than vanishing on a
        // delete that did not happen.
        setFailure(`Could not delete "${c.title}": ${r.error.message}`);
      }
      void refresh();
    },
    [refresh],
  );

  const flush = useCallback(() => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
    const c = pendingRef.current;
    pendingRef.current = null;
    setPending(null);
    if (c) void send(c);
  }, [send]);

  // Leaving (or closing) inside the Undo window still deletes.
  useEffect(() => {
    const onHide = () => flush();
    window.addEventListener("pagehide", onHide);
    return () => {
      window.removeEventListener("pagehide", onHide);
      flush();
    };
  }, [flush]);

  const remove = (c: ConversationSummary) => {
    flush(); // one pending delete at a time: the previous one goes now
    setConfirming(null);
    setFailure(null);
    pendingRef.current = c;
    setPending(c);
    onDeleted(c.id);
    timer.current = window.setTimeout(flush, UNDO_SECONDS * 1000);
  };

  const undo = () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
    pendingRef.current = null;
    setPending(null);
  };

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return list.filter((c) => c.id !== pending?.id && (!q || c.title.toLowerCase().includes(q)));
  }, [list, pending, query]);

  return (
    <section aria-label="Recent chats" className="border-t border-ink-700 px-3 pb-3 pt-3">
      <div className="mb-2 flex items-center justify-between px-1">
        <h2 className="text-xs font-medium text-slateish-500">Recent chats</h2>
        <button
          type="button"
          onClick={onNew}
          className="rounded-[var(--radius-sm)] px-1.5 py-0.5 text-xs text-slateish-400 hover:bg-ink-800 hover:text-slateish-200"
        >
          New chat
        </button>
      </div>
      {list.length > 5 && (
        <label className="mb-2 block">
          <span className="sr-only">Search chats</span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search chats"
            className="w-full rounded-[var(--radius-sm)] border border-ink-700 bg-ink-900 px-2 py-1 text-xs text-slateish-200 placeholder:text-slateish-500"
          />
        </label>
      )}
      {load.s === "loading" && <p className="px-1 text-xs text-slateish-500">Loading…</p>}
      {load.s === "error" && (
        <p className="px-1 text-xs text-slateish-500" role="status">
          {load.disconnected ? "Chats unavailable while the backend is offline." : load.error.message}{" "}
          <button type="button" onClick={() => void refresh()} className="text-signal-400 underline">
            Retry
          </button>
        </p>
      )}
      {load.s === "ready" && list.length === 0 && (
        <p className="px-1 text-xs text-slateish-500">No chats yet.</p>
      )}
      {load.s === "ready" && list.length > 0 && shown.length === 0 && query && (
        <p className="px-1 text-xs text-slateish-500">No chat matches "{query}".</p>
      )}
      <ul className="max-h-72 space-y-0.5 overflow-y-auto">
        {shown.map((c) => (
          <li key={c.id} className="group relative">
            {confirming === c.id ? (
              <div className="rounded-[var(--radius-sm)] bg-ink-800 px-2 py-1.5 text-xs text-slateish-300" role="group" aria-label={`Delete ${c.title}?`}>
                <p className="truncate">Delete "{c.title}"?</p>
                <div className="mt-1 flex gap-2">
                  <button type="button" onClick={() => remove(c)} className="text-danger-500 underline">
                    Delete
                  </button>
                  <button type="button" onClick={() => setConfirming(null)} className="underline">
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <>
                <button
                  type="button"
                  aria-current={c.id === currentId ? "true" : undefined}
                  onClick={() => onOpen(c.id)}
                  className={[
                    "block w-full truncate rounded-[var(--radius-sm)] px-2 py-1.5 pe-7 text-left text-sm motion-safe:transition-colors",
                    c.id === currentId ? "bg-ink-700 text-slateish-100" : "text-slateish-300 hover:bg-ink-800",
                  ].join(" ")}
                >
                  {c.title}
                </button>
                <button
                  type="button"
                  aria-label={`Delete conversation ${c.title}`}
                  onClick={() => setConfirming(c.id)}
                  className="absolute end-1 top-1 rounded-[var(--radius-xs)] px-1.5 py-0.5 text-xs text-slateish-500 opacity-0 hover:bg-ink-600 hover:text-danger-500 focus:opacity-100 group-hover:opacity-100"
                >
                  ×
                </button>
              </>
            )}
          </li>
        ))}
      </ul>
      {pending && (
        <p role="status" className="mt-2 rounded-[var(--radius-sm)] border border-ink-600 bg-ink-800 px-2 py-1.5 text-xs text-slateish-300">
          Chat deleted.{" "}
          <button type="button" onClick={undo} className="font-semibold text-signal-400 underline">
            Undo
          </button>
        </p>
      )}
      {failure && (
        <p role="alert" className="mt-2 text-xs text-danger-500">
          {failure}
        </p>
      )}
    </section>
  );
}
