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

function Row({ row, onCite }: { row: ClaimRow; onCite: (evidenceId: string) => void }) {
  const hasRaw = row.raw_value !== null || row.raw_unit !== null;
  const hasNormalised = row.normalized_value !== null && row.normalized_unit !== null;
  return (
    <li className="border-t border-ink-700/60 py-2.5 first:border-t-0">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-xs text-slateish-400">
        <button
          type="button"
          onClick={() => onCite(row.evidence_id)}
          aria-label={`Show evidence from ${row.filename}, page ${row.page_start}`}
          className="rounded font-medium text-slateish-200 underline decoration-ink-500 underline-offset-2 hover:decoration-slateish-300"
        >
          {row.filename}
        </button>
        <span>p.{row.page_start}</span>
        {row.section !== null && <span>&sect; {row.section}</span>}
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
    </li>
  );
}

export function ClaimTable({
  clusters,
  onCite,
}: {
  clusters: ClaimCluster[];
  onCite: (evidenceId: string) => void;
}) {
  return (
    <section aria-label="Claim comparison" className="rounded-lg border border-ink-600 bg-ink-850 p-4">
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
            <li key={`${c.facet}-${i}`} className="rounded border border-ink-700 p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h4 className="text-sm font-semibold text-slateish-200">{c.facet}</h4>
                <LabelMark label={c.label} />
              </div>
              <ul className="mt-2">
                {c.rows.map((r) => (
                  <Row key={r.evidence_id} row={r} onCite={onCite} />
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
