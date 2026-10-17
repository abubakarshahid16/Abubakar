/**
 * "@ a document": choose which documents the next answers come from.
 *
 * THE LIST IS THE READER'S OWN: `/api/documents` returns only what they may
 * read, and the backend intersects the choice with their permission again,
 * so a picked document can only ever NARROW a search (CLAUDE.md rule 5).
 * Nothing picked means "all my documents", which is said in words.
 */
import { useEffect, useLayoutEffect, useState, type RefObject } from "react";
import { createPortal } from "react-dom";

import { api } from "../../api/client";
import type { DocumentRecord } from "../../types/api";

export interface PickedDocument {
  id: string;
  name: string;
}

export const MAX_PICKED = 20;

export function DocumentPicker({
  picked,
  anchorRef,
  onChange,
  onClose,
}: {
  picked: PickedDocument[];
  anchorRef: RefObject<HTMLButtonElement | null>;
  onChange: (next: PickedDocument[]) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [docs, setDocs] = useState<DocumentRecord[] | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [placement, setPlacement] = useState({ top: 16, left: 16, maxHeight: 320, listHeight: 160 });

  useLayoutEffect(() => {
    const place = () => {
      const anchor = anchorRef.current?.getBoundingClientRect();
      const margin = 16;
      const width = Math.min(352, window.innerWidth - margin * 2);
      const maxHeight = Math.max(160, Math.min(420, window.innerHeight - margin * 2));
      const left = anchor
        ? Math.max(margin, Math.min(anchor.left, window.innerWidth - width - margin))
        : margin;
      const below = anchor ? window.innerHeight - anchor.bottom - margin : 0;
      const above = anchor ? anchor.top - margin : 0;
      const openBelow = below >= Math.min(260, maxHeight) || below >= above;
      const top = anchor
        ? openBelow
          ? Math.min(anchor.bottom + 8, window.innerHeight - maxHeight - margin)
          : Math.max(margin, anchor.top - maxHeight - 8)
        : margin;
      setPlacement({ top, left, maxHeight, listHeight: Math.max(48, maxHeight - 132) });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [anchorRef]);

  useEffect(() => {
    const dismiss = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (document.getElementById("chat-document-picker")?.contains(target)) return;
      if (anchorRef.current?.contains(target)) return;
      onClose();
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        anchorRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", escape);
    };
  }, [anchorRef, onClose]);

  useEffect(() => {
    let cancelled = false;
    const t = window.setTimeout(() => {
      void api.documents({ limit: 50, q: query.trim() || undefined }).then((r) => {
        if (cancelled) return;
        if (r.ok) {
          setDocs(r.data);
          setFailure(null);
        } else setFailure(r.error.message);
      });
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [query]);

  const chosen = new Set(picked.map((p) => p.id));
  const toggle = (d: DocumentRecord) => {
    if (chosen.has(d.id)) onChange(picked.filter((p) => p.id !== d.id));
    else if (picked.length < MAX_PICKED) onChange([...picked, { id: d.id, name: d.filename }]);
  };

  return createPortal((
    <div
      id="chat-document-picker"
      role="dialog"
      aria-label="Choose documents"
      style={{ position: "fixed", top: placement.top, left: placement.left, width: "min(22rem, calc(100vw - 2rem))", maxHeight: placement.maxHeight }}
      className="z-[100] flex flex-col overflow-hidden rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-2 shadow-[var(--shadow-floating)]"
    >
      <label className="block">
        <span className="sr-only">Find a document</span>
        <input
          type="search"
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Find a document"
          className="w-full rounded-[var(--radius-sm)] border border-ink-600 bg-ink-900 px-2.5 py-1.5 text-sm text-slateish-100 placeholder:text-slateish-500"
        />
      </label>
      <p className="mt-1.5 px-1 text-xs text-slateish-500">
        {picked.length === 0
          ? "Nothing chosen: answers come from all your documents."
          : `Answers come from ${picked.length === 1 ? "this document" : `these ${picked.length} documents`} only.`}
      </p>
      {failure && (
        <p role="alert" className="mt-1.5 px-1 text-xs text-danger-500">
          {failure}
        </p>
      )}
      <ul style={{ maxHeight: placement.listHeight }} className="mt-1.5 min-h-0 flex-1 space-y-0.5 overflow-y-auto">
        {docs === null && !failure && <li className="px-1 text-xs text-slateish-500">Loading…</li>}
        {docs !== null && docs.length === 0 && (
          <li className="px-1 text-xs text-slateish-500">No document matches.</li>
        )}
        {(docs ?? []).map((d) => (
          <li key={d.id}>
            <label className="flex cursor-pointer items-center gap-2 rounded-[var(--radius-sm)] px-2 py-1.5 text-sm text-slateish-200 hover:bg-ink-700">
              <input type="checkbox" checked={chosen.has(d.id)} onChange={() => toggle(d)} />
              <span className="truncate">{d.filename}</span>
            </label>
          </li>
        ))}
      </ul>
      <div className="mt-1.5 flex justify-between gap-2">
        <button
          type="button"
          onClick={() => onChange([])}
          disabled={picked.length === 0}
          className="rounded-[var(--radius-sm)] px-2 py-1 text-xs text-slateish-400 hover:bg-ink-700 disabled:opacity-50"
        >
          Use all my documents
        </button>
        <button
          type="button"
          onClick={onClose}
          className="rounded-[var(--radius-sm)] border border-ink-600 px-3 py-1 text-xs text-slateish-200 hover:bg-ink-700"
        >
          Done
        </button>
      </div>
    </div>
  ), document.body);
}

