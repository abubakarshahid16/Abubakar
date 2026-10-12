import type { AnswerView } from "./AnswerCardContent";
import { PassageLocation } from "./EvidencePanel";
import { asSentence, sourcesOf } from "./AnswerCardContent";
import { NOT_DETERMINED } from "./AnswerVerdict";

export function InsufficientAnswer({ view, onSelectSource }: { view: AnswerView; onSelectSource: (i: number) => void }) {
  const sources = sourcesOf(view);
  return <div className="surface-card rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-4"><p className="text-sm font-semibold text-slateish-200">{NOT_DETERMINED}</p><p className="mt-1 text-sm text-slateish-400">{asSentence(view.reason ?? "nothing credible was retrieved")} Nothing was made up to fill the gap — try rephrasing, or check that the right document has been uploaded.</p>{sources.length > 0 && <div className="mt-3"><p className="text-xs uppercase tracking-wide text-slateish-500">What was considered, so you can judge for yourself</p><ul className="mt-1.5 space-y-1">{sources.map((p, i) => <li key={p.chunk_id}><button type="button" onClick={() => onSelectSource(i)} className="w-full rounded-[var(--radius-sm)] border border-ink-700 px-2 py-1.5 text-left hover:bg-ink-800"><PassageLocation passage={p} /></button></li>)}</ul></div>}</div>;
}
