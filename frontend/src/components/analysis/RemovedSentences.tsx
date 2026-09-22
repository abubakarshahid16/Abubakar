export interface RemovedSentence {
  sentence: string;
  reason: string;
}

/** Sentences the checks took OUT of a generated answer, and why (B34).
 *
 * Shown, never hidden: this used to sit inside a collapsed `<details>`, and on
 * the recommendation it was not shown at all - the backend threw the list
 * away. A reader who sees a short or empty answer needs to see what was cut
 * and the reason ("value 300 not in cited passage") without having to know
 * there is something to expand.
 *
 * GREYED, and outside the answer. The prose above never contains these; this
 * block is visibly not part of it - muted text, its own labelled region - so a
 * removed number cannot be read as a stated one.
 */
export function RemovedSentences({
  removed,
  what,
}: {
  removed: RemovedSentence[];
  what: "summary" | "recommendation";
}) {
  if (removed.length === 0) return null;
  const shown = removed.filter((s) => s.sentence.trim() !== "");
  const withheld = removed.length - shown.length;
  return (
    <section
      aria-label={`Sentences removed from this ${what}`}
      className="surface-card rounded-[var(--radius-sm)] border border-dashed border-ink-700 bg-ink-850 px-3 py-2"
    >
      <p className="text-xs text-slateish-400">
        {removed.length} sentence{removed.length === 1 ? " was" : "s were"} removed from this {what}.
        {" "}Not part of the answer - shown so you can see what was cut and why.
      </p>
      {shown.length > 0 && <ul className="mt-2 space-y-1.5">{shown.map((s, i) => (
        <li
          key={`${i}-${s.sentence.slice(0, 24)}`}
          data-removed="true"
          className="text-xs text-slateish-500 opacity-70"
        >
          <span>{s.sentence}</span>
          {s.reason.trim() !== "" && <span className="ms-1 italic">&mdash; {s.reason}</span>}
        </li>
      ))}</ul>}
      {withheld > 0 && <p className="mt-2 text-xs text-slateish-500">
        {withheld === 1 ? "One of them was reported without the removed text, so it is not shown here." : `${withheld} of them were reported without the removed text, so they are not shown here.`}
      </p>}
    </section>
  );
}
