/**
 * The mechanical cross-document claim comparison.
 *
 * Every span in this table is the DOCUMENT'S OWN WORDS - `exact_span` is
 * verbatim - so it is set in serif on a quote rule, the Tier 1 style from
 * AnswerCard. Nothing here is generated prose and nothing here may look like it.
 *
 * Labels are text plus an icon, never colour alone. "possible_conflict" says
 * "possible": the documents carry no revision or approval status, so the table
 * can show that two values disagree but cannot say which one governs.
 *
 * `normalized_value` is null when the unit is not in the normaliser's table.
 * A null renders NOTHING - never a guess, never 0.
 */
import type { ClaimCluster, ClaimLabel, ClaimRow } from "../../types/analysis";

const LABELS: Record<ClaimLabel, { icon: string; text: string; tone: string }> = {
  agreement: { icon: "=", text: "Agree", tone: "text-signal-400" },
  addition: { icon: "+", text: "Adds", tone: "text-slateish-300" },
  possible_conflict: { icon: "▲", text: "Possible conflict", tone: "text-warn-500" },
  unresolved: { icon: "?", text: "Unresolved", tone: "text-slateish-400" },
};

const POSSIBLE_CONFLICT_CAPTION =
  "Values disagree. Whether one supersedes the other cannot be determined: documents carry no revision or approval status.";

function LabelMark({ label }: { label: ClaimLabel }) {
  const l = LABELS[label];
  return (
    <span className={["text-[11px] font-semibold uppercase tracking-wider", l.tone].join(" ")}>
      <span aria-hidden="true" className="mr-1 font-mono">
        {l.icon}
      </span>
      {l.text}
    </span>
  );
}

/**
 * THE WHOLE ROW IS THE CONTROL, not the filename inside it.
 *
 * It used to be a ~60px filename button with the passage, the page and the
 * figures beside it as inert text: on a screen whose entire claim is
 * auditability, opening the evidence was the hardest thing on it to hit, and
 * nothing but that one word gave a hover affordance.
 *
 * `role="button"` with a keydown handler rather than a real <button>, because a
 * button element may only contain phrasing content and this row contains a
 * <blockquote> and a <dl>. Enter and Space are handled explicitly - that is
 * what a real button would give for free, and it is the part that must not be
 * skipped. What the activation DOES is unchanged: onCite(evidence_id).
 *
 * The selected row says "Showing" in words as well as taking the signal
 * border - colour alone is not a state.
 */
function Row({
  row,
  onCite,
  selected,
}: {
  row: ClaimRow;
  onCite: (evidenceId: string) => void;
  selected: boolean;
}) {
  const hasRaw = row.raw_value !== null || row.raw_unit !== null;
  const hasNormalised = row.normalized_value !== null && row.normalized_unit !== null;

  function activate() {
    onCite(row.evidence_id);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;
    // Space scrolls the page by default; Enter would submit an enclosing form.
    e.preventDefault();
    activate();
  }

  return (
    <li className="border-t border-ink-700/60 first:border-t-0">
      <div
        role="button"
        tabIndex={0}
        aria-pressed={selected}
        aria-label={`Show evidence from ${row.filename}, page ${row.page_start}`}
        onClick={activate}
        onKeyDown={onKeyDown}
        className={[
          "cursor-pointer rounded-[var(--radius-xs)] border px-2 py-2.5",
          "hover:bg-ink-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal-400",
          selected ? "border-signal-500/50 bg-signal-500/10" : "border-transparent",
        ].join(" ")}
      >
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-xs text-slateish-400">
        <span className="font-medium text-slateish-200 underline decoration-ink-500 underline-offset-2">
          {row.filename}
        </span>
        <span>p.{row.page_start}</span>
        {selected && (
          <span className="text-[11px] font-semibold uppercase tracking-wider text-signal-300">
            Showing
          </span>
        )}
        {/* NO CLAUSE LABEL. `row.section` traces to analysis.py:70
            `hit.get("section")`, which is the chunker's value - wrong on 5 of
            6 cited passages, and 0 of 11 correct on doc16. Chat stopped
            printing it and the PDF no longer prints it; this was the third
            place, and three surfaces disagreeing about the same clause is
            worse than none of them naming it.

            Document and page only. The section renders as nothing rather than
            as a placeholder, because an absent value must be visibly absent.

            NOT the same value as GapAnalysisCard's baseline section, which the
            USER types and which is unaffected. */}
      </div>
      <blockquote className="document-quote mt-1.5 whitespace-pre-wrap border-l-2 border-signal-500/60 bg-ink-900 py-2 pl-4 pr-3 text-[14px] text-slateish-100">
        {row.exact_span}
      </blockquote>
      {(hasRaw || hasNormalised) && (
        <dl className="mt-1.5 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs">
          {hasRaw && (
            <div className="flex items-baseline gap-1.5">
              <dt className="text-slateish-500">as written</dt>
              <dd className="font-mono text-slateish-200">
                {[row.raw_value, row.raw_unit].filter((v) => v !== null).join(" ")}
              </dd>
            </div>
          )}
          {hasNormalised && (
            <div className="flex items-baseline gap-1.5">
              <dt className="text-slateish-500">normalised</dt>
              <dd className="font-mono text-slateish-400">
                {row.normalized_value} {row.normalized_unit}
              </dd>
            </div>
          )}
        </dl>
      )}
      </div>
    </li>
  );
}

export function ClaimTable({
  clusters,
  onCite,
  selectedEvidenceId = null,
}: {
  clusters: ClaimCluster[];
  onCite: (evidenceId: string) => void;
  /** The evidence id the Sources panel is currently showing, so the row that
   *  put it there can say so. Optional: a caller that tracks no selection
   *  renders exactly what it did before. */
  selectedEvidenceId?: string | null;
}) {
  return (
    <section aria-label="Claim comparison" className="rounded-[var(--radius-md)] border border-ink-600 bg-ink-850 p-4">
      <h3 className="text-[11px] font-semibold uppercase tracking-wider text-signal-400">
        Claim comparison &mdash; quoted verbatim from the documents
      </h3>

      {clusters.length === 0 ? (
        <p className="mt-2 text-sm text-slateish-500">
          No comparable claims were extracted from the retrieved passages.
        </p>
      ) : (
        <ul className="mt-3 space-y-4">
          {clusters.map((c, i) => (
            <li key={`${c.facet}-${i}`} className="rounded-[var(--radius-xs)] border border-ink-700 p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h4 className="text-sm font-semibold text-slateish-200">{c.facet}</h4>
                <LabelMark label={c.label} />
              </div>
              <ul className="mt-2">
                {c.rows.map((r) => (
                  <Row
                    key={r.evidence_id}
                    row={r}
                    onCite={onCite}
                    selected={r.evidence_id === selectedEvidenceId}
                  />
                ))}
              </ul>
              {c.label === "possible_conflict" && (
                <p className="mt-2 border-t border-warn-500/30 pt-2 text-xs text-warn-500">
                  {POSSIBLE_CONFLICT_CAPTION}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}

      <p className="mt-3 border-t border-ink-700 pt-2 text-xs text-slateish-500">
        Compares the passages this answer retrieved. It does not claim these are the only
        relevant claims in the corpus.
      </p>
    </section>
  );
}
