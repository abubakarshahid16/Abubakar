/**
 * Numbered source chips under an answer, and ONE full-width preview of the
 * chip that is open: which document, which page and clause, the passage with
 * the exact words the answer stood on marked, and "Open page" for the
 * rendered page itself (the evidence panel, unchanged).
 *
 * The chip numbers are the answer's superscripts: chip 2 is `²` in the text.
 * A source that was supplied but not cited is still listed - the reader may
 * want to see what the model was given - but it says so.
 */
import type { ReactNode } from "react";

import type { AnswerPassage, ChatSource } from "../../types/api";
import { ProvenanceMark, isRecognised } from "./Provenance";

export interface PreviewSource {
  n: number;
  /** from the server's presentation, when the turn carries one */
  meta: ChatSource | null;
  /** the passage itself, for its text */
  passage: AnswerPassage | null;
}

/** Pair the presentation sources with the passages they number. */
export function previewSources(passages: AnswerPassage[], meta: ChatSource[] | undefined): PreviewSource[] {
  const byN = new Map((meta ?? []).map((s) => [s.n, s]));
  return passages.map((p, i) => ({ n: i + 1, meta: byN.get(i + 1) ?? null, passage: p }));
}

function nameOf(s: PreviewSource): string {
  return s.meta?.display_name || s.passage?.filename || "Source";
}

function pageOf(s: PreviewSource): string | null {
  const page = s.meta?.page ?? s.passage?.page_start ?? null;
  const end = s.meta?.page_end ?? s.passage?.page_end ?? null;
  if (page == null) return null;
  return end != null && end !== page ? `p.${page}-${end}` : `p.${page}`;
}

export function SourceChips({
  sources,
  open,
  onOpen,
}: {
  sources: PreviewSource[];
  open: number | null;
  onOpen: (index: number | null) => void;
}) {
  if (sources.length === 0) return null;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
      <span className="text-slateish-500">Sources</span>
      {sources.map((s, i) => {
        const active = open === i;
        const page = pageOf(s);
        return (
          <button
            key={s.n}
            type="button"
            aria-pressed={active}
            aria-label={`Source ${s.n}: ${nameOf(s)}${page ? `, ${page}` : ""}`}
            onClick={() => onOpen(active ? null : i)}
            className={[
              "inline-flex items-center gap-1.5 rounded-[var(--radius-full)] border px-2.5 py-1 motion-safe:transition-colors",
              active
                ? "border-signal-500/70 bg-signal-500/10 text-slateish-100"
                : "border-ink-600 text-slateish-300 hover:border-signal-500/50 hover:bg-ink-800",
              s.meta && !s.meta.cited ? "opacity-70" : "",
            ].join(" ")}
          >
            <span className="font-mono font-semibold text-signal-400">{s.n}</span>
            <span className="max-w-[16rem] truncate">{nameOf(s)}</span>
            {page && <span className="text-slateish-500">· {page}</span>}
          </button>
        );
      })}
    </div>
  );
}

/** The passage, with each verified quote marked where it occurs. */
function Marked({ text, quotes }: { text: string; quotes: string[] }) {
  const spans: [number, number][] = [];
  const lower = text.toLowerCase();
  for (const q of quotes) {
    const at = q.trim() ? lower.indexOf(q.trim().toLowerCase()) : -1;
    if (at >= 0) spans.push([at, at + q.trim().length]);
  }
  spans.sort((a, b) => a[0] - b[0]);
  const out: ReactNode[] = [];
  let last = 0;
  spans.forEach(([s, e], i) => {
    if (s < last) return; // overlapping quotes: keep the first
    if (s > last) out.push(text.slice(last, s));
    out.push(
      <mark key={i} className="rounded-sm bg-signal-500/20 px-0.5 text-slateish-100">
        {text.slice(s, e)}
      </mark>,
    );
    last = e;
  });
  if (last < text.length) out.push(text.slice(last));
  return <>{out}</>;
}

export function SourcePreview({
  source,
  onOpenPage,
  onClose,
}: {
  source: PreviewSource;
  onOpenPage: () => void;
  onClose: () => void;
}) {
  const p = source.passage;
  const meta = source.meta;
  const quotes = meta?.quotes ?? [];
  const rows = meta?.rows ?? [];
  const page = pageOf(source);
  const clause = meta?.clause ?? p?.section ?? null;
  return (
    <section
      aria-label={`Source ${source.n} preview`}
      className="mt-2 overflow-hidden rounded-[var(--radius-md)] border border-ink-600 bg-ink-850"
    >
      <header className="flex items-start justify-between gap-3 border-b border-ink-700 px-3.5 py-2.5">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slateish-100">{nameOf(source)}</p>
          <p className="mt-0.5 text-xs text-slateish-500">
            {[meta?.document_number, page ? page.replace("p.", "page ") : null, clause]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {p && (
            <button
              type="button"
              onClick={onOpenPage}
              className="rounded-[var(--radius-sm)] border border-ink-600 px-2.5 py-1 text-xs text-slateish-200 hover:border-signal-500/50 hover:bg-ink-700"
            >
              Open page
            </button>
          )}
          <button
            type="button"
            aria-label="Close source preview"
            onClick={onClose}
            className="rounded-[var(--radius-sm)] px-2 py-1 text-xs text-slateish-400 hover:bg-ink-700"
          >
            ×
          </button>
        </div>
      </header>
      {p && isRecognised(p) && (
        <div className="border-b border-ink-700 px-3.5 py-1.5">
          <ProvenanceMark passage={p} variant="short" />
        </div>
      )}
      {rows.length > 0 ? (
        <table className="w-full text-left text-sm">
          <tbody>
            {rows.map((row, i) => (
              <tr
                key={i}
                className={[
                  "border-b border-ink-700 last:border-b-0",
                  row.cited ? "bg-signal-500/10 text-slateish-100" : "text-slateish-400",
                ].join(" ")}
              >
                {Object.entries(row)
                  .filter(([k]) => k !== "cited")
                  .map(([k, v]) => (
                    <td key={k} className="px-3.5 py-2">{String(v ?? "")}</td>
                  ))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : p ? (
        <blockquote className="max-h-56 overflow-y-auto whitespace-pre-wrap px-3.5 py-2.5 text-sm leading-6 text-slateish-300">
          <Marked text={p.text} quotes={quotes} />
        </blockquote>
      ) : null}
      <footer className="border-t border-ink-700 px-3.5 py-2 text-xs text-slateish-500">
        {quotes.length > 0
          ? `The marked words are what the answer stood on; they were found on this page.`
          : meta && !meta.cited
            ? "Given to the model but not cited in the answer."
            : "Open the page to check the passage in place."}
      </footer>
    </section>
  );
}
