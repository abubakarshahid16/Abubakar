/**
 * "@ a document": choose which documents the next answers come from.
 *
 * THE LIST IS THE READER'S OWN: `/api/documents` returns only what they may
 * read, and the backend intersects the choice with their permission again,
 * so a picked document can only ever NARROW a search (CLAUDE.md rule 5).
 * Nothing picked means "all my documents", which is said in words.
 */
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import type { DocumentRecord } from "../../types/api";

export interface PickedDocument {
  id: string;
  name: string;
}

export const MAX_PICKED = 20;

export function DocumentPicker({
  picked,
  onChange,
  onClose,
}: {
  picked: PickedDocument[];
  onChange: (next: PickedDocument[]) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [docs, setDocs] = useState<DocumentRecord[] | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

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

  return (
    <div
      role="dialog"
      aria-label="Choose documents"
      className="absolute bottom-12 left-0 z-30 w-[22rem] max-w-[90vw] rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-2 shadow-[var(--shadow-floating)]"
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
      <ul className="mt-1.5 max-h-64 space-y-0.5 overflow-y-auto">
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
  );
}
