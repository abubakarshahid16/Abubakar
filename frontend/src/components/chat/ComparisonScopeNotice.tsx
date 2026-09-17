export function ComparisonScopeNotice({ documents }: { documents: number }) {
  return <p role="note" className="mt-2 rounded-[var(--radius-sm)] border border-warn-500/40 bg-warn-500/[0.08] px-2.5 py-1.5 text-xs text-warn-500">
    Answered from {documents} document{documents === 1 ? "" : "s"}. This question asks for a comparison across documents; comparison across the corpus is not performed in Chat.
  </p>;
}
