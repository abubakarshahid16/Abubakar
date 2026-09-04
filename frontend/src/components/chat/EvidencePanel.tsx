/**
 * The evidence panel: what the answer actually rests on.
 *
 * Document, page, clause, the quoted passage with the answering span marked,
 * and the rendered page image. The image is the part that matters most: the
 * extracted text loses equation operators and flattens table columns, so the
 * only way to verify a citation for certain is to look at the real page.
 */
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import type { AnswerPassage } from "../../types/api";
import { Spinner } from "../states";

function Highlighted({ passage }: { passage: AnswerPassage }) {
  const h = passage.highlight;
  if (!h) return <>{passage.text}</>;
  const [start, end] = h;
  // Guard rather than trust: a bad offset should degrade to plain text, not
  // slice the passage into nonsense.
  if (start < 0 || end > passage.text.length || start >= end) return <>{passage.text}</>;
  return (
    <>
      {passage.text.slice(0, start)}
      <mark className="rounded bg-signal-500/25 px-0.5 text-slateish-100">
        {passage.text.slice(start, end)}
      </mark>
      {passage.text.slice(end)}
    </>
  );
}

export function PassageLocation({ passage }: { passage: AnswerPassage }) {
  const pages =
    passage.page_start === passage.page_end
      ? `page ${passage.page_start}`
      : `pages ${passage.page_start}–${passage.page_end}`;
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
      <span className="font-medium text-slateish-300">{passage.filename}</span>
      <span className="text-slateish-500">·</span>
      <span className="text-slateish-400">{pages}</span>
      {passage.section ? (
        <>
          <span className="text-slateish-500">·</span>
          <span className="rounded bg-ink-700 px-1.5 py-0.5 font-mono text-[11px] text-slateish-200">
            {passage.section}
          </span>
        </>
      ) : (
        <>
          <span className="text-slateish-500">·</span>
          {/* A missing clause is stated, not hidden. This document does not
              number its headings, and pretending otherwise would misrepresent
              the citation. */}
          <span className="text-slateish-500 italic">no clause numbering</span>
        </>
      )}
    </span>
  );
}

export function EvidencePanel({
  passages,
  selected,
  onSelect,
  onClose,
}: {
  passages: AnswerPassage[];
  selected: number;
  onSelect: (i: number) => void;
  onClose: () => void;
}) {
  const [imageLoading, setImageLoading] = useState(true);
  const passage = passages[selected];

  useEffect(() => setImageLoading(true), [selected]);

  if (!passage) return null;

  return (
    <aside
      aria-label="Evidence"
      className="flex h-full min-h-0 w-full flex-col border-ink-700 bg-ink-850 lg:w-[26rem] lg:shrink-0 lg:border-l"
    >
      <div className="flex items-start justify-between gap-2 border-b border-ink-700 px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-slateish-200">Evidence</h2>
          <p className="mt-0.5 text-xs text-slateish-400">
            The source behind the answer, as it appears in the document
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close evidence panel"
          className="rounded border border-ink-600 px-2 py-1 text-xs text-slateish-300 hover:bg-ink-700"
        >
          Close
        </button>
      </div>

      {passages.length > 1 && (
        <div role="group" aria-label="Sources" className="flex flex-wrap gap-1 px-4 pt-3">
          {passages.map((p, i) => (
            <button
              key={p.chunk_id}
              type="button"
              aria-pressed={i === selected}
              onClick={() => onSelect(i)}
              className={[
                "rounded border px-2 py-1 text-xs",
                i === selected
                  ? "border-signal-500/60 bg-signal-500/15 text-signal-400"
                  : "border-ink-600 text-slateish-300 hover:bg-ink-700",
              ].join(" ")}
            >
              Source {i + 1}
            </button>
          ))}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        <PassageLocation passage={passage} />

        <h3 className="mt-4 text-xs uppercase tracking-wide text-slateish-400">
          Quoted passage
        </h3>
        <blockquote className="mt-1.5 whitespace-pre-wrap rounded border-l-2 border-signal-500/50 bg-ink-900 px-3 py-2 font-serif text-sm leading-relaxed text-slateish-200">
          <Highlighted passage={passage} />
        </blockquote>

        <h3 className="mt-5 text-xs uppercase tracking-wide text-slateish-400">
          Page {passage.page_start} as printed
        </h3>
        <p className="mt-1 text-xs text-slateish-500">
          Extraction flattens tables and drops equation operators. This is the
          real page.
        </p>
        <div className="mt-2 overflow-auto rounded border border-ink-700 bg-ink-950 p-2">
          {imageLoading && <Spinner label={`Rendering page ${passage.page_start}`} />}
          <img
            key={`${passage.document_id}-${passage.page_start}`}
            src={api.pageImageUrl(passage.document_id, passage.page_start)}
            alt={`Page ${passage.page_start} of ${passage.filename}`}
            onLoad={() => setImageLoading(false)}
            onError={() => setImageLoading(false)}
            className="block w-full rounded bg-white"
          />
        </div>
      </div>
    </aside>
  );
}
