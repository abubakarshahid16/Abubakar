/** Answered cards out of all cards, as a ring with its count beside it. */
export function ProgressRing({ answered, total }: { answered: number; total: number }) {
  const r = 16;
  const length = 2 * Math.PI * r;
  const share = total > 0 ? answered / total : 0;
  return (
    <div className="flex items-center gap-2" role="img" aria-label={`${answered} of ${total} answered`}>
      <svg width="40" height="40" viewBox="0 0 40 40" aria-hidden="true">
        <circle cx="20" cy="20" r={r} fill="none" strokeWidth="4" className="stroke-ink-700" />
        <circle
          cx="20" cy="20" r={r} fill="none" strokeWidth="4" strokeLinecap="round"
          className="stroke-signal-500 transition-[stroke-dashoffset] duration-500 motion-reduce:transition-none"
          strokeDasharray={length} strokeDashoffset={length * (1 - share)}
          transform="rotate(-90 20 20)"
        />
      </svg>
      <span className="text-sm tabular-nums text-slateish-200">{answered}/{total}</span>
    </div>
  );
}
