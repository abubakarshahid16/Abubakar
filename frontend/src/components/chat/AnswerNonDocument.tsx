import type { AnswerView } from "./AnswerCardContent";

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
