/**
 * Page image viewer.
 *
 * Extraction loses equation operators and flattens table column pairing.
 * Neither is fixable in text mode, so the durable answer is to show the real
 * page. This is how a citation is verified against the source.
 */
import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { ApiError, DocumentRecord, PageRecord } from "../types/api";
import { Drawer } from "./Drawer";
import { DisconnectedState, ErrorState, Spinner } from "./states";
import { useAuthedImage } from "./useAuthedImage";

const PAGE_SIZE = 100;
const ZOOMS = [0.5, 0.75, 1, 1.5, 2] as const;

export function PageImageViewer({
  doc,
  onClose,
}: {
  doc: DocumentRecord;
  onClose: () => void;
}) {
  const [pages, setPages] = useState<PageRecord[]>([]);
  const [selected, setSelected] = useState(1);
  const [zoom, setZoom] = useState<number>(1);
  const image = useAuthedImage(api.pageImageUrl(doc.id, selected));
  const [state, setState] = useState<
    { s: "loading" } | { s: "error"; error: ApiError; disconnected: boolean } | { s: "ready" }
  >({ s: "loading" });

  const load = useCallback(async () => {
    setState({ s: "loading" });
    const r = await api.pages(doc.id, { limit: PAGE_SIZE, offset: 0 });
    if (r.ok) {
      setPages(r.data.pages);
      setState({ s: "ready" });
    } else {
      setState({ s: "error", error: r.error, disconnected: r.disconnected });
    }
  }, [doc.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const current = pages.find((p) => p.page_no === selected);
  const total = doc.page_count ?? pages.length;

  return (
    <Drawer
      title={`Pages — ${doc.filename}`}
      subtitle="The rendered page, so a citation can be checked against the source"
      onClose={onClose}
    >
      {state.s === "loading" && <Spinner label="Loading pages" />}
      {state.s === "error" &&
        (state.disconnected ? (
          <DisconnectedState onRetry={load} />
        ) : (
          <ErrorState error={state.error} onRetry={load} />
        ))}

      {state.s === "ready" && (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <label className="text-xs text-slateish-400">
              Page{" "}
              <input
                type="number"
                min={1}
                max={total}
                value={selected}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  if (Number.isFinite(n)) setSelected(Math.min(Math.max(1, n), total || 1));
                }}
                className="ms-1 w-20 rounded border border-ink-600 bg-ink-850 px-2 py-1 font-mono text-slateish-200"
              />
              <span className="ms-1">of {total}</span>
            </label>

            <div className="flex gap-1">
              <button
                type="button"
                disabled={selected <= 1}
                onClick={() => setSelected((n) => Math.max(1, n - 1))}
                className="rounded border border-ink-600 px-3 py-1 text-xs text-slateish-300 disabled:opacity-40 hover:bg-ink-700"
              >
                Previous
              </button>
              <button
                type="button"
                disabled={selected >= total}
                onClick={() => setSelected((n) => Math.min(total, n + 1))}
                className="rounded border border-ink-600 px-3 py-1 text-xs text-slateish-300 disabled:opacity-40 hover:bg-ink-700"
              >
                Next
              </button>
            </div>

            <div role="group" aria-label="Zoom" className="ms-auto flex gap-1">
              {ZOOMS.map((z) => (
                <button
                  key={z}
                  type="button"
                  aria-pressed={zoom === z}
                  onClick={() => setZoom(z)}
                  className={[
                    "rounded border px-2 py-1 text-xs",
                    zoom === z
                      ? "border-signal-500/60 bg-signal-500/15 text-signal-400"
                      : "border-ink-600 text-slateish-300 hover:bg-ink-700",
                  ].join(" ")}
                >
                  {z * 100}%
                </button>
              ))}
            </div>
          </div>

          {current && (
            <p className="mb-2 flex flex-wrap gap-2 text-xs">
              <span className="text-slateish-400">{current.char_count} characters extracted</span>
              {current.needs_ocr && (
                <span className="rounded bg-warn-500/15 px-2 py-0.5 text-warn-500">
                  scanned — no extractable text
                </span>
              )}
              {current.equation_heavy && (
                <span className="rounded bg-info-500/15 px-2 py-0.5 text-info-500">
                  equation-heavy — the maths did not survive extraction
                </span>
              )}
            </p>
          )}

          <div className="overflow-auto rounded border border-ink-700 bg-ink-950 p-3">
            {image.loading && <Spinner label={`Rendering page ${selected}`} />}
            {image.failed && (
              <p className="text-xs text-warn-500">
                The page image could not be rendered. The extracted text above is
                what the system searched and cited.
              </p>
            )}
            {image.src && (
              <img
                key={`${doc.id}-${selected}`}
                src={image.src}
                alt={`Page ${selected} of ${doc.filename}`}
                style={{ width: `${zoom * 100}%` }}
                className="mx-auto block max-w-none rounded bg-white"
              />
            )}
          </div>
        </>
      )}
    </Drawer>
  );
}
