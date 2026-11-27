/**
 * A written answer from the documents, laid out as a chat answer: plain text
 * with superscript source numbers, the sources as chips, one preview open at
 * a time, and "Open page" for the rendered page.
 *
 * EVERY WARNING THE CARD CARRIED IS STILL HERE, word for word: the answer is
 * the model's words and not the document's; it stopped at its length limit;
 * a source did not fit the context window; a source number the model invented
 * was removed; a comparison was answered from one document. The layout moved,
 * the honesty did not.
 */
import { useState } from "react";

import type { ChatSource } from "../../types/api";
import { type AnswerView, asksForComparison, documentsAnsweredFrom, sourcesOf } from "./AnswerCardContent";
import { ComparisonScopeNotice as ComparisonScopeNoticeView } from "./ComparisonScopeNotice";
import { Markdown } from "./Markdown";
import { SourceChips, SourcePreview, previewSources } from "./SourcePreview";

// no model file name on the screen (owner, 27 Nov 2026): the parameter stays for callers; the name stays in the answer's technical record
export const MODEL_WORDS_LABEL = (_model?: string | null) => "Written by the AI, not the document's own words";

export function GeneratedAnswer({
  view,
  sources: meta,
  onOpenPage,
  explainsEarlier,
  question,
}: {
  view: AnswerView;
  sources?: ChatSource[];
  /** Open the rendered page for passage `index` (the evidence panel). */
  onOpenPage: (index: number) => void;
  explainsEarlier?: boolean;
  question?: string | null;
}) {
  const passages = sourcesOf(view);
  const sources = previewSources(passages, meta);
  const [open, setOpen] = useState<number | null>(null);
  const answeredFrom = documentsAnsweredFrom(view);
  const comparisonFromOneDocument = asksForComparison(question) && answeredFrom.length === 1;
  const current = open != null ? sources[open] : undefined;

  return (
    <div>
      <p className="mb-1.5 text-xs text-info-500">{MODEL_WORDS_LABEL(view.model)}</p>
      {explainsEarlier && (
        <p className="mb-1.5 text-xs text-slateish-500">
          An explanation of the quoted answer above. The quotation remains the
          authoritative text.
        </p>
      )}

      <Markdown
        text={view.answer ?? ""}
        onCite={(i) => setOpen((o) => (o === i ? null : i))}
        activeSource={open}
      />

      {view.truncated && (
        <p className="mt-2 rounded-[var(--radius-sm)] border border-warn-500/40 bg-warn-500/[0.08] px-2.5 py-1.5 text-xs text-warn-500">
          This answer reached its length limit and stops early. The sources below are complete: open them for the rest.
        </p>
      )}

      {comparisonFromOneDocument && <ComparisonScopeNoticeView documents={answeredFrom.length} />}

      {view.evidence_removed.length > 0 && (
        <div className="mt-2 rounded-[var(--radius-sm)] border border-warn-500/40 bg-warn-500/[0.08] px-2.5 py-1.5 text-xs text-warn-500">
          <p>
            {view.evidence_removed.length === 1
              ? "One source was too long for the AI to read in full."
              : `${view.evidence_removed.length} sources were too long for the AI to read in full.`}{" "}
            This answer was written without {view.evidence_removed.length === 1 ? "it" : "them"}.
          </p>
          <ul className="mt-1 space-y-0.5">
            {view.evidence_removed.map((e) => (
              <li key={`${e.index}-${e.filename ?? ""}`}>
                <span className="font-mono">{e.filename ?? "a source"}</span>
                {e.page_start !== null && <> p{e.page_start}</>}
                {" — "}
                {e.action === "dropped"
                  ? "not used at all"
                  : `shortened, ${e.characters_dropped.toLocaleString()} characters left out`}
              </li>
            ))}
          </ul>
        </div>
      )}

      {view.rejected_citations.length > 0 && (
        <p className="mt-2 rounded-[var(--radius-sm)] border border-danger-500/40 bg-danger-500/10 px-2 py-1.5 text-xs text-slateish-300">
          The AI used {view.rejected_citations.map((n) => `[S${n}]`).join(", ")}, which
          {view.rejected_citations.length === 1 ? " was" : " were"} not among the sources
          supplied. Removed from the answer above rather than shown to you.
        </p>
      )}

      <SourceChips sources={sources} open={open} onOpen={setOpen} />
      {current && (
        <SourcePreview
          source={current}
          onOpenPage={() => onOpenPage(open!)}
          onClose={() => setOpen(null)}
        />
      )}

    </div>
  );
}
