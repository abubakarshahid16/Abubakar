import type { ReactNode } from "react";

export function AnalysisHeader() {
  return (
    <header className="border-b border-ink-700 pb-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-signal-400">Enterprise FEED intelligence</p>
      <h1 className="mt-1 text-xl font-semibold text-slateish-100">Analysis</h1>
      <p className="mt-1 text-sm font-semibold text-signal-300">Document submittal review</p>
      <p className="mt-2 max-w-3xl text-sm text-slateish-300">
        Ask one engineering question, choose the work to run, and inspect only cited document evidence.
        Public evidence is isolated from private document context.
      </p>
      <div className="mt-4 grid gap-2 md:grid-cols-3">
        <Rule title="Evidence rule">Document claims render only when citations resolve to page evidence.</Rule>
        <Rule title="Recommendation rule">Advisory output is separate from document facts and carries engineer review.</Rule>
        <Rule title="Market rule" warning>Public market rows are sample data unless a governed provider is enabled.</Rule>
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
