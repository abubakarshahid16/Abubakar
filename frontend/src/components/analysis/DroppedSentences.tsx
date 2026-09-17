export interface DroppedSentence {
  sentence: string;
  reason: string;
}

/** Transparent disclosure of text the model removed from a summary. */
export function DroppedSentences({ dropped }: { dropped: DroppedSentence[] }) {
  if (dropped.length === 0) return null;
  const shown = dropped.filter((s) => s.sentence.trim() !== "");
  const withheld = dropped.length - shown.length;
  return (
    <details className="surface-card rounded-[var(--radius-sm)] border border-ink-700 bg-ink-850 px-3 py-2">
      <summary className="cursor-pointer text-xs text-slateish-400">
        {dropped.length} sentence{dropped.length === 1 ? " was" : "s were"} removed from this summary
      </summary>
      {shown.length > 0 && <ul className="mt-2 space-y-1.5">{shown.map((s, i) => (
        <li key={`${i}-${s.sentence.slice(0, 24)}`} className="text-xs text-slateish-400">
          <span className="text-slateish-300">{s.sentence}</span>
          {s.reason.trim() !== "" && <span className="ml-1 text-slateish-500">&mdash; {s.reason}</span>}
        </li>
      ))}</ul>}
      {withheld > 0 && <p className="mt-2 text-xs text-slateish-500">
        {withheld === 1 ? "One of them was reported without the removed text, so it is not shown here." : `${withheld} of them were reported without the removed text, so they are not shown here.`}
      </p>}
    </details>
  );
}
