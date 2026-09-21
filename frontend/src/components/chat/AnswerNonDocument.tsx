import type { AnswerView } from "./AnswerCardContent";
import type { CorpusFact } from "../../types/api";

export function GuidanceAnswer({ view }: { view: AnswerView }) {
  const [lead, ...rest] = (view.answer ?? "").split("Try one of these:");
  return (
    <div className="surface-card rounded-[var(--radius-md)] border border-ink-700 bg-ink-850/60 p-4">
      <p className="text-sm text-slateish-300">{lead.trim()}</p>
      {view.examples.length > 0 && <><p className="mt-3 text-xs uppercase tracking-wide text-slateish-500">Questions your documents can answer</p><ul className="mt-1.5 space-y-1">{view.examples.map((q) => <li key={q} className="text-sm text-slateish-400"><span aria-hidden className="me-2 text-slateish-500">&bull;</span>{q}</li>)}</ul></>}
      {view.examples.length === 0 && rest.length > 0 && <p className="mt-2 whitespace-pre-wrap text-sm text-slateish-400">{rest.join("")}</p>}
    </div>
  );
}

export function MetadataAnswer({ view }: { view: AnswerView }) {
  return <div className="surface-card rounded-[var(--radius-md)] border border-signal-500/40 bg-signal-500/10 p-4"><p className="text-xs uppercase tracking-wide text-signal-400">Application statistic</p><p className="mt-1 text-sm text-slateish-200">{view.answer}</p><p className="mt-2 text-xs text-slateish-500">This count comes from accessible system metadata, not document text.</p></div>;
}

/** The LIBRARY's half of a two-part answer: counted, not searched. Styled as
 *  the metadata card is, because it is the same kind of fact - and labelled,
 *  so it cannot be read as something a document said. */
export function CorpusPart({ fact }: { fact: CorpusFact }) {
  return (
    <div
      aria-label="From the library"
      className="surface-card rounded-[var(--radius-md)] border border-signal-500/40 bg-signal-500/10 p-4"
    >
      <p className="text-xs uppercase tracking-wide text-signal-400">From the library</p>
      <p className="mt-1 text-sm text-slateish-200">{fact.text}</p>
      <p className="mt-2 text-xs text-slateish-500">
        Counted from the database, not from document text. The part of your
        question about content is answered below, from the documents.
      </p>
    </div>
  );
}

/** Said beside a generated answer whose count of documents was re-bounded.
 *  The correction is already in the text; this says why it is there. */
export function CountsBoundedNote({ count }: { count: number }) {
  return (
    <p role="note" className="text-xs text-slateish-400">
      {count === 1 ? "A count" : `${count} counts`} of documents in this answer{" "}
      {count === 1 ? "was" : "were"} marked as a count of the passages
      retrieved. The answer sees only those passages, never the whole library;
      to count what is loaded, ask how many are loaded.
    </p>
  );
}
