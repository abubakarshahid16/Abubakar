import type { ReactNode } from "react";

import { MoreText } from "../../components/MoreText";

export function AnalysisHeader() {
  return (
    <header className="border-b border-ink-700 pb-4">
      <h1 className="text-xl font-semibold text-slateish-100">Analysis Hub</h1>
      <p className="mt-1 text-sm font-semibold text-signal-300">Ask about your documents</p>
      <MoreText className="mt-2 max-w-3xl" summary="Ask one engineering question about your documents; every answer shows the page it comes from.">
        <p className="text-sm text-slateish-300">
          Ask one engineering question, choose the work to run, and inspect only cited document evidence.
          Public evidence is isolated from private document context.
        </p>
      <div className="mt-4 grid gap-2 md:grid-cols-2">
        <Rule title="Evidence rule">A statement about a document is shown only when the page it comes from is found.</Rule>
        <Rule title="Recommendation rule">Advice is kept apart from what the documents say, and an engineer checks it.</Rule>
      </div>
      </MoreText>
      {/* An honesty label (rule 4: samples are labelled samples): always visible, never folded. */}
      <div className="mt-3 max-w-3xl">
        <Rule title="Market rule" warning>Market prices shown here are sample data unless an approved market price service is switched on.</Rule>
      </div>
    </header>
  );
}

function Rule({ title, children, warning = false }: { title: string; children: ReactNode; warning?: boolean }) {
  return (
    <div className={warning ? "rounded-[var(--radius-xs)] border border-warn-500/40 bg-warn-500/10 px-3 py-2" : "rounded-[var(--radius-xs)] border border-ink-600 bg-ink-850 px-3 py-2"}>
      <p className={warning ? "text-xs font-semibold uppercase tracking-wide text-warn-500" : "text-xs font-semibold uppercase tracking-wide text-slateish-400"}>{title}</p>
      <p className="mt-1 text-xs text-slateish-300">{children}</p>
    </div>
  );
}
