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
      <span data-testid="general-measured-sentence">{measured.sentence}</span>
    </div>
  );
}
