/**
 * Excluded content viewer.
 *
 * Grouped by rule first, so "content_quality_gate rejected 400 chunks" is
 * visible at a glance rather than one row at a time. Nothing is dropped
 * silently, and this is where that promise is redeemed.
 */
import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { ApiError, DocumentRecord, ExclusionsResponse } from "../types/api";
import { Drawer } from "./Drawer";
import { DisconnectedState, EmptyState, ErrorState, Spinner } from "./states";

const PAGE_SIZE = 25;
const nf = new Intl.NumberFormat("en-GB");

const RULE_EXPLANATION: Record<string, string> = {
  content_quality_gate:
    "The text did not read like natural language and was not structured like a table.",
  page_classified_toc: "A contents page — dense keyword lists that would outrank real answers.",
  page_classified_frontmatter: "Title page, copyright, credits or dedication.",
  page_classified_index: "A back-of-book index.",
  page_classified_references: "A bibliography or reference list.",
};

export function ExcludedViewer({
  doc,
  onClose,
}: {
  doc: DocumentRecord;
  onClose: () => void;
}) {
  const [offset, setOffset] = useState(0);
  const [activeRule, setActiveRule] = useState<string | null>(null);
  const [state, setState] = useState<
    | { s: "loading" }
    | { s: "error"; error: ApiError; disconnected: boolean }
    | { s: "ready"; data: ExclusionsResponse }
  >({ s: "loading" });

  const load = useCallback(async () => {
    setState({ s: "loading" });
    const r = await api.excluded(doc.id, { limit: PAGE_SIZE, offset });
    if (r.ok) setState({ s: "ready", data: r.data });
    else setState({ s: "error", error: r.error, disconnected: r.disconnected });
  }, [doc.id, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  const rows =
    state.s === "ready"
      ? state.data.excluded.filter((e) => !activeRule || e.rule === activeRule)
      : [];

  return (
    <Drawer
      title={`Excluded from search — ${doc.filename}`}
      subtitle="Every page and chunk search cannot see, with the rule that excluded it"
      onClose={onClose}
    >
      {state.s === "loading" && <Spinner label="Loading exclusions" />}
      {state.s === "error" &&
        (state.disconnected ? (
          <DisconnectedState onRetry={load} />
        ) : (
          <ErrorState error={state.error} onRetry={load} />
        ))}

      {state.s === "ready" && state.data.total === 0 && (
        <EmptyState
          title="Nothing was excluded"
          hint="Every chunk in this document is searchable."
        />
      )}

      {state.s === "ready" && state.data.total > 0 && (
        <>
          <section aria-labelledby="by-rule" className="mb-5">
            <h3 id="by-rule" className="text-sm font-medium text-slateish-200">
              By rule
            </h3>
            <ul className="mt-2 space-y-2">
              {state.data.summary.map((s) => {
                const selected = activeRule === s.rule;
                return (
                  <li key={`${s.scope}-${s.rule}`}>
                    <button
                      type="button"
                      aria-pressed={selected}
                      onClick={() => setActiveRule(selected ? null : s.rule)}
                      className={[
                        "flex w-full items-center justify-between rounded border px-3 py-2 text-left text-sm",
                        selected
                          ? "border-warn-500/60 bg-warn-500/10"
                          : "border-ink-700 bg-ink-850 hover:bg-ink-800",
                      ].join(" ")}
                    >
                      <span className="min-w-0">
                        <span className="block font-mono text-xs text-slateish-200">
                          {s.rule}
                        </span>
                        <span className="block text-xs text-slateish-400">
                          {RULE_EXPLANATION[s.rule] ?? `Excluded ${s.scope}s.`}
                        </span>
                        {(s.clause_heading_pages ?? 0) > 0 && (
                          <span className="mt-1 block text-xs font-medium text-danger-500">
                            {nf.format(s.clause_heading_pages ?? 0)} of these carried
                            numbered clause headings — probably real content
                          </span>
                        )}
                      </span>
                      <span className="ml-3 shrink-0 text-right">
                        <span className="block font-mono text-sm text-warn-500">
                          {nf.format(s.count)} {s.scope}s
                        </span>
                        <span className="block text-[11px] text-slateish-400">
                          {nf.format(s.characters_dropped)} chars
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
            {activeRule && (
              <p className="mt-2 text-xs text-slateish-400">
                Showing only <span className="font-mono">{activeRule}</span> on this page.{" "}
                <button
                  type="button"
                  className="underline decoration-dotted"
                  onClick={() => setActiveRule(null)}
                >
                  Clear filter
                </button>
              </p>
            )}
          </section>

          <section aria-labelledby="dropped">
            <div className="mb-2 flex items-center justify-between">
              <h3 id="dropped" className="text-sm font-medium text-slateish-200">
                What was dropped
              </h3>
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs text-slateish-400">
                  {offset + 1}–{offset + state.data.excluded.length} of {state.data.total}
                </span>
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
                  disabled={offset + state.data.excluded.length >= state.data.total}
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                  className="rounded border border-ink-600 px-3 py-1 text-xs text-slateish-300 disabled:opacity-40 hover:bg-ink-700"
                >
                  Next
                </button>
              </div>
            </div>

            <ul className="space-y-3">
              {rows.map((e, i) => (
                <li
                  key={`${e.chunk_id ?? e.page_start}-${i}`}
                  className={[
                    "rounded border p-3",
                    (e.clause_headings ?? 0) > 0
                      ? "border-danger-500/50 bg-danger-500/10"
                      : "border-ink-700 bg-ink-850",
                  ].join(" ")}
                >
                  {(e.clause_headings ?? 0) > 0 && (
                    <p role="alert" className="mb-2 text-xs font-medium text-danger-500">
                      This page carried numbered clause headings and real prose.
                      That is body text, and dropping it almost certainly lost
                      real content.
                    </p>
                  )}
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="rounded bg-warn-500/15 px-2 py-0.5 text-warn-500">
                      {e.scope}
                    </span>
                    <span className="font-mono text-slateish-300">{e.rule}</span>
                    <span className="text-slateish-400">
                      {e.page_start === e.page_end
                        ? `page ${e.page_start}`
                        : `pages ${e.page_start}–${e.page_end}`}
                    </span>
                    <span className="ml-auto text-slateish-400">
                      {nf.format(e.text_length)} chars
                    </span>
                  </div>
                  {e.reason && (
                    <p className="mt-1 font-mono text-[11px] text-warn-500">{e.reason}</p>
                  )}
                  <pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-words rounded bg-ink-900 p-3 font-mono text-[11px] text-slateish-300">
{e.text_sample}
                  </pre>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </Drawer>
  );
}
