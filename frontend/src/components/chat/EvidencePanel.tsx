/**
 * The evidence panel: what the answer actually rests on.
 *
 * Document, page, clause, the quoted passage with the answering span marked,
 * and the rendered page image. The image is the part that matters most: the
 * extracted text loses equation operators and flattens table columns, so the
 * only way to verify a citation for certain is to look at the real page.
 */

import { api } from "../../api/client";
import { clauseLabel, OcrConfidence, ProvenanceMark } from "./Provenance";
import type { AnswerPassage } from "../../types/api";
import { Spinner } from "../states";
import { useAuthedImage } from "../useAuthedImage";

/** Exported because the answer card needs it too.
 *
 *  It lived here alone, so the answering span was marked in the side panel and
 *  NOT in the answer the reader actually looks at first. On a passage of
 *  standards prose the answering fragment can be nine words at the end of
 *  ninety, in the same weight and colour as everything around it - the product
 *  promises the document's own words back, and that only helps if the reader
 *  can find the words.
 */
export function Highlighted({ passage }: { passage: AnswerPassage }) {
  const h = passage.highlight;
  if (!h) return <>{passage.text}</>;
  const [start, end] = h;
  // Guard rather than trust: a bad offset should degrade to plain text, not
  // slice the passage into nonsense.
  if (start < 0 || end > passage.text.length || start >= end) return <>{passage.text}</>;
  // And a span covering the whole passage is not emphasis. Marking everything
  // marks nothing, and it tells the reader their eye can stop nowhere. The
  // page-image path refuses a box covering more than 60% of the page for
  // exactly this reason; this is the same rule in text.
  if (end - start >= 0.9 * passage.text.length) return <>{passage.text}</>;
  return (
    <>
      {passage.text.slice(0, start)}
      <mark className="rounded-[var(--radius-xs)] bg-signal-500/25 px-0.5 text-slateish-100">
        {passage.text.slice(start, end)}
      </mark>
      {passage.text.slice(end)}
    </>
  );
}

/** The citation, set as a citation rather than as a row of metadata.
 *
 *  An engineer cites a specification as "NORSOK M-501, clause A.1, page 17".
 *  Rendering that as three chips of equal weight makes the reader assemble it
 *  themselves; rendering it as a line makes it quotable straight into an
 *  email, which is what they actually do with it.
 *
 *  THE CLAUSE IS GONE FROM THIS LINE, and the document and page are not.
 *  `chunks.section` is wrong far more often than it is right - it does not
 *  reset at chapter and appendix boundaries, so a stale heading carries
 *  forward and is asserted here over text it has nothing to do with. See
 *  `clauseLabel` in Provenance.tsx for the two measurements and the tradeoff.
 *  Document plus page is the claim, it is auditable, and it stands.
 */
export function Citation({ passage }: { passage: AnswerPassage }) {
  const pages =
    passage.page_start === passage.page_end
      ? `page ${passage.page_start}`
      : `pages ${passage.page_start}–${passage.page_end}`;
  // null today, always. Rendered only if it is ever a label worth standing
  // behind; null renders as NOTHING, never as a placeholder. The old `(no
  // clause numbering)` branch went with it - now that no clause is ever
  // printed, saying it of one document would imply the others had one shown.
  const clause = clauseLabel(passage);
  return (
    <cite className="text-[13px] not-italic leading-relaxed text-slateish-300">
      <span className="font-medium">{passage.filename}</span>
      {clause && (
        <>
          {", clause "}
          <span className="font-mono text-[12px] text-slateish-200">
            {clause.split(" ")[0]}
          </span>
          <span className="text-slateish-400"> {clause.split(" ").slice(1).join(" ")}</span>
        </>
      )}
      {", "}
      <span className="text-slateish-400">{pages}</span>
      {/* A citation is a claim about where words came from, so it must say
          when they were recognised rather than extracted. See rule 8. */}
      {passage.text_source === "recognised" && (
        <>
          {" "}
          <ProvenanceMark passage={passage} />{" "}
          <OcrConfidence passage={passage} />
        </>
      )}
    </cite>
  );
}


/** The same claim in a list row: document and page, and no clause. See
 *  `clauseLabel` in Provenance.tsx. */
export function PassageLocation({ passage }: { passage: AnswerPassage }) {
  const pages =
    passage.page_start === passage.page_end
      ? `page ${passage.page_start}`
      : `pages ${passage.page_start}–${passage.page_end}`;
  const clause = clauseLabel(passage);
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
      <span className="font-medium text-slateish-300">{passage.filename}</span>
      <span className="text-slateish-500">·</span>
      <span className="text-slateish-400">{pages}</span>
      {clause && (
        <>
          <span className="text-slateish-500">·</span>
          <span className="rounded-[var(--radius-xs)] bg-ink-700 px-1.5 py-0.5 font-mono text-xs text-slateish-200">
            {clause}
          </span>
        </>
      )}
      {passage.text_source === "recognised" && (
        <ProvenanceMark passage={passage} />
      )}
    </span>
  );
}

export function EvidencePanel({
  passages,
  selected,
  onSelect,
  onClose,
  question,
}: {
  passages: AnswerPassage[];
  selected: number;
  onSelect: (i: number) => void;
  onClose: () => void;
  /** The question, so the answering sentence can be boxed on the page. */
  question?: string;
}) {
  const passage = passages[selected];

  // The box is only requested when there IS an answering span to box, so an
  // unboxed page never leaves the reader wondering whether the answer is on it.
  const boxed = Boolean(question && passage?.highlight);
  // Fetched with the bearer header, never as a bare <img src>: see useAuthedImage.
  const image = useAuthedImage(
    passage
      ? boxed
        ? api.pageImageWithAnswerUrl(
            passage.document_id,
            passage.page_start,
            passage.chunk_id,
            question!,
          )
        : api.pageImageUrl(passage.document_id, passage.page_start)
      : null,
  );

  if (!passage) return null;

  return (
    <aside
      aria-label="Evidence"
      className="card-3d surface-card flex h-full min-h-0 w-full flex-col border-ink-700 bg-ink-850/90 backdrop-blur-xl lg:w-80 xl:w-[22rem] lg:shrink-0 lg:border-l"
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
          className="rounded-[var(--radius-sm)] border border-ink-600 px-2 py-1 text-xs text-slateish-300 motion-safe:transition-colors hover:border-signal-500/50 hover:bg-ink-700"
        >
          Close
        </button>
      </div>

      {passages.length > 1 && (
        <div role="group" aria-label="Sources" className="flex flex-wrap gap-1.5 px-4 pt-3">
          {passages.map((p, i) => (
            <button
              key={p.chunk_id}
              type="button"
              aria-pressed={i === selected}
              onClick={() => onSelect(i)}
              className={[
                "rounded-[var(--radius-full)] border px-3 py-1 font-mono text-xs motion-safe:transition-colors",
                i === selected
                  ? "border-signal-500/60 bg-signal-500/18 text-signal-300 shadow-[0_0_0_1px_rgba(79,201,181,.35)]"
                  : "border-ink-600 text-slateish-300 hover:bg-ink-700",
              ].join(" ")}
            >
              {i + 1}
            </button>
          ))}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        <Citation passage={passage} />

        <h3 className="mt-4 text-xs uppercase tracking-wide text-slateish-400">
          Quoted passage
        </h3>
        <blockquote
          className={[
            "evidence-quote mt-1.5 rounded-[var(--radius-sm)] border-l-2 border-signal-500/50 bg-ink-900 px-3 py-2.5 text-slateish-200 shadow-[var(--shadow-resting)]",
            passage.kind === "table"
              ? "document-table"
              : "document-quote whitespace-pre-wrap text-sm",
          ].join(" ")}
        >
          <Highlighted passage={passage} />
        </blockquote>

        <h3 className="mt-5 text-xs uppercase tracking-wide text-slateish-400">
          Page {passage.page_start} as printed
          {boxed && image.answerLocated !== false && (
            <span className="ms-2 rounded-[var(--radius-full)] bg-signal-500/20 px-1.5 py-0.5 text-xs normal-case tracking-normal text-signal-300">
              answer outlined
            </span>
          )}
        </h3>
        <p className="mt-1 text-xs text-slateish-500">
          {boxed && image.answerLocated !== false
            ? "The answering sentence is outlined on the real page. Extraction flattens tables and drops equation operators; this is the page as printed."
            : boxed && image.answerLocated === false
              ? "The page was rendered, but the server could not locate the answering sentence to outline. Extraction flattens tables and drops equation operators."
            : "Extraction flattens tables and drops equation operators. This is the real page."}
        </p>
        {boxed && image.answerLocated === false && (
          <p className="mt-1 text-xs text-warn-500 italic">
            The answering sentence could not be located on this page, so nothing
            is outlined.
          </p>
        )}
        {question && !passage.highlight && (
          <p className="mt-1 text-xs text-slateish-500 italic">
            The exact location of the answer on this page could not be
            confirmed, so nothing is outlined.
          </p>
        )}
        <div className="mt-2 overflow-auto rounded-[var(--radius-md)] border border-ink-700 bg-ink-950 p-2 shadow-[var(--shadow-floating)]">
          {image.loading && <Spinner label={`Rendering page ${passage.page_start}`} />}
          {image.failed && (
            <p className="text-xs text-warn-500">
              The page image could not be rendered. The passage text above is what
              was cited.
            </p>
          )}
          {image.src && (
            <img
              key={`${passage.document_id}-${passage.page_start}-${boxed ? "boxed" : "plain"}`}
              src={image.src}
              alt={
                boxed && image.answerLocated !== false
                  ? `Page ${passage.page_start} of ${passage.filename}, with the answer outlined`
                  : `Page ${passage.page_start} of ${passage.filename}`
              }
              className="block w-full rounded-[var(--radius-sm)] bg-white shadow-[0_0_0_1px_rgba(255,255,255,0.08)]"
            />
          )}
        </div>
      </div>
    </aside>
  );
}
