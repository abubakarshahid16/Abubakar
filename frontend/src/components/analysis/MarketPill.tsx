export function MarketPill({ children }: { children: React.ReactNode }) {
  return <span className="rounded-[var(--radius-full)] border border-ink-500 bg-ink-800 px-2 py-0.5 font-mono text-xs uppercase tracking-wider text-slateish-300">{children}</span>;
}
