/**
 * The measured score of a paper KIND, shown on the general review's page (order 14, piece G).
 *
 * The sentence comes from the server (`aim_review_measured.for_run`) and is drawn as written. "below target" is marked visibly
 * (warning colour, a word, and an icon-free text label so it never depends on colour alone); "not measured" is shown as a plain
 * note, never as a score. A null `measured` renders nothing. No number is made up here: nothing is computed on this side.
 */

export interface GeneralMeasured {
  kind_label: string;
  found: number | null;
  target: number;
  verdict: "at or above target" | "below target" | "not measured";
  sentence: string;
  /** The strict reader's wrong-comment share, only when both counts were recorded (the sentence already says it in words). */
  false_alarm?: { wrong: number; of: number; percent: number; target_percent: number; within_target: boolean; sentence: string } | null;
}

/** The score in plain words, from the fields themselves (never rounded up: 6.96 is said as 6.9, as the server does). */
export function plainMeasured(m: GeneralMeasured): string {
  if (m.verdict === "not measured" || m.found === null) return "This kind of paper has not been measured on test copies yet.";
  const found = Math.floor(Math.round(m.found * 10 * 1e6) / 1e6) / 10;
  const wrong = m.false_alarm ? ` ${m.false_alarm.wrong} of ${m.false_alarm.of} of its comments were wrong (the limit is ${m.false_alarm.target_percent}%).` : "";
  return `On test copies with planted mistakes, this kind of paper found ${found} of 10 (the target is ${m.target}).${wrong}`;
}

export function MeasuredBadge({ measured }: { measured: GeneralMeasured | null | undefined }) {
  if (!measured || !measured.sentence) return null; // null renders as nothing
  const below = measured.verdict === "below target";
  const tone = below
    ? "border-warn-500 text-slateish-100"
    : "border-ink-500 text-slateish-200";
  return (
    <div
      role="note"
      data-testid="general-measured"
      data-verdict={measured.verdict}
      className={`rounded-[var(--radius-md)] border p-3 text-sm ${tone}`}
    >
      {below && (
        <strong data-testid="general-measured-below" className="mr-2 rounded-[var(--radius-sm)] border border-warn-500 px-2 py-0.5 text-xs uppercase text-warn-500">
          Below target
        </strong>
      )}
      <span className="mr-1 text-xs text-slateish-400">{measured.kind_label}:</span>
      {/* PLAIN WORDS FIRST (H's audit, 27 Nov 2026: a version code, "a strict reader judged" and a round note read as machine talk
          on an engineer's screen): the score in a sentence of its own; the server's full sentence, with its date, version and
          round, one click away under "How this was measured". Nothing is dropped, and this note is never part of a comment. */}
      <span data-testid="general-measured-plain">{plainMeasured(measured)}</span>
      <details className="mt-1 text-xs text-slateish-300"><summary className="cursor-pointer">How this was measured</summary>
        <span data-testid="general-measured-sentence">{measured.sentence}</span>
      </details>
    </div>
  );
}
