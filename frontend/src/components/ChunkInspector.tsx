/**
 * Chunk inspector.
 *
 * Every defect found so far came from reading raw chunk JSON by hand: the
 * publisher's address inherited as a section heading, contents pages indexed
 * as prose, tables rejected wholesale, adjacent chunks duplicating each other.
 * This screen exists so that is possible without a chat window - id, section,
 * page range, token count, kind, retrievable flag, quality_flags and the FULL
 * text, filterable by retrievable.
 */
import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { ApiError, ChunkRecord, DocumentRecord } from "../types/api";
import { Drawer } from "./Drawer";
import { DisconnectedState, EmptyState, ErrorState, Spinner } from "./states";

type Filter = "true" | "false" | "all";
const PAGE_SIZE = 25;

const KIND_TONE: Record<string, string> = {
  prose: "bg-ink-700 text-slateish-300",
  table: "bg-info-500/20 text-info-500",
  toc: "bg-warn-500/15 text-warn-500",
  frontmatter: "bg-warn-500/15 text-warn-500",
  index: "bg-warn-500/15 text-warn-500",
  references: "bg-warn-500/15 text-warn-500",
};

export function ChunkInspector({
  doc,
  onClose,
}: {
  doc: DocumentRecord;
  onClose: () => void;
}) {
  const [filter, setFilter] = useState<Filter>("true");
  const [offset, setOffset] = useState(0);
  const [state, setState] = useState<
    | { s: "loading" }
    | { s: "error"; error: ApiError; disconnected: boolean }
    | { s: "ready"; chunks: ChunkRecord[]; total: number }
  >({ s: "loading" });

  const load = useCallback(async () => {
    setState({ s: "loading" });
    const r = await api.chunks(doc.id, { limit: PAGE_SIZE, offset, retrievable: filter });
    if (r.ok) setState({ s: "ready", chunks: r.data.chunks, total: r.data.total_matching });
    else setState({ s: "error", error: r.error, disconnected: r.disconnected });
  }, [doc.id, filter, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  const total = state.s === "ready" ? state.total : 0;
  const shownFrom = total === 0 ? 0 : offset + 1;
  const shownTo = state.s === "ready" ? offset + state.chunks.length : 0;

  return (
    <Drawer
      title={`Chunks — ${doc.filename}`}
      subtitle={`${doc.chunk_count} searchable of ${doc.chunk_count_total} total`}
      onClose={onClose}
    >
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div role="group" aria-label="Filter by retrievable" className="flex gap-1">
          {(
            [
              ["true", "Searchable"],
              ["false", "Excluded"],
              ["all", "All"],
            ] as [Filter, string][]
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={filter === value}
              onClick={() => {
                setFilter(value);
                setOffset(0);
              }}
              className={[
                "rounded border px-3 py-1 text-xs",
                filter === value
                  ? "border-signal-500/60 bg-signal-500/15 text-signal-400"
                  : "border-ink-600 text-slateish-300 hover:bg-ink-700",
              ].join(" ")}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="font-mono text-xs text-slateish-400">
          {shownFrom}–{shownTo} of {total}
        </span>
        <div className="ml-auto flex gap-1">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            className="rounded border border-ink-600 px-3 py-1 text-xs text-slateish-300 disabled:opacity-40 hover:bg-ink-700"
          >
            Previous
          </button>
          <button
            type="button"
            disabled={shownTo >= total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
            className="rounded border border-ink-600 px-3 py-1 text-xs text-slateish-300 disabled:opacity-40 hover:bg-ink-700"
          >
            Next
          </button>
        </div>
      </div>

      {state.s === "loading" && <Spinner label="Loading chunks" />}
      {state.s === "error" &&
        (state.disconnected ? (
          <DisconnectedState onRetry={load} />
        ) : (
          <ErrorState error={state.error} onRetry={load} />
        ))}
      {state.s === "ready" && state.chunks.length === 0 && (
        <EmptyState
          title={
            filter === "false"
              ? "Nothing was excluded from this document"
              : "No chunks match this filter"
          }
        />
      )}

      {state.s === "ready" && state.chunks.length > 0 && (
        <ul className="space-y-3">
          {state.chunks.map((c) => (
            <li key={c.id} className="rounded border border-ink-700 bg-ink-850 p-3">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className={`rounded px-2 py-0.5 ${KIND_TONE[c.kind] ?? KIND_TONE.prose}`}>
                  {c.kind}
                </span>
                <span
                  className={[
                    "rounded px-2 py-0.5",
                    c.retrievable
                      ? "bg-signal-500/15 text-signal-400"
                      : "bg-warn-500/15 text-warn-500",
                  ].join(" ")}
                >
                  {c.retrievable ? "searchable" : "excluded"}
                </span>
                <span className="text-slateish-400">
                  {c.page_start === c.page_end
                    ? `page ${c.page_start}`
                    : `pages ${c.page_start}–${c.page_end}`}
                </span>
                <span className="text-slateish-400">{c.token_count} tokens</span>
                <span className="ml-auto font-mono text-[11px] text-slateish-400">
                  #{c.ordinal}
                </span>
              </div>

              <p className="mt-2 text-xs text-slateish-400">
                section:{" "}
                {c.section ? (
                  <span className="text-slateish-300">{c.section}</span>
                ) : (
                  <span className="italic">none — null rather than a guess</span>
                )}
              </p>

              {c.quality_flags && (
                <p className="mt-1 font-mono text-[11px] text-warn-500">
                  excluded because: {c.quality_flags}
                </p>
              )}

              <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-ink-900 p-3 font-mono text-[11px] leading-relaxed text-slateish-300">
{c.text}
              </pre>

              <p className="mt-1 font-mono text-[10px] text-slateish-400">{c.id}</p>
            </li>
          ))}
        </ul>
      )}
    </Drawer>
  );
}
